from datetime import datetime, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.network.models import NetworkDevice
from apps.operations.models import (
    Alarm,
    AlarmStatus,
    AlarmType,
    Outage,
    OutageStatus,
    OutageType,
    Severity,
)
from apps.operations.services.root_cause import RootCauseInputError, RootCauseService


@pytest.mark.django_db
def test_root_cause_service_confirms_main_bng_source_without_incident_or_ground_truth_fields():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    outage.root_cause_category = "unknown"
    outage.root_cause_summary = ""
    outage.incident.root_cause_category = "unknown"
    outage.incident.root_cause_summary = ""

    results = RootCauseService().analyze(outage=outage, snapshot=snapshot)

    assert results[0].outage_code == "OUT-MAL-BNG-001"
    assert results[0].candidate_device_code == "BNG-MAL-001"
    assert results[0].candidate_device_type == "bng"
    assert results[0].evidence_score == 100
    assert results[0].classification == "confirmed"
    assert results[0].supporting_alarm_codes == [
        "ALM-OUT-MAL-BNG-001-LINK",
        "ALM-OUT-MAL-BNG-001-PRIMARY",
    ]
    assert results[0].missing_evidence == []
    assert results[0].snapshot["id"] == snapshot.id
    assert results[0].evaluation_window == {
        "started_at": outage.started_at.isoformat(),
        "ended_at": outage.ended_at.isoformat(),
    }
    assert {item["criterion"] for item in results[0].evidence} == {
        "outage_source_device_match",
        "strong_alarm_support",
        "alarm_time_proximity",
        "topology_alignment",
    }


@pytest.mark.django_db
def test_root_cause_service_does_not_mix_other_bng_branch_candidate():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-RCA-OTHER-BNG",
        alarm_type_code="BNG_UNREACHABLE",
        device_code="BNG-MAL-002",
        detected_at=outage.started_at,
    )

    results = RootCauseService().analyze(outage=outage, snapshot=snapshot)

    assert "BNG-MAL-002" not in [result.candidate_device_code for result in results]


@pytest.mark.django_db
def test_root_cause_service_reports_unknown_when_source_has_no_supporting_alarm():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    Alarm.objects.filter(data_snapshot=snapshot, device=outage.source_device).delete()

    result = RootCauseService().analyze(outage=outage, snapshot=snapshot)[0]

    assert result.candidate_device_code == "BNG-MAL-001"
    assert result.evidence_score == 50
    assert result.classification == "unknown"
    assert result.supporting_alarm_codes == []
    assert result.missing_evidence == [
        "no_direct_alarm_on_outage_source_device",
        "no_strong_alarm_support",
        "no_near_start_alarm",
    ]


@pytest.mark.django_db
def test_root_cause_service_reports_unknown_for_only_distant_source_alarm():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    Alarm.objects.filter(data_snapshot=snapshot, device=outage.source_device).delete()
    create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-RCA-DISTANT-BNG",
        alarm_type_code="BNG_UNREACHABLE",
        device_code="BNG-MAL-001",
        detected_at=outage.started_at + timedelta(minutes=20),
    )

    result = RootCauseService().analyze(outage=outage, snapshot=snapshot)[0]

    assert result.candidate_device_code == "BNG-MAL-001"
    assert result.evidence_score == 75
    assert result.classification == "unknown"
    assert result.evidence[2]["score"] == 0
    assert result.evidence[2]["nearest_alarm_time_difference_seconds"] == 20 * 60
    assert result.missing_evidence == ["no_near_start_alarm"]


@pytest.mark.django_db
def test_root_cause_service_excludes_cross_snapshot_alarm():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    Alarm.objects.filter(data_snapshot=snapshot, device=outage.source_device).delete()
    other_alarm = create_other_snapshot_alarm(outage.started_at)

    results = RootCauseService().analyze(outage=outage, snapshot=snapshot)

    assert other_alarm.alarm_id not in [
        alarm_code
        for result in results
        for alarm_code in result.supporting_alarm_codes
    ]
    assert results[0].classification == "unknown"


@pytest.mark.django_db
def test_root_cause_service_can_rank_same_bng_branch_candidate_as_probable():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    Alarm.objects.filter(data_snapshot=snapshot, device=outage.source_device).delete()
    create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-RCA-BRANCH-ACCESS",
        alarm_type_code="ACCESS_DEVICE_UNREACHABLE",
        device_code="OLT-MAL-ALT-001",
        detected_at=outage.started_at + timedelta(minutes=2),
    )
    create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-RCA-BRANCH-LINK",
        alarm_type_code="LINK_DOWN",
        device_code="OLT-MAL-ALT-001",
        detected_at=outage.started_at + timedelta(minutes=2),
    )

    results = RootCauseService().analyze(outage=outage, snapshot=snapshot)

    assert [result.candidate_device_code for result in results[:2]] == [
        "OLT-MAL-ALT-001",
        "BNG-MAL-001",
    ]
    assert results[0].evidence_score == 55
    assert results[0].classification == "probable"


@pytest.mark.django_db
def test_root_cause_service_rejects_missing_source_device():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    outage.source_device_id = None

    with pytest.raises(RootCauseInputError, match="has no source device"):
        RootCauseService().analyze(outage=outage, snapshot=snapshot)


@pytest.mark.django_db
def test_root_cause_service_rejects_ongoing_outage_without_evaluation_time():
    snapshot = seed_snapshot()
    outage = create_ongoing_outage(snapshot)

    with pytest.raises(RootCauseInputError, match="evaluation_time is required"):
        RootCauseService().analyze(outage=outage, snapshot=snapshot)


@pytest.mark.django_db
def test_root_cause_service_rejects_naive_evaluation_time():
    snapshot = seed_snapshot()
    outage = create_ongoing_outage(snapshot)

    with pytest.raises(RootCauseInputError, match="timezone-aware"):
        RootCauseService().analyze(
            outage=outage,
            snapshot=snapshot,
            evaluation_time=datetime(2026, 7, 20, 11, 30),
        )


@pytest.mark.django_db
def test_root_cause_service_handles_ongoing_outage_with_explicit_evaluation_time():
    snapshot = seed_snapshot()
    outage = create_ongoing_outage(snapshot)
    create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-RCA-ONGOING-BNG",
        alarm_type_code="BNG_UNREACHABLE",
        device_code="BNG-MAL-001",
        detected_at=outage.started_at,
    )

    result = RootCauseService().analyze(
        outage=outage,
        snapshot=snapshot,
        evaluation_time=outage.started_at + timedelta(minutes=45),
    )[0]

    assert result.candidate_device_code == "BNG-MAL-001"
    assert result.classification == "confirmed"
    assert result.evaluation_window["ended_at"] == (
        outage.started_at + timedelta(minutes=45)
    ).isoformat()


def seed_snapshot() -> DataSnapshot:
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def get_outage(snapshot: DataSnapshot, outage_code: str) -> Outage:
    return Outage.objects.select_related("source_device", "incident", "data_snapshot").get(
        data_snapshot=snapshot,
        outage_code=outage_code,
    )


def create_alarm(
    *,
    snapshot: DataSnapshot,
    alarm_id: str,
    alarm_type_code: str,
    device_code: str,
    detected_at,
) -> Alarm:
    alarm_type = AlarmType.objects.get(data_snapshot=snapshot, code=alarm_type_code)
    device = NetworkDevice.objects.get(data_snapshot=snapshot, code=device_code)
    return Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id=alarm_id,
        alarm_type=alarm_type,
        device=device,
        severity=Severity.MAJOR,
        status=AlarmStatus.OPEN,
        detected_at=detected_at,
    )


def create_ongoing_outage(snapshot: DataSnapshot) -> Outage:
    source_device = NetworkDevice.objects.get(data_snapshot=snapshot, code="BNG-MAL-001")
    started_at = timezone.datetime(
        2026,
        7,
        20,
        10,
        15,
        tzinfo=timezone.get_current_timezone(),
    )
    return Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-RCA-ONGOING",
        source_device=source_device,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.OPEN,
        detected_at=started_at,
        started_at=started_at,
    )


def create_other_snapshot_alarm(detected_at) -> Alarm:
    dataset = DatasetVersion.objects.create(
        name="Other Root Cause Dataset",
        generator_version="other-v1",
        seed="other-seed",
    )
    snapshot = DataSnapshot.objects.create(dataset_version=dataset, name="Other Snapshot")
    source_alarm = Alarm.objects.select_related("alarm_type", "device").first()
    alarm_type = AlarmType.objects.create(
        data_snapshot=snapshot,
        code="BNG_UNREACHABLE",
        name="Other BNG unreachable",
        severity=Severity.CRITICAL,
        category=source_alarm.alarm_type.category,
    )
    device = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="BNG-OTHER-RCA-001",
        device_type=source_alarm.device.device_type,
        city=source_alarm.device.city,
        district=source_alarm.device.district,
    )
    return Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id="ALM-OTHER-RCA-001",
        alarm_type=alarm_type,
        device=device,
        severity=Severity.CRITICAL,
        detected_at=detected_at,
    )
