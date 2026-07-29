from decimal import Decimal
from itertools import groupby

import pytest
from django.core.management import call_command

from apps.compensation.models import CompensationEvaluation
from apps.compensation.services.calculation import CompensationService
from apps.customers.models import Subscription, SubscriptionConnection
from apps.customers.services.impact import CustomerImpactService
from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion, DataSnapshot, GroundTruthCase
from apps.operations.models import Alarm, Incident, Outage
from apps.operations.services.alarm_correlation import AlarmCorrelationService
from apps.operations.services.outages import OutageService
from apps.operations.services.root_cause import RootCauseService
from apps.rules.models import Rule, RuleVersion
from apps.rules.services.evaluation import RuleEvaluationService


@pytest.mark.django_db
def test_main_bng_outage_deterministic_chain_matches_ground_truth():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    ground_truth = get_ground_truth(snapshot, "OUT-MAL-BNG-001")

    duration = OutageService().calculate_duration(outage=outage)
    impact = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)
    root_cause = RootCauseService().analyze(outage=outage, snapshot=snapshot)[0]
    rule_result = RuleEvaluationService().evaluate_for_outage(
        snapshot=snapshot,
        rule_code="REFUND-001",
        outage=outage,
        context=eligible_rule_context(duration_seconds=duration.seconds),
    )
    compensation_total = calculate_compensation_total(
        snapshot=snapshot,
        outage=outage,
        subscription_codes=ground_truth.affected_subscription_codes,
    )
    correlation = get_correlation_result(
        snapshot=snapshot,
        anchor_alarm_code="ALM-OUT-MAL-BNG-001-PRIMARY",
        candidate_alarm_code="ALM-OUT-MAL-BNG-001-LINK",
    )

    assert duration.seconds == 12000
    assert duration.minutes == 200
    assert impact.affected_subscription_count == 150
    assert impact.affected_customer_count == 140
    assert impact.affected_subscription_codes == ground_truth.affected_subscription_codes
    assert impact.affected_customer_codes == ground_truth.affected_customer_codes
    assert root_cause.candidate_device_code == "BNG-MAL-001"
    assert root_cause.classification == "confirmed"
    assert root_cause.evidence_score == 100
    assert correlation.correlated is True
    assert correlation.evidence_score == 100
    assert rule_result.rule_code == "REFUND-001"
    assert rule_result.rule_version == 2
    assert rule_result.evaluation_status == "matched"
    assert compensation_total == Decimal("5173.50")
    assert compensation_total == ground_truth.expected_total_refund_amount


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("outage_code", "expected_seconds", "expected_rule_version"),
    [
        ("OUT-MAL-OLT-001", 2700, 1),
        ("OUT-MAL-DSLAM-001", 4200, 2),
    ],
)
def test_short_outage_chains_match_ground_truth_and_remain_ineligible(
    outage_code,
    expected_seconds,
    expected_rule_version,
):
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, outage_code)
    ground_truth = get_ground_truth(snapshot, outage_code)

    duration = OutageService().calculate_duration(outage=outage)
    impact = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)
    rule_result = RuleEvaluationService().evaluate_for_outage(
        snapshot=snapshot,
        rule_code="REFUND-001",
        outage=outage,
        context=eligible_rule_context(duration_seconds=duration.seconds),
    )
    compensation_total = calculate_compensation_total(
        snapshot=snapshot,
        outage=outage,
        subscription_codes=ground_truth.affected_subscription_codes,
    )

    assert duration.seconds == expected_seconds
    assert impact.affected_subscription_codes == ground_truth.affected_subscription_codes
    assert impact.affected_customer_codes == ground_truth.affected_customer_codes
    assert impact.affected_subscription_count == ground_truth.affected_subscription_count
    assert impact.affected_customer_count == ground_truth.affected_customer_count
    assert rule_result.rule_version == expected_rule_version
    assert rule_result.evaluation_status == "unmatched"
    assert compensation_total == Decimal("0.00")
    assert compensation_total == ground_truth.expected_total_refund_amount


@pytest.mark.django_db
def test_duplicate_customer_subscriptions_are_counted_once_but_compensated_separately():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    impact = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)
    subscriptions = get_two_affected_subscriptions_for_same_customer(
        snapshot=snapshot,
        subscription_codes=impact.affected_subscription_codes,
    )

    results = [
        CompensationService().evaluate_subscription(
            outage=outage,
            subscription=subscription,
            snapshot=snapshot,
        )
        for subscription in subscriptions
    ]

    assert impact.affected_subscription_count == 150
    assert impact.affected_customer_count == 140
    assert impact.affected_subscription_count > impact.affected_customer_count
    assert len({subscription.customer.customer_number for subscription in subscriptions}) == 1
    assert len({subscription.subscription_number for subscription in subscriptions}) == 2
    assert all(result.status == "eligible" for result in results)
    assert all(result.compensation_amount > Decimal("0.00") for result in results)


@pytest.mark.django_db
def test_invalid_line_connection_date_is_excluded_from_impact_and_compensation():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    connection = get_first_affected_connection(snapshot, outage)
    connection.line_connection.valid_to = outage.started_at
    connection.line_connection.save(update_fields=["valid_to"])
    connection.subscription.refresh_from_db()

    impact = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)
    compensation = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=connection.subscription,
        snapshot=snapshot,
    )

    assert impact.affected_subscription_count == 149
    assert connection.subscription.subscription_number not in impact.affected_subscription_codes
    assert compensation.status == "manual_review"
    assert compensation.reason_code == "missing_data"
    assert compensation.missing_fields == ["subscription_connection"]


@pytest.mark.django_db
def test_deterministic_services_are_repeatable_and_do_not_create_domain_records():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    subscription = get_subscription(
        snapshot=snapshot,
        subscription_number=get_ground_truth(
            snapshot,
            "OUT-MAL-BNG-001",
        ).affected_subscription_codes[0],
    )
    counts_before = count_domain_records(snapshot)

    first = run_core_service_snapshot(snapshot=snapshot, outage=outage, subscription=subscription)
    second = run_core_service_snapshot(snapshot=snapshot, outage=outage, subscription=subscription)

    assert first == second
    assert count_domain_records(snapshot) == counts_before


def run_core_service_snapshot(
    *,
    snapshot: DataSnapshot,
    outage: Outage,
    subscription: Subscription,
) -> dict:
    impact = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)
    root_cause = RootCauseService().analyze(outage=outage, snapshot=snapshot)
    compensation = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=subscription,
        snapshot=snapshot,
    )
    correlation_results = AlarmCorrelationService().find_correlations(
        anchor_alarm=get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY"),
        snapshot=snapshot,
    )
    return {
        "duration_seconds": OutageService().calculate_duration(outage=outage).seconds,
        "affected_subscription_codes": impact.affected_subscription_codes,
        "affected_customer_codes": impact.affected_customer_codes,
        "root_cause_devices": [candidate.candidate_device_code for candidate in root_cause],
        "correlation_codes": [result.candidate_alarm_code for result in correlation_results],
        "compensation": {
            "status": compensation.status,
            "rule_version": compensation.rule_version,
            "amount": str(compensation.compensation_amount),
        },
    }


def seed_snapshot() -> DataSnapshot:
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def get_outage(snapshot: DataSnapshot, outage_code: str) -> Outage:
    return Outage.objects.select_related("source_device").get(
        data_snapshot=snapshot,
        outage_code=outage_code,
    )


def get_ground_truth(snapshot: DataSnapshot, outage_code: str) -> GroundTruthCase:
    return GroundTruthCase.objects.get(data_snapshot=snapshot, outage_code=outage_code)


def get_alarm(snapshot: DataSnapshot, alarm_id: str) -> Alarm:
    return Alarm.objects.select_related("alarm_type", "device").get(
        data_snapshot=snapshot,
        alarm_id=alarm_id,
    )


def get_subscription(snapshot: DataSnapshot, subscription_number: str) -> Subscription:
    return Subscription.objects.select_related("customer", "service_package").get(
        data_snapshot=snapshot,
        subscription_number=subscription_number,
    )


def get_first_affected_connection(snapshot: DataSnapshot, outage: Outage) -> SubscriptionConnection:
    return (
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            subscription__subscription_number__in=get_ground_truth(
                snapshot,
                outage.outage_code,
            ).affected_subscription_codes,
        )
        .select_related("subscription", "line_connection")
        .order_by("subscription__subscription_number")
        .first()
    )


def get_two_affected_subscriptions_for_same_customer(
    *,
    snapshot: DataSnapshot,
    subscription_codes: list[str],
) -> list[Subscription]:
    subscriptions = list(
        Subscription.objects.select_related("customer")
        .filter(data_snapshot=snapshot, subscription_number__in=subscription_codes)
        .order_by("customer__customer_number", "subscription_number")
    )
    for _customer_number, group in groupby(
        subscriptions,
        key=lambda item: item.customer.customer_number,
    ):
        grouped = list(group)
        if len(grouped) == 2:
            return grouped
    raise AssertionError("Expected at least one affected customer with two subscriptions.")


def calculate_compensation_total(
    *,
    snapshot: DataSnapshot,
    outage: Outage,
    subscription_codes: list[str],
) -> Decimal:
    subscriptions = Subscription.objects.select_related("customer", "service_package").filter(
        data_snapshot=snapshot,
        subscription_number__in=subscription_codes,
    )
    return sum(
        (
            CompensationService()
            .evaluate_subscription(
                outage=outage,
                subscription=subscription,
                snapshot=snapshot,
            )
            .compensation_amount
            for subscription in subscriptions
        ),
        Decimal("0.00"),
    )


def get_correlation_result(
    *,
    snapshot: DataSnapshot,
    anchor_alarm_code: str,
    candidate_alarm_code: str,
):
    results = AlarmCorrelationService().find_correlations(
        anchor_alarm=get_alarm(snapshot, anchor_alarm_code),
        snapshot=snapshot,
    )
    return next(result for result in results if result.candidate_alarm_code == candidate_alarm_code)


def eligible_rule_context(*, duration_seconds: int) -> dict:
    return {
        "outage_type": "full_outage",
        "outage_duration_seconds": duration_seconds,
        "subscription_active_during_outage": True,
        "connection_active_during_outage": True,
    }


def count_domain_records(snapshot: DataSnapshot) -> dict[str, int]:
    return {
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "incidents": Incident.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "compensation_evaluations": CompensationEvaluation.objects.filter(
            data_snapshot=snapshot,
        ).count(),
        "rules": Rule.objects.filter(data_snapshot=snapshot).count(),
        "rule_versions": RuleVersion.objects.filter(data_snapshot=snapshot).count(),
        "subscriptions": Subscription.objects.filter(data_snapshot=snapshot).count(),
        "subscription_connections": SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
        ).count(),
    }
