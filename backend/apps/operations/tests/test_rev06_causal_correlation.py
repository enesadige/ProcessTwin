from datetime import timedelta

import pytest
from django.utils import timezone

from apps.operations.contracts import CausalEventStatus, CausalEventType, EventOrigin
from apps.operations.models import (
    Alarm,
    AlarmStatus,
    CausalEvent,
    Outage,
    OutageStatus,
    OutageType,
    Severity,
)
from apps.operations.services.alarm_correlation import AlarmCorrelationService
from apps.operations.services.root_cause import RootCauseService
from apps.operations.tests.test_operations_models import (
    create_access_line,
    create_alarm_type,
    create_snapshot,
)


def create_event(snapshot, *, code, started_at, root_device=None, root_network_link=None):
    return CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code=code,
        event_type=CausalEventType.LINK_FAILURE,
        status=CausalEventStatus.ACTIVE,
        started_at=started_at,
        source_system="synthetic",
        origin=EventOrigin.SYNTHETIC,
        root_device=root_device,
        root_network_link=root_network_link,
    )


def causal_snapshot():
    snapshot = create_snapshot()
    snapshot.dataset_version.config = {
        **snapshot.dataset_version.config,
        "reference_datetime": timezone.now().isoformat(),
    }
    snapshot.dataset_version.save(update_fields=["config"])
    return snapshot


def create_alarm(
    snapshot, event, alarm_type, alarm_id, detected_at, *, device, metadata=None, cleared_at=None
):
    return Alarm.objects.create(
        data_snapshot=snapshot,
        causal_event=event,
        alarm_id=alarm_id,
        alarm_type=alarm_type,
        device=device,
        severity=Severity.MAJOR,
        status=AlarmStatus.CLEARED if cleared_at else AlarmStatus.OPEN,
        detected_at=detected_at,
        cleared_at=cleared_at,
        metadata=metadata or {},
    )


@pytest.mark.django_db
def test_causal_chain_keeps_delayed_child_and_symptom_roles_deterministic():
    snapshot = causal_snapshot()
    root, child, _, _, _ = create_access_line(snapshot)
    started_at = timezone.now() - timedelta(hours=1)
    event = create_event(snapshot, code="CE-REV06-001", started_at=started_at, root_device=root)
    root_type = create_alarm_type(snapshot, "UPLINK_ROOT")
    symptom_type = create_alarm_type(snapshot, "ACCESS_SYMPTOM")
    anchor = create_alarm(snapshot, event, root_type, "ALM-ROOT", started_at, device=root)
    child_alarm = create_alarm(
        snapshot, event, symptom_type, "ALM-SYMPTOM", started_at + timedelta(minutes=45),
        device=child, metadata={"normalization": {"role_candidate": "symptom"}},
    )

    result = AlarmCorrelationService().score_pair(
        anchor_alarm=anchor, candidate_alarm=child_alarm, snapshot=snapshot
    )

    assert result.correlated is True
    assert result.correlation_role == "symptom"
    assert "temporal_propagation" in result.reason_codes
    assert result.description == "Candidate is a downstream access symptom, not a root assertion."


@pytest.mark.django_db
def test_different_causal_events_and_cross_technology_do_not_merge():
    snapshot = causal_snapshot()
    root, child, _, _, _ = create_access_line(snapshot)
    started_at = timezone.now() - timedelta(hours=1)
    first = create_event(snapshot, code="CE-REV06-002A", started_at=started_at, root_device=root)
    second = create_event(snapshot, code="CE-REV06-002B", started_at=started_at, root_device=child)
    alarm_type = create_alarm_type(snapshot, "LINK_DOWN")
    anchor = create_alarm(snapshot, first, alarm_type, "ALM-FIRST", started_at, device=root)
    candidate = create_alarm(snapshot, second, alarm_type, "ALM-SECOND", started_at, device=child)

    result = AlarmCorrelationService().score_pair(
        anchor_alarm=anchor, candidate_alarm=candidate, snapshot=snapshot
    )

    assert result.correlated is False
    assert result.correlation_role == "unrelated"
    assert result.evidence[0] == {
        "criterion": "causal_event_boundary",
        "matched": False,
        "score": 0,
    }


@pytest.mark.django_db
def test_temperature_is_supporting_not_root_and_clear_conflict_weakens_chain():
    snapshot = causal_snapshot()
    root, child, _, _, _ = create_access_line(snapshot)
    started_at = timezone.now() - timedelta(hours=1)
    event = create_event(snapshot, code="CE-REV06-003", started_at=started_at, root_device=root)
    root_type = create_alarm_type(snapshot, "LINK_DOWN")
    temp_type = create_alarm_type(snapshot, "TEMPERATURE_SIGNAL")
    anchor = create_alarm(
        snapshot, event, root_type, "ALM-LINK", started_at, device=root,
        cleared_at=started_at + timedelta(minutes=50),
    )
    temperature = create_alarm(
        snapshot, event, temp_type, "ALM-TEMP", started_at + timedelta(minutes=5), device=child,
        metadata={"normalization": {"role_candidate": "supporting"}},
        cleared_at=started_at + timedelta(minutes=10),
    )

    result = AlarmCorrelationService().score_pair(
        anchor_alarm=anchor, candidate_alarm=temperature, snapshot=snapshot
    )

    assert result.correlation_role == "supporting"
    assert result.evidence[-1]["consistent"] is False
    assert result.evidence[-1]["score"] < 0


@pytest.mark.django_db
def test_root_cause_prefers_structured_causal_root_over_symptom_fanout():
    snapshot = causal_snapshot()
    root, child, link, _, _ = create_access_line(snapshot)
    started_at = timezone.now() - timedelta(hours=1)
    event = create_event(
        snapshot, code="CE-REV06-004", started_at=started_at, root_network_link=link
    )
    root_type = create_alarm_type(snapshot, "LINK_DOWN")
    symptom_type = create_alarm_type(snapshot, "ACCESS_SYMPTOM")
    create_alarm(snapshot, event, root_type, "ALM-UPLINK", started_at, device=root)
    for index in range(3):
        create_alarm(
            snapshot, event, symptom_type, f"ALM-SYM-{index}",
            started_at + timedelta(minutes=20 + index), device=child,
            metadata={"normalization": {"role_candidate": "symptom"}},
        )
    outage = Outage.objects.create(
        data_snapshot=snapshot,
        causal_event=event,
        outage_code="OUT-REV06-004",
        source_device=child,
        outage_type=OutageType.LINK,
        status=OutageStatus.OPEN,
        detected_at=started_at,
        started_at=started_at,
        ended_at=started_at + timedelta(hours=1),
    )

    results = RootCauseService().analyze(outage=outage, snapshot=snapshot)

    assert results[0].candidate_device_code == root.code
    assert results[0].correlation_role == "root"
    assert results[0].candidate_resource_code == link.link_code
    assert all(result.correlation_role != "root" for result in results[1:])
