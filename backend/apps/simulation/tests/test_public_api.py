from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.compensation.models import CompensationEvaluation
from apps.operations.models import Alarm, CausalEvent, CustomerImpactAssessment, Incident, Outage
from apps.operations.tests.test_operations_models import (
    create_access_line,
    create_snapshot,
    create_subscription_connection,
)
from apps.simulation.models import SimulationRun, SimulationRunStatus
from apps.simulation.services import CanonicalFailureSimulationService, SimulationService

API = "/api/simulation/"
CLOCK = "2026-07-01T12:00:00+00:00"


def _analyst_client():
    user = get_user_model().objects.create_user(
        username="simulation-analyst", password="correct-pass-123", role="analyst"
    )
    client = Client()
    client.force_login(user)
    return client


def _source_world(code_suffix="API"):
    snapshot = create_snapshot(f"simulation-api-{code_suffix}")
    device, _access, link, _port, line = create_access_line(snapshot, code_suffix=code_suffix)
    line.valid_from = datetime(2026, 6, 30, tzinfo=UTC)
    line.save(update_fields=["valid_from"])
    create_subscription_connection(snapshot, line)
    return snapshot, device, link, line


def _scenario_payload(snapshot, *, anchor_type, anchor_code, code="SIM-API-001"):
    return {
        "source_snapshot_identifier": snapshot.snapshot_key,
        "scenario_code": code,
        "name": "Public ProcessTwin scenario",
        "anchor_type": anchor_type,
        "anchor_code": anchor_code,
        "failure_type": f"{anchor_type}_failure",
        "default_parameters": {
            "duration_seconds": 600,
            "outage_classification": "full_outage",
            "sla_target_seconds": 300,
        },
    }


def _post(client, path, payload):
    return client.post(path, data=json.dumps(payload), content_type="application/json")


def _operational_counts(snapshot):
    return {
        "events": CausalEvent.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "incidents": Incident.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "assessments": CustomerImpactAssessment.objects.filter(data_snapshot=snapshot).count(),
        "compensations": CompensationEvaluation.objects.filter(data_snapshot=snapshot).count(),
    }


@pytest.mark.django_db
def test_scenario_contract_supports_generic_anchor_families_and_role_boundaries():
    snapshot, device, link, line = _source_world("ANCHORS")
    client = Client()
    device_payload = _scenario_payload(
        snapshot, anchor_type="network_device", anchor_code=device.code
    )
    assert _post(client, f"{API}scenarios/validate/", device_payload).status_code == 401

    viewer = get_user_model().objects.create_user(
        username="simulation-viewer", password="correct-pass-123", role="viewer"
    )
    client.force_login(viewer)
    assert _post(client, f"{API}scenarios/validate/", device_payload).status_code == 403

    client = _analyst_client()
    for anchor_type, anchor_code in (
        ("network_device", device.code),
        ("network_link", link.link_code),
        ("line_connection", line.line_code),
    ):
        response = _post(
            client,
            f"{API}scenarios/validate/",
            _scenario_payload(snapshot, anchor_type=anchor_type, anchor_code=anchor_code),
        )
        assert response.status_code == 200
        assert response.json()["data"]["definition"]["anchor_type"] == anchor_type

    unsupported = _post(
        client,
        f"{API}scenarios/validate/",
        _scenario_payload(snapshot, anchor_type="network_port", anchor_code="PON-01"),
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["error"]["code"] == "unsupported_anchor_type"


@pytest.mark.django_db
def test_baseline_candidate_result_cursor_and_isolation_without_reexecution(monkeypatch):
    snapshot, device, _link, _line = _source_world("RUN")
    client = _analyst_client()
    create = _post(
        client,
        f"{API}scenarios/",
        _scenario_payload(snapshot, anchor_type="network_device", anchor_code=device.code),
    )
    assert create.status_code == 201

    baseline = _post(
        client,
        f"{API}runs/baseline/",
        {
            "source_snapshot_identifier": snapshot.snapshot_key,
            "scenario_code": "SIM-API-001",
            "deterministic_seed": "api-baseline-seed",
            "virtual_start": CLOCK,
            "speed": 10,
        },
    )
    assert baseline.status_code == 201
    baseline_code = baseline.json()["data"]["run"]["run_code"]
    candidate = _post(
        client,
        f"{API}runs/candidate/",
        {
            "source_snapshot_identifier": snapshot.snapshot_key,
            "baseline_run_code": baseline_code,
            "candidate_overrides": {"sla_target_seconds": 900},
        },
    )
    assert candidate.status_code == 201
    candidate_code = candidate.json()["data"]["run"]["run_code"]

    before = _operational_counts(snapshot)
    assert _post(client, f"{API}runs/{baseline_code}/start/", {}).status_code == 200
    assert _post(client, f"{API}runs/{candidate_code}/start/", {}).status_code == 200
    assert _operational_counts(snapshot) == before

    status = client.get(f"{API}runs/{candidate_code}/status/")
    assert status.status_code == 200
    assert status.json()["data"]["run"]["status"] == SimulationRunStatus.COMPLETED
    assert status.json()["data"]["run"]["result_ready"] is True

    def must_not_execute(*_args, **_kwargs):
        raise AssertionError("Result GET must not execute the simulation core.")

    monkeypatch.setattr(CanonicalFailureSimulationService, "execute", must_not_execute)
    result = client.get(f"{API}runs/{candidate_code}/result/")
    assert result.status_code == 200
    payload = result.json()["data"]["result"]
    assert payload["event"]["anchor_type"] == "network_device"
    assert payload["projection"]["basis"] == "simulation_projection"
    assert payload["projection"]["projected_unknown_subscriptions"] == 0
    assert payload["historical_evidence"]["basis"] == "not_used_for_device_anchor"
    assert payload["comparison"]["sla_breached"] == {
        "baseline": True,
        "candidate": False,
        "changed": True,
    }

    first = client.get(f"{API}runs/{candidate_code}/events/", {"limit": 3})
    assert first.status_code == 200
    first_events = first.json()["data"]["events"]
    assert [event["sequence"] for event in first_events] == [1, 2, 3]
    assert "result" not in first_events[-1]["context"]
    second = client.get(
        f"{API}runs/{candidate_code}/events/",
        {"cursor": first.json()["data"]["next_cursor"], "limit": 100},
    )
    second_events = second.json()["data"]["events"]
    assert second_events
    assert second_events[0]["sequence"] == 4
    assert set(event["sequence"] for event in first_events).isdisjoint(
        event["sequence"] for event in second_events
    )

    duplicate = _post(client, f"{API}runs/{candidate_code}/start/", {})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_start"
    invalid_pause = _post(client, f"{API}runs/{candidate_code}/pause/", {})
    assert invalid_pause.status_code == 409
    assert invalid_pause.json()["error"]["code"] == "invalid_lifecycle_transition"


@pytest.mark.django_db
def test_lifecycle_replay_and_cross_snapshot_candidate_rejection():
    snapshot, device, _link, _line = _source_world("LIFECYCLE")
    client = _analyst_client()
    assert _post(
        client,
        f"{API}scenarios/",
        _scenario_payload(snapshot, anchor_type="network_device", anchor_code=device.code),
    ).status_code == 201
    baseline = _post(
        client,
        f"{API}runs/baseline/",
        {
            "source_snapshot_identifier": snapshot.snapshot_key,
            "scenario_code": "SIM-API-001",
            "deterministic_seed": "api-lifecycle-seed",
            "virtual_start": CLOCK,
        },
    ).json()["data"]["run"]

    running = SimulationRun.objects.get(run_code=baseline["run_code"])
    SimulationService().start(running)
    assert _post(client, f"{API}runs/{running.run_code}/pause/", {}).status_code == 200
    assert _post(client, f"{API}runs/{running.run_code}/resume/", {}).status_code == 200
    stopped = _post(client, f"{API}runs/{running.run_code}/stop/", {})
    assert stopped.status_code == 200
    assert stopped.json()["data"]["run"]["status"] == SimulationRunStatus.STOPPED

    replay = _post(client, f"{API}runs/{running.run_code}/replay/", {})
    assert replay.status_code == 201
    assert replay.json()["data"]["run"]["replay_of_run_code"] == running.run_code

    other_snapshot, _other_device, _other_link, _other_line = _source_world("OTHER")
    rejected = _post(
        client,
        f"{API}runs/candidate/",
        {
            "source_snapshot_identifier": other_snapshot.snapshot_key,
            "baseline_run_code": running.run_code,
            "candidate_overrides": {},
        },
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "cross_snapshot_reference"


@pytest.mark.django_db
def test_candidate_override_and_input_validation_are_strict():
    snapshot, device, _link, _line = _source_world("VALIDATION")
    client = _analyst_client()
    payload = _scenario_payload(snapshot, anchor_type="network_device", anchor_code=device.code)
    payload["default_parameters"] = {"duration_seconds": -1}
    invalid = _post(client, f"{API}scenarios/validate/", payload)
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_override"

    valid = _scenario_payload(snapshot, anchor_type="network_device", anchor_code=device.code)
    assert _post(client, f"{API}scenarios/", valid).status_code == 201
    baseline = _post(
        client,
        f"{API}runs/baseline/",
        {
            "source_snapshot_identifier": snapshot.snapshot_key,
            "scenario_code": "SIM-API-001",
            "deterministic_seed": "api-validation-seed",
            "virtual_start": CLOCK,
            "speed": 5,
        },
    )
    assert baseline.status_code == 400
    assert baseline.json()["error"]["code"] == "invalid_speed"

    baseline = _post(
        client,
        f"{API}runs/baseline/",
        {
            "source_snapshot_identifier": snapshot.snapshot_key,
            "scenario_code": "SIM-API-001",
            "deterministic_seed": "api-validation-seed",
            "virtual_start": CLOCK,
        },
    ).json()["data"]["run"]
    invalid_candidate = _post(
        client,
        f"{API}runs/candidate/",
        {
            "source_snapshot_identifier": snapshot.snapshot_key,
            "baseline_run_code": baseline["run_code"],
            "candidate_overrides": {"anchor_code": "OTHER"},
        },
    )
    assert invalid_candidate.status_code == 400
    assert invalid_candidate.json()["error"]["code"] == "invalid_candidate_override"
