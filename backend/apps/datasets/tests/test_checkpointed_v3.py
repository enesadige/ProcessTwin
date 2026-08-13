from datetime import timedelta
from types import SimpleNamespace

import pytest
from data_generator.seeders import checkpointed_v3
from data_generator.seeders.causal_timeline import TimelineScheduleEntry
from django.utils import timezone

from apps.core.choices import ResultStatus
from apps.datasets.models import DatasetSnapshotStatus
from apps.operations.contracts import CausalEventStatus, CausalEventType, EventOrigin
from apps.operations.models import Alarm, AlarmStatus, CausalEvent, Severity
from apps.operations.tests.test_operations_models import (
    create_access_line,
    create_alarm_type,
    create_snapshot,
    create_subscription_connection,
)


class _FakeImpactService:
    def evaluate(self, **kwargs):
        return [], SimpleNamespace(
            potential_connection_count=0,
            verified_impacted_count=0,
            failover_protected_count=0,
            insufficient_evidence_count=0,
        )


class _FakeContext:
    def __init__(self):
        self.customer_impact_service = _FakeImpactService()
        self.batch_size = 100
        self.impact_evidence_cache = {}


@pytest.mark.django_db
def test_checkpointed_v3_resume_skips_committed_events_and_keeps_checkpoint(monkeypatch):
    source = create_snapshot("checkpoint-source")
    target = create_snapshot("checkpoint-target")
    entries = (
        TimelineScheduleEntry("İstanbul", 6, "SCN-ONE", 3, 2),
        TimelineScheduleEntry("İzmir", 6, "SCN-TWO", 5, 8),
    )
    context = _FakeContext()
    created_indexes = []

    monkeypatch.setattr(checkpointed_v3, "scheduled_timeline", lambda: entries)
    monkeypatch.setattr(checkpointed_v3, "clone_base_world", lambda **kwargs: None)
    monkeypatch.setattr(checkpointed_v3, "build_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(checkpointed_v3, "_persisted_validation_checks", lambda **kwargs: [])

    def create_event(*, entry, index, **kwargs):
        created_indexes.append(index)
        started_at = timezone.now()
        event = CausalEvent.objects.create(
            data_snapshot=target,
            event_code=f"CE-CHK-{index:04d}",
            event_type=CausalEventType.UNKNOWN,
            status=CausalEventStatus.RESOLVED,
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=1),
            source_system="test",
            origin=EventOrigin.SYNTHETIC,
            metadata={"v3_schedule_index": index},
        )
        context.impact_evidence_cache[event.id] = {
            "potential_connections": [],
            "selected_connections": [],
            "session_events": [],
        }
        return {"causal_event": event, "outage": None}

    monkeypatch.setattr(checkpointed_v3, "create_scheduled_scenario_instance", create_event)
    checkpointed_v3.resume_or_build(
        snapshot=target,
        source=source,
        batch_size=100,
        stdout=SimpleNamespace(write=lambda value: None),
    )
    first_state = checkpointed_v3.status(target)

    checkpointed_v3.resume_or_build(
        snapshot=target,
        source=source,
        batch_size=100,
        stdout=SimpleNamespace(write=lambda value: None),
    )

    assert created_indexes == [1, 2]
    assert CausalEvent.objects.filter(data_snapshot=target).count() == 2
    assert first_state["state"] == "completed"
    assert checkpointed_v3.status(target)["resume_point"] == 3


@pytest.mark.django_db
def test_checkpointed_v3_persists_stopped_state_and_resumes_from_last_commit(monkeypatch):
    source = create_snapshot("interrupted-source")
    target = create_snapshot("interrupted-target")
    entries = (
        TimelineScheduleEntry("İstanbul", 6, "SCN-ONE", 3, 2),
        TimelineScheduleEntry("İzmir", 6, "SCN-TWO", 5, 8),
    )
    context = _FakeContext()
    calls = []

    monkeypatch.setattr(checkpointed_v3, "scheduled_timeline", lambda: entries)
    monkeypatch.setattr(checkpointed_v3, "clone_base_world", lambda **kwargs: None)
    monkeypatch.setattr(checkpointed_v3, "clone_correlation_helpers", lambda **kwargs: 0)
    monkeypatch.setattr(checkpointed_v3, "build_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(checkpointed_v3, "_persisted_validation_checks", lambda **kwargs: [])

    def create_or_interrupt(**kwargs):
        index = kwargs["index"]
        calls.append(index)
        if index == 2:
            raise KeyboardInterrupt
        return _create_test_event(target=target, context=context, index=index)

    monkeypatch.setattr(
        checkpointed_v3,
        "create_scheduled_scenario_instance",
        create_or_interrupt,
    )
    checkpointed_v3.resume_or_build(
        snapshot=target,
        source=source,
        batch_size=100,
        stdout=SimpleNamespace(write=lambda value: None),
    )

    assert checkpointed_v3.status(target)["state"] == "stopped"
    assert checkpointed_v3.status(target)["resume_point"] == 2
    assert CausalEvent.objects.filter(data_snapshot=target).count() == 1

    monkeypatch.setattr(
        checkpointed_v3,
        "create_scheduled_scenario_instance",
        lambda **kwargs: _create_test_event(
            target=target,
            context=context,
            index=kwargs["index"],
        ),
    )
    checkpointed_v3.resume_or_build(
        snapshot=target,
        source=source,
        batch_size=100,
        stdout=SimpleNamespace(write=lambda value: None),
    )

    assert calls == [1, 2]
    assert CausalEvent.objects.filter(data_snapshot=target).count() == 2


@pytest.mark.django_db
def test_checkpointed_v3_final_validation_uses_only_persisted_rows(monkeypatch):
    snapshot = create_snapshot("persisted-validation")
    entry = TimelineScheduleEntry("İstanbul", 6, "SCN-ONE", 3, 2)
    started_at = timezone.now()

    monkeypatch.setattr(checkpointed_v3, "scheduled_timeline", lambda: (entry,))
    CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-V3-0001",
        event_type=CausalEventType.UNKNOWN,
        status=CausalEventStatus.RESOLVED,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=1),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        metadata={
            "scenario_code": entry.scenario_code,
            "scheduled_city": entry.city_name,
            "scheduled_month": entry.month,
            "v3_schedule_index": 1,
            "v3_schedule_fingerprint": checkpointed_v3._entry_fingerprint(entry),
        },
    )
    for helper_index, event_code in enumerate(
        checkpointed_v3._CORRELATION_HELPER_EVENT_CODES,
        start=1,
    ):
        CausalEvent.objects.create(
            data_snapshot=snapshot,
            event_code=event_code,
            event_type=CausalEventType.UNKNOWN,
            status=CausalEventStatus.RESOLVED,
            started_at=started_at + timedelta(minutes=helper_index),
            ended_at=started_at + timedelta(minutes=helper_index + 1),
            source_system="test",
            origin=EventOrigin.SYNTHETIC,
        )
    checkpointed_v3.initialize_run(snapshot=snapshot, source=snapshot)

    def unexpected_recalculation(*args, **kwargs):
        raise AssertionError("final validation must not resolve impact scope")

    monkeypatch.setattr(
        "apps.operations.services.customer_impact_assessment.CustomerImpactAssessmentService._get_potential_connections",
        unexpected_recalculation,
    )
    checkpointed_v3._finalize_persisted_snapshot(
        snapshot=snapshot,
        stdout=SimpleNamespace(write=lambda value: None),
    )
    snapshot.refresh_from_db()

    assert snapshot.status == DatasetSnapshotStatus.VALIDATED
    assert snapshot.validation_status == ResultStatus.EXACT


def _create_test_event(*, target, context, index):
    started_at = timezone.now()
    event = CausalEvent.objects.create(
        data_snapshot=target,
        event_code=f"CE-STOP-{index:04d}",
        event_type=CausalEventType.UNKNOWN,
        status=CausalEventStatus.RESOLVED,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=1),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        metadata={"v3_schedule_index": index},
    )
    context.impact_evidence_cache[event.id] = {
        "potential_connections": [],
        "selected_connections": [],
        "session_events": [],
    }
    return {"causal_event": event, "outage": None}


@pytest.mark.django_db
def test_checkpointed_v3_clones_base_world_with_external_ids_and_local_foreign_keys():
    source = create_snapshot("clone-source")
    target = create_snapshot("clone-target")
    root, _child, _link, _port, line = create_access_line(source)
    connection = create_subscription_connection(source, line)
    alarm_type = create_alarm_type(source)
    started_at = timezone.now()
    helper = CausalEvent.objects.create(
        data_snapshot=source,
        event_code="CE-XREG-0001",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=20),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=root,
    )
    Alarm.objects.create(
        data_snapshot=source,
        causal_event=helper,
        alarm_id="ALM-XREG-0001",
        alarm_type=alarm_type,
        device=root,
        severity=Severity.CRITICAL,
        status=AlarmStatus.CLEARED,
        detected_at=started_at,
        cleared_at=started_at + timedelta(minutes=20),
    )

    mappings = checkpointed_v3.clone_base_world(source=source, target=target, batch_size=100)
    helper_count = checkpointed_v3.clone_correlation_helpers(
        source=source,
        target=target,
        mappings=mappings,
        batch_size=100,
    )

    source_ids = {
        "devices": set(source.network_devices.values_list("code", flat=True)),
        "lines": set(source.line_connections.values_list("line_code", flat=True)),
        "subscriptions": set(source.subscriptions.values_list("subscription_number", flat=True)),
        "alarm_types": set(source.alarm_types.values_list("code", flat=True)),
    }
    target_ids = {
        "devices": set(target.network_devices.values_list("code", flat=True)),
        "lines": set(target.line_connections.values_list("line_code", flat=True)),
        "subscriptions": set(target.subscriptions.values_list("subscription_number", flat=True)),
        "alarm_types": set(target.alarm_types.values_list("code", flat=True)),
    }
    cloned_connection = target.subscription_connections.get(
        subscription__subscription_number=connection.subscription.subscription_number
    )

    assert target_ids == source_ids
    assert cloned_connection.subscription.data_snapshot_id == target.id
    assert cloned_connection.line_connection.data_snapshot_id == target.id
    assert helper_count == 1
    assert (
        target.causal_events.get(event_code="CE-XREG-0001").root_device.data_snapshot_id
        == target.id
    )
    assert target.alarms.get(alarm_id="ALM-XREG-0001").causal_event.event_code == "CE-XREG-0001"
