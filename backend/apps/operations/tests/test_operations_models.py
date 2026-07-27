from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.geography.models import AreaProfileType, City, District
from apps.network.models import NetworkDevice, NetworkDeviceType
from apps.operations.models import (
    Alarm,
    AlarmCategory,
    AlarmStatus,
    AlarmType,
    Incident,
    IncidentAlarm,
    IncidentAlarmRole,
    IncidentStatus,
    OperationalEvent,
    OperationalEventType,
    Outage,
    OutageStatus,
    OutageType,
    QualityMeasurement,
    QualityMetricType,
    RootCauseCategory,
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


def create_alarm_type(snapshot: DataSnapshot, code: str = "BNG_DOWN") -> AlarmType:
    return AlarmType.objects.create(
        data_snapshot=snapshot,
        code=code,
        name="BNG down",
        severity=Severity.CRITICAL,
        category=AlarmCategory.CORE,
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

    with pytest.raises(IntegrityError):
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
