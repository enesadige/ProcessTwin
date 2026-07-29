from decimal import Decimal
from itertools import groupby

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.compensation.services.calculation import CompensationInputError, CompensationService
from apps.customers.models import Customer, ServicePackage, Subscription, SubscriptionConnection
from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion, DataSnapshot, GroundTruthCase
from apps.network.models import NetworkDevice
from apps.operations.models import Outage, OutageStatus, OutageType
from apps.rules.models import RuleVersion, RuleVersionStatus


@pytest.mark.django_db
def test_compensation_service_marks_main_bng_affected_subscription_eligible():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    subscription = get_affected_subscription_by_price(
        snapshot=snapshot,
        outage_code="OUT-MAL-BNG-001",
        monthly_price=Decimal("399.90"),
    )

    result = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=subscription,
        snapshot=snapshot,
    )

    assert result.status == "eligible"
    assert result.reason_code == "rule_matched"
    assert result.rule_code == "REFUND-001"
    assert result.rule_version == 2
    assert result.monthly_price == Decimal("399.90")
    assert result.refund_rate == Decimal("0.10")
    assert result.compensation_amount == Decimal("39.99")
    assert result.currency == "TRY"
    assert result.subscription_code == subscription.subscription_number
    assert result.customer_code == subscription.customer.customer_number
    assert result.snapshot["id"] == snapshot.id
    assert {item["name"] for item in result.deferred_checks} == {
        "PaymentRecord",
        "CampaignEnrollment",
        "CompensationHistory",
        "debt_or_late_payment",
        "campaign_discount",
        "previous_compensation",
    }


@pytest.mark.django_db
def test_compensation_service_rounds_499_90_monthly_price_to_49_99_try():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    subscription = get_affected_subscription_by_price(
        snapshot=snapshot,
        outage_code="OUT-MAL-BNG-001",
        monthly_price=Decimal("499.90"),
    )

    result = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=subscription,
        snapshot=snapshot,
    )

    assert result.status == "eligible"
    assert result.compensation_amount == Decimal("49.99")


@pytest.mark.django_db
def test_compensation_service_marks_short_outage_below_threshold_ineligible():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-OLT-001")
    subscription = get_affected_subscription(
        snapshot=snapshot,
        outage_code="OUT-MAL-OLT-001",
    )

    result = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=subscription,
        snapshot=snapshot,
    )

    assert result.status == "ineligible"
    assert result.reason_code == "duration_below_threshold"
    assert result.rule_version == 1
    assert result.compensation_amount == Decimal("0.00")


@pytest.mark.django_db
def test_compensation_service_marks_inactive_subscription_ineligible():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    subscription = get_affected_subscription(snapshot=snapshot, outage_code="OUT-MAL-BNG-001")
    Subscription.objects.filter(pk=subscription.pk).update(
        valid_to=outage.started_at,
    )
    subscription.refresh_from_db()

    result = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=subscription,
        snapshot=snapshot,
    )

    assert result.status == "ineligible"
    assert result.reason_code == "subscription_not_active_during_outage"
    assert result.compensation_amount == Decimal("0.00")


@pytest.mark.django_db
def test_compensation_service_returns_manual_review_without_valid_subscription_connection():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    subscription = get_affected_subscription(snapshot=snapshot, outage_code="OUT-MAL-BNG-001")
    SubscriptionConnection.objects.filter(
        data_snapshot=snapshot,
        subscription=subscription,
    ).update(valid_to=outage.started_at)

    result = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=subscription,
        snapshot=snapshot,
    )

    assert result.status == "manual_review"
    assert result.reason_code == "missing_data"
    assert result.missing_fields == ["subscription_connection"]
    assert result.compensation_amount == Decimal("0.00")


@pytest.mark.django_db
def test_compensation_service_returns_manual_review_for_missing_or_invalid_monthly_price():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    subscription = get_affected_subscription(snapshot=snapshot, outage_code="OUT-MAL-BNG-001")
    subscription.monthly_price = None

    result = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=subscription,
        snapshot=snapshot,
    )

    assert result.status == "manual_review"
    assert result.reason_code == "missing_data"
    assert result.missing_fields == ["monthly_price"]
    assert result.compensation_amount == Decimal("0.00")


@pytest.mark.django_db
def test_compensation_service_returns_manual_review_when_rule_evaluation_is_manual_review():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    subscription = get_affected_subscription(snapshot=snapshot, outage_code="OUT-MAL-BNG-001")
    RuleVersion.objects.filter(data_snapshot=snapshot, rule__code="REFUND-001", version=2).update(
        status=RuleVersionStatus.RETIRED,
    )

    result = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=subscription,
        snapshot=snapshot,
    )

    assert result.status == "manual_review"
    assert result.reason_code == "rule_manual_review"
    assert result.rule_version is None
    assert result.compensation_amount == Decimal("0.00")


@pytest.mark.django_db
def test_compensation_service_returns_manual_review_for_unsupported_action_config():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    subscription = get_affected_subscription(snapshot=snapshot, outage_code="OUT-MAL-BNG-001")
    version = RuleVersion.objects.get(data_snapshot=snapshot, rule__code="REFUND-001", version=2)
    version.action_config = {
        **version.action_config,
        "refund_formula": {
            **version.action_config["refund_formula"],
            "type": "formula_string",
        },
    }
    version.save(update_fields=["action_config"])

    result = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=subscription,
        snapshot=snapshot,
    )

    assert result.status == "manual_review"
    assert result.reason_code == "unsupported_action_config"
    assert result.compensation_amount == Decimal("0.00")


@pytest.mark.django_db
def test_compensation_service_evaluates_two_subscriptions_of_same_customer_separately():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    subscriptions = get_two_affected_subscriptions_for_same_customer(
        snapshot=snapshot,
        outage_code="OUT-MAL-BNG-001",
    )

    results = [
        CompensationService().evaluate_subscription(
            outage=outage,
            subscription=subscription,
            snapshot=snapshot,
        )
        for subscription in subscriptions
    ]

    assert len(results) == 2
    assert {result.subscription_code for result in results} == {
        subscription.subscription_number for subscription in subscriptions
    }
    assert len({result.customer_code for result in results}) == 1
    assert all(result.status == "eligible" for result in results)
    assert all(result.compensation_amount > Decimal("0.00") for result in results)


@pytest.mark.django_db
def test_compensation_service_rejects_cross_snapshot_subscription():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    other_subscription = create_other_snapshot_subscription()

    with pytest.raises(CompensationInputError, match="does not belong to snapshot"):
        CompensationService().evaluate_subscription(
            outage=outage,
            subscription=other_subscription,
            snapshot=snapshot,
        )


@pytest.mark.django_db
def test_compensation_service_handles_ongoing_outage_with_explicit_evaluation_time():
    snapshot = seed_snapshot()
    source_device = NetworkDevice.objects.get(data_snapshot=snapshot, code="BNG-MAL-001")
    outage = Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-COMP-ONGOING",
        source_device=source_device,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.OPEN,
        detected_at=timezone.datetime(2026, 7, 20, 10, 15, tzinfo=timezone.get_current_timezone()),
        started_at=timezone.datetime(2026, 7, 20, 10, 15, tzinfo=timezone.get_current_timezone()),
    )
    subscription = get_affected_subscription(snapshot=snapshot, outage_code="OUT-MAL-BNG-001")

    result = CompensationService().evaluate_subscription(
        outage=outage,
        subscription=subscription,
        snapshot=snapshot,
        evaluation_time=outage.started_at + timezone.timedelta(minutes=200),
    )

    assert result.status == "eligible"
    assert result.rule_version == 2
    assert result.compensation_amount > Decimal("0.00")


@pytest.mark.django_db
def test_compensation_service_requires_evaluation_time_for_ongoing_outage():
    snapshot = seed_snapshot()
    source_device = NetworkDevice.objects.get(data_snapshot=snapshot, code="BNG-MAL-001")
    outage = Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-COMP-ONGOING",
        source_device=source_device,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.OPEN,
        detected_at=timezone.datetime(2026, 7, 20, 10, 15, tzinfo=timezone.get_current_timezone()),
        started_at=timezone.datetime(2026, 7, 20, 10, 15, tzinfo=timezone.get_current_timezone()),
    )
    subscription = get_affected_subscription(snapshot=snapshot, outage_code="OUT-MAL-BNG-001")

    with pytest.raises(CompensationInputError, match="evaluation_time is required"):
        CompensationService().evaluate_subscription(
            outage=outage,
            subscription=subscription,
            snapshot=snapshot,
        )


@pytest.mark.django_db
def test_compensation_service_total_for_main_outage_matches_ground_truth_oracle():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    ground_truth = get_ground_truth(snapshot=snapshot, outage_code="OUT-MAL-BNG-001")
    subscriptions = Subscription.objects.filter(
        data_snapshot=snapshot,
        subscription_number__in=ground_truth.affected_subscription_codes,
    ).select_related("customer", "service_package")

    total = sum(
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

    assert total == Decimal("5173.50")
    assert total == ground_truth.expected_total_refund_amount


def seed_snapshot() -> DataSnapshot:
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def get_outage(snapshot: DataSnapshot, outage_code: str) -> Outage:
    return Outage.objects.select_related("source_device", "data_snapshot").get(
        data_snapshot=snapshot,
        outage_code=outage_code,
    )


def get_ground_truth(*, snapshot: DataSnapshot, outage_code: str) -> GroundTruthCase:
    return GroundTruthCase.objects.get(data_snapshot=snapshot, outage_code=outage_code)


def get_affected_subscription(*, snapshot: DataSnapshot, outage_code: str) -> Subscription:
    code = get_ground_truth(
        snapshot=snapshot,
        outage_code=outage_code,
    ).affected_subscription_codes[0]
    return get_subscription(snapshot=snapshot, subscription_number=code)


def get_affected_subscription_by_price(
    *,
    snapshot: DataSnapshot,
    outage_code: str,
    monthly_price: Decimal,
) -> Subscription:
    codes = get_ground_truth(snapshot=snapshot, outage_code=outage_code).affected_subscription_codes
    return (
        Subscription.objects.select_related("customer", "service_package")
        .filter(
            data_snapshot=snapshot,
            subscription_number__in=codes,
            monthly_price=monthly_price,
        )
        .order_by("subscription_number")
        .first()
    )


def get_subscription(*, snapshot: DataSnapshot, subscription_number: str) -> Subscription:
    return Subscription.objects.select_related("customer", "service_package").get(
        data_snapshot=snapshot,
        subscription_number=subscription_number,
    )


def get_two_affected_subscriptions_for_same_customer(
    *,
    snapshot: DataSnapshot,
    outage_code: str,
) -> list[Subscription]:
    affected_codes = set(
        get_ground_truth(snapshot=snapshot, outage_code=outage_code).affected_subscription_codes
    )
    subscriptions = list(
        Subscription.objects.select_related("customer")
        .filter(data_snapshot=snapshot, subscription_number__in=affected_codes)
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


def create_other_snapshot_subscription() -> Subscription:
    template = Subscription.objects.select_related(
        "customer",
        "service_package",
    ).first()
    dataset = DatasetVersion.objects.create(
        name="Other Compensation Dataset",
        generator_version="other-v1",
        seed="other-compensation-seed",
    )
    snapshot = DataSnapshot.objects.create(dataset_version=dataset, name="Other Snapshot")
    customer = Customer.objects.create(
        data_snapshot=snapshot,
        customer_number="CUST-OTHER-COMP-001",
        display_name="Other Compensation Customer",
        segment=template.customer.segment,
        priority_level=template.customer.priority_level,
        city=template.customer.city,
        district=template.customer.district,
        neighborhood=template.customer.neighborhood,
    )
    service_package = ServicePackage.objects.create(
        data_snapshot=snapshot,
        package_code="PKG-OTHER-COMP-001",
        name="Other compensation package",
        technology=template.service_package.technology,
        download_mbps=template.service_package.download_mbps,
        upload_mbps=template.service_package.upload_mbps,
        monthly_price=template.service_package.monthly_price,
        commitment_months=template.service_package.commitment_months,
    )
    return Subscription.objects.create(
        data_snapshot=snapshot,
        subscription_number="SUB-OTHER-COMP-001",
        customer=customer,
        service_package=service_package,
        status=template.status,
        valid_from=template.valid_from,
        valid_to=template.valid_to,
        is_active=template.is_active,
        monthly_price=template.monthly_price,
    )
