from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.customers.models import (
    Customer,
    ServicePackage,
    ServiceType,
    Subscription,
    SubscriptionConnection,
)
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.geography.models import AreaProfileType, City, District
from apps.network.models import (
    AccessSegment,
    AccessTechnology,
    LineConnection,
    NetworkDevice,
    NetworkDeviceAccessRole,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
)
from apps.operations.models import (
    Alarm,
    AlarmCategory,
    AlarmSourceKind,
    AlarmStatus,
    AlarmType,
    AlarmTypeAllowedSourceKind,
    FailoverResult,
    Incident,
    IncidentAlarm,
    IncidentAlarmRole,
    IncidentStatus,
    IncidentType,
    MaintenanceWindow,
    MaintenanceWindowStatus,
    OperationalEvent,
    OperationalEventType,
    Outage,
    OutageStatus,
    OutageType,
    QualityMeasurement,
    QualityMetricType,
    RootCauseCategory,
    ServiceImpactClass,
    Severity,
)


def create_snapshot(seed: str = "maltepe-ops-seed-001") -> DataSnapshot:
    dataset = DatasetVersion.objects.create(
        name=f"Maltepe Operations {seed}",
        generator_version="gen-0.1.0",
        seed=seed,
    )
    return DataSnapshot.objects.create(dataset_version=dataset, name="Initial snapshot")


def create_maltepe_bng(snapshot: DataSnapshot, code: str = "BNG-MAL-001") -> NetworkDevice:
    city = City.objects.create(name=f"İstanbul {snapshot.id}", plate_code="34")
    district = District.objects.create(
        city=city,
        name="Maltepe",
        profile_type=AreaProfileType.MIXED,
    )
    return NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code=code,
        name="Maltepe BNG 001",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )


def create_network_device(
    snapshot: DataSnapshot,
    *,
    code: str,
    device_type: str,
    city: City,
    district: District,
    access_role: str | None = None,
) -> NetworkDevice:
    return NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code=code,
        name=code,
        device_type=device_type,
        access_role=access_role,
        city=city,
        district=district,
    )


def create_alarm_type(snapshot: DataSnapshot, code: str = "BNG_DOWN") -> AlarmType:
    return AlarmType.objects.create(
        data_snapshot=snapshot,
        code=code,
        name="BNG down",
        severity=Severity.CRITICAL,
        category=AlarmCategory.CORE,
    )


def create_access_line(snapshot: DataSnapshot, *, code_suffix: str = "001"):
    bng = create_maltepe_bng(snapshot, code=f"BNG-MAL-{code_suffix}")
    access_node = create_network_device(
        snapshot,
        code=f"AN-MAL-{code_suffix}",
        device_type=NetworkDeviceType.ACCESS_NODE,
        access_role=NetworkDeviceAccessRole.STANDARD_ACCESS,
        city=bng.city,
        district=bng.district,
    )
    network_link = NetworkLink.objects.create(
        data_snapshot=snapshot,
        link_code=f"LNK-MAL-{code_suffix}",
        source_device=bng,
        target_device=access_node,
    )
    port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=access_node,
        port_code=f"PORT-{code_suffix}",
        capacity_mbps=1000,
    )
    segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code=f"SEG-MAL-{code_suffix}",
        name=f"Segment {code_suffix}",
        technology=AccessTechnology.FIBER,
        serving_device=access_node,
        city=bng.city,
        district=bng.district,
    )
    line = LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code=f"LINE-MAL-{code_suffix}",
        port=port,
        access_segment=segment,
        technology=AccessTechnology.FIBER,
        valid_from=timezone.now() - timedelta(days=1),
    )
    return bng, access_node, network_link, port, line


def create_subscription_connection(snapshot: DataSnapshot, line: LineConnection):
    customer = Customer.objects.create(
        data_snapshot=snapshot,
        customer_number=f"CUST-{line.line_code}",
        display_name="Synthetic customer",
        city=line.port.device.city,
        district=line.port.device.district,
    )
    package = ServicePackage.objects.create(
        data_snapshot=snapshot,
        package_code=f"PKG-{line.line_code}",
        name="Fiber test",
        technology=AccessTechnology.FIBER,
        service_type=ServiceType.BROADBAND,
        download_mbps=100,
        upload_mbps=20,
        monthly_price=Decimal("399.90"),
        commitment_months=12,
    )
    subscription = Subscription.objects.create(
        data_snapshot=snapshot,
        subscription_number=f"SUB-{line.line_code}",
        customer=customer,
        service_package=package,
        valid_from=line.valid_from,
        monthly_price=package.monthly_price,
    )
    return SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        line_connection=line,
        valid_from=line.valid_from,
    )


@pytest.mark.django_db
def test_bng_alarm_incident_and_outage_chain_has_deterministic_duration():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    alarm_type = create_alarm_type(snapshot)
    started_at = timezone.now() - timedelta(hours=3)
    ended_at = started_at + timedelta(minutes=180)

    alarm = Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id="ALM-MAL-001",
        alarm_type=alarm_type,
        device=bng,
        severity=Severity.CRITICAL,
        status=AlarmStatus.CLEARED,
        detected_at=started_at,
        cleared_at=ended_at,
    )
    incident = Incident.objects.create(
        data_snapshot=snapshot,
        incident_number="INC-MAL-001",
        title="Maltepe BNG outage",
        status=IncidentStatus.RESOLVED,
        severity=Severity.CRITICAL,
        primary_device=bng,
        root_cause_category=RootCauseCategory.BNG_FAILURE,
        root_cause_summary="BNG process failure",
        detected_at=started_at + timedelta(minutes=2),
        started_at=started_at,
        resolved_at=ended_at,
    )
    relation = IncidentAlarm.objects.create(
        data_snapshot=snapshot,
        incident=incident,
        alarm=alarm,
        role=IncidentAlarmRole.PRIMARY,
    )
    outage = Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-001",
        incident=incident,
        source_device=bng,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.RESOLVED,
        root_cause_category=RootCauseCategory.BNG_FAILURE,
        root_cause_summary="BNG process failure",
        detected_at=started_at + timedelta(minutes=2),
        started_at=started_at,
        ended_at=ended_at,
        resolved_at=ended_at,
        impact_scope={"district": "Maltepe"},
    )

    assert str(alarm) == "ALM-MAL-001 - BNG-MAL-001"
    assert str(relation) == "INC-MAL-001 -> ALM-MAL-001"
    assert outage.duration_seconds == 10800
    assert incident.duration_seconds == 10800
    assert alarm.duration_seconds == 10800
    assert outage.impact_scope == {"district": "Maltepe"}


@pytest.mark.django_db
def test_alarm_rejects_cross_snapshot_device_or_type():
    first_snapshot = create_snapshot("first-seed")
    second_snapshot = create_snapshot("second-seed")
    first_bng = create_maltepe_bng(first_snapshot)
    second_alarm_type = create_alarm_type(second_snapshot)

    alarm = Alarm(
        data_snapshot=second_snapshot,
        alarm_id="ALM-MAL-001",
        alarm_type=second_alarm_type,
        device=first_bng,
        severity=Severity.CRITICAL,
        detected_at=timezone.now(),
    )

    with pytest.raises(ValidationError):
        alarm.full_clean()


@pytest.mark.django_db
def test_incident_alarm_rejects_cross_snapshot_relation():
    first_snapshot = create_snapshot("first-seed")
    second_snapshot = create_snapshot("second-seed")
    first_bng = create_maltepe_bng(first_snapshot)
    second_bng = create_maltepe_bng(second_snapshot)
    first_alarm_type = create_alarm_type(first_snapshot)
    alarm = Alarm.objects.create(
        data_snapshot=first_snapshot,
        alarm_id="ALM-MAL-001",
        alarm_type=first_alarm_type,
        device=first_bng,
        severity=Severity.CRITICAL,
        detected_at=timezone.now(),
    )
    incident = Incident.objects.create(
        data_snapshot=second_snapshot,
        incident_number="INC-MAL-001",
        title="Cross snapshot incident",
        severity=Severity.MAJOR,
        primary_device=second_bng,
        detected_at=timezone.now(),
        started_at=timezone.now(),
    )

    relation = IncidentAlarm(data_snapshot=second_snapshot, incident=incident, alarm=alarm)

    with pytest.raises(ValidationError):
        relation.full_clean()


@pytest.mark.django_db
def test_outage_rejects_invalid_time_range_and_cross_snapshot_incident():
    first_snapshot = create_snapshot("first-seed")
    second_snapshot = create_snapshot("second-seed")
    first_bng = create_maltepe_bng(first_snapshot)
    second_bng = create_maltepe_bng(second_snapshot)
    now = timezone.now()
    incident = Incident.objects.create(
        data_snapshot=first_snapshot,
        incident_number="INC-MAL-001",
        title="First snapshot incident",
        severity=Severity.MAJOR,
        primary_device=first_bng,
        detected_at=now,
        started_at=now,
    )
    outage = Outage(
        data_snapshot=second_snapshot,
        outage_code="OUT-MAL-001",
        incident=incident,
        source_device=second_bng,
        outage_type=OutageType.DEVICE,
        detected_at=now,
        started_at=now,
        ended_at=now - timedelta(minutes=1),
    )

    with pytest.raises(ValidationError):
        outage.full_clean()


@pytest.mark.django_db
def test_operational_event_and_quality_measurement_keep_device_context():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    occurred_at = timezone.now()

    event = OperationalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="EVT-MAL-001",
        event_type=OperationalEventType.MANUAL_INTERVENTION,
        occurred_at=occurred_at,
        device=bng,
        source="noc",
        summary="Engineer restarted BNG service",
    )
    measurement = QualityMeasurement.objects.create(
        data_snapshot=snapshot,
        device=bng,
        metric_type=QualityMetricType.LATENCY_MS,
        measured_at=occurred_at,
        value=Decimal("12.5000"),
        unit="ms",
    )

    assert str(event) == "EVT-MAL-001 - Manual intervention"
    assert measurement.value == Decimal("12.5000")


@pytest.mark.django_db
def test_unique_operational_identifiers_are_snapshot_scoped():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    alarm_type = create_alarm_type(snapshot)
    detected_at = timezone.now()
    Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id="ALM-MAL-001",
        alarm_type=alarm_type,
        device=bng,
        severity=Severity.CRITICAL,
        detected_at=detected_at,
    )

    with pytest.raises((IntegrityError, ValidationError)):
        with transaction.atomic():
            Alarm.objects.create(
                data_snapshot=snapshot,
                alarm_id="ALM-MAL-001",
                alarm_type=alarm_type,
                device=bng,
                severity=Severity.CRITICAL,
                detected_at=detected_at + timedelta(minutes=1),
            )


@pytest.mark.django_db
def test_quality_measurement_rejects_negative_values():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    measurement = QualityMeasurement(
        data_snapshot=snapshot,
        device=bng,
        metric_type=QualityMetricType.PACKET_LOSS_PERCENT,
        measured_at=timezone.now(),
        value=Decimal("-1.0000"),
        unit="percent",
    )

    with pytest.raises(ValidationError):
        measurement.full_clean()


@pytest.mark.django_db
def test_alarm_requires_exactly_one_structured_source():
    snapshot = create_snapshot()
    bng, _access_node, network_link, _port, _line = create_access_line(snapshot)
    alarm_type = create_alarm_type(snapshot)

    no_source = Alarm(
        data_snapshot=snapshot,
        alarm_id="ALM-NO-SOURCE",
        alarm_type=alarm_type,
        severity=Severity.CRITICAL,
        detected_at=timezone.now(),
    )
    multi_source = Alarm(
        data_snapshot=snapshot,
        alarm_id="ALM-MULTI-SOURCE",
        alarm_type=alarm_type,
        device=bng,
        network_link=network_link,
        severity=Severity.CRITICAL,
        detected_at=timezone.now(),
    )

    with pytest.raises(ValidationError):
        no_source.full_clean()
    with pytest.raises(ValidationError):
        multi_source.full_clean()


@pytest.mark.django_db
def test_alarm_type_rejects_unsupported_source_kind():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    alarm_type = create_alarm_type(snapshot)
    AlarmTypeAllowedSourceKind.objects.create(
        data_snapshot=snapshot,
        alarm_type=alarm_type,
        source_kind=AlarmSourceKind.NETWORK_LINK,
    )

    alarm = Alarm(
        data_snapshot=snapshot,
        alarm_id="ALM-UNSUPPORTED-SOURCE",
        alarm_type=alarm_type,
        device=bng,
        severity=Severity.CRITICAL,
        detected_at=timezone.now(),
    )

    with pytest.raises(ValidationError, match="does not support source kind"):
        alarm.full_clean()


@pytest.mark.django_db
def test_acknowledged_alarm_can_remain_open_and_cleared_alarm_requires_clear_time():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    alarm_type = create_alarm_type(snapshot)
    detected_at = timezone.now()
    open_alarm = Alarm(
        data_snapshot=snapshot,
        alarm_id="ALM-ACK-OPEN",
        alarm_type=alarm_type,
        device=bng,
        severity=Severity.CRITICAL,
        status=AlarmStatus.OPEN,
        detected_at=detected_at,
        acknowledged_at=detected_at + timedelta(minutes=2),
    )
    cleared_without_time = Alarm(
        data_snapshot=snapshot,
        alarm_id="ALM-CLEARED-NO-TIME",
        alarm_type=alarm_type,
        device=bng,
        severity=Severity.CRITICAL,
        status=AlarmStatus.CLEARED,
        detected_at=detected_at,
    )

    open_alarm.full_clean()
    with pytest.raises(ValidationError, match="cleared_at is required"):
        cleared_without_time.full_clean()


@pytest.mark.django_db
def test_duplicate_open_alarm_updates_existing_occurrence_count():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    alarm_type = create_alarm_type(snapshot)
    detected_at = timezone.now()
    Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id="ALM-DEDUP-001",
        alarm_type=alarm_type,
        device=bng,
        severity=Severity.CRITICAL,
        status=AlarmStatus.OPEN,
        detected_at=detected_at,
        deduplication_key="BNG_DOWN:BNG-MAL-001",
    )

    duplicate = Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id="ALM-DEDUP-002",
        alarm_type=alarm_type,
        device=bng,
        severity=Severity.CRITICAL,
        status=AlarmStatus.OPEN,
        detected_at=detected_at + timedelta(minutes=1),
        deduplication_key="BNG_DOWN:BNG-MAL-001",
    )

    existing = Alarm.objects.get(data_snapshot=snapshot, alarm_id="ALM-DEDUP-001")
    assert duplicate.pk == existing.pk
    assert (
        Alarm.objects.filter(
            data_snapshot=snapshot, deduplication_key="BNG_DOWN:BNG-MAL-001"
        ).count()
        == 1
    )
    assert existing.occurrence_count == 2
    assert existing.last_seen_at == detected_at + timedelta(minutes=1)


@pytest.mark.django_db
def test_suppressed_alarm_and_flapping_recurrence_group_do_not_create_incident():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    alarm_type = create_alarm_type(snapshot, code="LINK_FLAPPING")

    for index in range(2):
        Alarm.objects.create(
            data_snapshot=snapshot,
            alarm_id=f"ALM-FLAP-{index}",
            alarm_type=alarm_type,
            device=bng,
            severity=Severity.MAJOR,
            status=AlarmStatus.SUPPRESSED if index == 0 else AlarmStatus.OPEN,
            detected_at=timezone.now() + timedelta(minutes=index),
            recurrence_group_key="REC-FLAP-BNG-001",
            suppression_reason="child/noise alarm",
        )

    assert Incident.objects.filter(data_snapshot=snapshot).count() == 0
    assert (
        Alarm.objects.filter(
            data_snapshot=snapshot,
            recurrence_group_key="REC-FLAP-BNG-001",
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_degradation_and_protection_loss_incidents_do_not_require_outage():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    detected_at = timezone.now()
    Incident.objects.create(
        data_snapshot=snapshot,
        incident_number="INC-DEG-001",
        title="Degradation only",
        severity=Severity.MAJOR,
        incident_type=IncidentType.SERVICE_DEGRADATION,
        service_impact_class=ServiceImpactClass.DEGRADATION,
        primary_device=bng,
        detected_at=detected_at,
        started_at=detected_at,
    )
    Incident.objects.create(
        data_snapshot=snapshot,
        incident_number="INC-PROT-001",
        title="Protection loss only",
        severity=Severity.MINOR,
        incident_type=IncidentType.PROTECTION_EVENT,
        service_impact_class=ServiceImpactClass.PROTECTION_LOSS,
        failover_result=FailoverResult.HITLESS,
        primary_device=bng,
        detected_at=detected_at,
        started_at=detected_at,
    )

    assert Outage.objects.filter(data_snapshot=snapshot).count() == 0


@pytest.mark.django_db
def test_outage_rejects_degradation_but_allows_short_interruption():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    started_at = timezone.now()
    short_outage = Outage(
        data_snapshot=snapshot,
        outage_code="OUT-SHORT-001",
        source_device=bng,
        outage_type=OutageType.LINK,
        impact_type=ServiceImpactClass.SHORT_INTERRUPTION,
        status=OutageStatus.RESOLVED,
        detected_at=started_at,
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=30),
    )
    degradation_outage = Outage(
        data_snapshot=snapshot,
        outage_code="OUT-DEG-001",
        source_device=bng,
        outage_type=OutageType.LINK,
        impact_type=ServiceImpactClass.DEGRADATION,
        detected_at=started_at,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=10),
    )

    short_outage.full_clean()
    with pytest.raises(ValidationError, match="Outage records are only allowed"):
        degradation_outage.full_clean()


@pytest.mark.django_db
def test_maintenance_window_normal_and_overrun_linked_incident():
    snapshot = create_snapshot()
    bng = create_maltepe_bng(snapshot)
    planned_start = timezone.now()
    normal = MaintenanceWindow.objects.create(
        data_snapshot=snapshot,
        reference_code="MW-MAL-001",
        status=MaintenanceWindowStatus.COMPLETED,
        planned_start_at=planned_start,
        planned_end_at=planned_start + timedelta(hours=1),
        actual_start_at=planned_start,
        actual_end_at=planned_start + timedelta(minutes=55),
        expected_impact_class=ServiceImpactClass.SHORT_INTERRUPTION,
        actual_impact_class=ServiceImpactClass.SHORT_INTERRUPTION,
    )
    incident = Incident.objects.create(
        data_snapshot=snapshot,
        incident_number="INC-MW-OVERRUN-001",
        title="Maintenance overrun impact",
        severity=Severity.MAJOR,
        incident_type=IncidentType.NETWORK_OUTAGE,
        service_impact_class=ServiceImpactClass.PARTIAL_OUTAGE,
        primary_device=bng,
        detected_at=planned_start + timedelta(hours=1, minutes=5),
        started_at=planned_start + timedelta(hours=1, minutes=5),
    )
    overrun = MaintenanceWindow.objects.create(
        data_snapshot=snapshot,
        reference_code="MW-MAL-002",
        status=MaintenanceWindowStatus.OVERRUN,
        planned_start_at=planned_start,
        planned_end_at=planned_start + timedelta(hours=1),
        actual_start_at=planned_start,
        actual_end_at=planned_start + timedelta(hours=2),
        expected_impact_class=ServiceImpactClass.SHORT_INTERRUPTION,
        actual_impact_class=ServiceImpactClass.PARTIAL_OUTAGE,
        overrun_minutes=60,
        linked_incident=incident,
    )

    assert str(normal) == "MW-MAL-001 - completed"
    assert overrun.linked_incident == incident


@pytest.mark.django_db
def test_quality_measurement_supports_link_line_and_subscription_sources():
    snapshot = create_snapshot()
    _bng, _access_node, network_link, _port, line = create_access_line(snapshot)
    subscription_connection = create_subscription_connection(snapshot, line)
    measured_at = timezone.now()

    link_measurement = QualityMeasurement.objects.create(
        data_snapshot=snapshot,
        network_link=network_link,
        metric_type=QualityMetricType.PACKET_LOSS_PERCENT,
        measured_at=measured_at,
        value=Decimal("0.5000"),
        unit="percent",
    )
    line_measurement = QualityMeasurement.objects.create(
        data_snapshot=snapshot,
        line_connection=line,
        metric_type=QualityMetricType.JITTER_MS,
        measured_at=measured_at,
        value=Decimal("4.0000"),
        unit="ms",
    )
    subscription_measurement = QualityMeasurement.objects.create(
        data_snapshot=snapshot,
        subscription_connection=subscription_connection,
        metric_type=QualityMetricType.BANDWIDTH_UTILIZATION_PERCENT,
        measured_at=measured_at,
        value=Decimal("65.0000"),
        unit="percent",
    )
    invalid_measurement = QualityMeasurement(
        data_snapshot=snapshot,
        network_link=network_link,
        line_connection=line,
        metric_type=QualityMetricType.LATENCY_MS,
        measured_at=measured_at,
        value=Decimal("12.0000"),
        unit="ms",
    )

    assert link_measurement.get_source_kind() == AlarmSourceKind.NETWORK_LINK
    assert line_measurement.get_source_kind() == AlarmSourceKind.LINE_CONNECTION
    assert subscription_measurement.get_source_kind() == AlarmSourceKind.SUBSCRIPTION_CONNECTION
    with pytest.raises(ValidationError):
        invalid_measurement.full_clean()


@pytest.mark.django_db
def test_maintenance_scope_rejects_cross_snapshot_device():
    first_snapshot = create_snapshot("first-maintenance")
    second_snapshot = create_snapshot("second-maintenance")
    first_bng = create_maltepe_bng(first_snapshot)
    maintenance = MaintenanceWindow.objects.create(
        data_snapshot=second_snapshot,
        reference_code="MW-CROSS-001",
        planned_start_at=timezone.now(),
        planned_end_at=timezone.now() + timedelta(hours=1),
    )

    scope = maintenance.device_scopes.model(
        data_snapshot=second_snapshot,
        maintenance_window=maintenance,
        device=first_bng,
    )

    with pytest.raises(ValidationError):
        scope.full_clean()
