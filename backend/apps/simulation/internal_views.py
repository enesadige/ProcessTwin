"""Service-token protected, persisted-only reads for the Simulation MCP."""

from __future__ import annotations

from typing import Any

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.core.internal_api import internal_service_required
from apps.datasets.models import DataSnapshot
from apps.simulation.api_serializers import (
    serialize_event,
    serialize_evidence,
    serialize_result,
    serialize_run,
)
from apps.simulation.models import SimulationEvidence, SimulationRun


class InternalSimulationAPIError(Exception):
    def __init__(self, code: str, message: str, *, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _error(exc: InternalSimulationAPIError) -> JsonResponse:
    return JsonResponse(
        {"error": {"code": exc.code, "message": exc.message, "details": {}}},
        status=exc.status,
    )


def _snapshot(request) -> DataSnapshot:
    identifier = request.GET.get("snapshot_identifier", "").strip()
    if not identifier:
        raise InternalSimulationAPIError(
            "validation_error", "snapshot_identifier is required.", status=400
        )
    snapshot = DataSnapshot.objects.filter(snapshot_key=identifier).first()
    if snapshot is None:
        raise InternalSimulationAPIError(
            "not_found", "Simulation snapshot was not found.", status=404
        )
    return snapshot


def _run(*, snapshot: DataSnapshot, run_code: str) -> SimulationRun:
    run = (
        SimulationRun.objects.select_related(
            "source_snapshot", "scenario", "baseline_run", "replay_of", "simulation_evidence"
        )
        .filter(source_snapshot=snapshot, run_code=run_code)
        .first()
    )
    if run is None:
        raise InternalSimulationAPIError("not_found", "Simulation run was not found.", status=404)
    return run


def _ok(*, request, snapshot: DataSnapshot, data: dict[str, Any]) -> JsonResponse:
    return JsonResponse(
        {
            "data": data,
            "warnings": [],
            "evidence": [],
            "metadata": {
                "correlation_id": request.correlation_id,
                "snapshot": {"id": snapshot.id, "snapshot_key": snapshot.snapshot_key},
            },
        }
    )


def _persisted_result(run: SimulationRun) -> dict[str, Any]:
    result = run.lifecycle_context.get("canonical_failure_result")
    if not isinstance(result, dict):
        result = run.lifecycle_context.get("canonical_bng_result")
    if not isinstance(result, dict):
        raise InternalSimulationAPIError(
            "result_not_ready", "Simulation result is not ready.", status=409
        )
    return result


def _cursor_and_limit(request) -> tuple[int, int]:
    try:
        cursor = int(request.GET.get("cursor", "0"))
        limit = int(request.GET.get("limit", "50"))
    except ValueError as exc:
        raise InternalSimulationAPIError(
            "validation_error", "cursor and limit must be integers.", status=400
        ) from exc
    if cursor < 0:
        raise InternalSimulationAPIError(
            "validation_error", "cursor must be zero or greater.", status=400
        )
    if not 1 <= limit <= 100:
        raise InternalSimulationAPIError(
            "validation_error", "limit must be between 1 and 100.", status=400
        )
    return cursor, limit


@require_GET
@internal_service_required
def get_simulation_run_status(request, run_code: str):
    try:
        snapshot = _snapshot(request)
        run = _run(snapshot=snapshot, run_code=run_code)
        return _ok(request=request, snapshot=snapshot, data={"run": serialize_run(run)})
    except InternalSimulationAPIError as exc:
        return _error(exc)


@require_GET
@internal_service_required
def get_simulation_result(request, run_code: str):
    try:
        snapshot = _snapshot(request)
        run = _run(snapshot=snapshot, run_code=run_code)
        # Return only the finalized runtime payload; no comparison or execution occurs on read.
        return _ok(
            request=request,
            snapshot=snapshot,
            data={"result": serialize_result(run, _persisted_result(run), None)},
        )
    except InternalSimulationAPIError as exc:
        return _error(exc)


@require_GET
@internal_service_required
def get_simulation_events(request, run_code: str):
    try:
        snapshot = _snapshot(request)
        run = _run(snapshot=snapshot, run_code=run_code)
        cursor, limit = _cursor_and_limit(request)
        events = list(run.events.filter(sequence__gt=cursor).order_by("sequence")[: limit + 1])
        has_more = len(events) > limit
        events = events[:limit]
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "run_code": run.run_code,
                "events": [serialize_event(event) for event in events],
                "result_count": len(events),
                "next_cursor": events[-1].sequence if events else None,
                "has_more": has_more,
            },
        )
    except InternalSimulationAPIError as exc:
        return _error(exc)


@require_GET
@internal_service_required
def get_simulation_evidence(request, run_code: str):
    try:
        snapshot = _snapshot(request)
        run = _run(snapshot=snapshot, run_code=run_code)
        try:
            evidence = run.simulation_evidence
        except SimulationEvidence.DoesNotExist as exc:
            raise InternalSimulationAPIError(
                "evidence_not_ready", "Simulation evidence is not ready.", status=409
            ) from exc
        if not evidence.finalized:
            raise InternalSimulationAPIError(
                "evidence_not_ready", "Simulation evidence is not finalized.", status=409
            )
        return _ok(
            request=request,
            snapshot=snapshot,
            data={"evidence": serialize_evidence(evidence)},
        )
    except InternalSimulationAPIError as exc:
        return _error(exc)
