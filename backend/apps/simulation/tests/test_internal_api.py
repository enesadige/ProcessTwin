from __future__ import annotations

import pytest
from django.test import override_settings

from apps.operations.models import Alarm, CausalEvent, CustomerImpactAssessment, Incident, Outage
from apps.simulation.services import (
    CanonicalFailureSimulationService,
    SimulationEvidenceService,
    SimulationService,
)
from apps.simulation.tests.test_canonical_bng_simulation import clock, setup_bng_scenario

SERVICE_TOKEN = "simulation-mcp-service-token"
API = "/api/internal/v1/simulation/"


def _completed_run():
    snapshot, scenario = setup_bng_scenario()
    runtime = SimulationService()
    run = runtime.create_run(
        scenario=scenario,
        comparison_role="baseline",
        deterministic_seed="simulation-internal-read-seed",
        virtual_clock=clock(),
    )
    CanonicalFailureSimulationService(runtime=runtime).execute(run)
    run.refresh_from_db()
    return snapshot, run


def _source_counts(snapshot):
    return {
        "events": CausalEvent.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "incidents": Incident.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "assessments": CustomerImpactAssessment.objects.filter(data_snapshot=snapshot).count(),
    }


def _get(client, path, snapshot_key, **params):
    return client.get(
        path,
        {"snapshot_identifier": snapshot_key, **params},
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="simulation-mcp-read-1",
    )


@pytest.mark.django_db
@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_internal_simulation_reads_are_persisted_snapshot_local_and_read_only(client, monkeypatch):
    snapshot, run = _completed_run()
    before_run = (run.status, run.lifecycle_context, run.updated_at)
    before_source = _source_counts(snapshot)

    unauthorized = client.get(
        f"{API}runs/{run.run_code}/status/", {"snapshot_identifier": snapshot.snapshot_key}
    )
    assert unauthorized.status_code == 401

    status = _get(client, f"{API}runs/{run.run_code}/status/", snapshot.snapshot_key)
    assert status.status_code == 200
    assert status.headers["X-Correlation-ID"] == "simulation-mcp-read-1"
    assert status.json()["data"]["run"]["status"] == "completed"

    def must_not_execute(*_args, **_kwargs):
        raise AssertionError("Simulation result GET must not execute the runtime.")

    def must_not_materialize(*_args, **_kwargs):
        raise AssertionError("Simulation evidence GET must not materialize evidence.")

    monkeypatch.setattr(CanonicalFailureSimulationService, "execute", must_not_execute)
    monkeypatch.setattr(SimulationEvidenceService, "materialize", must_not_materialize)

    result = _get(client, f"{API}runs/{run.run_code}/result/", snapshot.snapshot_key)
    assert result.status_code == 200
    payload = result.json()["data"]["result"]
    assert payload["projection"]["basis"] == "simulation_projection"
    assert payload["comparison"] is None

    events = _get(
        client, f"{API}runs/{run.run_code}/events/", snapshot.snapshot_key, cursor=0, limit=2
    )
    assert events.status_code == 200
    assert events.json()["data"]["events"]

    evidence = _get(client, f"{API}runs/{run.run_code}/evidence/", snapshot.snapshot_key)
    assert evidence.status_code == 200
    evidence_payload = evidence.json()["data"]["evidence"]
    assert evidence_payload["finalized"] is True
    assert (
        evidence_payload["payload"]["semantics"]["result_kind"]
        == "hypothetical_simulation_projection"
    )

    run.refresh_from_db()
    assert (run.status, run.lifecycle_context, run.updated_at) == before_run
    assert _source_counts(snapshot) == before_source


@pytest.mark.django_db
@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_internal_simulation_reads_reject_invalid_and_cross_snapshot_runs(client):
    snapshot, run = _completed_run()
    from apps.operations.tests.test_operations_models import create_snapshot

    other = create_snapshot("simulation-mcp-other")
    missing = _get(client, f"{API}runs/MISSING/status/", snapshot.snapshot_key)
    assert missing.status_code == 404
    cross_snapshot = _get(client, f"{API}runs/{run.run_code}/status/", other.snapshot_key)
    assert cross_snapshot.status_code == 404
    missing_snapshot = client.get(
        f"{API}runs/{run.run_code}/status/",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
    )
    assert missing_snapshot.status_code == 400
