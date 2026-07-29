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
    CustomerPriorityLevel,
    CustomerSegment,
    PaymentRecord,
    PaymentStatus,
    ServicePackage,
    ServiceType,
    Subscription,
    SubscriptionConnection,
    SubscriptionConnectionRole,
    SubscriptionStatus,
)
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.geography.models import AreaProfileType, City, District, Neighborhood
from apps.network.models import (
    AccessSegment,
    AccessTechnology,
    LineConnection,
    NetworkDevice,
    NetworkDeviceAccessRole,
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
    suffix: str = "001",
) -> LineConnection:
    bng = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code=f"BNG-MAL-{suffix}",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )
    port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=bng,
        port_code=f"1/1/{int(suffix)}",
        port_type=NetworkPortType.DOWNLINK,
    )
    segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code=f"SEG-MAL-{technology.value.upper()}-{suffix}",
        name=f"Maltepe {technology.label} access {suffix}",
        technology=technology,
        serving_device=bng,
        city=city,
        district=district,
        estimated_customer_count=500,
    )
    return LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code=f"LINE-MAL-{technology.value.upper()}-{suffix}",
        port=port,
        access_segment=segment,
        technology=technology,
        valid_from=timezone.now() - timedelta(days=30),
    )


def create_access_node_fiber_line(
    snapshot: DataSnapshot,
    city: City,
    district: District,
    *,
    suffix: str = "001",
    access_role: NetworkDeviceAccessRole = NetworkDeviceAccessRole.CORPORATE_FIBER_AGGREGATION,
) -> LineConnection:
    device = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code=f"AN-MAL-{suffix}",
        device_type=NetworkDeviceType.ACCESS_NODE,
        access_role=access_role,
        city=city,
        district=district,
    )
    port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=device,
        port_code=f"AN-PORT-{suffix}",
        port_type=NetworkPortType.CUSTOMER,
    )
    segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code=f"SEG-MAL-FIBER-AN-{suffix}",
        name=f"Maltepe corporate fiber access {suffix}",
        technology=AccessTechnology.FIBER,
        serving_device=device,
        city=city,
        district=district,
        estimated_customer_count=1,
    )
    return LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code=f"LINE-MAL-FIBER-AN-{suffix}",
        port=port,
        access_segment=segment,
        technology=AccessTechnology.FIBER,
        valid_from=timezone.now() - timedelta(days=30),
    )


def create_customer_subscription(
    snapshot: DataSnapshot,
    city: City,
    district: District,
    neighborhood: Neighborhood,
    technology: AccessTechnology = AccessTechnology.VDSL,
    suffix: str = "0001",
) -> tuple[Customer, ServicePackage, Subscription]:
    customer = Customer.objects.create(
        data_snapshot=snapshot,
        customer_number=f"CUST-MAL-{suffix}",
        display_name=f"Maltepe Test Customer {suffix}",
        segment=CustomerSegment.INDIVIDUAL,
        city=city,
        district=district,
        neighborhood=neighborhood,
    )
    package = ServicePackage.objects.create(
        data_snapshot=snapshot,
        package_code=f"PKG-{technology.value.upper()}-50-{suffix}",
        name=f"{technology.label} 50 Mbps {suffix}",
        technology=technology,
        download_mbps=50,
        upload_mbps=10,
        monthly_price=Decimal("399.90"),
        commitment_months=12,
    )
    subscription = Subscription.objects.create(
        data_snapshot=snapshot,
        subscription_number=f"SUB-MAL-{suffix}",
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
def test_customer_priority_level_defaults_to_standard():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()

    customer = Customer.objects.create(
        data_snapshot=snapshot,
        customer_number="CUST-MAL-PRIORITY-001",
        display_name="Standard Priority Customer",
        city=city,
        district=district,
        neighborhood=neighborhood,
    )

    assert customer.priority_level == CustomerPriorityLevel.STANDARD


@pytest.mark.django_db
def test_customer_priority_level_can_store_vip_independently_from_segment():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()

    customer = Customer.objects.create(
        data_snapshot=snapshot,
        customer_number="CUST-MAL-VIP-001",
        display_name="VIP SME Customer",
        segment=CustomerSegment.SME,
        priority_level=CustomerPriorityLevel.VIP,
        city=city,
        district=district,
        neighborhood=neighborhood,
    )

    assert customer.segment == CustomerSegment.SME
    assert customer.priority_level == CustomerPriorityLevel.VIP


@pytest.mark.django_db
def test_service_package_service_type_defaults_to_broadband():
    snapshot = create_snapshot()
    package = ServicePackage.objects.create(
        data_snapshot=snapshot,
        package_code="PKG-FIBER-100",
        name="Fiber 100",
        technology=AccessTechnology.FIBER,
        download_mbps=100,
        upload_mbps=20,
        monthly_price=Decimal("399.90"),
        commitment_months=12,
    )

    assert package.service_type == ServiceType.BROADBAND


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
def test_subscription_connection_accepts_fiber_package_on_gpon_line():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    line = create_line_connection(snapshot, city, district, AccessTechnology.GPON)
    _customer, _package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
        AccessTechnology.FIBER,
    )

    connection = SubscriptionConnection(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=line,
        valid_from=timezone.now(),
    )

    connection.full_clean()


@pytest.mark.django_db
def test_subscription_connection_accepts_metro_ethernet_package_on_fiber_line():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    line = create_access_node_fiber_line(snapshot, city, district)
    _customer, package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
        AccessTechnology.FIBER,
    )
    package.service_type = ServiceType.METRO_ETHERNET
    package.save(update_fields=["service_type"])

    connection = SubscriptionConnection(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=line,
        valid_from=timezone.now(),
    )

    connection.full_clean()


@pytest.mark.django_db
def test_subscription_connection_rejects_metro_ethernet_package_on_gpon_line():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    line = create_line_connection(snapshot, city, district, AccessTechnology.GPON)
    _customer, package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
        AccessTechnology.FIBER,
    )
    package.service_type = ServiceType.METRO_ETHERNET
    package.save(update_fields=["service_type"])

    connection = SubscriptionConnection(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=line,
        valid_from=timezone.now(),
    )

    with pytest.raises(ValidationError):
        connection.full_clean()


@pytest.mark.django_db
def test_subscription_connection_rejects_metro_ethernet_on_standard_access_node():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    line = create_access_node_fiber_line(
        snapshot,
        city,
        district,
        access_role=NetworkDeviceAccessRole.STANDARD_ACCESS,
    )
    _customer, package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
        AccessTechnology.FIBER,
    )
    package.service_type = ServiceType.METRO_ETHERNET
    package.save(update_fields=["service_type"])

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
def test_subscription_connection_rejects_overlapping_active_connection_for_same_subscription():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    first_line = create_line_connection(snapshot, city, district, suffix="001")
    second_line = create_line_connection(snapshot, city, district, suffix="002")
    _customer, _package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
    )
    now = timezone.now()
    SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=first_line,
        valid_from=now - timedelta(days=5),
        valid_to=now + timedelta(days=5),
    )

    with pytest.raises(ValidationError):
        SubscriptionConnection.objects.create(
            data_snapshot=snapshot,
            subscription=subscription,
            line_connection=second_line,
            valid_from=now,
            valid_to=now + timedelta(days=10),
        )


@pytest.mark.django_db
def test_subscription_connection_allows_open_primary_and_backup_for_same_subscription():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    primary_line = create_line_connection(snapshot, city, district, suffix="001")
    backup_line = create_line_connection(snapshot, city, district, suffix="002")
    _customer, _package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
    )
    now = timezone.now()

    primary = SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=primary_line,
        connection_role=SubscriptionConnectionRole.PRIMARY,
        valid_from=now - timedelta(days=1),
    )
    backup = SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=backup_line,
        connection_role=SubscriptionConnectionRole.BACKUP,
        valid_from=now,
    )

    assert primary.connection_role == SubscriptionConnectionRole.PRIMARY
    assert backup.connection_role == SubscriptionConnectionRole.BACKUP


@pytest.mark.django_db
def test_subscription_connection_rejects_second_open_backup_for_same_subscription():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    primary_line = create_line_connection(snapshot, city, district, suffix="001")
    first_backup_line = create_line_connection(snapshot, city, district, suffix="002")
    second_backup_line = create_line_connection(snapshot, city, district, suffix="003")
    _customer, _package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
    )
    now = timezone.now()
    SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=primary_line,
        connection_role=SubscriptionConnectionRole.PRIMARY,
        valid_from=now - timedelta(days=1),
    )
    SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=first_backup_line,
        connection_role=SubscriptionConnectionRole.BACKUP,
        valid_from=now,
    )

    with pytest.raises(ValidationError):
        SubscriptionConnection.objects.create(
            data_snapshot=snapshot,
            subscription=subscription,
            line_connection=second_backup_line,
            connection_role=SubscriptionConnectionRole.BACKUP,
            valid_from=now,
        )


@pytest.mark.django_db
def test_subscription_connection_rejects_open_backup_without_primary():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    backup_line = create_line_connection(snapshot, city, district)
    _customer, _package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
    )

    with pytest.raises(ValidationError):
        SubscriptionConnection.objects.create(
            data_snapshot=snapshot,
            subscription=subscription,
            line_connection=backup_line,
            connection_role=SubscriptionConnectionRole.BACKUP,
            valid_from=timezone.now(),
        )


@pytest.mark.django_db
def test_subscription_connection_rejects_overlapping_active_connection_for_same_line():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    line = create_line_connection(snapshot, city, district)
    _customer, _package, first_subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
        suffix="0001",
    )
    _other_customer, _other_package, second_subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
        suffix="0002",
    )
    now = timezone.now()
    SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=first_subscription,
        line_connection=line,
        valid_from=now - timedelta(days=5),
        valid_to=now + timedelta(days=5),
    )

    with pytest.raises(ValidationError):
        SubscriptionConnection.objects.create(
            data_snapshot=snapshot,
            subscription=second_subscription,
            line_connection=line,
            valid_from=now,
            valid_to=now + timedelta(days=10),
        )


@pytest.mark.django_db
def test_subscription_connection_allows_adjacent_active_connection_ranges():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    first_line = create_line_connection(snapshot, city, district, suffix="001")
    second_line = create_line_connection(snapshot, city, district, suffix="002")
    _customer, _package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
    )
    now = timezone.now()
    first_connection = SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=first_line,
        valid_from=now - timedelta(days=5),
        valid_to=now,
    )
    second_connection = SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=second_line,
        valid_from=now,
        valid_to=now + timedelta(days=5),
    )

    assert first_connection.is_valid_at(now - timedelta(seconds=1))
    assert not first_connection.is_valid_at(now)
    assert second_connection.is_valid_at(now)


@pytest.mark.django_db
def test_subscription_connection_must_stay_inside_subscription_and_line_ranges():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()
    line = create_line_connection(snapshot, city, district)
    _customer, _package, subscription = create_customer_subscription(
        snapshot,
        city,
        district,
        neighborhood,
    )

    starts_too_early = SubscriptionConnection(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=line,
        valid_from=subscription.valid_from - timedelta(days=1),
    )

    with pytest.raises(ValidationError):
        starts_too_early.full_clean()


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
