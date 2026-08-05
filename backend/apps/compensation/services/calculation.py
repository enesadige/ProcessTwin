import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.compensation.models import DecisionEvidence
from apps.customers.models import (
    CompensationDecisionStatus,
    CompensationHistory,
    Subscription,
    SubscriptionConnection,
    SubscriptionStatus,
    SuspensionReason,
)
from apps.customers.services.impact import CustomerImpactService
from apps.datasets.models import DataSnapshot
from apps.network.models import LineConnectionStatus, NetworkPortStatus
from apps.operations.models import Outage
from apps.operations.services.outages import OutageService, OutageServiceInputError
from apps.rules.models import RuleActionType
from apps.rules.services.evaluation import RuleEvaluationResult, RuleEvaluationService

SUPPORTED_REFUND_FORMULA_TYPES = frozenset({"monthly_price_percentage"})
DEFAULT_RULE_CODE = "REFUND-001"
MVP_OUTAGE_TYPE_CONTEXT = "full_outage"
MONEY_QUANT = Decimal("0.01")
EVIDENCE_SCHEMA_VERSION = 1
DEFERRED_CHECKS = (
    "PaymentRecord",
    "CampaignEnrollment",
    "CompensationHistory",
    "debt_or_late_payment",
    "campaign_discount",
    "previous_compensation",
)


class CompensationServiceError(Exception):
    """Base error for deterministic compensation calculation failures."""


class CompensationInputError(CompensationServiceError):
    """Raised when outage, subscription, snapshot, or evaluation time inputs are invalid."""


@dataclass(frozen=True)
class CompensationCalculationResult:
    outage_code: str
    subscription_code: str
    customer_code: str
    status: str
    reason_code: str
    rule_code: str
    rule_version: int | None
    monthly_price: Decimal | None
    refund_rate: Decimal | None
    compensation_amount: Decimal
    currency: str
    matched_conditions: list[dict[str, Any]]
    unmatched_conditions: list[dict[str, Any]]
    missing_fields: list[str]
    deferred_checks: list[dict[str, Any]]
    calculation_trace: list[dict[str, Any]]
    snapshot: dict[str, Any]


@dataclass(frozen=True)
class PolicyAmountResult:
    status: str
    reason_code: str
    unrounded_amount: Decimal
    final_amount: Decimal
    currency: str
    calculation_trace: list[dict[str, Any]]
    manual_review_reasons: list[str]


class CompensationService:
    def __init__(
        self,
        *,
        outage_service: OutageService | None = None,
        impact_service: CustomerImpactService | None = None,
        rule_evaluation_service: RuleEvaluationService | None = None,
    ) -> None:
        self.outage_service = outage_service or OutageService()
        self.impact_service = impact_service or CustomerImpactService()
        self.rule_evaluation_service = rule_evaluation_service or RuleEvaluationService()

    def evaluate_subscription(
        self,
        *,
        outage: Outage,
        subscription: Subscription,
        snapshot: DataSnapshot,
        evaluation_time=None,
        rule_code: str = DEFAULT_RULE_CODE,
    ) -> CompensationCalculationResult:
        self._validate_inputs(
            outage=outage,
            subscription=subscription,
            snapshot=snapshot,
            evaluation_time=evaluation_time,
            rule_code=rule_code,
        )
        duration = self._calculate_duration(
            outage=outage,
            evaluation_time=evaluation_time,
        )
        window_start = outage.started_at
        window_end = outage.ended_at or evaluation_time
        connection_result = self._get_valid_subscription_connection(
            subscription=subscription,
            snapshot=snapshot,
            window_start=window_start,
            window_end=window_end,
        )
        if connection_result["status"] != "selected":
            return self._manual_review_result(
                outage=outage,
                subscription=subscription,
                snapshot=snapshot,
                rule_code=rule_code,
                reason_code=connection_result["reason_code"],
                missing_fields=connection_result["missing_fields"],
                calculation_trace=[
                    self._trace("outage_duration", "calculated", seconds=duration.seconds),
                    self._trace(
                        "subscription_connection",
                        connection_result["status"],
                        reason_code=connection_result["reason_code"],
                    ),
                ],
            )

        subscription_active = is_subscription_active_during_window(
            subscription=subscription,
            window_start=window_start,
            window_end=window_end,
        )
        if not subscription_active:
            rule_result = self._evaluate_rule(
                snapshot=snapshot,
                rule_code=rule_code,
                outage=outage,
                duration_seconds=duration.seconds,
                subscription_active=False,
                connection_active=True,
            )
            return self._ineligible_result(
                outage=outage,
                subscription=subscription,
                snapshot=snapshot,
                rule_result=rule_result,
                reason_code="subscription_not_active_during_outage",
                calculation_trace=[
                    self._trace("outage_duration", "calculated", seconds=duration.seconds),
                    self._trace("subscription_temporal_validity", "unmatched"),
                ],
            )

        impact_result = self.impact_service.calculate_impact(
            outage=outage,
            snapshot=snapshot,
            evaluation_time=evaluation_time,
        )
        if subscription.subscription_number not in impact_result.affected_subscription_codes:
            rule_result = self._evaluate_rule(
                snapshot=snapshot,
                rule_code=rule_code,
                outage=outage,
                duration_seconds=duration.seconds,
                subscription_active=True,
                connection_active=True,
            )
            return self._ineligible_result(
                outage=outage,
                subscription=subscription,
                snapshot=snapshot,
                rule_result=rule_result,
                reason_code="subscription_not_affected_by_outage",
                calculation_trace=[
                    self._trace("outage_duration", "calculated", seconds=duration.seconds),
                    self._trace("customer_impact", "not_affected"),
                ],
            )

        rule_result = self._evaluate_rule(
            snapshot=snapshot,
            rule_code=rule_code,
            outage=outage,
            duration_seconds=duration.seconds,
            subscription_active=True,
            connection_active=True,
        )
        if rule_result.evaluation_status == "manual_review":
            return self._manual_review_from_rule_result(
                outage=outage,
                subscription=subscription,
                snapshot=snapshot,
                rule_result=rule_result,
                calculation_trace=[
                    self._trace("outage_duration", "calculated", seconds=duration.seconds),
                    self._trace("rule_evaluation", "manual_review", errors=rule_result.errors),
                ],
            )
        if rule_result.evaluation_status == "unmatched":
            return self._ineligible_result(
                outage=outage,
                subscription=subscription,
                snapshot=snapshot,
                rule_result=rule_result,
                reason_code=derive_unmatched_reason(rule_result),
                calculation_trace=[
                    self._trace("outage_duration", "calculated", seconds=duration.seconds),
                    self._trace("rule_evaluation", "unmatched"),
                ],
            )

        monthly_price = normalize_monthly_price(subscription.monthly_price)
        if monthly_price is None:
            return self._manual_review_from_rule_result(
                outage=outage,
                subscription=subscription,
                snapshot=snapshot,
                rule_result=rule_result,
                reason_code="missing_data",
                missing_fields=["monthly_price"],
                calculation_trace=[
                    self._trace("outage_duration", "calculated", seconds=duration.seconds),
                    self._trace("monthly_price", "missing_or_invalid"),
                ],
            )

        formula_result = parse_refund_formula(rule_result.action_config)
        if formula_result["status"] != "supported":
            return self._manual_review_from_rule_result(
                outage=outage,
                subscription=subscription,
                snapshot=snapshot,
                rule_result=rule_result,
                reason_code=formula_result["reason_code"],
                missing_fields=formula_result["missing_fields"],
                calculation_trace=[
                    self._trace("outage_duration", "calculated", seconds=duration.seconds),
                    self._trace(
                        "action_config",
                        "unsupported",
                        reason_code=formula_result["reason_code"],
                    ),
                ],
            )

        refund_rate = formula_result["refund_rate"]
        amount = calculate_refund_amount(monthly_price=monthly_price, refund_rate=refund_rate)
        return CompensationCalculationResult(
            outage_code=outage.outage_code,
            subscription_code=subscription.subscription_number,
            customer_code=subscription.customer.customer_number,
            status="eligible",
            reason_code="rule_matched",
            rule_code=rule_result.rule_code,
            rule_version=rule_result.rule_version,
            monthly_price=monthly_price,
            refund_rate=refund_rate,
            compensation_amount=amount,
            currency=formula_result["currency"],
            matched_conditions=rule_result.matched_conditions,
            unmatched_conditions=rule_result.unmatched_conditions,
            missing_fields=[],
            deferred_checks=build_deferred_checks(),
            calculation_trace=[
                self._trace("outage_duration", "calculated", seconds=duration.seconds),
                self._trace("customer_impact", "affected"),
                self._trace("rule_evaluation", "matched", rule_version=rule_result.rule_version),
                self._trace(
                    "amount_calculation",
                    "calculated",
                    monthly_price=str(monthly_price),
                    refund_rate=str(refund_rate),
                    amount=str(amount),
                    currency=formula_result["currency"],
                ),
            ],
            snapshot=self._snapshot_dict(snapshot),
        )

    def evaluate_subscription_policy_preconditions(
        self,
        *,
        subscription: Subscription,
    ) -> dict[str, Any]:
        if subscription.status == SubscriptionStatus.PENDING:
            return {"status": "ineligible", "reason_code": "pending_subscription"}
        if subscription.status == SubscriptionStatus.CANCELLED:
            return {"status": "ineligible", "reason_code": "cancelled_subscription"}
        if subscription.status != SubscriptionStatus.SUSPENDED:
            return {"status": "eligible", "reason_code": "subscription_status_allowed"}
        if subscription.suspension_reason in {
            SuspensionReason.CUSTOMER_REQUEST,
            SuspensionReason.PAYMENT_RELATED,
        }:
            return {
                "status": "ineligible",
                "reason_code": f"suspended_{subscription.suspension_reason}",
            }
        if subscription.suspension_reason == SuspensionReason.PROVIDER_FAULT:
            return {"status": "eligible", "reason_code": "provider_fault_suspension"}
        return {
            "status": "manual_review",
            "reason_code": f"suspended_{subscription.suspension_reason or 'unknown'}",
        }

    def calculate_policy_amount(
        self,
        *,
        action_type: str,
        action_config: dict[str, Any],
        price_basis_amount: Decimal | None,
        context: dict[str, Any],
    ) -> PolicyAmountResult:
        price = normalize_monthly_price(price_basis_amount)
        if price is None and action_type not in {
            RuleActionType.INELIGIBLE,
            RuleActionType.MANUAL_REVIEW,
            RuleActionType.EVIDENCE_ONLY,
            RuleActionType.CAP_FLOOR,
        }:
            return policy_manual_review("missing_price_basis", ["price_basis_amount"])
        if action_type == RuleActionType.INELIGIBLE:
            return policy_zero("ineligible", action_config.get("reason_code", "ineligible"))
        if action_type == RuleActionType.MANUAL_REVIEW:
            return policy_manual_review(action_config.get("reason_code", "manual_review"), [])
        if action_type == RuleActionType.EVIDENCE_ONLY:
            return policy_zero("evidence_only", action_config.get("reason_code", "evidence_only"))
        if action_type == RuleActionType.TIERED_PERCENTAGE:
            duration_field = action_config.get("duration_field", "outage_duration_seconds")
            return calculate_tiered_percentage(
                price=price,
                duration_seconds=int(context.get(duration_field, 0)),
                action_config=action_config,
            )
        if action_type == RuleActionType.PRORATED:
            return calculate_prorated(
                price=price,
                affected_duration_seconds=context.get("affected_duration_seconds")
                or context.get("outage_duration_seconds"),
                billing_period_seconds=context.get("billing_period_seconds"),
                affected_capacity_ratio=context.get("affected_capacity_ratio"),
                action_config=action_config,
            )
        if action_type == RuleActionType.SLA_MATRIX:
            return calculate_sla_matrix(
                price=price,
                exceedance_ratio=context.get("exceedance_ratio"),
                action_config=action_config,
            )
        if action_type == RuleActionType.MULTIPLIER:
            return calculate_multiplier(
                base_amount=context.get("base_amount"),
                action_config=action_config,
            )
        if action_type == RuleActionType.CAP_FLOOR:
            return apply_cap_floor_policy(
                amount=context.get("amount"),
                price_basis_amount=context.get("price_basis_amount"),
                monthly_cumulative_amount=context.get("billing_period_cumulative_amount", 0),
                action_config=action_config,
            )
        return policy_manual_review("unsupported_action_type", ["action_type"])

    def create_decision_evidence(
        self,
        *,
        data_snapshot: DataSnapshot,
        compensation_evaluation=None,
        rule_set=None,
        selected_rule_version=None,
        price_basis: str = "",
        selected_price: Decimal | None = None,
        unrounded_amount: Decimal | None = None,
        final_amount: Decimal = Decimal("0.00"),
        currency: str = "TRY",
        decision: str,
        matched_conditions: list[dict[str, Any]] | None = None,
        failed_conditions: list[dict[str, Any]] | None = None,
        excluded_rules: list[dict[str, Any]] | None = None,
        candidate_base_rules: list[dict[str, Any]] | None = None,
        applied_modifiers: list[dict[str, Any]] | None = None,
        formula_inputs: dict[str, Any] | None = None,
        cap_floor_trace: list[dict[str, Any]] | None = None,
        manual_review_reasons: list[str] | None = None,
        context_snapshot: dict[str, Any] | None = None,
    ) -> DecisionEvidence:
        payload = {
            "rule_set": str(rule_set) if rule_set else None,
            "selected_rule_version": (
                f"{selected_rule_version.rule.code}:v{selected_rule_version.version}"
                if selected_rule_version
                else None
            ),
            "price_basis": price_basis,
            "selected_price": str(selected_price) if selected_price is not None else None,
            "unrounded_amount": str(unrounded_amount) if unrounded_amount is not None else None,
            "final_amount": str(final_amount),
            "currency": currency,
            "decision": decision,
            "matched_conditions": matched_conditions or [],
            "failed_conditions": failed_conditions or [],
            "excluded_rules": excluded_rules or [],
            "candidate_base_rules": candidate_base_rules or [],
            "applied_modifiers": applied_modifiers or [],
            "formula_inputs": formula_inputs or {},
            "cap_floor_trace": cap_floor_trace or [],
            "manual_review_reasons": manual_review_reasons or [],
            "context_snapshot": context_snapshot or {},
        }
        evidence_hash = build_decision_evidence_hash(payload)
        evidence, _ = DecisionEvidence.objects.get_or_create(
            data_snapshot=data_snapshot,
            evidence_hash=evidence_hash,
            defaults={
                "compensation_evaluation": compensation_evaluation,
                "rule_set": rule_set,
                "selected_rule_version": selected_rule_version,
                "price_basis": price_basis,
                "selected_price": selected_price,
                "unrounded_amount": unrounded_amount,
                "final_amount": final_amount,
                "currency": currency,
                "decision": decision,
                "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
                "matched_conditions": matched_conditions or [],
                "failed_conditions": failed_conditions or [],
                "excluded_rules": excluded_rules or [],
                "candidate_base_rules": candidate_base_rules or [],
                "applied_modifiers": applied_modifiers or [],
                "formula_inputs": formula_inputs or {},
                "cap_floor_trace": cap_floor_trace or [],
                "manual_review_reasons": manual_review_reasons or [],
                "context_snapshot": context_snapshot or {},
                "finalized": True,
            },
        )
        return evidence

    def build_evaluation_idempotency_key(
        self,
        *,
        snapshot_identifier: str,
        subscription_code: str,
        incident_code: str,
        conflict_group: str,
        rule_set_code: str,
        rule_set_version: int,
    ) -> str:
        payload = {
            "snapshot": snapshot_identifier,
            "subscription": subscription_code,
            "incident": incident_code,
            "conflict_group": conflict_group,
            "rule_set": rule_set_code,
            "rule_set_version": rule_set_version,
        }
        return build_decision_evidence_hash(payload)

    def has_final_compensation_for_conflict_group(
        self,
        *,
        subscription: Subscription,
        incident,
        conflict_group: str,
    ) -> bool:
        return CompensationHistory.objects.filter(
            data_snapshot=subscription.data_snapshot,
            subscription=subscription,
            incident=incident,
            decision_status__in=[
                CompensationDecisionStatus.APPROVED,
                CompensationDecisionStatus.REJECTED,
            ],
            rule_version__rule__conflict_group=conflict_group,
        ).exists()

    def _validate_inputs(
        self,
        *,
        outage: Outage,
        subscription: Subscription,
        snapshot: DataSnapshot,
        evaluation_time,
        rule_code: str,
    ) -> None:
        if snapshot is None:
            raise CompensationInputError("A DataSnapshot must be provided explicitly.")
        if outage is None:
            raise CompensationInputError("An Outage must be provided.")
        if subscription is None:
            raise CompensationInputError("A Subscription must be provided.")
        if not snapshot.pk:
            raise CompensationInputError("Snapshot must be a persisted DataSnapshot.")
        if not outage.pk:
            raise CompensationInputError("Outage must be a persisted Outage.")
        if not subscription.pk:
            raise CompensationInputError("Subscription must be a persisted Subscription.")
        if not rule_code:
            raise CompensationInputError("rule_code must be provided.")
        if outage.data_snapshot_id != snapshot.id:
            raise CompensationInputError(
                f"Outage {outage.outage_code} does not belong to snapshot {snapshot.snapshot_key}."
            )
        if subscription.data_snapshot_id != snapshot.id:
            raise CompensationInputError(
                f"Subscription {subscription.subscription_number} does not belong to snapshot "
                f"{snapshot.snapshot_key}."
            )
        if subscription.customer.data_snapshot_id != snapshot.id:
            raise CompensationInputError(
                f"Subscription customer {subscription.customer.customer_number} does not belong "
                f"to snapshot {snapshot.snapshot_key}."
            )
        if evaluation_time is not None and timezone.is_naive(evaluation_time):
            raise CompensationInputError("evaluation_time must be timezone-aware.")

    def _calculate_duration(self, *, outage: Outage, evaluation_time):
        try:
            return self.outage_service.calculate_duration(
                outage=outage,
                evaluation_time=evaluation_time,
            )
        except OutageServiceInputError as exc:
            raise CompensationInputError(str(exc)) from exc

    def _get_valid_subscription_connection(
        self,
        *,
        subscription: Subscription,
        snapshot: DataSnapshot,
        window_start,
        window_end,
    ) -> dict[str, Any]:
        connections = list(
            SubscriptionConnection.objects.filter(
                data_snapshot=snapshot,
                subscription=subscription,
                is_active=True,
                line_connection__data_snapshot=snapshot,
                line_connection__is_active=True,
                line_connection__status=LineConnectionStatus.ACTIVE,
                line_connection__port__data_snapshot=snapshot,
                line_connection__port__inventory_status=NetworkPortStatus.ACTIVE,
            )
            .filter(valid_from__lt=window_end)
            .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=window_start))
            .filter(line_connection__valid_from__lt=window_end)
            .filter(
                Q(line_connection__valid_to__isnull=True)
                | Q(line_connection__valid_to__gt=window_start)
            )
            .select_related("line_connection", "line_connection__port")
            .order_by("valid_from", "id")
        )
        if len(connections) == 1:
            return {
                "status": "selected",
                "connection": connections[0],
                "reason_code": "",
                "missing_fields": [],
            }
        if not connections:
            return {
                "status": "missing",
                "connection": None,
                "reason_code": "missing_data",
                "missing_fields": ["subscription_connection"],
            }
        return {
            "status": "ambiguous",
            "connection": None,
            "reason_code": "ambiguous_subscription_connection",
            "missing_fields": [],
        }

    def _evaluate_rule(
        self,
        *,
        snapshot: DataSnapshot,
        rule_code: str,
        outage: Outage,
        duration_seconds: int,
        subscription_active: bool,
        connection_active: bool,
    ) -> RuleEvaluationResult:
        return self.rule_evaluation_service.evaluate_for_outage(
            snapshot=snapshot,
            rule_code=rule_code,
            outage=outage,
            context={
                "outage_type": MVP_OUTAGE_TYPE_CONTEXT,
                "outage_duration_seconds": duration_seconds,
                "subscription_active_during_outage": subscription_active,
                "connection_active_during_outage": connection_active,
            },
        )

    def _ineligible_result(
        self,
        *,
        outage: Outage,
        subscription: Subscription,
        snapshot: DataSnapshot,
        rule_result: RuleEvaluationResult,
        reason_code: str,
        calculation_trace: list[dict[str, Any]],
    ) -> CompensationCalculationResult:
        return CompensationCalculationResult(
            outage_code=outage.outage_code,
            subscription_code=subscription.subscription_number,
            customer_code=subscription.customer.customer_number,
            status="ineligible",
            reason_code=reason_code,
            rule_code=rule_result.rule_code,
            rule_version=rule_result.rule_version,
            monthly_price=normalize_monthly_price(subscription.monthly_price),
            refund_rate=None,
            compensation_amount=Decimal("0.00"),
            currency="TRY",
            matched_conditions=rule_result.matched_conditions,
            unmatched_conditions=rule_result.unmatched_conditions,
            missing_fields=rule_result.missing_fields,
            deferred_checks=build_deferred_checks(),
            calculation_trace=calculation_trace,
            snapshot=self._snapshot_dict(snapshot),
        )

    def _manual_review_result(
        self,
        *,
        outage: Outage,
        subscription: Subscription,
        snapshot: DataSnapshot,
        rule_code: str,
        reason_code: str,
        missing_fields: list[str],
        calculation_trace: list[dict[str, Any]],
    ) -> CompensationCalculationResult:
        return CompensationCalculationResult(
            outage_code=outage.outage_code,
            subscription_code=subscription.subscription_number,
            customer_code=subscription.customer.customer_number,
            status="manual_review",
            reason_code=reason_code,
            rule_code=rule_code,
            rule_version=None,
            monthly_price=normalize_monthly_price(subscription.monthly_price),
            refund_rate=None,
            compensation_amount=Decimal("0.00"),
            currency="TRY",
            matched_conditions=[],
            unmatched_conditions=[],
            missing_fields=missing_fields,
            deferred_checks=build_deferred_checks(),
            calculation_trace=calculation_trace,
            snapshot=self._snapshot_dict(snapshot),
        )

    def _manual_review_from_rule_result(
        self,
        *,
        outage: Outage,
        subscription: Subscription,
        snapshot: DataSnapshot,
        rule_result: RuleEvaluationResult,
        calculation_trace: list[dict[str, Any]],
        reason_code: str = "rule_manual_review",
        missing_fields: list[str] | None = None,
    ) -> CompensationCalculationResult:
        return CompensationCalculationResult(
            outage_code=outage.outage_code,
            subscription_code=subscription.subscription_number,
            customer_code=subscription.customer.customer_number,
            status="manual_review",
            reason_code=reason_code,
            rule_code=rule_result.rule_code,
            rule_version=rule_result.rule_version,
            monthly_price=normalize_monthly_price(subscription.monthly_price),
            refund_rate=None,
            compensation_amount=Decimal("0.00"),
            currency="TRY",
            matched_conditions=rule_result.matched_conditions,
            unmatched_conditions=rule_result.unmatched_conditions,
            missing_fields=missing_fields or rule_result.missing_fields,
            deferred_checks=build_deferred_checks(),
            calculation_trace=calculation_trace,
            snapshot=self._snapshot_dict(snapshot),
        )

    def _trace(self, step: str, status: str, **details) -> dict[str, Any]:
        return {
            "step": step,
            "status": status,
            "details": details,
        }

    def _snapshot_dict(self, snapshot: DataSnapshot) -> dict[str, Any]:
        return {
            "id": snapshot.id,
            "snapshot_key": snapshot.snapshot_key,
            "dataset_slug": snapshot.dataset_version.slug,
        }


def is_subscription_active_during_window(
    *,
    subscription: Subscription,
    window_start,
    window_end,
) -> bool:
    if not subscription.is_active or subscription.status != SubscriptionStatus.ACTIVE:
        return False
    if subscription.valid_from >= window_end:
        return False
    return subscription.valid_to is None or subscription.valid_to > window_start


def normalize_monthly_price(value) -> Decimal | None:
    if value is None:
        return None
    try:
        price = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if price < Decimal("0.00"):
        return None
    return price.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def parse_refund_formula(action_config: dict[str, Any]) -> dict[str, Any]:
    formula = action_config.get("refund_formula") if isinstance(action_config, dict) else None
    if not isinstance(formula, dict):
        return {
            "status": "unsupported",
            "reason_code": "unsupported_action_config",
            "missing_fields": ["refund_formula"],
        }
    if formula.get("type") not in SUPPORTED_REFUND_FORMULA_TYPES:
        return {
            "status": "unsupported",
            "reason_code": "unsupported_action_config",
            "missing_fields": [],
        }
    percentage = formula.get("percentage")
    if percentage is None:
        return {
            "status": "unsupported",
            "reason_code": "unsupported_action_config",
            "missing_fields": ["refund_formula.percentage"],
        }
    try:
        refund_rate = Decimal(str(percentage))
    except (InvalidOperation, TypeError, ValueError):
        return {
            "status": "unsupported",
            "reason_code": "unsupported_action_config",
            "missing_fields": ["refund_formula.percentage"],
        }
    currency = formula.get("currency", "TRY")
    if currency != "TRY":
        return {
            "status": "unsupported",
            "reason_code": "unsupported_action_config",
            "missing_fields": [],
        }
    return {
        "status": "supported",
        "reason_code": "",
        "missing_fields": [],
        "refund_rate": refund_rate,
        "currency": currency,
    }


def calculate_refund_amount(*, monthly_price: Decimal, refund_rate: Decimal) -> Decimal:
    return (monthly_price * refund_rate).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def calculate_tiered_percentage(
    *,
    price: Decimal | None,
    duration_seconds: int,
    action_config: dict[str, Any],
) -> PolicyAmountResult:
    if price is None:
        return policy_manual_review("missing_price_basis", ["price_basis_amount"])
    tiers = sorted(action_config.get("tiers", []), key=lambda item: int(item["min_seconds"]))
    selected_rate = Decimal("0")
    selected_tier: dict[str, Any] | None = None
    for tier in tiers:
        min_seconds = int(tier["min_seconds"])
        max_seconds = tier.get("max_seconds")
        if duration_seconds < min_seconds:
            continue
        if max_seconds is not None and duration_seconds >= int(max_seconds):
            continue
        selected_rate = Decimal(str(tier["rate"]))
        selected_tier = tier
        break
    if selected_tier is None or selected_rate == Decimal("0"):
        return policy_zero("ineligible", "duration_below_threshold")
    unrounded = price * selected_rate
    final = apply_positive_floor_and_cap(
        amount=unrounded,
        price=price,
        floor=Decimal(str(action_config.get("minimum_positive_amount", "0.00"))),
        cap_percent=Decimal(str(action_config.get("incident_cap_percent", "1.00"))),
        absolute_cap=optional_decimal(action_config.get("absolute_cap_amount")),
    )
    return policy_amount(
        reason_code="tiered_percentage_matched",
        unrounded_amount=unrounded,
        final_amount=final,
        trace=[{"step": "selected_tier", "details": selected_tier}],
    )


def calculate_prorated(
    *,
    price: Decimal | None,
    affected_duration_seconds,
    billing_period_seconds,
    affected_capacity_ratio,
    action_config: dict[str, Any],
) -> PolicyAmountResult:
    if price is None:
        return policy_manual_review("missing_price_basis", ["price_basis_amount"])
    if affected_duration_seconds is None or billing_period_seconds is None:
        return policy_manual_review("missing_duration_context", ["affected_duration_seconds"])
    if affected_capacity_ratio is None:
        return policy_manual_review("missing_affected_capacity_ratio", ["affected_capacity_ratio"])
    duration = Decimal(str(affected_duration_seconds))
    period = Decimal(str(billing_period_seconds))
    ratio = Decimal(str(affected_capacity_ratio))
    if period <= 0 or duration < 0 or ratio < 0 or ratio > 1:
        return policy_manual_review("invalid_proration_context", [])
    minimum_duration = Decimal(str(action_config.get("minimum_duration_seconds", "0")))
    if duration < minimum_duration:
        return policy_zero("ineligible", "duration_below_threshold")
    unrounded = price * duration / period * ratio
    final = apply_positive_floor_and_cap(
        amount=unrounded,
        price=price,
        floor=Decimal(str(action_config.get("minimum_positive_amount", "0.00"))),
        cap_percent=Decimal(str(action_config.get("incident_cap_percent", "1.00"))),
        absolute_cap=optional_decimal(action_config.get("absolute_cap_amount")),
    )
    return policy_amount(
        reason_code="prorated_matched",
        unrounded_amount=unrounded,
        final_amount=final,
        trace=[
            {
                "step": "proration",
                "details": {
                    "affected_duration_seconds": str(duration),
                    "billing_period_seconds": str(period),
                    "affected_capacity_ratio": str(ratio),
                },
            }
        ],
    )


def calculate_sla_matrix(
    *,
    price: Decimal | None,
    exceedance_ratio,
    action_config: dict[str, Any],
) -> PolicyAmountResult:
    if price is None:
        return policy_manual_review("missing_price_basis", ["price_basis_amount"])
    if exceedance_ratio is None:
        return policy_manual_review("missing_exceedance_ratio", ["exceedance_ratio"])
    ratio = Decimal(str(exceedance_ratio))
    selected_rate = Decimal("0")
    selected_tier: dict[str, Any] | None = None
    for tier in sorted(
        action_config.get("exceedance_tiers", []),
        key=lambda item: Decimal(str(item["min_ratio_exclusive"])),
    ):
        lower = Decimal(str(tier["min_ratio_exclusive"]))
        upper = tier.get("max_ratio_inclusive")
        if ratio <= lower:
            continue
        if upper is not None and ratio > Decimal(str(upper)):
            continue
        selected_rate = Decimal(str(tier["rate"]))
        selected_tier = tier
        break
    if selected_tier is None:
        return policy_zero("ineligible", "threshold_not_breached")
    unrounded = price * selected_rate
    final = apply_positive_floor_and_cap(
        amount=unrounded,
        price=price,
        floor=Decimal(str(action_config.get("minimum_positive_amount", "0.00"))),
        cap_percent=Decimal(str(action_config.get("incident_cap_percent", "1.00"))),
        absolute_cap=optional_decimal(action_config.get("absolute_cap_amount")),
    )
    return policy_amount(
        reason_code="sla_matrix_matched",
        unrounded_amount=unrounded,
        final_amount=final,
        trace=[{"step": "selected_sla_tier", "details": selected_tier}],
    )


def calculate_multiplier(
    *,
    base_amount,
    action_config: dict[str, Any],
) -> PolicyAmountResult:
    if base_amount is None:
        return policy_manual_review("missing_base_amount", ["base_amount"])
    base = Decimal(str(base_amount))
    rate = Decimal(str(action_config.get("modifier_rate", "0")))
    unrounded = base * rate
    return policy_amount(
        reason_code="modifier_matched",
        unrounded_amount=unrounded,
        final_amount=money(unrounded),
        trace=[{"step": "modifier", "details": {"rate": str(rate)}}],
    )


def apply_cap_floor_policy(
    *,
    amount,
    price_basis_amount,
    monthly_cumulative_amount,
    action_config: dict[str, Any],
) -> PolicyAmountResult:
    if amount is None or price_basis_amount is None:
        return policy_manual_review("missing_cap_context", ["amount", "price_basis_amount"])
    raw_amount = Decimal(str(amount))
    price = Decimal(str(price_basis_amount))
    if raw_amount <= 0:
        return policy_zero("ineligible", "non_positive_amount")
    if raw_amount > price or raw_amount > Decimal("10000.00"):
        return policy_manual_review("high_amount_manual_review", [])
    floor = Decimal(str(action_config.get("minimum_positive_amount", "0.00")))
    incident_cap = price * Decimal(str(action_config.get("incident_cap_percent", "1.00")))
    monthly_cap = price * Decimal(str(action_config.get("monthly_cumulative_cap_percent", "1.00")))
    remaining_monthly_cap = monthly_cap - Decimal(str(monthly_cumulative_amount))
    capped = min(max(raw_amount, floor), incident_cap, remaining_monthly_cap)
    return policy_amount(
        reason_code="cap_floor_applied",
        unrounded_amount=raw_amount,
        final_amount=max(Decimal("0.00"), money(capped)),
        trace=[
            {
                "step": "cap_floor",
                "details": {
                    "floor": str(floor),
                    "incident_cap": str(money(incident_cap)),
                    "monthly_cap": str(money(monthly_cap)),
                },
            }
        ],
    )


def apply_positive_floor_and_cap(
    *,
    amount: Decimal,
    price: Decimal,
    floor: Decimal,
    cap_percent: Decimal,
    absolute_cap: Decimal | None = None,
) -> Decimal:
    if amount <= Decimal("0.00"):
        return Decimal("0.00")
    cap_values = [price * cap_percent]
    if absolute_cap is not None:
        cap_values.append(absolute_cap)
    capped = min(max(amount, floor), *cap_values)
    return money(capped)


def optional_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def policy_amount(
    *,
    reason_code: str,
    unrounded_amount: Decimal,
    final_amount: Decimal,
    trace: list[dict[str, Any]],
) -> PolicyAmountResult:
    return PolicyAmountResult(
        status="eligible",
        reason_code=reason_code,
        unrounded_amount=unrounded_amount,
        final_amount=final_amount,
        currency="TRY",
        calculation_trace=trace,
        manual_review_reasons=[],
    )


def policy_zero(status: str, reason_code: str) -> PolicyAmountResult:
    return PolicyAmountResult(
        status=status,
        reason_code=reason_code,
        unrounded_amount=Decimal("0.00"),
        final_amount=Decimal("0.00"),
        currency="TRY",
        calculation_trace=[],
        manual_review_reasons=[],
    )


def policy_manual_review(reason_code: str, missing_fields: list[str]) -> PolicyAmountResult:
    return PolicyAmountResult(
        status="manual_review",
        reason_code=reason_code,
        unrounded_amount=Decimal("0.00"),
        final_amount=Decimal("0.00"),
        currency="TRY",
        calculation_trace=[],
        manual_review_reasons=[reason_code, *missing_fields],
    )


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def build_decision_evidence_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def derive_unmatched_reason(rule_result: RuleEvaluationResult) -> str:
    for condition in rule_result.unmatched_conditions:
        if condition["field"] == "outage_duration_seconds":
            return "duration_below_threshold"
        if condition["field"] == "subscription_active_during_outage":
            return "subscription_not_active_during_outage"
        if condition["field"] == "connection_active_during_outage":
            return "connection_not_active_during_outage"
    return "rule_unmatched"


def build_deferred_checks() -> list[dict[str, Any]]:
    return [
        {
            "name": item,
            "status": "deferred",
            "effect_on_current_result": "not_evaluated_in_mvp",
        }
        for item in DEFERRED_CHECKS
    ]
