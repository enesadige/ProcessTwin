from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.compensation.models import CompensationEvaluation
from apps.operations.models import Alarm, CausalEvent, CustomerImpactAssessment, Outage
from apps.simulation.models import (
    SimulationComparisonRole,
    SimulationRun,
    SimulationRunStatus,
)
from apps.simulation.services import SimulationLifecycleError, SimulationService
from apps.simulation.tests.test_simulation_models import create_scenario, create_snapshot


def fixed_clock() -> datetime:
    return datetime(2026, 6, 1, 8, 0, tzinfo=UTC)


def create_baseline(service: SimulationService, *, snapshot=None, speed=1) -> SimulationRun:
    snapshot = snapshot or create_snapshot("runtime")
    scenario = create_scenario(snapshot)
    scenario.default_parameters = {
        "duration_minutes": 90,
        "routing": {"path": "primary", "retry": 1},
    }
    scenario.save()
    return service.create_run(
        scenario=scenario,
        comparison_role=SimulationComparisonRole.BASELINE,
        deterministic_seed="runtime-seed-001",
        virtual_clock=fixed_clock(),
        speed_multiplier=speed,
    )


@pytest.mark.django_db
def test_lifecycle_pause_resume_and_virtual_clock_are_explicit():
    service = SimulationService()
    run = create_baseline(service)

    run = service.start(run)
    assert run.status == SimulationRunStatus.RUNNING
    assert list(run.events.values_list("event_type", flat=True)) == ["runtime_started"]

    run = service.pause(run)
    paused_clock = run.virtual_clock
    with pytest.raises(SimulationLifecycleError, match="running simulations can advance"):
        service.advance(run, simulation_step=timedelta(minutes=1))
    run.refresh_from_db()
    assert run.virtual_clock == paused_clock

    run = service.resume(run)
    run = service.advance(run, simulation_step=timedelta(minutes=2))
    assert run.virtual_clock == fixed_clock() + timedelta(minutes=2)
    assert list(run.events.values_list("event_type", flat=True)) == [
        "runtime_started",
        "runtime_paused",
        "runtime_resumed",
        "runtime_tick",
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("speed", [1, 10, 60])
def test_virtual_clock_applies_only_supported_speed_multiplier(speed):
    service = SimulationService()
    run = service.start(create_baseline(service, speed=speed))

    run = service.advance(run, simulation_step=timedelta(minutes=3))

    assert run.virtual_clock == fixed_clock() + timedelta(minutes=3 * speed)
    tick = run.events.get(sequence=2)
    assert tick.event_context["base_step_microseconds"] == 180_000_000
    assert tick.event_context["speed_multiplier"] == speed


@pytest.mark.django_db
def test_replay_reproduces_same_runtime_schedule_without_wall_clock_dependency():
    service = SimulationService()
    original = service.start(create_baseline(service))
    original = service.advance(original, simulation_step=timedelta(minutes=4))
    original = service.pause(original)
    original = service.resume(original)
    original = service.advance(original, simulation_step=timedelta(minutes=2))
    original = service.stop(original)

    replay = service.start(service.replay(original))
    replay = service.advance(replay, simulation_step=timedelta(minutes=4))
    replay = service.pause(replay)
    replay = service.resume(replay)
    replay = service.advance(replay, simulation_step=timedelta(minutes=2))
    replay = service.stop(replay)

    fields = ("sequence", "event_code", "event_type", "virtual_occurred_at", "event_context")
    assert list(original.events.values_list(*fields)) == list(replay.events.values_list(*fields))
    assert replay.replay_of_id == original.id
    assert replay.replay_identity == original.replay_identity


@pytest.mark.django_db
def test_candidate_inputs_are_independent_and_do_not_mutate_baseline_or_defaults():
    service = SimulationService()
    baseline = create_baseline(service)
    candidate = service.create_candidate(
        baseline_run=baseline,
        input_overrides={"routing": {"retry": 3}, "duration_minutes": 120},
    )

    baseline_inputs = service.effective_inputs(baseline)
    candidate_inputs = service.effective_inputs(candidate)
    assert baseline_inputs == {"duration_minutes": 90, "routing": {"path": "primary", "retry": 1}}
    assert candidate_inputs == {"duration_minutes": 120, "routing": {"path": "primary", "retry": 3}}

    service.start(candidate)
    baseline.refresh_from_db()
    candidate.refresh_from_db()
    baseline.scenario.refresh_from_db()
    assert baseline.input_parameters == {}
    assert candidate.input_parameters == {"routing": {"retry": 3}, "duration_minutes": 120}
    assert baseline.scenario.default_parameters["routing"]["retry"] == 1
    assert candidate.lifecycle_context["effective_inputs"] == candidate_inputs


@pytest.mark.django_db
def test_reset_preserves_terminal_history_and_replay_creates_new_trace():
    service = SimulationService()
    mutable = service.start(create_baseline(service))
    mutable = service.advance(mutable, simulation_step=timedelta(minutes=1))
    reset = service.reset(mutable)
    assert reset.status == SimulationRunStatus.DRAFT
    assert reset.virtual_clock == fixed_clock()
    assert reset.events.count() == 0
    assert reset.lifecycle_context["reset_count"] == 1

    terminal = service.stop(
        service.start(create_baseline(service, snapshot=create_snapshot("terminal-history")))
    )
    before_events = list(terminal.events.values_list("sequence", "event_code"))
    with pytest.raises(SimulationLifecycleError, match="must be replayed"):
        service.reset(terminal)
    terminal.refresh_from_db()
    assert list(terminal.events.values_list("sequence", "event_code")) == before_events

    replay = service.replay(terminal)
    assert replay.pk != terminal.pk
    assert replay.replay_of_id == terminal.id
    assert replay.status == SimulationRunStatus.DRAFT
    assert replay.events.count() == 0


@pytest.mark.django_db
def test_candidate_replay_keeps_a_matching_replayed_baseline_context():
    service = SimulationService()
    baseline = create_baseline(service)
    candidate = service.create_candidate(
        baseline_run=baseline, input_overrides={"duration_minutes": 120}
    )
    baseline = service.advance(service.start(baseline), simulation_step=timedelta(minutes=1))
    candidate = service.advance(service.start(candidate), simulation_step=timedelta(minutes=1))

    candidate_replay = service.replay(candidate)

    assert candidate_replay.replay_of_id == candidate.id
    assert candidate_replay.baseline_run.replay_of_id == baseline.id
    assert candidate_replay.virtual_clock == candidate_replay.baseline_run.virtual_clock
    assert candidate_replay.input_parameters == candidate.input_parameters


@pytest.mark.django_db
def test_same_virtual_timestamp_uses_explicit_sequence_tie_breaking():
    service = SimulationService()
    run = service.start(create_baseline(service))
    run = service.pause(run)
    run = service.resume(run)

    events = list(run.events.order_by("sequence"))
    assert [event.sequence for event in events] == [1, 2, 3]
    assert [event.event_type for event in events] == [
        "runtime_started",
        "runtime_paused",
        "runtime_resumed",
    ]
    assert len({event.virtual_occurred_at for event in events}) == 1


@pytest.mark.django_db
def test_service_keeps_snapshot_boundaries_and_operational_tables_unchanged():
    service = SimulationService()
    snapshot = create_snapshot("runtime-isolation")
    before = {
        "events": CausalEvent.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "assessments": CustomerImpactAssessment.objects.filter(data_snapshot=snapshot).count(),
        "compensations": CompensationEvaluation.objects.filter(data_snapshot=snapshot).count(),
    }
    baseline = create_baseline(service, snapshot=snapshot)
    candidate = service.create_candidate(baseline_run=baseline)

    assert candidate.source_snapshot_id == baseline.source_snapshot_id == snapshot.id
    assert candidate.scenario_id == baseline.scenario_id
    assert candidate.baseline_run_id == baseline.id

    run = service.start(baseline)
    run = service.advance(run, simulation_step=timedelta(minutes=5))
    service.stop(run)

    assert {
        "events": CausalEvent.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "assessments": CustomerImpactAssessment.objects.filter(data_snapshot=snapshot).count(),
        "compensations": CompensationEvaluation.objects.filter(data_snapshot=snapshot).count(),
    } == before
