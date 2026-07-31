from __future__ import annotations

from dataclasses import asdict
from typing import Any

from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from apps.compensation.models import DecisionEvidence
from apps.core.internal_api import internal_service_required
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.rules.internal_serializers import (
    decision_evidence_summary,
    rule_set_summary,
    rule_summary,
    safe_payload,
    snapshot_payload,
    version_detail,
    version_summary,
)
from apps.rules.models import Rule, RuleVersion, RuleVersionStatus
from apps.rules.services.evaluation import PolicyRuleCandidate, select_primary_base_rule
from apps.rules.services.version_selection import select_rule_version_for_moment

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class InternalRuleAPIError(Exception):
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


def _error(exc: InternalRuleAPIError) -> JsonResponse:
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
        InternalRuleAPIError(
            "internal_error",
            "Rule internal API failed.",
            status=500,
            details={"reason": exc.__class__.__name__},
        )
    )


def _resolve_snapshot(identifier: str | None) -> DataSnapshot:
    if not identifier:
        raise InternalRuleAPIError(
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
        raise InternalRuleAPIError(
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
        raise InternalRuleAPIError(
            "validation_error",
            "Dataset slug must resolve to exactly one snapshot.",
            status=400,
            details={"dataset_slug": identifier, "snapshot_count": len(snapshots)},
        )
    return snapshots[0]


def _parse_dt(value: str | None, *, field_name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise InternalRuleAPIError(
                "validation_error",
                f"{field_name} is required.",
                status=400,
                details={"field": field_name},
            )
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise InternalRuleAPIError(
            "validation_error",
            f"{field_name} must be a valid ISO 8601 datetime.",
            status=400,
            details={"field": field_name},
        )
    if timezone.is_naive(parsed):
        raise InternalRuleAPIError(
            "validation_error",
            f"{field_name} must be timezone-aware.",
            status=400,
            details={"field": field_name},
        )
    return parsed


def _parse_bool(request, field_name: str, *, default: bool = False) -> bool:
    value = request.GET.get(field_name)
    if value in (None, ""):
        return default
    if value.lower() in {"true", "1", "yes"}:
        return True
    if value.lower() in {"false", "0", "no"}:
        return False
    raise InternalRuleAPIError(
        "validation_error",
        f"{field_name} must be a boolean.",
        status=400,
        details={"field": field_name},
    )


def _parse_limit(request, *, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    value = request.GET.get("limit", str(default))
    try:
        limit = int(value)
    except ValueError as exc:
        raise InternalRuleAPIError(
            "validation_error",
            "limit must be an integer.",
            status=400,
            details={"field": "limit"},
        ) from exc
    if limit < 1 or limit > maximum:
        raise InternalRuleAPIError(
            "validation_error",
            f"limit must be between 1 and {maximum}.",
            status=400,
            details={"field": "limit", "maximum": maximum},
        )
    return limit


def _parse_cursor(request) -> int:
    value = request.GET.get("cursor", "0")
    if value in ("", None):
        return 0
    try:
        cursor = int(value)
    except ValueError as exc:
        raise InternalRuleAPIError(
            "validation_error",
            "cursor must be an integer offset.",
            status=400,
            details={"field": "cursor"},
        ) from exc
    if cursor < 0:
        raise InternalRuleAPIError(
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


def _rule_queryset(snapshot: DataSnapshot):
    return (
        Rule.objects.filter(data_snapshot=snapshot)
        .select_related("rule_set")
        .prefetch_related("versions")
        .order_by("code")
    )


def _version_queryset(snapshot: DataSnapshot):
    return (
        RuleVersion.objects.filter(data_snapshot=snapshot)
        .select_related("rule", "rule__rule_set")
        .order_by("rule__code", "-version")
    )


def _get_rule(snapshot: DataSnapshot, rule_code: str) -> Rule:
    try:
        return _rule_queryset(snapshot).get(code=rule_code)
    except Rule.DoesNotExist as exc:
        raise InternalRuleAPIError(
            "not_found",
            "Rule was not found.",
            status=404,
            details={"rule_code": rule_code},
        ) from exc


def _filter_rules(queryset, request):
    if request.GET.get("rule_set_code"):
        queryset = queryset.filter(rule_set__code=request.GET["rule_set_code"])
    if request.GET.get("rule_code"):
        queryset = queryset.filter(code=request.GET["rule_code"])
    if request.GET.get("family"):
        queryset = queryset.filter(family=request.GET["family"])
    if request.GET.get("rule_type"):
        queryset = queryset.filter(rule_type=request.GET["rule_type"])
    if request.GET.get("status"):
        queryset = queryset.filter(status=request.GET["status"])
    if request.GET.get("conflict_group"):
        queryset = queryset.filter(conflict_group=request.GET["conflict_group"])
    if request.GET.get("action_type"):
        queryset = queryset.filter(versions__action_type=request.GET["action_type"])
    if request.GET.get("price_basis"):
        queryset = queryset.filter(versions__price_basis=request.GET["price_basis"])
    return queryset.distinct()


def _active_version_for_rule(rule: Rule, active_at):
    if active_at is None:
        return None
    selection = select_rule_version_for_moment(
        snapshot=rule.data_snapshot,
        rule_code=rule.code,
        moment=active_at,
    )
    return selection.selected_version if selection.status == "selected" else None


def _latest_version_for_rule(rule: Rule) -> RuleVersion | None:
    return (
        RuleVersion.objects.filter(data_snapshot=rule.data_snapshot, rule=rule)
        .order_by("-version")
        .first()
    )


def _select_rule_version(
    *,
    snapshot: DataSnapshot,
    rule: Rule,
    version_number: int | None,
    effective_at,
):
    if version_number is not None and effective_at is not None:
        raise InternalRuleAPIError(
            "validation_error",
            "version and effective_at cannot be used together.",
            status=400,
            details={"fields": ["version", "effective_at"]},
        )
    if version_number is not None:
        try:
            return RuleVersion.objects.select_related("rule", "rule__rule_set").get(
                data_snapshot=snapshot,
                rule=rule,
                version=version_number,
            )
        except RuleVersion.DoesNotExist as exc:
            raise InternalRuleAPIError(
                "not_found",
                "Rule version was not found.",
                status=404,
                details={"rule_code": rule.code, "version": version_number},
            ) from exc
    if effective_at is not None:
        selection = select_rule_version_for_moment(
            snapshot=snapshot,
            rule_code=rule.code,
            moment=effective_at,
        )
        if selection.status != "selected" or selection.selected_version is None:
            raise InternalRuleAPIError(
                "validation_error",
                "No single effective RuleVersion was selected for effective_at.",
                status=400,
                details={"rule_code": rule.code, "reason": selection.reason},
            )
        return selection.selected_version
    active_versions = list(
        RuleVersion.objects.filter(
            data_snapshot=snapshot,
            rule=rule,
            status=RuleVersionStatus.ACTIVE,
            active=True,
        ).select_related("rule", "rule__rule_set")
    )
    if len(active_versions) != 1:
        raise InternalRuleAPIError(
            "validation_error",
            "Rule version selection is ambiguous without version or effective_at.",
            status=400,
            details={"rule_code": rule.code, "active_version_count": len(active_versions)},
        )
    return active_versions[0]


def _version_overlap_warnings(versions: list[RuleVersion]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for index, first in enumerate(versions):
        for second in versions[index + 1 :]:
            first_end = first.valid_to
            second_end = second.valid_to
            overlaps = (first_end is None or second.valid_from < first_end) and (
                second_end is None or first.valid_from < second_end
            )
            if overlaps:
                warnings.append(
                    {
                        "code": "rule_version_overlap",
                        "message": "Rule versions have overlapping validity ranges.",
                        "details": {
                            "rule_code": first.rule.code,
                            "versions": [first.version, second.version],
                        },
                    }
                )
    return warnings


@require_GET
@internal_service_required
def search_rules(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        active_at = _parse_dt(request.GET.get("active_at"), field_name="active_at")
        rules = list(_filter_rules(_rule_queryset(snapshot), request))
        rows = []
        for rule in rules:
            payload = {"rule": rule_summary(rule)}
            if active_at is not None:
                payload["effective_version_summary"] = version_summary(
                    _active_version_for_rule(rule, active_at)
                )
            else:
                payload["latest_version_summary"] = version_summary(_latest_version_for_rule(rule))
            rows.append(payload)
        page, next_cursor = _page(rows, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "rules": page,
                "result_count": len(page),
                "next_cursor": next_cursor,
                "active_at": active_at.isoformat() if active_at else None,
            },
        )
    except InternalRuleAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def get_rule(request, rule_code: str):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        include_raw_config = _parse_bool(request, "include_raw_config", default=False)
        include_schema_summary = _parse_bool(
            request,
            "include_schema_summary",
            default=True,
        )
        version_number = request.GET.get("version")
        version_number = int(version_number) if version_number not in (None, "") else None
        effective_at = _parse_dt(request.GET.get("effective_at"), field_name="effective_at")
        rule = _get_rule(snapshot, rule_code)
        version = _select_rule_version(
            snapshot=snapshot,
            rule=rule,
            version_number=version_number,
            effective_at=effective_at,
        )
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "rule_set": rule_set_summary(rule.rule_set),
                "rule": rule_summary(rule),
                "selected_version": version_detail(
                    version,
                    include_raw_config=include_raw_config,
                    include_schema_summary=include_schema_summary,
                ),
                "selection": {
                    "version": version_number,
                    "effective_at": effective_at.isoformat() if effective_at else None,
                    "include_raw_config": include_raw_config,
                },
            },
        )
    except ValueError:
        return _error(
            InternalRuleAPIError(
                "validation_error",
                "version must be an integer.",
                status=400,
                details={"field": "version"},
            )
        )
    except InternalRuleAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def get_rules_effective_at(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        evaluation_time = _parse_dt(
            request.GET.get("evaluation_time"),
            field_name="evaluation_time",
            required=True,
        )
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        queryset = _version_queryset(snapshot).filter(
            status=RuleVersionStatus.ACTIVE,
            active=True,
            valid_from__lte=evaluation_time,
        ).filter(Q(valid_to__isnull=True) | Q(valid_to__gt=evaluation_time))
        queryset = _filter_versions(queryset, request)
        rows = [version_summary(version) for version in queryset]
        page, next_cursor = _page(rows, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "evaluation_time": evaluation_time.isoformat(),
                "effective_versions": page,
                "result_count": len(page),
                "next_cursor": next_cursor,
                "note": "Conditions are not evaluated by this endpoint.",
            },
        )
    except InternalRuleAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


def _filter_versions(queryset, request):
    if request.GET.get("rule_set_code"):
        queryset = queryset.filter(rule__rule_set__code=request.GET["rule_set_code"])
    if request.GET.get("rule_code"):
        queryset = queryset.filter(rule__code=request.GET["rule_code"])
    if request.GET.get("family"):
        queryset = queryset.filter(rule__family=request.GET["family"])
    if request.GET.get("rule_type"):
        queryset = queryset.filter(rule__rule_type=request.GET["rule_type"])
    if request.GET.get("conflict_group"):
        queryset = queryset.filter(rule__conflict_group=request.GET["conflict_group"])
    return queryset.order_by("priority", "rule__code", "version")


@require_GET
@internal_service_required
def get_rule_version_history(request, rule_code: str):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        include_raw_config = _parse_bool(request, "include_raw_config", default=False)
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        rule = _get_rule(snapshot, rule_code)
        versions = list(
            RuleVersion.objects.filter(data_snapshot=snapshot, rule=rule)
            .select_related("rule", "rule__rule_set")
            .order_by("valid_from", "version")
        )
        rows = [
            version_detail(
                version,
                include_raw_config=include_raw_config,
                include_schema_summary=True,
            )
            for version in versions
        ]
        page, next_cursor = _page(rows, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "rule": rule_summary(rule),
                "versions": page,
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
            warnings=_version_overlap_warnings(versions),
        )
    except InternalRuleAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def find_related_rules(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        relation_fields = [
            "rule_code",
            "rule_set_code",
            "family",
            "conflict_group",
            "action_type",
            "price_basis",
        ]
        if not any(request.GET.get(field_name) for field_name in relation_fields):
            raise InternalRuleAPIError(
                "validation_error",
                "At least one relation input is required.",
                status=400,
                details={"fields": relation_fields},
            )
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        rules = _filter_related_rules(snapshot=snapshot, request=request)
        page, next_cursor = _page(rules, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "related_rules": page,
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
        )
    except InternalRuleAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


def _filter_related_rules(*, snapshot: DataSnapshot, request) -> list[dict[str, Any]]:
    queryset = _rule_queryset(snapshot)
    reasons: dict[int, set[str]] = {}
    if request.GET.get("rule_code"):
        anchor = _get_rule(snapshot, request.GET["rule_code"])
        predicates = Q(pk=anchor.pk)
        if anchor.rule_set_id:
            predicates |= Q(rule_set_id=anchor.rule_set_id)
        if anchor.family:
            predicates |= Q(family=anchor.family)
        if anchor.conflict_group:
            predicates |= Q(conflict_group=anchor.conflict_group)
        queryset = queryset.filter(predicates)
    else:
        queryset = _filter_rules(queryset, request)
    for rule in queryset:
        reason_set = reasons.setdefault(rule.id, set())
        if request.GET.get("rule_code") == rule.code:
            reason_set.add("anchor_rule")
        if (
            request.GET.get("rule_set_code")
            and rule.rule_set
            and rule.rule_set.code == request.GET["rule_set_code"]
        ):
            reason_set.add("same_rule_set")
        if request.GET.get("family") and rule.family == request.GET["family"]:
            reason_set.add("same_family")
        if (
            request.GET.get("conflict_group")
            and rule.conflict_group == request.GET["conflict_group"]
        ):
            reason_set.add("same_conflict_group")
        if (
            request.GET.get("action_type")
            and rule.versions.filter(action_type=request.GET["action_type"]).exists()
        ):
            reason_set.add("same_action_type")
        if (
            request.GET.get("price_basis")
            and rule.versions.filter(price_basis=request.GET["price_basis"]).exists()
        ):
            reason_set.add("same_price_basis")
        if request.GET.get("rule_code") and not reason_set:
            reason_set.add("related_by_anchor_attributes")
    return [
        {
            "rule": rule_summary(rule),
            "relation_reason": sorted(reasons.get(rule.id) or {"matched_filter"}),
            "latest_version_summary": version_summary(_latest_version_for_rule(rule)),
        }
        for rule in queryset.order_by("code")
    ]


@require_GET
@internal_service_required
def detect_rule_conflicts(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        if not any(
            request.GET.get(field_name)
            for field_name in ("rule_set_code", "rule_code", "conflict_group")
        ):
            raise InternalRuleAPIError(
                "validation_error",
                "At least one conflict scope filter is required.",
                status=400,
                details={"fields": ["rule_set_code", "rule_code", "conflict_group"]},
            )
        evaluation_time = _parse_dt(
            request.GET.get("evaluation_time"),
            field_name="evaluation_time",
        )
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        queryset = _conflict_versions(snapshot=snapshot, request=request)
        if evaluation_time:
            queryset = queryset.filter(
                status=RuleVersionStatus.ACTIVE,
                active=True,
                valid_from__lte=evaluation_time,
            ).filter(Q(valid_to__isnull=True) | Q(valid_to__gt=evaluation_time))
        candidates = [
            _candidate_from_version(version)
            for version in queryset
            if version.rule.conflict_group
        ]
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                candidate.priority,
                -candidate.specific_condition_count,
                candidate.rule_code,
            ),
        )
        page, next_cursor = _page(ordered, cursor=cursor, limit=limit)
        ordering_hint = select_primary_base_rule(ordered)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "evaluation_time": evaluation_time.isoformat() if evaluation_time else None,
                "candidate_order": [asdict(candidate) for candidate in page],
                "ordering_hint": asdict(ordering_hint) if ordering_hint else None,
                "ordering_policy": (
                    "priority asc, specificity desc, rule_code asc; conditions are not evaluated"
                ),
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
        )
    except InternalRuleAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


def _conflict_versions(*, snapshot: DataSnapshot, request):
    queryset = _version_queryset(snapshot).filter(rule__conflict_group__gt="")
    if request.GET.get("rule_code"):
        rule = _get_rule(snapshot, request.GET["rule_code"])
        if not rule.conflict_group:
            return queryset.none()
        queryset = queryset.filter(rule__conflict_group=rule.conflict_group)
    if request.GET.get("rule_set_code"):
        queryset = queryset.filter(rule__rule_set__code=request.GET["rule_set_code"])
    if request.GET.get("conflict_group"):
        queryset = queryset.filter(rule__conflict_group=request.GET["conflict_group"])
    return queryset.order_by("priority", "rule__code", "version")


def _candidate_from_version(version: RuleVersion) -> PolicyRuleCandidate:
    return PolicyRuleCandidate(
        rule_code=version.rule.code,
        rule_version=version.version,
        priority=version.priority,
        specific_condition_count=specific_condition_count(version.condition_tree),
        action_type=version.action_type,
        price_basis=version.price_basis,
        stackable=version.stackable,
        conflict_group=version.rule.conflict_group,
        evaluation_status="not_evaluated",
        matched=False,
        matched_conditions=[],
        unmatched_conditions=[],
        action_config={},
    )


def specific_condition_count(condition_tree: dict[str, Any]) -> int:
    count = 0

    def walk(node: Any) -> None:
        nonlocal count
        if not isinstance(node, dict):
            return
        if "conditions" in node:
            for child in node.get("conditions") or []:
                walk(child)
            return
        if "all" in node or "any" in node:
            for child in node.get("all") or node.get("any") or []:
                walk(child)
            return
        if node.get("field"):
            count += 1

    walk(condition_tree)
    return count


@require_GET
@internal_service_required
def get_rule_evidence(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        fields = [
            "evidence_hash",
            "evaluation_code",
            "rule_code",
            "rule_set_code",
            "outage_code",
            "subscription_number",
        ]
        if not any(request.GET.get(field_name) for field_name in fields):
            raise InternalRuleAPIError(
                "validation_error",
                "At least one evidence identifier is required.",
                status=400,
                details={"fields": fields},
            )
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        queryset = _evidence_queryset(snapshot=snapshot, request=request)
        items = list(queryset)
        if request.GET.get("evidence_hash") and not items:
            raise InternalRuleAPIError(
                "not_found",
                "DecisionEvidence was not found.",
                status=404,
                details={"evidence_hash": request.GET["evidence_hash"]},
            )
        page, next_cursor = _page(items, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "decision_evidence": [
                    decision_evidence_summary(record)
                    for record in page
                ],
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
        )
    except InternalRuleAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


def _evidence_queryset(*, snapshot: DataSnapshot, request):
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
    if request.GET.get("evidence_hash"):
        queryset = queryset.filter(evidence_hash=request.GET["evidence_hash"])
    if request.GET.get("evaluation_code"):
        queryset = queryset.filter(
            compensation_evaluation__evaluation_code=request.GET["evaluation_code"]
        )
    if request.GET.get("rule_code"):
        queryset = queryset.filter(selected_rule_version__rule__code=request.GET["rule_code"])
    if request.GET.get("rule_set_code"):
        queryset = queryset.filter(rule_set__code=request.GET["rule_set_code"])
    if request.GET.get("outage_code"):
        queryset = queryset.filter(
            compensation_evaluation__outage__outage_code=request.GET["outage_code"]
        )
    if request.GET.get("subscription_number"):
        queryset = queryset.filter(
            compensation_evaluation__subscription__subscription_number=request.GET["subscription_number"]
        )
    if request.GET.get("decision"):
        queryset = queryset.filter(decision=request.GET["decision"])
    return queryset
