from datetime import timedelta

import pytest
from django.utils import timezone

from apps.geography.models import City, District
from apps.network.models import NetworkDevice, NetworkDeviceType
from apps.operations.contracts import CausalEventStatus, CausalEventType, EventOrigin
from apps.operations.models import Alarm, AlarmStatus, CausalEvent, Severity
from apps.operations.services.alarm_correlation import (
    AlarmCorrelationService,
    CrossIncidentCorrelationStatus,
)
from apps.operations.tests.test_operations_models import (
    create_access_line,
    create_alarm_type,
    create_snapshot,
)


def correlation_snapshot():
    snapshot = create_snapshot()
    snapshot.dataset_version.config = {
        **snapshot.dataset_version.config,
        "reference_datetime": timezone.now().isoformat(),
    }
    snapshot.dataset_version.save(update_fields=["config"])
    return snapshot


def create_unrelated_device(snapshot, source, suffix):
    return NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code=f"UNRELATED-{suffix}",
        name=f"Unrelated {suffix}",
        device_type=NetworkDeviceType.OLT,
        city=source.city,
        district=source.district,
    )


def create_event(snapshot, *, code, started_at, root_device, metadata=None):
    return CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code=code,
        event_type=CausalEventType.LINK_FAILURE,
        status=CausalEventStatus.ACTIVE,
        started_at=started_at,
        source_system="synthetic",
        origin=EventOrigin.SYNTHETIC,
        root_device=root_device,
        metadata=metadata or {},
    )


def create_event_alarm(snapshot, event, alarm_type, alarm_id, detected_at, device):
    return Alarm.objects.create(
        data_snapshot=snapshot,
        causal_event=event,
        alarm_id=alarm_id,
        alarm_type=alarm_type,
        device=device,
        severity=Severity.MAJOR,
        status=AlarmStatus.OPEN,
        detected_at=detected_at,
    )


@pytest.mark.django_db
def test_cross_incident_time_and_topology_is_verified_without_claiming_physical_cause():
    snapshot = correlation_snapshot()
    root, child, _, _, _ = create_access_line(snapshot)
    started = timezone.now() - timedelta(hours=1)
    anchor = create_event(snapshot, code="CE-XCORR-001", started_at=started, root_device=root)
    candidate = create_event(
        snapshot, code="CE-XCORR-002", started_at=started + timedelta(minutes=37), root_device=child
    )
    alarm_type = create_alarm_type(snapshot, "CROSS_LINK_DOWN")
    create_event_alarm(snapshot, anchor, alarm_type, "ALM-XCORR-001", started, root)
    create_event_alarm(
        snapshot, candidate, alarm_type, "ALM-XCORR-002", candidate.started_at, child
    )

    result = AlarmCorrelationService().correlate_events(
        anchor_event=anchor, candidate_event=candidate, snapshot=snapshot, window_seconds=60 * 60
    )

    assert result.correlation_status == CrossIncidentCorrelationStatus.VERIFIED_RELATION
    assert result.topology_relation == "direct_parent_child"
    assert result.root_symptom_status == "not_verified"
    assert "physical" not in str(result.evidence).casefold()


@pytest.mark.django_db
def test_cross_incident_temporal_only_is_insufficient_evidence():
    snapshot = correlation_snapshot()
    root, _, _, _, _ = create_access_line(snapshot)
    unrelated = create_unrelated_device(snapshot, root, "002")
    started = timezone.now() - timedelta(hours=1)
    anchor = create_event(snapshot, code="CE-XCORR-003", started_at=started, root_device=root)
    candidate = create_event(
        snapshot,
        code="CE-XCORR-004",
        started_at=started + timedelta(minutes=10),
        root_device=unrelated,
    )
    alarm_type = create_alarm_type(snapshot, "CROSS_TEMP_ONLY")
    create_event_alarm(snapshot, anchor, alarm_type, "ALM-XCORR-003", started, root)
    create_event_alarm(
        snapshot, candidate, alarm_type, "ALM-XCORR-004", candidate.started_at, unrelated
    )

    result = AlarmCorrelationService().correlate_events(
        anchor_event=anchor, candidate_event=candidate, snapshot=snapshot, window_seconds=60 * 60
    )

    assert result.correlation_status == CrossIncidentCorrelationStatus.INSUFFICIENT_EVIDENCE
    assert result.topology_relation == "unrelated"


@pytest.mark.django_db
def test_cross_incident_topology_outside_window_is_not_verified():
    snapshot = correlation_snapshot()
    root, child, _, _, _ = create_access_line(snapshot)
    started = timezone.now() - timedelta(hours=3)
    anchor = create_event(snapshot, code="CE-XCORR-005", started_at=started, root_device=root)
    candidate = create_event(
        snapshot, code="CE-XCORR-006", started_at=started + timedelta(hours=3), root_device=child
    )
    alarm_type = create_alarm_type(snapshot, "CROSS_OUTSIDE_WINDOW")
    create_event_alarm(snapshot, anchor, alarm_type, "ALM-XCORR-005", started, root)
    create_event_alarm(
        snapshot, candidate, alarm_type, "ALM-XCORR-006", candidate.started_at, child
    )

    result = AlarmCorrelationService().correlate_events(
        anchor_event=anchor, candidate_event=candidate, snapshot=snapshot, window_seconds=60 * 60
    )

    assert result.correlation_status == CrossIncidentCorrelationStatus.INSUFFICIENT_EVIDENCE
    assert result.within_window is False


@pytest.mark.django_db
def test_cross_incident_unrelated_time_and_topology_is_no_relation():
    snapshot = correlation_snapshot()
    root, _, _, _, _ = create_access_line(snapshot)
    unrelated = create_unrelated_device(snapshot, root, "003")
    started = timezone.now() - timedelta(hours=5)
    anchor = create_event(snapshot, code="CE-XCORR-007", started_at=started, root_device=root)
    candidate = create_event(
        snapshot,
        code="CE-XCORR-008",
        started_at=started + timedelta(hours=3),
        root_device=unrelated,
    )
    alarm_type = create_alarm_type(snapshot, "CROSS_UNRELATED")
    create_event_alarm(snapshot, anchor, alarm_type, "ALM-XCORR-007", started, root)
    create_event_alarm(
        snapshot, candidate, alarm_type, "ALM-XCORR-008", candidate.started_at, unrelated
    )

    result = AlarmCorrelationService().correlate_events(
        anchor_event=anchor, candidate_event=candidate, snapshot=snapshot, window_seconds=60 * 60
    )

    assert result.correlation_status == CrossIncidentCorrelationStatus.NO_RELATION


@pytest.mark.django_db
def test_cross_incident_root_symptom_requires_explicit_event_relation():
    snapshot = correlation_snapshot()
    root, child, _, _, _ = create_access_line(snapshot)
    started = timezone.now() - timedelta(hours=1)
    candidate = create_event(
        snapshot, code="CE-XCORR-010", started_at=started + timedelta(minutes=10), root_device=child
    )
    anchor = create_event(
        snapshot,
        code="CE-XCORR-009",
        started_at=started,
        root_device=root,
        metadata={
            "cross_incident_relations": [
                {
                    "event_code": candidate.event_code,
                    "relation_type": "root_symptom",
                    "root_symptom_direction": "anchor_root",
                }
            ]
        },
    )
    alarm_type = create_alarm_type(snapshot, "CROSS_ROOT_SYMPTOM")
    create_event_alarm(snapshot, anchor, alarm_type, "ALM-XCORR-009", started, root)
    create_event_alarm(
        snapshot, candidate, alarm_type, "ALM-XCORR-010", candidate.started_at, child
    )

    result = AlarmCorrelationService().correlate_events(
        anchor_event=anchor, candidate_event=candidate, snapshot=snapshot, window_seconds=60 * 60
    )

    assert result.correlation_status == CrossIncidentCorrelationStatus.VERIFIED_RELATION
    assert result.root_symptom_status == "anchor_root"


@pytest.mark.django_db
def test_cross_incident_timestamp_order_does_not_infer_root_symptom_direction():
    snapshot = correlation_snapshot()
    root, child, _, _, _ = create_access_line(snapshot)
    started = timezone.now() - timedelta(hours=1)
    anchor = create_event(snapshot, code="CE-XCORR-011", started_at=started, root_device=root)
    candidate = create_event(
        snapshot, code="CE-XCORR-012", started_at=started + timedelta(minutes=5), root_device=child
    )
    alarm_type = create_alarm_type(snapshot, "CROSS_DIRECTION_UNVERIFIED")
    create_event_alarm(snapshot, anchor, alarm_type, "ALM-XCORR-011", started, root)
    create_event_alarm(
        snapshot, candidate, alarm_type, "ALM-XCORR-012", candidate.started_at, child
    )

    result = AlarmCorrelationService().correlate_events(
        anchor_event=anchor, candidate_event=candidate, snapshot=snapshot, window_seconds=60 * 60
    )

    assert result.correlation_status == CrossIncidentCorrelationStatus.VERIFIED_RELATION
    assert result.root_symptom_status == "not_verified"


@pytest.mark.django_db
def test_cross_region_topology_relation_is_not_blocked_by_city_boundary():
    snapshot = correlation_snapshot()
    root, child, _, _, _ = create_access_line(snapshot)
    other_city = City.objects.create(name="Other Correlation City", plate_code="77")
    other_district = District.objects.create(city=other_city, name="Other Correlation District")
    child.city = other_city
    child.district = other_district
    child.save(update_fields=["city", "district"])
    started = timezone.now() - timedelta(hours=1)
    anchor = create_event(snapshot, code="CE-XCORR-013", started_at=started, root_device=root)
    candidate = create_event(
        snapshot, code="CE-XCORR-014", started_at=started + timedelta(minutes=20), root_device=child
    )
    alarm_type = create_alarm_type(snapshot, "CROSS_REGION_LINK")
    create_event_alarm(snapshot, anchor, alarm_type, "ALM-XCORR-013", started, root)
    create_event_alarm(
        snapshot, candidate, alarm_type, "ALM-XCORR-014", candidate.started_at, child
    )

    result = AlarmCorrelationService().correlate_events(
        anchor_event=anchor, candidate_event=candidate, snapshot=snapshot, window_seconds=60 * 60
    )

    assert result.correlation_status == CrossIncidentCorrelationStatus.VERIFIED_RELATION
