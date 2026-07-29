from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.customers.models import Subscription, SubscriptionConnection, SubscriptionStatus
from apps.customers.services.impact import CustomerImpactService
from apps.datasets.models import DataSnapshot
from apps.network.models import LineConnectionStatus, NetworkPortStatus
from apps.operations.models import Outage
from apps.operations.services.outages import OutageService, OutageServiceInputError
from apps.rules.services.evaluation import RuleEvaluationResult, RuleEvaluationService

SUPPORTED_REFUND_FORMULA_TYPES = frozenset({"monthly_price_percentage"})
DEFAULT_RULE_CODE = "REFUND-001"
MVP_OUTAGE_TYPE_CONTEXT = "full_outage"
MONEY_QUANT = Decimal("0.01")
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
                f"Outage {outage.outage_code} does not belong to snapshot "
                f"{snapshot.snapshot_key}."
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
