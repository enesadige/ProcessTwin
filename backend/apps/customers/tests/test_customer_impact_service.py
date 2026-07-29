from datetime import datetime, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.customers.models import (
    Customer,
    ServicePackage,
    Subscription,
    SubscriptionConnection,
    SubscriptionConnectionRole,
    SubscriptionStatus,
)
from apps.customers.services.impact import CustomerImpactInputError, CustomerImpactService
from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion, DataSnapshot, GroundTruthCase
from apps.geography.models import City, District
from apps.network.models import (
    AccessSegment,
    AccessTechnology,
    LineConnection,
    NetworkDevice,
    NetworkDeviceType,
    NetworkPort,
)
from apps.operations.models import Outage, OutageStatus, OutageType
from apps.operations.services.outages import OutageServiceInputError


@pytest.mark.django_db
def test_customer_impact_main_bng_outage_matches_ground_truth():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    ground_truth = get_ground_truth(snapshot, outage.outage_code)

    result = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)

    assert result.outage_code == "OUT-MAL-BNG-001"
    assert result.source_device_code == "BNG-MAL-001"
    assert result.snapshot["id"] == snapshot.id
    assert result.evaluation_window["started_at"] == outage.started_at.isoformat()
    assert result.evaluation_window["ended_at"] == outage.ended_at.isoformat()
    assert result.evaluation_window["duration_seconds"] == "12000"
    assert result.affected_subscription_count == 150
    assert result.affected_customer_count == 140
    assert result.affected_subscription_codes == ground_truth.affected_subscription_codes
    assert result.affected_customer_codes == ground_truth.affected_customer_codes
    assert result.package_technology_counts == {
        AccessTechnology.ADSL: 15,
        AccessTechnology.FIBER: 80,
        AccessTechnology.VDSL: 55,
    }
    assert result.customer_segment_counts == ground_truth.affected_segment_counts
    assert result.customer_priority_counts == ground_truth.affected_priority_counts


@pytest.mark.django_db
@pytest.mark.parametrize("outage_code", ["OUT-MAL-OLT-001", "OUT-MAL-DSLAM-001"])
def test_customer_impact_short_outages_match_ground_truth(outage_code):
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, outage_code)
    ground_truth = get_ground_truth(snapshot, outage.outage_code)

    result = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)

    assert result.affected_subscription_codes == ground_truth.affected_subscription_codes
    assert result.affected_subscription_count == ground_truth.affected_subscription_count
    assert result.affected_customer_codes == ground_truth.affected_customer_codes
    assert result.affected_customer_count == ground_truth.affected_customer_count
    assert result.customer_segment_counts == ground_truth.affected_segment_counts
    assert result.customer_priority_counts == ground_truth.affected_priority_counts
    assert sum(result.package_technology_counts.values()) == result.affected_subscription_count


@pytest.mark.django_db
def test_customer_impact_excludes_cross_snapshot_connection():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    ground_truth = get_ground_truth(snapshot, outage.outage_code)
    existing_customer = Customer.objects.filter(data_snapshot=snapshot).first()
    existing_package = ServicePackage.objects.filter(data_snapshot=snapshot).first()
    other_line = create_other_snapshot_line()
    subscription = Subscription.objects.create(
        data_snapshot=snapshot,
        subscription_number="SUB-MAL-CROSS-SNAPSHOT-001",
        customer=existing_customer,
        service_package=existing_package,
        status=SubscriptionStatus.ACTIVE,
        valid_from=outage.started_at - timedelta(days=1),
        monthly_price=existing_package.monthly_price,
    )
    SubscriptionConnection.objects.bulk_create(
        [
            SubscriptionConnection(
                data_snapshot=snapshot,
                subscription=subscription,
                line_connection=other_line,
                valid_from=outage.started_at - timedelta(hours=1),
                is_active=True,
            )
        ]
    )

    result = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)

    assert result.affected_subscription_count == ground_truth.affected_subscription_count
    assert "SUB-MAL-CROSS-SNAPSHOT-001" not in result.affected_subscription_codes


@pytest.mark.django_db
def test_customer_impact_excludes_connection_not_valid_during_outage():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    connection = get_first_affected_connection(snapshot, outage)
    SubscriptionConnection.objects.filter(pk=connection.pk).update(
        valid_to=outage.started_at - timedelta(seconds=1)
    )

    result = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)

    assert result.affected_subscription_count == 149
    assert connection.subscription.subscription_number not in result.affected_subscription_codes


@pytest.mark.django_db
def test_customer_impact_excludes_inactive_subscription():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    connection = get_first_affected_connection(snapshot, outage)
    Subscription.objects.filter(pk=connection.subscription_id).update(is_active=False)

    result = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)

    assert result.affected_subscription_count == 149
    assert connection.subscription.subscription_number not in result.affected_subscription_codes


@pytest.mark.django_db
def test_customer_impact_deduplicates_customer_with_two_affected_subscriptions():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")

    result = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)

    assert result.affected_subscription_count == 150
    assert result.affected_customer_count == 140
    assert len(result.affected_customer_codes) == len(set(result.affected_customer_codes))
    assert result.affected_subscription_count > result.affected_customer_count


@pytest.mark.django_db
def test_customer_impact_excludes_subscription_when_primary_impacted_and_backup_healthy():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    primary = get_first_connection_by_bng_and_technology(
        snapshot,
        bng_code="BNG-MAL-001",
        technology=AccessTechnology.FIBER,
    )
    backup_line = create_additional_fiber_line_on_bng(
        snapshot,
        bng_code="BNG-MAL-002",
        suffix="FAILOVER-HEALTHY",
    )
    SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=primary.subscription,
        line_connection=backup_line,
        connection_role=SubscriptionConnectionRole.BACKUP,
        valid_from=outage.started_at - timedelta(days=1),
    )

    result = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)

    assert primary.subscription.subscription_number not in result.affected_subscription_codes
    assert primary.subscription.subscription_number in (
        result.failover_protected_subscription_codes
    )
    assert result.failover_protected_subscription_count == 1
    assert result.affected_subscription_count == 149


@pytest.mark.django_db
def test_customer_impact_counts_subscription_once_when_primary_and_backup_impacted():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    primary = get_first_connection_by_bng_and_technology(
        snapshot,
        bng_code="BNG-MAL-001",
        technology=AccessTechnology.FIBER,
    )
    backup_line = create_additional_fiber_line_on_bng(
        snapshot,
        bng_code="BNG-MAL-001",
        suffix="FAILOVER-IMPACTED",
    )
    SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=primary.subscription,
        line_connection=backup_line,
        connection_role=SubscriptionConnectionRole.BACKUP,
        valid_from=outage.started_at - timedelta(days=1),
    )

    result = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)

    assert result.affected_subscription_codes.count(
        primary.subscription.subscription_number
    ) == 1
    assert primary.subscription.subscription_number not in (
        result.failover_protected_subscription_codes
    )
    assert result.affected_subscription_count == 150


@pytest.mark.django_db
def test_customer_impact_ignores_subscription_when_only_backup_is_impacted():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    primary = get_first_connection_by_bng_and_technology(
        snapshot,
        bng_code="BNG-MAL-002",
        technology=AccessTechnology.FIBER,
    )
    backup_line = create_additional_fiber_line_on_bng(
        snapshot,
        bng_code="BNG-MAL-001",
        suffix="ONLY-BACKUP-IMPACTED",
    )
    SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=primary.subscription,
        line_connection=backup_line,
        connection_role=SubscriptionConnectionRole.BACKUP,
        valid_from=outage.started_at - timedelta(days=1),
    )

    result = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)

    assert primary.subscription.subscription_number not in result.affected_subscription_codes
    assert primary.subscription.subscription_number not in (
        result.failover_protected_subscription_codes
    )
    assert result.affected_subscription_count == 150


@pytest.mark.django_db
def test_customer_impact_rejects_missing_source_device():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    outage.source_device_id = None

    with pytest.raises(CustomerImpactInputError, match="has no source device"):
        CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)


@pytest.mark.django_db
def test_customer_impact_requires_evaluation_time_for_ongoing_outage():
    snapshot = seed_snapshot()
    outage = create_ongoing_outage(snapshot)

    with pytest.raises(OutageServiceInputError, match="evaluation_time is required"):
        CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)


@pytest.mark.django_db
def test_customer_impact_rejects_naive_evaluation_time_for_ongoing_outage():
    snapshot = seed_snapshot()
    outage = create_ongoing_outage(snapshot)

    with pytest.raises(OutageServiceInputError, match="timezone-aware"):
        CustomerImpactService().calculate_impact(
            outage=outage,
            snapshot=snapshot,
            evaluation_time=datetime(2026, 7, 20, 10, 30),
        )


def seed_snapshot() -> DataSnapshot:
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def get_outage(snapshot: DataSnapshot, outage_code: str) -> Outage:
    return Outage.objects.get(data_snapshot=snapshot, outage_code=outage_code)


def get_ground_truth(snapshot: DataSnapshot, outage_code: str) -> GroundTruthCase:
    return GroundTruthCase.objects.get(data_snapshot=snapshot, outage_code=outage_code)


def get_first_affected_connection(snapshot: DataSnapshot, outage: Outage) -> SubscriptionConnection:
    return (
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            line_connection__port__device__metadata__parent_bng=outage.source_device.code,
        )
        .select_related("subscription")
        .order_by("subscription__subscription_number")
        .first()
    )


def get_first_connection_by_bng_and_technology(
    snapshot: DataSnapshot,
    *,
    bng_code: str,
    technology: AccessTechnology,
) -> SubscriptionConnection:
    return (
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            connection_role=SubscriptionConnectionRole.PRIMARY,
            subscription__service_package__technology=technology,
            line_connection__port__device__metadata__parent_bng=bng_code,
        )
        .select_related("subscription", "line_connection")
        .order_by("subscription__subscription_number")
        .first()
    )


def create_additional_fiber_line_on_bng(
    snapshot: DataSnapshot,
    *,
    bng_code: str,
    suffix: str,
) -> LineConnection:
    device = (
        NetworkDevice.objects.filter(
            data_snapshot=snapshot,
            device_type=NetworkDeviceType.ACCESS_NODE,
            metadata__parent_bng=bng_code,
        )
        .order_by("code")
        .first()
    )
    port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=device,
        port_code=f"PORT-{suffix}",
    )
    segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code=f"SEG-{suffix}",
        name=f"Additional fiber segment {suffix}",
        technology=AccessTechnology.FIBER,
        serving_device=device,
        city=device.city,
        district=device.district,
        neighborhood=device.neighborhood,
        estimated_customer_count=1,
    )
    return LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code=f"LINE-{suffix}",
        port=port,
        access_segment=segment,
        technology=AccessTechnology.FIBER,
        valid_from=timezone.datetime(
            2026,
            7,
            1,
            0,
            0,
            tzinfo=timezone.get_current_timezone(),
        ),
    )


def create_ongoing_outage(snapshot: DataSnapshot) -> Outage:
    source_device = NetworkDevice.objects.get(data_snapshot=snapshot, code="BNG-MAL-001")
    started_at = timezone.datetime(2026, 7, 20, 10, 15, tzinfo=timezone.get_current_timezone())
    return Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-ONGOING-IMPACT-001",
        source_device=source_device,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.OPEN,
        detected_at=started_at,
        started_at=started_at,
    )


def create_other_snapshot_line() -> LineConnection:
    dataset = DatasetVersion.objects.create(
        name="Other Customer Impact Dataset",
        generator_version="other-v1",
        seed="other-seed",
    )
    snapshot = DataSnapshot.objects.create(dataset_version=dataset, name="Other Snapshot")
    city = City.objects.create(name="Other İstanbul", plate_code="34")
    district = District.objects.create(city=city, name="Other Maltepe")
    device = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="BNG-OTHER-001",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )
    port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=device,
        port_code="OTHER-PORT-001",
    )
    segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code="SEG-OTHER-FIBER-001",
        name="Other fiber segment",
        technology=AccessTechnology.FIBER,
        serving_device=device,
        city=city,
        district=district,
        estimated_customer_count=1,
    )
    return LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code="LINE-OTHER-FIBER-001",
        port=port,
        access_segment=segment,
        technology=AccessTechnology.FIBER,
        valid_from=timezone.now() - timedelta(days=1),
    )
