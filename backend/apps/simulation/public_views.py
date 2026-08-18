"""Authenticated read/write endpoints for the isolated ProcessTwin runtime."""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import UserRole
from apps.datasets.models import DataSnapshot
from apps.simulation.api_serializers import (
    DEFAULT_EVENT_PAGE_SIZE,
    MAX_EVENT_PAGE_SIZE,
    SimulationAPIError,
    serialize_event,
    serialize_evidence,
    serialize_result,
    serialize_run,
    validate_anchor,
    validate_parameters,
)
from apps.simulation.models import (
    SimulationComparisonRole,
    SimulationEvidence,
    SimulationRun,
    SimulationScenario,
)
from apps.simulation.services import (
    CanonicalFailureSimulationError,
    CanonicalFailureSimulationService,
    SimulationLifecycleError,
    SimulationRuntimeError,
    SimulationService,
)


def _access_error(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": {"code": "authentication_required", "message": "Authentication required."}},
            status=401,
        )
    if request.user.role not in {UserRole.ANALYST, UserRole.ADMIN}:
        return JsonResponse(
            {
                "error": {
                    "code": "permission_denied",
                    "message": "Simulation access is not allowed.",
                }
            },
            status=403,
        )
    return None


def _payload(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SimulationAPIError("validation_error", "Request body is invalid.") from exc
    if not isinstance(payload, dict):
        raise SimulationAPIError("validation_error", "Request body must be an object.")
    return payload


def _error_response(exc: Exception):
    if isinstance(exc, SimulationAPIError):
        return JsonResponse(
            {"error": {"code": exc.code, "message": exc.message}}, status=exc.status
        )
    if isinstance(exc, SimulationLifecycleError):
        return JsonResponse(
            {
                "error": {
                    "code": "invalid_lifecycle_transition",
                    "message": str(exc),
                }
            },
            status=409,
        )
    if isinstance(exc, (SimulationRuntimeError, CanonicalFailureSimulationError)):
        return JsonResponse(
            {"error": {"code": "run_failed", "message": str(exc)}}, status=409
        )
    raise exc


def _snapshot(identifier: object):
    if not isinstance(identifier, str) or not identifier.strip():
        raise SimulationAPIError("validation_error", "source_snapshot_identifier is required.")
    snapshot = DataSnapshot.objects.filter(snapshot_key=identifier.strip()).first()
    if snapshot is None:
        raise SimulationAPIError("not_found", "Source snapshot was not found.", status=404)
    return snapshot


def _virtual_start(value: object):
    if not isinstance(value, str):
        raise SimulationAPIError("validation_error", "virtual_start is required.")
    parsed = parse_datetime(value)
    if parsed is None or parsed.tzinfo is None:
        raise SimulationAPIError(
            "validation_error", "virtual_start must be an ISO-8601 timezone-aware datetime."
        )
    return parsed


def _speed(value: object) -> int:
    speed = 1 if value is None else value
    if speed not in SimulationRun.SUPPORTED_SPEED_MULTIPLIERS:
        raise SimulationAPIError("invalid_speed", "Supported speed values are 1, 10, and 60.")
    return speed


def _scenario(snapshot, scenario_code: object):
    if not isinstance(scenario_code, str) or not scenario_code.strip():
        raise SimulationAPIError("validation_error", "scenario_code is required.")
    scenario = SimulationScenario.objects.filter(
        source_snapshot=snapshot, scenario_code=scenario_code.strip()
    ).first()
    if scenario is None:
        raise SimulationAPIError("not_found", "Simulation scenario was not found.", status=404)
    return scenario


def _run(run_code: str):
    run = SimulationRun.objects.select_related(
        "source_snapshot", "scenario", "baseline_run", "replay_of", "simulation_evidence"
    ).filter(run_code=run_code).first()
    if run is None:
        raise SimulationAPIError("not_found", "Simulation run was not found.", status=404)
    return run


def _scenario_data(payload: dict):
    snapshot = _snapshot(payload.get("source_snapshot_identifier"))
    anchor_type = payload.get("anchor_type")
    anchor_code = payload.get("anchor_code")
    if not anchor_type and isinstance(payload.get("source_device_code"), str):
        anchor_type = "network_device"
        anchor_code = payload["source_device_code"]
    if not isinstance(anchor_type, str) or not isinstance(anchor_code, str):
        raise SimulationAPIError("invalid_anchor", "anchor_type and anchor_code are required.")
    anchor_type, anchor_code, default_failure_type = validate_anchor(
        snapshot=snapshot,
        anchor_type=anchor_type,
        anchor_code=anchor_code,
    )
    failure_type = payload.get("failure_type", default_failure_type)
    if failure_type != default_failure_type:
        raise SimulationAPIError(
            "invalid_anchor", "failure_type must match the selected generic anchor type."
        )
    default_parameters = validate_parameters(payload.get("default_parameters", {}))
    if "duration_seconds" not in default_parameters:
        raise SimulationAPIError(
            "validation_error", "default_parameters.duration_seconds is required."
        )
    return snapshot, anchor_type, anchor_code, failure_type, default_parameters


@require_POST
def scenario_validate(request):
    if response := _access_error(request):
        return response
    try:
        payload = _payload(request)
        snapshot, anchor_type, anchor_code, failure_type, parameters = _scenario_data(payload)
    except Exception as exc:
        return _error_response(exc)
    return JsonResponse(
        {
            "data": {
                "valid": True,
                "source_snapshot_identifier": snapshot.snapshot_key,
                "definition": {
                    "anchor_type": anchor_type,
                    "anchor_code": anchor_code,
                    "failure_type": failure_type,
                },
                "default_parameters": parameters,
            }
        }
    )


@require_POST
def scenario_create(request):
    if response := _access_error(request):
        return response
    try:
        payload = _payload(request)
        snapshot, anchor_type, anchor_code, failure_type, parameters = _scenario_data(payload)
        scenario_code = payload.get("scenario_code")
        name = payload.get("name")
        if not isinstance(scenario_code, str) or not scenario_code.strip():
            raise SimulationAPIError("validation_error", "scenario_code is required.")
        if not isinstance(name, str) or not name.strip():
            raise SimulationAPIError("validation_error", "name is required.")
        if SimulationScenario.objects.filter(
            source_snapshot=snapshot, scenario_code=scenario_code.strip()
        ).exists():
            raise SimulationAPIError(
                "duplicate_scenario", "Scenario code already exists.", status=409
            )
        description = payload.get("description", "")
        scenario = SimulationScenario.objects.create(
            source_snapshot=snapshot,
            scenario_code=scenario_code.strip(),
            name=name.strip(),
            scenario_type=failure_type,
            description=description if isinstance(description, str) else "",
            definition={
                "anchor_type": anchor_type,
                "anchor_code": anchor_code,
                "failure_type": failure_type,
            },
            default_parameters=parameters,
        )
    except Exception as exc:
        return _error_response(exc)
    return JsonResponse(
        {
            "data": {
                "scenario": {
                    "scenario_code": scenario.scenario_code,
                    "name": scenario.name,
                    "source_snapshot_identifier": scenario.source_snapshot.snapshot_key,
                    "definition": scenario.definition,
                    "default_parameters": scenario.default_parameters,
                }
            }
        },
        status=201,
    )


@require_POST
def baseline_create(request):
    if response := _access_error(request):
        return response
    try:
        payload = _payload(request)
        snapshot = _snapshot(payload.get("source_snapshot_identifier"))
        scenario = _scenario(snapshot, payload.get("scenario_code"))
        seed = payload.get("deterministic_seed")
        if not isinstance(seed, str) or not seed.strip():
            raise SimulationAPIError("validation_error", "deterministic_seed is required.")
        runtime = SimulationService()
        run = runtime.create_run(
            scenario=scenario,
            comparison_role=SimulationComparisonRole.BASELINE,
            deterministic_seed=seed.strip(),
            virtual_clock=_virtual_start(payload.get("virtual_start")),
            speed_multiplier=_speed(payload.get("speed")),
            input_parameters=validate_parameters(payload.get("baseline_overrides", {})),
        )
    except Exception as exc:
        return _error_response(exc)
    return JsonResponse({"data": {"run": serialize_run(run)}}, status=201)


@require_POST
def candidate_create(request):
    if response := _access_error(request):
        return response
    try:
        payload = _payload(request)
        snapshot = _snapshot(payload.get("source_snapshot_identifier"))
        baseline = _run(payload.get("baseline_run_code", ""))
        if baseline.source_snapshot_id != snapshot.id:
            raise SimulationAPIError(
                "cross_snapshot_reference",
                "Candidate must use the baseline source snapshot.",
            )
        runtime = SimulationService()
        candidate = runtime.create_candidate(
            baseline_run=baseline,
            input_overrides=validate_parameters(
                payload.get("candidate_overrides", {}), candidate=True
            ),
            speed_multiplier=_speed(payload.get("speed")) if "speed" in payload else None,
        )
    except Exception as exc:
        return _error_response(exc)
    return JsonResponse({"data": {"run": serialize_run(candidate)}}, status=201)


@require_POST
def run_start(request, run_code: str):
    if response := _access_error(request):
        return response
    try:
        run = _run(run_code)
        if run.status in {"completed", "failed", "stopped"}:
            raise SimulationAPIError(
                "duplicate_start",
                "Terminal simulation runs must be replayed, not started again.",
                status=409,
            )
        result = CanonicalFailureSimulationService().execute(run)
        run.refresh_from_db()
    except Exception as exc:
        return _error_response(exc)
    return JsonResponse(
        {
            "data": {
                "run": serialize_run(run),
                "result": serialize_result(run, result.to_dict(), None),
            }
        }
    )


def _lifecycle_action(request, run_code: str, action: str):
    if response := _access_error(request):
        return response
    try:
        run = _run(run_code)
        runtime = SimulationService()
        updated = getattr(runtime, action)(run)
    except Exception as exc:
        return _error_response(exc)
    return JsonResponse({"data": {"run": serialize_run(updated)}})


@require_POST
def run_pause(request, run_code: str):
    return _lifecycle_action(request, run_code, "pause")


@require_POST
def run_resume(request, run_code: str):
    return _lifecycle_action(request, run_code, "resume")


@require_POST
def run_stop(request, run_code: str):
    return _lifecycle_action(request, run_code, "stop")


@require_POST
def run_replay(request, run_code: str):
    if response := _access_error(request):
        return response
    try:
        replay = SimulationService().replay(_run(run_code))
    except Exception as exc:
        return _error_response(exc)
    return JsonResponse({"data": {"run": serialize_run(replay)}}, status=201)


@require_GET
def run_status(request, run_code: str):
    if response := _access_error(request):
        return response
    try:
        run = _run(run_code)
    except Exception as exc:
        return _error_response(exc)
    return JsonResponse({"data": {"run": serialize_run(run)}})


@require_GET
def run_result(request, run_code: str):
    if response := _access_error(request):
        return response
    try:
        run = _run(run_code)
        result = run.lifecycle_context.get("canonical_failure_result")
        if not isinstance(result, dict):
            result = run.lifecycle_context.get("canonical_bng_result")
        if not isinstance(result, dict):
            raise SimulationAPIError(
                "result_not_ready", "Canonical simulation result is not ready.", status=409
            )
        comparison = None
        if run.comparison_role == SimulationComparisonRole.CANDIDATE and run.baseline_run_id:
            comparison = CanonicalFailureSimulationService().compare(
                baseline_run=run.baseline_run,
                candidate_run=run,
            )
    except Exception as exc:
        return _error_response(exc)
    return JsonResponse({"data": {"result": serialize_result(run, result, comparison)}})


@require_GET
def run_evidence(request, run_code: str):
    if response := _access_error(request):
        return response
    try:
        run = _run(run_code)
        snapshot_identifier = request.GET.get("snapshot_identifier", "").strip()
        if not snapshot_identifier:
            raise SimulationAPIError(
                "validation_error", "snapshot_identifier is required for simulation evidence."
            )
        if snapshot_identifier != run.source_snapshot.snapshot_key:
            raise SimulationAPIError(
                "not_found",
                "Simulation evidence was not found in the requested snapshot.",
                status=404,
            )
        evidence = run.simulation_evidence
    except SimulationEvidence.DoesNotExist:
        return _error_response(
            SimulationAPIError(
                "evidence_not_ready", "Simulation evidence is not ready.", status=409
            )
        )
    except Exception as exc:
        return _error_response(exc)
    return JsonResponse({"data": {"evidence": serialize_evidence(evidence)}})


@require_GET
def run_events(request, run_code: str):
    if response := _access_error(request):
        return response
    try:
        run = _run(run_code)
        cursor_text = request.GET.get("cursor", "").strip()
        cursor = int(cursor_text) if cursor_text else 0
        if cursor < 0:
            raise ValueError
        limit_text = request.GET.get("limit", str(DEFAULT_EVENT_PAGE_SIZE)).strip()
        limit = int(limit_text)
        if not 1 <= limit <= MAX_EVENT_PAGE_SIZE:
            raise ValueError
    except ValueError:
        return _error_response(
            SimulationAPIError(
                "validation_error", f"limit must be between 1 and {MAX_EVENT_PAGE_SIZE}."
            )
        )
    except Exception as exc:
        return _error_response(exc)

    records = list(run.events.filter(sequence__gt=cursor).order_by("sequence")[: limit + 1])
    has_more = len(records) > limit
    records = records[:limit]
    return JsonResponse(
        {
            "data": {
                "run_code": run.run_code,
                "events": [serialize_event(event) for event in records],
                "result_count": len(records),
                "next_cursor": records[-1].sequence if records else None,
                "has_more": has_more,
            }
        }
    )
