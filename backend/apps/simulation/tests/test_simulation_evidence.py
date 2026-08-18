from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError

from apps.simulation.models import SimulationComparisonRole, SimulationEvidence, SimulationRunStatus
from apps.simulation.services import (
    CanonicalFailureSimulationService,
    SimulationEvidenceService,
    SimulationService,
)
from apps.simulation.tests.test_canonical_bng_simulation import clock, setup_bng_scenario


def _completed_baseline_candidate():
    snapshot, scenario = setup_bng_scenario()
    runtime = SimulationService()
    baseline = runtime.create_run(
        scenario=scenario,
        comparison_role=SimulationComparisonRole.BASELINE,
        deterministic_seed="simulation-evidence-seed",
        virtual_clock=clock(),
    )
    candidate = runtime.create_candidate(
        baseline_run=baseline,
        input_overrides={"duration_seconds": 1200},
    )
    service = CanonicalFailureSimulationService(runtime=runtime)
    service.execute(baseline)
    service.execute(candidate)
    baseline.refresh_from_db()
    candidate.refresh_from_db()
    return snapshot, runtime, service, baseline, candidate


@pytest.mark.django_db
def test_completed_baseline_and_candidate_materialize_distinct_snapshot_local_evidence():
    snapshot, _runtime, _service, baseline, candidate = _completed_baseline_candidate()

    baseline_evidence = baseline.simulation_evidence
    candidate_evidence = candidate.simulation_evidence

    assert baseline.status == candidate.status == SimulationRunStatus.COMPLETED
    assert baseline_evidence.finalized is candidate_evidence.finalized is True
    assert (
        baseline_evidence.source_snapshot_id
        == candidate_evidence.source_snapshot_id
        == snapshot.id
    )
    assert baseline_evidence.simulation_run_id != candidate_evidence.simulation_run_id
    assert baseline_evidence.evidence_hash != candidate_evidence.evidence_hash
    assert (
        baseline_evidence.payload["semantics"]["result_kind"]
        == "hypothetical_simulation_projection"
    )
    assert (
        baseline_evidence.payload["semantics"]["projection"]["basis"]
        == "simulation_projection"
    )
    assert (
        baseline_evidence.payload["semantics"]["historical_evidence"]["basis"]
        == "persisted_session_evidence"
    )
    assert "projected_affected_subscription_ids" not in baseline_evidence.payload["semantics"][
        "projection"
    ]
    assert baseline_evidence.payload["semantics"]["selected_rule_version"] == {
        "status": "selected",
        "rule_code": "SIM-REFUND-001",
        "version": 1,
    }


@pytest.mark.django_db
def test_materialization_is_stable_immutable_and_does_not_change_completed_run():
    _snapshot, _runtime, _service, baseline, _candidate = _completed_baseline_candidate()
    before_context = deepcopy(baseline.lifecycle_context)
    evidence = baseline.simulation_evidence

    reread = SimulationEvidenceService().materialize(baseline)
    baseline.refresh_from_db()

    assert reread.pk == evidence.pk
    assert reread.evidence_hash == evidence.evidence_hash
    assert baseline.lifecycle_context == before_context
    assert SimulationEvidence.objects.filter(simulation_run=baseline).count() == 1

    evidence.payload = {"changed": True}
    with pytest.raises(ValidationError, match="immutable"):
        evidence.save()


@pytest.mark.django_db
def test_replay_has_distinct_evidence_and_preserves_original_lineage():
    _snapshot, runtime, service, _baseline, candidate = _completed_baseline_candidate()
    original_evidence = candidate.simulation_evidence
    original_payload = deepcopy(original_evidence.payload)

    replay = runtime.replay(candidate)
    service.execute(replay)
    replay.refresh_from_db()
    original_evidence.refresh_from_db()

    replay_evidence = replay.simulation_evidence
    assert replay_evidence.pk != original_evidence.pk
    assert replay_evidence.payload["run"]["replay_of_run_code"] == candidate.run_code
    assert replay_evidence.payload["run"]["baseline_run_code"] == replay.baseline_run.run_code
    assert original_evidence.payload == original_payload


@pytest.mark.django_db
def test_missing_unknown_and_rule_version_remain_uninvented_in_evidence():
    snapshot, scenario = setup_bng_scenario()
    run = SimulationService().create_run(
        scenario=scenario,
        comparison_role=SimulationComparisonRole.BASELINE,
        deterministic_seed="simulation-evidence-unknown",
        virtual_clock=clock(),
    )
    run.status = SimulationRunStatus.COMPLETED
    run.lifecycle_context = {
        "canonical_failure_result": {
            "event": {"selected_rule_version": None},
            "projection": {
                "basis": "simulation_projection",
                "projected_unknown_subscriptions": None,
            },
            "historical_evidence": {"basis": "not_used_for_device_anchor"},
            "compensation": {"status": "manual_review", "amount": None, "currency": None},
        }
    }
    run.save(update_fields=["status", "lifecycle_context", "updated_at"])

    evidence = SimulationEvidenceService().materialize(run)

    assert evidence.source_snapshot_id == snapshot.id
    assert evidence.payload["semantics"]["projection"]["projected_unknown_subscriptions"] is None
    assert evidence.payload["semantics"]["simulated_compensation"]["amount"] is None
    assert evidence.payload["semantics"]["selected_rule_version"] is None
