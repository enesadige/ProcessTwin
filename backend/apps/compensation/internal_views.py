from __future__ import annotations

from dataclasses import asdict
from typing import Any

from django.db import transaction
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_http_methods

from apps.compensation.internal_serializers import (
    campaign_enrollment_summary,
    compensation_result_summary,
    evaluation_summary,
    evidence_summary,
    outage_summary,
    policy_result_summary,
    rule_set_payload,
    safe_payload,
    snapshot_payload,
    subscription_summary,
)
from apps.compensation.models import (
    CompensationEvaluation,
    CompensationEvaluationStatus,
    CompensationResultType,
    DecisionEvidence,
)
from apps.compensation.services.calculation import (
    CompensationInputError,
    CompensationService,
    build_decision_evidence_hash,
)
from apps.core.internal_api import internal_service_required
from apps.customers.models import (
    Campaign,
    CampaignEnrollment,
    Subscription,
)
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.operations.models import Outage, OutageStatus
from apps.operations.services.outages import OutageService
from apps.rules.models import Rule, RuleSet, RuleVersion
from apps.rules.services.evaluation import PolicyRuleCandidate, RuleEvaluationService

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class InternalCompensationAPIError(Exception):
    def __init__(self, code: str, message: str, *, status: int, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def _ok(
    *,
    request,
    snapshot: DataSnapshot,
    data: dict[str, Any],
    warnings: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> JsonResponse:
    return JsonResponse(
        {
            "data": safe_payload(data),
            "warnings": warnings or [],
            "evidence": evidence or [],
            "metadata": {
                "correlation_id": getattr(request, "correlation_id", None),
                "snapshot": snapshot_payload(snapshot),
            },
        }
    )


def _error(exc: InternalCompensationAPIError) -> JsonResponse:
    return JsonResponse(
        {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
        status=exc.status,
    )


def _sanitize_error(exc: Exception) -> JsonResponse:
    return _error(
        InternalCompensationAPIError(
            "internal_error",
            "Compensation internal API failed.",
            status=500,
            details={"reason": exc.__class__.__name__},
        )
    )


def _resolve_snapshot(identifier: str | None) -> DataSnapshot:
    if not identifier:
        raise InternalCompensationAPIError(
            "validation_error",
            "snapshot_identifier is required.",
            status=400,
            details={"field": "snapshot_identifier"},
        )
    snapshot = (
        DataSnapshot.objects.select_related("dataset_version")
        .filter(snapshot_key=identifier)
        .first()
    )
    if snapshot:
        return snapshot
    dataset = DatasetVersion.objects.filter(slug=identifier).first()
    if dataset is None:
        raise InternalCompensationAPIError(
            "not_found",
            "Snapshot or dataset slug was not found.",
            status=404,
            details={"snapshot_identifier": identifier},
        )
    snapshots = list(
        DataSnapshot.objects.select_related("dataset_version")
        .filter(dataset_version=dataset)
        .order_by("snapshot_key")
    )
    if len(snapshots) != 1:
        raise InternalCompensationAPIError(
            "validation_error",
            "Dataset slug must resolve to exactly one snapshot.",
            status=400,
            details={"dataset_slug": identifier, "snapshot_count": len(snapshots)},
        )
    return snapshots[0]


def _request_payload(request) -> dict[str, Any]:
    if request.method == "GET":
        return request.GET.dict()
    if request.content_type == "application/json":
        import json

        if not request.body:
            return {}
        parsed = json.loads(request.body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise InternalCompensationAPIError(
                "validation_error",
                "JSON body must be an object.",
                status=400,
            )
        return parsed
    return request.POST.dict()


def _parse_dt(value: str | None, *, field_name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise InternalCompensationAPIError(
                "validation_error",
                f"{field_name} is required.",
                status=400,
                details={"field": field_name},
            )
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise InternalCompensationAPIError(
            "validation_error",
            f"{field_name} must be a valid ISO 8601 datetime.",
            status=400,
            details={"field": field_name},
        )
    if timezone.is_naive(parsed):
        raise InternalCompensationAPIError(
            "validation_error",
            f"{field_name} must be timezone-aware.",
            status=400,
            details={"field": field_name},
        )
    return parsed


def _parse_bool(payload: dict[str, Any], field_name: str, *, default: bool = False) -> bool:
    value = payload.get(field_name)
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    if str(value).lower() in {"true", "1", "yes"}:
        return True
    if str(value).lower() in {"false", "0", "no"}:
        return False
    raise InternalCompensationAPIError(
        "validation_error",
        f"{field_name} must be a boolean.",
        status=400,
        details={"field": field_name},
    )


def _parse_limit(payload: dict[str, Any], *, default: int = DEFAULT_LIMIT) -> int:
    value = payload.get("limit", default)
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise InternalCompensationAPIError(
            "validation_error",
            "limit must be an integer.",
            status=400,
            details={"field": "limit"},
        ) from exc
    if limit < 1 or limit > MAX_LIMIT:
        raise InternalCompensationAPIError(
            "validation_error",
            f"limit must be between 1 and {MAX_LIMIT}.",
            status=400,
            details={"field": "limit", "maximum": MAX_LIMIT},
        )
    return limit


def _parse_cursor(payload: dict[str, Any]) -> int:
    value = payload.get("cursor", 0)
    if value in ("", None):
        return 0
    try:
        cursor = int(value)
    except (TypeError, ValueError) as exc:
        raise InternalCompensationAPIError(
            "validation_error",
            "cursor must be an integer offset.",
            status=400,
            details={"field": "cursor"},
        ) from exc
    if cursor < 0:
        raise InternalCompensationAPIError(
            "validation_error",
            "cursor must be zero or greater.",
            status=400,
            details={"field": "cursor"},
        )
    return cursor


def _page(items: list[Any], *, cursor: int, limit: int) -> tuple[list[Any], str | None]:
    page = items[cursor : cursor + limit]
    next_cursor = str(cursor + limit) if len(items) > cursor + limit else None
    return page, next_cursor


def _resolve_outage(snapshot: DataSnapshot, outage_code: str | None) -> Outage:
    if not outage_code:
        raise InternalCompensationAPIError(
            "validation_error",
            "outage_code is required.",
            status=400,
            details={"field": "outage_code"},
        )
    try:
        return (
            Outage.objects.select_related("incident", "source_device")
            .get(data_snapshot=snapshot, outage_code=outage_code)
        )
    except Outage.DoesNotExist as exc:
        raise InternalCompensationAPIError(
            "not_found",
            "Outage was not found.",
            status=404,
            details={"outage_code": outage_code},
        ) from exc


def _resolve_subscription(snapshot: DataSnapshot, subscription_number: str | None) -> Subscription:
    if not subscription_number:
        raise InternalCompensationAPIError(
            "validation_error",
            "subscription_number is required.",
            status=400,
            details={"field": "subscription_number"},
        )
    try:
        return (
            Subscription.objects.select_related(
                "customer",
                "service_package",
                "sla_profile",
            )
            .get(data_snapshot=snapshot, subscription_number=subscription_number)
        )
    except Subscription.DoesNotExist as exc:
        raise InternalCompensationAPIError(
            "not_found",
            "Subscription was not found.",
            status=404,
            details={"subscription_number": subscription_number},
        ) from exc


def _validate_rule_inputs(
    *,
    snapshot: DataSnapshot,
    rule_code: str | None,
    rule_set_code: str | None,
) -> tuple[Rule | None, RuleSet | None]:
    if not rule_code and not rule_set_code:
        raise InternalCompensationAPIError(
            "validation_error",
            "rule_code or rule_set_code is required.",
            status=400,
            details={"fields": ["rule_code", "rule_set_code"]},
        )
    rule = None
    rule_set = None
    if rule_code:
        rule = (
            Rule.objects.select_related("rule_set")
            .filter(data_snapshot=snapshot, code=rule_code)
            .first()
        )
        if rule is None:
            raise InternalCompensationAPIError(
                "not_found",
                "Rule was not found.",
                status=404,
                details={"rule_code": rule_code},
            )
    if rule_set_code:
        rule_set = (
            RuleSet.objects.filter(data_snapshot=snapshot, code=rule_set_code)
            .order_by("version")
            .first()
        )
        if rule_set is None:
            raise InternalCompensationAPIError(
                "not_found",
                "RuleSet was not found.",
                status=404,
                details={"rule_set_code": rule_set_code},
            )
    if rule and rule_set and rule.rule_set_id != rule_set.id:
        raise InternalCompensationAPIError(
            "validation_error",
            "rule_code must belong to the requested rule_set_code.",
            status=400,
            details={"rule_code": rule_code, "rule_set_code": rule_set_code},
        )
    return rule, rule_set


def _require_finalizable_outage(outage: Outage, *, persist: bool) -> None:
    if outage.status == OutageStatus.OPEN or outage.ended_at is None:
        if persist:
            raise InternalCompensationAPIError(
                "validation_error",
                "persist=true is not allowed for ongoing outages.",
                status=400,
                details={"outage_code": outage.outage_code},
            )
        return


def _evaluate_mvp_refund(
    *,
    service: CompensationService,
    snapshot: DataSnapshot,
    outage: Outage,
    subscription: Subscription,
    evaluation_time,
    rule_code: str,
):
    try:
        return service.evaluate_subscription(
            outage=outage,
            subscription=subscription,
            snapshot=snapshot,
            evaluation_time=evaluation_time,
            rule_code=rule_code,
        )
    except CompensationInputError as exc:
        raise InternalCompensationAPIError(
            "validation_error",
            str(exc),
            status=400,
        ) from exc


def _selected_rule_version(
    snapshot: DataSnapshot,
    *,
    result,
    rule_code: str,
) -> RuleVersion | None:
    if result.rule_version is None:
        return None
    return (
        RuleVersion.objects.select_related("rule", "rule__rule_set")
        .filter(
            data_snapshot=snapshot,
            rule__code=rule_code,
            version=result.rule_version,
        )
        .first()
    )


def _result_type_for_decision(decision: str) -> str:
    if decision == "eligible":
        return CompensationResultType.ELIGIBLE
    if decision == "ineligible":
        return CompensationResultType.NOT_ELIGIBLE
    if decision == "manual_review":
        return CompensationResultType.MANUAL_REVIEW
    return CompensationResultType.INSUFFICIENT_DATA


def _decision_for_evidence(decision: str) -> str:
    if decision == "eligible":
        return "eligible"
    if decision == "ineligible":
        return "ineligible"
    if decision == "manual_review":
        return "manual_review"
    return "evidence_only"


def _evaluation_code(
    *,
    snapshot: DataSnapshot,
    outage: Outage,
    subscription: Subscription,
    version,
):
    payload = {
        "snapshot": snapshot.snapshot_key,
        "outage": outage.outage_code,
        "subscription": subscription.subscription_number,
        "rule": version.rule.code if version else None,
        "version": version.version if version else None,
    }
    return f"CE-{build_decision_evidence_hash(payload)[:24].upper()}"


def _existing_conflict_evaluation(
    *,
    snapshot: DataSnapshot,
    outage: Outage,
    subscription: Subscription,
    conflict_group: str,
    version: RuleVersion | None = None,
):
    queryset = (
        CompensationEvaluation.objects.select_related(
            "rule_version",
            "rule_version__rule",
            "outage",
            "subscription",
            "customer",
        )
        .filter(
            data_snapshot=snapshot,
            outage=outage,
            subscription=subscription,
        )
    )
    if conflict_group:
        queryset = queryset.filter(rule_version__rule__conflict_group=conflict_group)
    elif version is not None:
        queryset = queryset.filter(rule_version=version)
    else:
        return None
    return queryset.order_by("created_at", "evaluation_code").first()


def _existing_evidence_for_evaluation(evaluation: CompensationEvaluation):
    return (
        DecisionEvidence.objects.select_related(
            "rule_set",
            "selected_rule_version",
            "selected_rule_version__rule",
            "compensation_evaluation",
            "compensation_evaluation__outage",
            "compensation_evaluation__subscription",
            "compensation_evaluation__customer",
        )
        .filter(compensation_evaluation=evaluation)
        .first()
    )


def _build_evidence(
    *,
    service: CompensationService,
    snapshot: DataSnapshot,
    result,
    evaluation: CompensationEvaluation,
    version,
):
    return service.create_decision_evidence(
        data_snapshot=snapshot,
        compensation_evaluation=evaluation,
        rule_set=version.rule.rule_set if version and version.rule.rule_set_id else None,
        selected_rule_version=version,
        price_basis="contracted_monthly_price",
        selected_price=result.monthly_price,
        unrounded_amount=result.compensation_amount,
        final_amount=result.compensation_amount,
        currency=result.currency,
        decision=_decision_for_evidence(result.status),
        matched_conditions=result.matched_conditions,
        failed_conditions=result.unmatched_conditions,
        excluded_rules=[],
        candidate_base_rules=[],
        applied_modifiers=[],
        formula_inputs={
            "refund_rate": str(result.refund_rate) if result.refund_rate is not None else None,
            "monthly_price": (
                str(result.monthly_price) if result.monthly_price is not None else None
            ),
        },
        cap_floor_trace=[],
        manual_review_reasons=result.missing_fields if result.status == "manual_review" else [],
        context_snapshot={
            "outage_code": result.outage_code,
            "subscription_code": result.subscription_code,
            "reason_code": result.reason_code,
            "calculation_trace": result.calculation_trace,
        },
    )


def _evaluate_policy_amount(
    *,
    snapshot: DataSnapshot,
    outage: Outage,
    subscription: Subscription,
    rule_set: RuleSet,
    evaluation_time,
):
    context = _build_policy_context(
        outage,
        subscription,
        evaluation_time=evaluation_time,
    )
    policy = RuleEvaluationService().evaluate_rule_set(
        snapshot=snapshot,
        rule_set_code=rule_set.code,
        event_datetime=evaluation_time,
        context=context,
    )
    selected = policy.selected_base_rule
    version = None
    amount = None
    if selected:
        version = (
            RuleVersion.objects.select_related("rule", "rule__rule_set")
            .filter(
                data_snapshot=snapshot,
                rule__code=selected.rule_code,
                version=selected.rule_version,
            )
            .first()
        )
        amount = CompensationService().calculate_policy_amount(
            action_type=selected.action_type,
            action_config=selected.action_config,
            price_basis_amount=subscription.monthly_price,
            context=context,
        )
    return policy, selected, version, amount, context


def _evaluate_policy_ruleset_only(
    *,
    snapshot: DataSnapshot,
    outage: Outage,
    subscription: Subscription,
    rule_set: RuleSet,
    evaluation_time,
):
    context = _build_policy_context(
        outage,
        subscription,
        evaluation_time=evaluation_time,
    )
    policy = RuleEvaluationService().evaluate_rule_set(
        snapshot=snapshot,
        rule_set_code=rule_set.code,
        event_datetime=evaluation_time,
        context=context,
    )
    return policy


def _requested_policy_rule_was_selected(
    *,
    rule: Rule | None,
    selected,
) -> None:
    if rule is None or rule.rule_set_id is None or selected is None:
        return
    if selected.rule_code != rule.code:
        raise InternalCompensationAPIError(
            "conflict",
            "Requested rule_code is not the deterministic selected base rule.",
            status=409,
            details={
                "requested_rule_code": rule.code,
                "selected_rule_code": selected.rule_code,
                "conflict_group": rule.conflict_group,
            },
        )


def _policy_decision(policy, amount) -> str:
    if policy.evaluation_status == "manual_review":
        return "manual_review"
    if amount is None:
        return "ineligible"
    return amount.status


def _policy_amount_response(
    policy,
    selected,
    amount,
    *,
    price_basis_amount=None,
    persisted=False,
    existing_result=False,
):
    decision = _policy_decision(policy, amount)
    return {
        "decision": decision,
        "reason_code": amount.reason_code if amount else policy.evaluation_status,
        "selected_rule": (
            {"rule_code": selected.rule_code, "version": selected.rule_version}
            if selected
            else None
        ),
        "price_basis": selected.price_basis if selected else None,
        "selected_price": str(price_basis_amount) if amount else None,
        "unrounded_amount": str(amount.unrounded_amount) if amount else "0.00",
        "final_amount": str(amount.final_amount) if amount else "0.00",
        "currency": amount.currency if amount else None,
        "rounding_trace": amount.calculation_trace if amount else [],
        "modifier_trace": [asdict(item) for item in policy.applied_modifiers],
        "cap_floor_trace": [],
        "excluded_rules": policy.excluded_rules,
        "manual_review_reasons": (
            policy.manual_review_reasons
            + (amount.manual_review_reasons if amount else [])
        ),
        "candidate_base_rules": [asdict(item) for item in policy.candidate_base_rules],
        "persisted": persisted,
        "existing_result": existing_result,
    }


def _create_policy_evidence(
    *,
    service: CompensationService,
    snapshot: DataSnapshot,
    evaluation: CompensationEvaluation,
    rule_set: RuleSet,
    version: RuleVersion,
    policy,
    selected,
    amount,
    context: dict[str, Any],
):
    return service.create_decision_evidence(
        data_snapshot=snapshot,
        compensation_evaluation=evaluation,
        rule_set=rule_set,
        selected_rule_version=version,
        price_basis=selected.price_basis,
        selected_price=evaluation.subscription.monthly_price,
        unrounded_amount=amount.unrounded_amount,
        final_amount=amount.final_amount,
        currency=amount.currency,
        decision=_decision_for_evidence(amount.status),
        matched_conditions=selected.matched_conditions,
        failed_conditions=selected.unmatched_conditions,
        excluded_rules=policy.excluded_rules,
        candidate_base_rules=[asdict(item) for item in policy.candidate_base_rules],
        applied_modifiers=[asdict(item) for item in policy.applied_modifiers],
        formula_inputs=context,
        cap_floor_trace=amount.calculation_trace,
        manual_review_reasons=policy.manual_review_reasons + amount.manual_review_reasons,
        context_snapshot={"evaluation_status": policy.evaluation_status},
    )


@require_http_methods(["POST"])
@internal_service_required
def evaluate_refund_eligibility(request):
    try:
        payload = _request_payload(request)
        snapshot = _resolve_snapshot(payload.get("snapshot_identifier"))
        outage = _resolve_outage(snapshot, payload.get("outage_code"))
        subscription = _resolve_subscription(snapshot, payload.get("subscription_number"))
        evaluation_time = _parse_dt(payload.get("evaluation_time"), field_name="evaluation_time")
        rule, _rule_set = _validate_rule_inputs(
            snapshot=snapshot,
            rule_code=payload.get("rule_code"),
            rule_set_code=payload.get("rule_set_code"),
        )
        _require_finalizable_outage(outage, persist=False)
        policy_rule_set = _rule_set or (rule.rule_set if rule and rule.rule_set_id else None)
        if policy_rule_set is not None:
            policy = _evaluate_policy_ruleset_only(
                snapshot=snapshot,
                outage=outage,
                subscription=subscription,
                rule_set=policy_rule_set,
                evaluation_time=evaluation_time or outage.started_at,
            )
            _requested_policy_rule_was_selected(
                rule=rule,
                selected=policy.selected_base_rule,
            )
            response = {
                "decision": (
                    "manual_review"
                    if policy.evaluation_status == "manual_review"
                    else "eligible"
                    if policy.selected_base_rule
                    else "ineligible"
                ),
                "reason_code": policy.evaluation_status,
                "selected_rule": (
                    {
                        "rule_code": policy.selected_base_rule.rule_code,
                        "version": policy.selected_base_rule.rule_version,
                    }
                    if policy.selected_base_rule
                    else None
                ),
                "matched_conditions": (
                    policy.selected_base_rule.matched_conditions
                    if policy.selected_base_rule
                    else []
                ),
                "failed_conditions": (
                    policy.selected_base_rule.unmatched_conditions
                    if policy.selected_base_rule
                    else []
                ),
                "missing_fields": policy.manual_review_reasons,
                "deferred_checks": [],
                "manual_review_reasons": policy.manual_review_reasons,
                "candidate_base_rules": [asdict(item) for item in policy.candidate_base_rules],
                "excluded_rules": policy.excluded_rules,
            }
            response["amount_status"] = "not_calculated"
            return _ok(
                request=request,
                snapshot=snapshot,
                data={
                    "outage": outage_summary(outage),
                    "subscription": subscription_summary(subscription),
                    "eligibility": response,
                },
            )
        result = _evaluate_mvp_refund(
            service=CompensationService(),
            snapshot=snapshot,
            outage=outage,
            subscription=subscription,
            evaluation_time=evaluation_time,
            rule_code=rule.code if rule else payload.get("rule_code"),
        )
        response = compensation_result_summary(result)
        response["amount_status"] = "not_calculated"
        response.pop("final_amount", None)
        response.pop("selected_price", None)
        response.pop("refund_rate", None)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "outage": outage_summary(outage),
                "subscription": subscription_summary(subscription),
                "eligibility": response,
            },
        )
    except InternalCompensationAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_http_methods(["POST"])
@internal_service_required
def calculate_refund_amount(request):
    try:
        payload = _request_payload(request)
        persist = _parse_bool(payload, "persist", default=False)
        snapshot = _resolve_snapshot(payload.get("snapshot_identifier"))
        outage = _resolve_outage(snapshot, payload.get("outage_code"))
        subscription = _resolve_subscription(snapshot, payload.get("subscription_number"))
        evaluation_time = _parse_dt(payload.get("evaluation_time"), field_name="evaluation_time")
        rule, _rule_set = _validate_rule_inputs(
            snapshot=snapshot,
            rule_code=payload.get("rule_code"),
            rule_set_code=payload.get("rule_set_code"),
        )
        _require_finalizable_outage(outage, persist=persist)
        service = CompensationService()
        policy_rule_set = _rule_set or (rule.rule_set if rule and rule.rule_set_id else None)
        if policy_rule_set is not None:
            policy, selected, version, amount, context = _evaluate_policy_amount(
                snapshot=snapshot,
                outage=outage,
                subscription=subscription,
                rule_set=policy_rule_set,
                evaluation_time=evaluation_time or outage.started_at,
            )
            _requested_policy_rule_was_selected(rule=rule, selected=selected)
            if persist and (selected is None or version is None or amount is None):
                raise InternalCompensationAPIError(
                    "validation_error",
                    "A selected RuleVersion is required before persisting compensation.",
                    status=400,
                            details={"rule_set_code": policy_rule_set.code},
                )
            persisted = False
            existing_result = False
            evaluation = None
            evidence = None
            if persist:
                with transaction.atomic():
                    if service.has_final_compensation_for_conflict_group(
                        subscription=subscription,
                        incident=outage.incident,
                        conflict_group=version.rule.conflict_group,
                    ):
                        raise InternalCompensationAPIError(
                            "conflict",
                            "A final compensation history exists for this conflict group.",
                            status=409,
                            details={"conflict_group": version.rule.conflict_group},
                        )
                    existing = _existing_conflict_evaluation(
                        snapshot=snapshot,
                        outage=outage,
                        subscription=subscription,
                        conflict_group=version.rule.conflict_group,
                        version=version,
                    )
                    if existing:
                        evaluation = existing
                        evidence = _existing_evidence_for_evaluation(existing)
                        existing_result = True
                    else:
                        evaluation = CompensationEvaluation.objects.create(
                            data_snapshot=snapshot,
                            evaluation_code=_evaluation_code(
                                snapshot=snapshot,
                                outage=outage,
                                subscription=subscription,
                                version=version,
                            ),
                            outage=outage,
                            customer=subscription.customer,
                            subscription=subscription,
                            rule_version=version,
                            result_type=_result_type_for_decision(amount.status),
                            status=CompensationEvaluationStatus.CALCULATED,
                            proposed_amount=amount.final_amount,
                            currency=amount.currency,
                            explanation=amount.reason_code,
                            calculation_trace={
                                "policy_evaluation": policy.evaluation_status,
                                "calculation_trace": amount.calculation_trace,
                            },
                            metadata={
                                "source": "compensation_mcp",
                                "conflict_group": version.rule.conflict_group,
                            },
                        )
                    if evidence is None:
                        evidence = _create_policy_evidence(
                            service=service,
                            snapshot=snapshot,
                            evaluation=evaluation,
                            rule_set=policy_rule_set,
                            version=version,
                            policy=policy,
                            selected=selected,
                            amount=amount,
                            context=context,
                        )
                    persisted = True
            data = _policy_amount_response(
                policy,
                selected,
                amount,
                price_basis_amount=subscription.monthly_price,
                persisted=persisted,
                existing_result=existing_result,
            )
            data.update(
                {
                    "evaluation": evaluation_summary(evaluation),
                    "decision_evidence": evidence_summary(evidence),
                    "evidence_hash": evidence.evidence_hash if evidence else None,
                }
            )
            return _ok(
                request=request,
                snapshot=snapshot,
                data={
                    "outage": outage_summary(outage),
                    "subscription": subscription_summary(subscription),
                    "compensation": data,
                },
            )
        result = _evaluate_mvp_refund(
            service=service,
            snapshot=snapshot,
            outage=outage,
            subscription=subscription,
            evaluation_time=evaluation_time,
            rule_code=rule.code if rule else payload.get("rule_code"),
        )
        version = _selected_rule_version(snapshot, result=result, rule_code=result.rule_code)
        if persist and version is None:
            raise InternalCompensationAPIError(
                "validation_error",
                "A selected RuleVersion is required before persisting compensation.",
                status=400,
                details={"rule_code": result.rule_code},
            )
        persisted = False
        existing_result = False
        evaluation = None
        evidence = None
        if persist:
            with transaction.atomic():
                history_duplicate = service.has_final_compensation_for_conflict_group(
                    subscription=subscription,
                    incident=outage.incident,
                    conflict_group=version.rule.conflict_group,
                )
                if history_duplicate:
                    raise InternalCompensationAPIError(
                        "conflict",
                        "A final compensation history exists for this conflict group.",
                        status=409,
                        details={"conflict_group": version.rule.conflict_group},
                    )
                existing = _existing_conflict_evaluation(
                    snapshot=snapshot,
                    outage=outage,
                    subscription=subscription,
                    conflict_group=version.rule.conflict_group,
                    version=version,
                )
                if existing:
                    evaluation = existing
                    evidence = _existing_evidence_for_evaluation(existing)
                    existing_result = True
                else:
                    evaluation = CompensationEvaluation.objects.create(
                        data_snapshot=snapshot,
                        evaluation_code=_evaluation_code(
                            snapshot=snapshot,
                            outage=outage,
                            subscription=subscription,
                            version=version,
                        ),
                        outage=outage,
                        customer=subscription.customer,
                        subscription=subscription,
                        rule_version=version,
                        result_type=_result_type_for_decision(result.status),
                        status=CompensationEvaluationStatus.CALCULATED,
                        proposed_amount=result.compensation_amount,
                        currency=result.currency,
                        explanation=result.reason_code,
                        calculation_trace={
                            "calculation_trace": result.calculation_trace,
                            "matched_conditions": result.matched_conditions,
                            "unmatched_conditions": result.unmatched_conditions,
                            "missing_fields": result.missing_fields,
                        },
                        metadata={
                            "source": "compensation_mcp",
                            "conflict_group": version.rule.conflict_group,
                        },
                    )
                    evidence = _existing_evidence_for_evaluation(evaluation)
                    if evidence is None:
                        evidence = _build_evidence(
                            service=service,
                            snapshot=snapshot,
                            result=result,
                            evaluation=evaluation,
                            version=version,
                        )
                    persisted = True
        data = compensation_result_summary(result)
        data.update(
            {
                "unrounded_amount": str(result.compensation_amount),
                "rounding_trace": result.calculation_trace,
                "modifier_trace": [],
                "cap_floor_trace": [],
                "excluded_rules": [],
                "persisted": persisted,
                "existing_result": existing_result,
                "evaluation": evaluation_summary(evaluation),
                "decision_evidence": evidence_summary(evidence),
                "evidence_hash": evidence.evidence_hash if evidence else None,
            }
        )
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "outage": outage_summary(outage),
                "subscription": subscription_summary(subscription),
                "compensation": data,
            },
        )
    except InternalCompensationAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


def _build_policy_context(
    outage: Outage,
    subscription: Subscription,
    *,
    evaluation_time=None,
) -> dict[str, Any]:
    try:
        duration = OutageService().calculate_duration(
            outage=outage,
            evaluation_time=evaluation_time,
        )
    except Exception as exc:  # noqa: BLE001
        raise InternalCompensationAPIError(
            "validation_error",
            str(exc),
            status=400,
        ) from exc
    return {
        "service_type": subscription.service_package.service_type,
        "impact_class": outage.impact_type,
        "outage_duration_seconds": duration.seconds,
        "affected_duration_seconds": duration.seconds,
        "subscription_active_during_outage": True,
        "connection_active_during_outage": True,
        "customer_impacted": True,
        "price_available": subscription.monthly_price is not None,
        "root_cause_known": outage.root_cause_category != "unknown",
        "subscription_status": subscription.status,
        "suspension_reason": subscription.suspension_reason,
        "protection_loss_only": outage.impact_type == "protection_loss",
        "incident_type": outage.incident.incident_type if outage.incident_id else "",
        "maintenance_overrun_minutes": 0,
    }


def _policy_candidate_payload(candidate: PolicyRuleCandidate, *, amount=None) -> dict[str, Any]:
    payload = asdict(candidate)
    payload["amount"] = policy_result_summary(amount) if amount else None
    payload.pop("action_config", None)
    return payload


@require_http_methods(["POST"])
@internal_service_required
def evaluate_compensation_options(request):
    try:
        payload = _request_payload(request)
        snapshot = _resolve_snapshot(payload.get("snapshot_identifier"))
        outage = _resolve_outage(snapshot, payload.get("outage_code"))
        subscription = _resolve_subscription(snapshot, payload.get("subscription_number"))
        evaluation_time = _parse_dt(
            payload.get("evaluation_time") or outage.started_at.isoformat(),
            field_name="evaluation_time",
        )
        include_ineligible = _parse_bool(payload, "include_ineligible", default=False)
        _rule, rule_set = _validate_rule_inputs(
            snapshot=snapshot,
            rule_code=None,
            rule_set_code=payload.get("rule_set_code"),
        )
        context = _build_policy_context(
            outage,
            subscription,
            evaluation_time=evaluation_time,
        )
        evaluation = RuleEvaluationService().evaluate_rule_set(
            snapshot=snapshot,
            rule_set_code=rule_set.code,
            event_datetime=evaluation_time,
            context=context,
        )
        service = CompensationService()
        candidates = []
        for candidate in evaluation.candidate_base_rules:
            amount = service.calculate_policy_amount(
                action_type=candidate.action_type,
                action_config=candidate.action_config,
                price_basis_amount=subscription.monthly_price,
                context=context,
            )
            if include_ineligible or amount.status != "ineligible":
                candidates.append(_policy_candidate_payload(candidate, amount=amount))
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "rule_set": rule_set_payload(rule_set),
                "selected_base_rule": (
                    _policy_candidate_payload(evaluation.selected_base_rule)
                    if evaluation.selected_base_rule
                    else None
                ),
                "candidate_base_rules": candidates,
                "modifiers": [
                    _policy_candidate_payload(item)
                    for item in evaluation.applied_modifiers
                ],
                "excluded_rules": evaluation.excluded_rules,
                "manual_review_reasons": evaluation.manual_review_reasons,
                "evaluation_status": evaluation.evaluation_status,
                "persisted": False,
            },
        )
    except InternalCompensationAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_http_methods(["POST"])
@internal_service_required
def check_campaign_eligibility(request):
    try:
        payload = _request_payload(request)
        snapshot = _resolve_snapshot(payload.get("snapshot_identifier"))
        subscription = _resolve_subscription(snapshot, payload.get("subscription_number"))
        evaluation_time = _parse_dt(payload.get("evaluation_time"), field_name="evaluation_time")
        campaign_code = payload.get("campaign_code")
        queryset = (
            CampaignEnrollment.objects.filter(data_snapshot=snapshot, subscription=subscription)
            .select_related("campaign")
            .order_by("campaign_code", "valid_from")
        )
        if campaign_code:
            queryset = queryset.filter(campaign_code=campaign_code)
        enrollments = list(queryset)
        catalog_campaign = None
        if campaign_code:
            catalog_campaign = Campaign.objects.filter(
                data_snapshot=snapshot,
                code=campaign_code,
            ).first()
        status = "enrolled" if enrollments else "not_enrolled" if catalog_campaign else "unknown"
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "subscription": subscription_summary(subscription),
                "campaign_code": campaign_code,
                "status": status,
                "decision_source": "campaign_enrollment_read_model",
                "enrollments": [
                    campaign_enrollment_summary(item, evaluation_time=evaluation_time)
                    for item in enrollments
                ],
                "catalog_campaign_exists": catalog_campaign is not None,
                "persisted": False,
            },
            warnings=[
                {
                    "code": "no_campaign_eligibility_engine",
                    "message": "No new campaign eligibility decision is calculated.",
                    "details": {},
                }
            ],
        )
    except InternalCompensationAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_http_methods(["POST"])
@internal_service_required
def rank_compensation_options(request):
    try:
        payload = _request_payload(request)
        snapshot = _resolve_snapshot(payload.get("snapshot_identifier"))
        outage = _resolve_outage(snapshot, payload.get("outage_code"))
        subscription = _resolve_subscription(snapshot, payload.get("subscription_number"))
        evaluation_time = _parse_dt(
            payload.get("evaluation_time") or outage.started_at.isoformat(),
            field_name="evaluation_time",
        )
        limit = _parse_limit(payload, default=10)
        _rule, rule_set = _validate_rule_inputs(
            snapshot=snapshot,
            rule_code=None,
            rule_set_code=payload.get("rule_set_code"),
        )
        context = _build_policy_context(
            outage,
            subscription,
            evaluation_time=evaluation_time,
        )
        evaluation = RuleEvaluationService().evaluate_rule_set(
            snapshot=snapshot,
            rule_set_code=rule_set.code,
            event_datetime=evaluation_time,
            context=context,
        )
        service = CompensationService()
        ranked = []
        for candidate in evaluation.candidate_base_rules:
            amount = service.calculate_policy_amount(
                action_type=candidate.action_type,
                action_config=candidate.action_config,
                price_basis_amount=subscription.monthly_price,
                context=context,
            )
            ranked.append(_policy_candidate_payload(candidate, amount=amount))
        ranked = sorted(
            ranked,
            key=lambda item: (
                item["priority"],
                -item["specific_condition_count"],
                item["rule_code"],
            ),
        )[:limit]
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "rule_set": rule_set_payload(rule_set),
                "ranked_options": ranked,
                "ordering_reason": (
                    "Existing rule priority, specificity, and rule-code tie-break from "
                    "deterministic rule evaluation are used."
                ),
                "partial_order": False,
                "persisted": False,
            },
        )
    except InternalCompensationAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def get_compensation_evidence(request):
    try:
        payload = _request_payload(request)
        snapshot = _resolve_snapshot(payload.get("snapshot_identifier"))
        identifiers = [
            "evaluation_code",
            "evidence_hash",
            "outage_code",
            "subscription_number",
            "rule_code",
        ]
        if not any(payload.get(field) for field in identifiers):
            raise InternalCompensationAPIError(
                "validation_error",
                "At least one evidence identifier is required.",
                status=400,
                details={"fields": identifiers},
            )
        limit = _parse_limit(payload)
        cursor = _parse_cursor(payload)
        evaluations = _filter_evaluations(snapshot=snapshot, payload=payload)
        evidence = _filter_evidence(snapshot=snapshot, payload=payload)
        summary = _compensation_evidence_summary(evaluations=evaluations, evidence=evidence)
        eval_page, eval_next = _page(list(evaluations), cursor=cursor, limit=limit)
        evidence_page, evidence_next = _page(list(evidence), cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "evaluations": [evaluation_summary(item) for item in eval_page],
                "decision_evidence": [evidence_summary(item) for item in evidence_page],
                "result_count": max(len(eval_page), len(evidence_page)),
                "next_cursor": eval_next or evidence_next,
                "summary": summary,
            },
        )
    except InternalCompensationAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


def _filter_evaluations(*, snapshot: DataSnapshot, payload: dict[str, Any]):
    queryset = (
        CompensationEvaluation.objects.filter(data_snapshot=snapshot)
        .select_related(
            "outage",
            "outage__incident",
            "customer",
            "subscription",
            "rule_version",
            "rule_version__rule",
        )
        .order_by("-created_at", "evaluation_code")
    )
    if payload.get("evaluation_code"):
        queryset = queryset.filter(evaluation_code=payload["evaluation_code"])
    if payload.get("outage_code"):
        queryset = queryset.filter(outage__outage_code=payload["outage_code"])
    if payload.get("subscription_number"):
        queryset = queryset.filter(subscription__subscription_number=payload["subscription_number"])
    if payload.get("rule_code"):
        queryset = queryset.filter(rule_version__rule__code=payload["rule_code"])
    if payload.get("decision"):
        queryset = queryset.filter(result_type=payload["decision"])
    return queryset


def _filter_evidence(*, snapshot: DataSnapshot, payload: dict[str, Any]):
    queryset = (
        DecisionEvidence.objects.filter(data_snapshot=snapshot)
        .select_related(
            "rule_set",
            "selected_rule_version",
            "selected_rule_version__rule",
            "selected_rule_version__rule__rule_set",
            "compensation_evaluation",
            "compensation_evaluation__outage",
            "compensation_evaluation__subscription",
            "compensation_evaluation__customer",
        )
        .order_by("-created_at", "evidence_hash")
    )
    if payload.get("evidence_hash"):
        queryset = queryset.filter(evidence_hash=payload["evidence_hash"])
    if payload.get("evaluation_code"):
        queryset = queryset.filter(
            compensation_evaluation__evaluation_code=payload["evaluation_code"]
        )
    if payload.get("outage_code"):
        queryset = queryset.filter(
            compensation_evaluation__outage__outage_code=payload["outage_code"]
        )
    if payload.get("subscription_number"):
        queryset = queryset.filter(
            compensation_evaluation__subscription__subscription_number=payload[
                "subscription_number"
            ]
        )
    if payload.get("rule_code"):
        queryset = queryset.filter(selected_rule_version__rule__code=payload["rule_code"])
    if payload.get("decision"):
        queryset = queryset.filter(decision=payload["decision"])
    return queryset


def _compensation_evidence_summary(*, evaluations, evidence) -> dict[str, Any]:
    """Summarize all persisted matches instead of treating a page row as the answer."""
    # Pagination has a deterministic display order. It must not leak into GROUP BY
    # queries, where PostgreSQL would otherwise split identical values per row.
    summary_evaluations = evaluations.order_by()
    summary_evidence = evidence.order_by()
    aggregate = summary_evaluations.aggregate(
        consideration_count=Count("id"),
        total_amount=Sum("proposed_amount"),
    )
    consideration_count = aggregate["consideration_count"]
    if not consideration_count:
        return {
            "status": "pending",
            "consideration_count": None,
            "eligible": None,
            "ineligible_pending": None,
            "total_amount": None,
            "currency": None,
            "rule_versions": {},
            "evidence_reference": None,
            "evidence_count": 0,
        }

    result_counts = {
        row["result_type"]: row["count"]
        for row in summary_evaluations.values("result_type").annotate(count=Count("id"))
    }
    statuses = list(summary_evaluations.values_list("status", flat=True).distinct()[:2])
    currencies = list(summary_evaluations.values_list("currency", flat=True).distinct()[:2])
    rule_versions = {
        f"{row['rule_version__rule__code']}:v{row['rule_version__version']}": row["count"]
        for row in summary_evaluations.values(
            "rule_version__rule__code", "rule_version__version"
        ).annotate(count=Count("id"))
    }
    first_evidence = summary_evidence.values_list("evidence_hash", flat=True).first()
    return {
        "status": statuses[0] if len(statuses) == 1 else "mixed",
        "consideration_count": consideration_count,
        "eligible": result_counts.get(CompensationResultType.ELIGIBLE, 0),
        "ineligible_pending": consideration_count
        - result_counts.get(CompensationResultType.ELIGIBLE, 0),
        "total_amount": aggregate["total_amount"],
        "currency": currencies[0] if len(currencies) == 1 else None,
        "rule_versions": rule_versions,
        # The public read-only evidence detail endpoint is snapshot-local and
        # requires the immutable full hash. Presentation layers may abbreviate it.
        "evidence_reference": first_evidence,
        "evidence_count": summary_evidence.count(),
    }
