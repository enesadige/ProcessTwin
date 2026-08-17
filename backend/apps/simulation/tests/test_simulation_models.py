from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.compensation.models import CompensationEvaluation
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.operations.models import Alarm, CausalEvent, CustomerImpactAssessment, Outage
from apps.simulation.models import (
    SimulationComparisonRole,
    SimulationRun,
    SimulationRunEvent,
    SimulationScenario,
)


def create_snapshot(seed: str) -> DataSnapshot:
    dataset = DatasetVersion.objects.create(
        name=f"Simulation {seed}",
        generator_version="simulation-model-test",
        seed=seed,
    )
    return DataSnapshot.objects.create(dataset_version=dataset, name="Simulation snapshot")


def create_scenario(snapshot: DataSnapshot, *, code: str = "SIM-BNG-001") -> SimulationScenario:
    return SimulationScenario.objects.create(
        source_snapshot=snapshot,
        scenario_code=code,
        name="BNG outage comparison",
        scenario_type="bng_outage",
        definition={"root_kind": "bng"},
        default_parameters={"duration_minutes": 90},
    )


def create_baseline_run(
    scenario: SimulationScenario,
    *,
    seed: str = "simulation-seed-001",
    clock=None,
) -> SimulationRun:
    return SimulationRun.objects.create(
        source_snapshot=scenario.source_snapshot,
        scenario=scenario,
        comparison_role=SimulationComparisonRole.BASELINE,
        deterministic_seed=seed,
        virtual_clock=clock or timezone.now(),
    )


@pytest.mark.django_db
def test_simulation_runs_are_snapshot_local_and_operational_tables_remain_unchanged():
    snapshot = create_snapshot("isolation")
    before = {
        "causal_events": CausalEvent.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "assessments": CustomerImpactAssessment.objects.filter(data_snapshot=snapshot).count(),
        "compensations": CompensationEvaluation.objects.filter(data_snapshot=snapshot).count(),
    }

    scenario = create_scenario(snapshot)
    baseline = create_baseline_run(scenario)
    SimulationRunEvent.objects.create(
        simulation_run=baseline,
        sequence=1,
        event_code="SIM-EVT-001",
        event_type="planned_failure",
        virtual_occurred_at=baseline.virtual_clock,
        event_context={"source": "simulation"},
    )

    assert baseline.source_snapshot_id == snapshot.id
    assert baseline.events.count() == 1
    assert {
        "causal_events": CausalEvent.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "assessments": CustomerImpactAssessment.objects.filter(data_snapshot=snapshot).count(),
        "compensations": CompensationEvaluation.objects.filter(data_snapshot=snapshot).count(),
    } == before


@pytest.mark.django_db
def test_candidate_requires_matching_baseline_snapshot_scenario_seed_and_clock():
    snapshot = create_snapshot("candidate")
    scenario = create_scenario(snapshot)
    clock = timezone.now()
    baseline = create_baseline_run(scenario, clock=clock)

    candidate = SimulationRun.objects.create(
        source_snapshot=snapshot,
        scenario=scenario,
        comparison_role=SimulationComparisonRole.CANDIDATE,
        baseline_run=baseline,
        deterministic_seed=baseline.deterministic_seed,
        virtual_clock=clock,
        input_parameters={"refund_threshold_minutes": 120},
    )
    assert candidate.baseline_run_id == baseline.id

    with pytest.raises(ValidationError, match="same deterministic seed"):
        SimulationRun.objects.create(
            source_snapshot=snapshot,
            scenario=scenario,
            comparison_role=SimulationComparisonRole.CANDIDATE,
            baseline_run=baseline,
            deterministic_seed="different-seed",
            virtual_clock=clock,
        )

    other_snapshot = create_snapshot("candidate-other")
    other_scenario = create_scenario(other_snapshot, code="SIM-BNG-OTHER")
    with pytest.raises(ValidationError, match="Scenario must belong to the source snapshot"):
        SimulationRun.objects.create(
            source_snapshot=snapshot,
            scenario=other_scenario,
            comparison_role=SimulationComparisonRole.CANDIDATE,
            baseline_run=baseline,
            deterministic_seed=baseline.deterministic_seed,
            virtual_clock=clock,
        )


@pytest.mark.django_db
def test_speed_role_and_replay_constraints_are_validated_and_persisted():
    snapshot = create_snapshot("constraints")
    scenario = create_scenario(snapshot)
    baseline = create_baseline_run(scenario)

    with pytest.raises(ValidationError, match="Supported speed multipliers"):
        SimulationRun.objects.create(
            source_snapshot=snapshot,
            scenario=scenario,
            comparison_role=SimulationComparisonRole.BASELINE,
            deterministic_seed="invalid-speed",
            virtual_clock=timezone.now(),
            speed_multiplier=2,
        )

    with pytest.raises(ValidationError, match="require a baseline run"):
        SimulationRun.objects.create(
            source_snapshot=snapshot,
            scenario=scenario,
            comparison_role=SimulationComparisonRole.CANDIDATE,
            deterministic_seed="candidate-no-baseline",
            virtual_clock=timezone.now(),
        )

    replay = SimulationRun.objects.create(
        source_snapshot=snapshot,
        scenario=scenario,
        comparison_role=SimulationComparisonRole.BASELINE,
        deterministic_seed=baseline.deterministic_seed,
        virtual_clock=baseline.virtual_clock,
        replay_of=baseline,
        replay_identity=baseline.replay_identity,
    )
    assert replay.replay_of_id == baseline.id
    assert replay.replay_identity == baseline.replay_identity

    with pytest.raises(ValidationError, match="originating replay identity"):
        SimulationRun.objects.create(
            source_snapshot=snapshot,
            scenario=scenario,
            comparison_role=SimulationComparisonRole.BASELINE,
            deterministic_seed=baseline.deterministic_seed,
            virtual_clock=baseline.virtual_clock,
            replay_of=baseline,
        )

    with pytest.raises(IntegrityError):
        SimulationRun.objects.filter(pk=baseline.pk).update(speed_multiplier=2)


@pytest.mark.django_db
def test_run_events_are_owned_by_one_run_and_keep_virtual_time_sequence():
    snapshot = create_snapshot("events")
    baseline = create_baseline_run(create_scenario(snapshot))
    first_at = baseline.virtual_clock + timedelta(minutes=5)
    SimulationRunEvent.objects.create(
        simulation_run=baseline,
        sequence=1,
        event_code="SIM-EVT-001",
        event_type="alarm",
        virtual_occurred_at=first_at,
    )
    SimulationRunEvent.objects.create(
        simulation_run=baseline,
        sequence=2,
        event_code="SIM-EVT-002",
        event_type="incident",
        virtual_occurred_at=first_at + timedelta(minutes=2),
    )

    with pytest.raises(ValidationError, match="cannot precede an earlier sequence"):
        SimulationRunEvent.objects.create(
            simulation_run=baseline,
            sequence=3,
            event_code="SIM-EVT-003",
            event_type="outage",
            virtual_occurred_at=first_at + timedelta(minutes=1),
        )

    with pytest.raises(IntegrityError):
        SimulationRunEvent.objects.filter(simulation_run=baseline, sequence=2).update(sequence=1)
