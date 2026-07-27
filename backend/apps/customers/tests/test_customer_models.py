from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.customers.models import (
    CampaignEnrollment,
    CampaignStatus,
    CompensationHistory,
    CompensationHistoryStatus,
    Customer,
    CustomerSegment,
    PaymentRecord,
    PaymentStatus,
    ServicePackage,
    Subscription,
    SubscriptionConnection,
    SubscriptionStatus,
)
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.geography.models import AreaProfileType, City, District, Neighborhood
from apps.network.models import (
    AccessSegment,
    AccessTechnology,
    LineConnection,
    NetworkDevice,
    NetworkDeviceType,
    NetworkPort,
    NetworkPortType,
)


def create_snapshot(seed: str = "maltepe-customer-seed-001") -> DataSnapshot:
    dataset = DatasetVersion.objects.create(
        name=f"Maltepe Customers {seed}",
        generator_version="gen-0.1.0",
        seed=seed,
    )
    return DataSnapshot.objects.create(dataset_version=dataset, name="Initial snapshot")


def create_maltepe_location() -> tuple[City, District, Neighborhood]:
    city = City.objects.create(name="İstanbul", plate_code="34")
    district = District.objects.create(
        city=city,
        name="Maltepe",
        profile_type=AreaProfileType.MIXED,
    )
    neighborhood = Neighborhood.objects.create(
        district=district,
        name="Zümrütevler",
        profile_type=AreaProfileType.RESIDENTIAL,
    )
    return city, district, neighborhood


def create_line_connection(
    snapshot: DataSnapshot,
    city: City,
    district: District,
    technology: AccessTechnology = AccessTechnology.VDSL,
) -> LineConnection:
    bng = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="BNG-MAL-001",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )
    port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=bng,
        port_code="1/1/1",
        port_type=NetworkPortType.DOWNLINK,
    )
    segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code=f"SEG-MAL-{technology.value.upper()}-001",
        name=f"Maltepe {technology.label} access",
        technology=technology,
        serving_device=bng,
        city=city,
        district=district,
        estimated_customer_count=500,
    )
    return LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code=f"LINE-MAL-{technology.value.upper()}-001",
        port=port,
        access_segment=segment,
        technology=technology,
        valid_from=timezone.now() - timedelta(days=30),
    )


def create_customer_subscription(
    snapshot: DataSnapshot,
    city: City,
    district: District,
    neighborhood: Neighborhood,
    technology: AccessTechnology = AccessTechnology.VDSL,
) -> tuple[Customer, ServicePackage, Subscription]:
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
        package_code=f"PKG-{technology.value.upper()}-50",
        name=f"{technology.label} 50 Mbps",
        technology=technology,
        download_mbps=50,
        upload_mbps=10,
        monthly_price=Decimal("399.90"),
        commitment_months=12,
    )
    subscription = Subscription.objects.create(
        data_snapshot=snapshot,
        subscription_number="SUB-MAL-0001",
        customer=customer,
        service_package=package,
        status=SubscriptionStatus.ACTIVE,
        valid_from=timezone.now() - timedelta(days=10),
        monthly_price=Decimal("399.90"),
    )
    return customer, package, subscription


@pytest.mark.django_db
def test_active_subscription_connection_reaches_customer_from_bng_line():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    line = create_line_connection(snapshot, city, district, AccessTechnology.VDSL)
    customer, package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
        AccessTechnology.VDSL,
    )
    now = timezone.now()

    connection = SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=line,
        valid_from=now - timedelta(days=5),
        port_identifier="1/1/1",
    )

    assert line.port.device.code == "BNG-MAL-001"
    assert package.technology == AccessTechnology.VDSL
    assert connection.subscription.customer == customer
    assert subscription.is_valid_at(now)
    assert line.is_valid_at(now)
    assert connection.is_valid_at(now)


@pytest.mark.django_db
def test_subscription_connection_rejects_package_line_technology_mismatch():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    line = create_line_connection(snapshot, city, district, AccessTechnology.FIBER)
    _customer, _package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
        AccessTechnology.VDSL,
    )

    connection = SubscriptionConnection(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=line,
        valid_from=timezone.now(),
    )

    with pytest.raises(ValidationError):
        connection.full_clean()


@pytest.mark.django_db
def test_subscription_connection_rejects_cross_snapshot_line():
    first_snapshot = create_snapshot("first-seed")
    second_snapshot = create_snapshot("second-seed")
    city, district, neighborhood = create_maltepe_location()
    line = create_line_connection(first_snapshot, city, district, AccessTechnology.VDSL)
    _customer, _package, subscription = create_customer_subscription(
        second_snapshot,
        city,
        district,
        neighborhood,
        AccessTechnology.VDSL,
    )

    connection = SubscriptionConnection(
        data_snapshot=second_snapshot,
        subscription=subscription,
        line_connection=line,
        valid_from=timezone.now(),
    )

    with pytest.raises(ValidationError):
        connection.full_clean()


@pytest.mark.django_db
def test_customer_package_and_subscription_identifiers_are_unique_per_snapshot():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    customer, package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Customer.objects.create(
                data_snapshot=snapshot,
                customer_number=customer.customer_number,
                display_name="Duplicate customer",
                city=city,
                district=district,
            )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ServicePackage.objects.create(
                data_snapshot=snapshot,
                package_code=package.package_code,
                name="Duplicate package",
                technology=AccessTechnology.VDSL,
                monthly_price=Decimal("299.90"),
            )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Subscription.objects.create(
                data_snapshot=snapshot,
                subscription_number=subscription.subscription_number,
                customer=customer,
                service_package=package,
                valid_from=timezone.now(),
                monthly_price=Decimal("399.90"),
            )


@pytest.mark.django_db
def test_customer_location_chain_is_validated():
    snapshot = create_snapshot()
    istanbul = City.objects.create(name="İstanbul", plate_code="34")
    ankara = City.objects.create(name="Ankara", plate_code="06")
    maltepe = District.objects.create(city=istanbul, name="Maltepe")

    customer = Customer(
        data_snapshot=snapshot,
        customer_number="CUST-MAL-0001",
        display_name="Invalid Location",
        city=ankara,
        district=maltepe,
    )

    with pytest.raises(ValidationError):
        customer.full_clean()


@pytest.mark.django_db
def test_payment_campaign_and_compensation_history_keep_subscription_context():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    _customer, _package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
    )
    now = timezone.now()

    payment = PaymentRecord.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        period="2026-07",
        amount=Decimal("399.90"),
        status=PaymentStatus.PAID,
        paid_at=now,
    )
    campaign = CampaignEnrollment.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        campaign_code="CMP-MAL-001",
        name="Maltepe retention campaign",
        status=CampaignStatus.ACTIVE,
        valid_from=now - timedelta(days=10),
    )
    compensation = CompensationHistory.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        reference_code="COMP-MAL-001",
        amount=Decimal("47.99"),
        status=CompensationHistoryStatus.APPROVED,
        reason="MVP outage compensation example",
        decided_at=now,
    )

    assert str(payment) == "SUB-MAL-0001 - 2026-07"
    assert str(campaign) == "SUB-MAL-0001 - CMP-MAL-001"
    assert str(compensation) == "COMP-MAL-001 - SUB-MAL-0001"
