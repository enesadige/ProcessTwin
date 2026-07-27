from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.compensation.models import (
    CompensationEvaluation,
    CompensationEvaluationStatus,
    CompensationResultType,
)
from apps.customers.models import Customer, CustomerSegment, ServicePackage, Subscription
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.geography.models import AreaProfileType, City, District, Neighborhood
from apps.network.models import AccessTechnology, NetworkDevice, NetworkDeviceType
from apps.operations.models import Outage, OutageStatus, OutageType, RootCauseCategory
from apps.rules.models import Rule, RuleStatus, RuleType, RuleVersion, RuleVersionStatus


def create_snapshot(seed: str = "compensation-seed-001") -> DataSnapshot:
    dataset = DatasetVersion.objects.create(
        name=f"Compensation Dataset {seed}",
        generator_version="gen-0.1.0",
        seed=seed,
    )
    return DataSnapshot.objects.create(dataset_version=dataset, name="Initial snapshot")


def create_context(snapshot: DataSnapshot):
    city = City.objects.create(name=f"İstanbul {snapshot.id}", plate_code="34")
    district = District.objects.create(
        city=city,
        name="Maltepe",
        profile_type=AreaProfileType.MIXED,
    )
    neighborhood = Neighborhood.objects.create(district=district, name="Zümrütevler")
    bng = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="BNG-MAL-001",
        name="Maltepe BNG 001",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )
    customer = Customer.objects.create(
        data_snapshot=snapshot,
        customer_number="CUST-MAL-0001",
        display_name="Maltepe Test Customer",
        segment=CustomerSegment.INDIVIDUAL,
        city=city,
        district=district,
        neighborhood=neighborhood,
    )
    package = ServicePackage.objects.create(
        data_snapshot=snapshot,
        package_code="PKG-VDSL-50",
        name="VDSL 50 Mbps",
        technology=AccessTechnology.VDSL,
        download_mbps=50,
        upload_mbps=10,
        monthly_price=Decimal("399.90"),
    )
    subscription = Subscription.objects.create(
        data_snapshot=snapshot,
        subscription_number="SUB-MAL-0001",
        customer=customer,
        service_package=package,
        valid_from=timezone.now() - timedelta(days=30),
        monthly_price=Decimal("399.90"),
    )
    outage = Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-001",
        source_device=bng,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.RESOLVED,
        root_cause_category=RootCauseCategory.BNG_FAILURE,
        detected_at=timezone.now() - timedelta(hours=3),
        started_at=timezone.now() - timedelta(hours=3),
        ended_at=timezone.now(),
        resolved_at=timezone.now(),
    )
    rule = Rule.objects.create(
        data_snapshot=snapshot,
        code="REFUND-001",
        name="Placeholder compensation rule",
        rule_type=RuleType.COMPENSATION,
        status=RuleStatus.ACTIVE,
        description="Placeholder only; real calculation is implemented later.",
    )
    rule_version = RuleVersion.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        version=1,
        status=RuleVersionStatus.ACTIVE,
        valid_from=timezone.now() - timedelta(days=1),
        action_config={"amount_strategy": "service_defined"},
    )
    return customer, subscription, outage, rule_version


@pytest.mark.django_db
def test_compensation_evaluation_links_outage_subscription_customer_and_rule_version():
    snapshot = create_snapshot()
    customer, subscription, outage, rule_version = create_context(snapshot)

    evaluation = CompensationEvaluation.objects.create(
        data_snapshot=snapshot,
        evaluation_code="CE-MAL-001",
        outage=outage,
        customer=customer,
        subscription=subscription,
        rule_version=rule_version,
        result_type=CompensationResultType.ELIGIBLE,
        status=CompensationEvaluationStatus.CALCULATED,
        proposed_amount=Decimal("47.99"),
        currency="TRY",
        explanation="Placeholder evaluation record; formula will be added later.",
        calculation_trace={"source": "model_smoke"},
    )

    assert str(evaluation) == "CE-MAL-001 - SUB-MAL-0001"
    assert evaluation.outage.source_device.code == "BNG-MAL-001"
    assert evaluation.customer == customer
    assert evaluation.rule_version == rule_version
    assert evaluation.proposed_amount == Decimal("47.99")
    assert evaluation.calculation_trace == {"source": "model_smoke"}


@pytest.mark.django_db
def test_duplicate_evaluation_for_same_outage_subscription_rule_is_rejected():
    snapshot = create_snapshot()
    customer, subscription, outage, rule_version = create_context(snapshot)
    CompensationEvaluation.objects.create(
        data_snapshot=snapshot,
        evaluation_code="CE-MAL-001",
        outage=outage,
        customer=customer,
        subscription=subscription,
        rule_version=rule_version,
        result_type=CompensationResultType.MANUAL_REVIEW,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CompensationEvaluation.objects.create(
                data_snapshot=snapshot,
                evaluation_code="CE-MAL-002",
                outage=outage,
                customer=customer,
                subscription=subscription,
                rule_version=rule_version,
                result_type=CompensationResultType.MANUAL_REVIEW,
            )


@pytest.mark.django_db
def test_negative_amount_and_invalid_currency_are_rejected():
    snapshot = create_snapshot()
    customer, subscription, outage, rule_version = create_context(snapshot)
    evaluation = CompensationEvaluation(
        data_snapshot=snapshot,
        evaluation_code="CE-MAL-001",
        outage=outage,
        customer=customer,
        subscription=subscription,
        rule_version=rule_version,
        result_type=CompensationResultType.ELIGIBLE,
        proposed_amount=Decimal("-1.00"),
        currency="TL",
    )

    with pytest.raises(ValidationError):
        evaluation.full_clean()


@pytest.mark.django_db
def test_cross_snapshot_dependencies_are_rejected():
    first_snapshot = create_snapshot("first-seed")
    second_snapshot = create_snapshot("second-seed")
    customer, subscription, outage, rule_version = create_context(first_snapshot)

    evaluation = CompensationEvaluation(
        data_snapshot=second_snapshot,
        evaluation_code="CE-MAL-001",
        outage=outage,
        customer=customer,
        subscription=subscription,
        rule_version=rule_version,
        result_type=CompensationResultType.INSUFFICIENT_DATA,
    )

    with pytest.raises(ValidationError):
        evaluation.full_clean()


@pytest.mark.django_db
def test_subscription_must_belong_to_selected_customer():
    snapshot = create_snapshot()
    _customer, subscription, outage, rule_version = create_context(snapshot)
    other_customer = Customer.objects.create(
        data_snapshot=snapshot,
        customer_number="CUST-MAL-0002",
        display_name="Another Customer",
        city=subscription.customer.city,
        district=subscription.customer.district,
    )

    evaluation = CompensationEvaluation(
        data_snapshot=snapshot,
        evaluation_code="CE-MAL-001",
        outage=outage,
        customer=other_customer,
        subscription=subscription,
        rule_version=rule_version,
        result_type=CompensationResultType.MANUAL_REVIEW,
    )

    with pytest.raises(ValidationError):
        evaluation.full_clean()
