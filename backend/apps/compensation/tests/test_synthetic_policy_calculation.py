from decimal import Decimal

import pytest
from data_generator.configs.synthetic_compensation_policy_v1 import (
    BROADBAND_FULL_OUTAGE_TIERS,
    METRO_FAILED_FAILOVER_TIERS,
    SLA_EXCEEDANCE_TIERS,
)
from django.core.exceptions import ValidationError

from apps.compensation.models import DecisionEvidence
from apps.compensation.services.calculation import CompensationService
from apps.customers.models import Subscription, SubscriptionStatus, SuspensionReason
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.rules.models import RuleActionType


def test_broadband_full_outage_tier_boundaries_and_floor():
    service = CompensationService()
    action_config = {
        "tiers": BROADBAND_FULL_OUTAGE_TIERS,
        "minimum_positive_amount": "10.00",
        "incident_cap_percent": "0.40",
    }

    assert tier_amount(service, 29 * 60 + 59, action_config) == Decimal("0.00")
    assert tier_amount(service, 30 * 60, action_config) == Decimal("10.00")
    assert tier_amount(service, 119 * 60 + 59, action_config) == Decimal("10.00")
    assert tier_amount(service, 2 * 60 * 60, action_config) == Decimal("31.99")
    assert tier_amount(service, 6 * 60 * 60, action_config) == Decimal("79.98")
    assert tier_amount(service, 24 * 60 * 60, action_config) == Decimal("139.97")


def test_partial_proration_requires_capacity_ratio_and_uses_real_billing_period_seconds():
    service = CompensationService()
    config = {
        "minimum_duration_seconds": "1800",
        "minimum_positive_amount": "10.00",
        "incident_cap_percent": "0.25",
    }

    missing_ratio = service.calculate_policy_amount(
        action_type=RuleActionType.PRORATED,
        action_config=config,
        price_basis_amount=Decimal("699.90"),
        context={"affected_duration_seconds": 10800, "billing_period_seconds": 2678400},
    )
    calculated = service.calculate_policy_amount(
        action_type=RuleActionType.PRORATED,
        action_config=config,
        price_basis_amount=Decimal("699.90"),
        context={
            "affected_duration_seconds": 10800,
            "billing_period_seconds": 2678400,
            "affected_capacity_ratio": "0.50",
        },
    )

    assert missing_ratio.status == "manual_review"
    assert missing_ratio.reason_code == "missing_affected_capacity_ratio"
    assert calculated.status == "eligible"
    assert calculated.final_amount == Decimal("10.00")


def test_degradation_and_metro_sla_matrix_use_highest_exceedance_tier():
    result = CompensationService().calculate_policy_amount(
        action_type=RuleActionType.SLA_MATRIX,
        action_config={
            "exceedance_tiers": SLA_EXCEEDANCE_TIERS,
            "minimum_positive_amount": "10.00",
            "incident_cap_percent": "0.60",
        },
        price_basis_amount=Decimal("3799.90"),
        context={"exceedance_ratio": "1.50"},
    )

    assert result.status == "eligible"
    assert result.final_amount == Decimal("265.99")


def test_45_second_metro_failover_uses_half_percent_with_absolute_cap():
    result = CompensationService().calculate_policy_amount(
        action_type=RuleActionType.TIERED_PERCENTAGE,
        action_config={
            "tiers": [{"min_seconds": 31, "max_seconds": 61, "rate": "0.005"}],
            "duration_field": "transition_duration_seconds",
            "minimum_positive_amount": "10.00",
            "incident_cap_percent": "0.007143",
            "absolute_cap_amount": "50.00",
        },
        price_basis_amount=Decimal("6999.90"),
        context={"transition_duration_seconds": 45},
    )

    assert result.status == "eligible"
    assert result.final_amount == Decimal("35.00")


def test_failed_failover_tier_uses_metro_tiers():
    result = CompensationService().calculate_policy_amount(
        action_type=RuleActionType.TIERED_PERCENTAGE,
        action_config={
            "tiers": METRO_FAILED_FAILOVER_TIERS,
            "minimum_positive_amount": "10.00",
            "incident_cap_percent": "0.60",
        },
        price_basis_amount=Decimal("6999.90"),
        context={"outage_duration_seconds": 3 * 60 * 60},
    )

    assert result.status == "eligible"
    assert result.final_amount == Decimal("839.99")


def test_cap_floor_monthly_cap_and_high_amount_manual_review():
    service = CompensationService()
    config = {
        "minimum_positive_amount": "10.00",
        "incident_cap_percent": "0.40",
        "monthly_cumulative_cap_percent": "0.75",
    }

    capped = service.calculate_policy_amount(
        action_type=RuleActionType.CAP_FLOOR,
        action_config=config,
        price_basis_amount=None,
        context={
            "amount": "300.00",
            "price_basis_amount": "400.00",
            "billing_period_cumulative_amount": "200.00",
        },
    )
    high = service.calculate_policy_amount(
        action_type=RuleActionType.CAP_FLOOR,
        action_config=config,
        price_basis_amount=None,
        context={
            "amount": "12000.00",
            "price_basis_amount": "9000.00",
            "billing_period_cumulative_amount": "0.00",
        },
    )

    assert capped.final_amount == Decimal("100.00")
    assert high.status == "manual_review"
    assert high.reason_code == "high_amount_manual_review"


def test_idempotency_key_uses_conflict_group_and_rule_set_version_not_rule_version_id():
    service = CompensationService()

    first = service.build_evaluation_idempotency_key(
        snapshot_identifier="snapshot-1",
        subscription_code="SUB-001",
        incident_code="INC-001",
        conflict_group="metro_sla",
        rule_set_code="SYN-COMP-2026",
        rule_set_version=1,
    )
    second = service.build_evaluation_idempotency_key(
        snapshot_identifier="snapshot-1",
        subscription_code="SUB-001",
        incident_code="INC-001",
        conflict_group="metro_sla",
        rule_set_code="SYN-COMP-2026",
        rule_set_version=1,
    )
    changed_group = service.build_evaluation_idempotency_key(
        snapshot_identifier="snapshot-1",
        subscription_code="SUB-001",
        incident_code="INC-001",
        conflict_group="broadband_outage",
        rule_set_code="SYN-COMP-2026",
        rule_set_version=1,
    )

    assert first == second
    assert len(first) == 64
    assert first != changed_group


@pytest.mark.django_db
def test_suspension_reason_policy_and_payment_independence():
    subscription = Subscription(status=SubscriptionStatus.SUSPENDED)
    service = CompensationService()

    subscription.suspension_reason = SuspensionReason.PAYMENT_RELATED
    assert service.evaluate_subscription_policy_preconditions(subscription=subscription) == {
        "status": "ineligible",
        "reason_code": "suspended_payment_related",
    }

    subscription.suspension_reason = SuspensionReason.PROVIDER_FAULT
    assert service.evaluate_subscription_policy_preconditions(subscription=subscription) == {
        "status": "eligible",
        "reason_code": "provider_fault_suspension",
    }

    subscription.suspension_reason = SuspensionReason.UNKNOWN
    assert service.evaluate_subscription_policy_preconditions(subscription=subscription) == {
        "status": "manual_review",
        "reason_code": "suspended_unknown",
    }


@pytest.mark.django_db
def test_decision_evidence_hash_is_deterministic_and_finalized_evidence_is_immutable():
    snapshot = create_snapshot()
    service = CompensationService()

    evidence = service.create_decision_evidence(
        data_snapshot=snapshot,
        price_basis="contracted_monthly_price",
        selected_price=Decimal("399.90"),
        unrounded_amount=Decimal("31.992"),
        final_amount=Decimal("31.99"),
        decision="eligible",
        matched_conditions=[{"field": "impact_class", "matched": True}],
        formula_inputs={"rate": "0.08"},
    )

    assert len(evidence.evidence_hash) == 64
    assert DecisionEvidence.objects.get(pk=evidence.pk).evidence_hash == evidence.evidence_hash
    evidence.final_amount = Decimal("0.00")
    with pytest.raises(ValidationError, match="immutable"):
        evidence.save()


def tier_amount(
    service: CompensationService, duration_seconds: int, action_config: dict
) -> Decimal:
    return service.calculate_policy_amount(
        action_type=RuleActionType.TIERED_PERCENTAGE,
        action_config=action_config,
        price_basis_amount=Decimal("399.90"),
        context={"outage_duration_seconds": duration_seconds},
    ).final_amount


def create_snapshot() -> DataSnapshot:
    dataset = DatasetVersion.objects.create(
        name="Decision evidence dataset",
        generator_version="evidence-v1",
        seed="evidence-test",
    )
    return DataSnapshot.objects.create(dataset_version=dataset, name="Evidence snapshot")
