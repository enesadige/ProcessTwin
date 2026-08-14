from __future__ import annotations

import json

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import UserRole
from apps.compensation.models import DecisionEvidence
from apps.core.internal_api import resolve_correlation_id
from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice
from apps.network.services.topology_summary import (
    TopologySummaryInputError,
    TopologySummaryService,
)
from apps.operations.models import CausalEvent
from apps.orchestration.evidence_serializers import (
    evidence_record_detail as serialize_evidence_record,
)
from apps.orchestration.facade import OrchestrationFacade
from apps.orchestration.models import EvidenceRecord, QueryRun, QueryRunStatus
from apps.rules.internal_serializers import decision_evidence_summary


def get_orchestration_facade() -> OrchestrationFacade:
    return OrchestrationFacade()


@require_POST
def execute_authenticated_query(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": {"code": "authentication_required", "message": "Authentication required."}},
            status=401,
        )
    if request.user.role not in {UserRole.ANALYST, UserRole.ADMIN}:
        return JsonResponse(
            {"error": {"code": "permission_denied", "message": "Analysis access is not allowed."}},
            status=403,
        )

    correlation_id = resolve_correlation_id(request)
    if isinstance(correlation_id, JsonResponse):
        return correlation_id
    request.correlation_id = correlation_id
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse(
            {
                "status": "failed",
                "error": {"code": "validation_error", "message": "Request body is invalid."},
            },
            status=400,
        )
    outcome = get_orchestration_facade().execute(
        payload, request_id=correlation_id, owner=request.user
    )
    return JsonResponse(outcome.envelope.to_payload(), status=outcome.http_status)


def _status_payload(query_run: QueryRun) -> dict:
    status = QueryRunStatus(query_run.status)
    executed = [item for item in query_run.executed_tools if isinstance(item, dict)]
    planned = [item for item in query_run.planned_tools if isinstance(item, dict)]
    succeeded = sum(item.get("status") == "succeeded" for item in executed)
    failed = sum(
        item.get("status") in {"failed", "skipped_dependency_failed"} for item in executed
    )
    phase = {
        QueryRunStatus.PENDING: "request_received",
        QueryRunStatus.PLANNED: "plan_prepared",
        QueryRunStatus.EXECUTING: "tools_executing",
        QueryRunStatus.COMPLETED: "completed",
        QueryRunStatus.FAILED: "failed",
    }[status]
    now = timezone.now()
    started = query_run.started_at or query_run.created_at
    ended = query_run.completed_at or now
    return {
        "query_run_code": query_run.query_run_code,
        "status": status.value,
        "phase": phase,
        "planned_tool_count": len(planned),
        "executed_tool_count": len(executed),
        "succeeded_tool_count": succeeded,
        "failed_tool_count": failed,
        "planned_tools": sorted(
            {item.get("tool_name") for item in planned if item.get("tool_name")}
        ),
        "executed_tools": sorted(
            {item.get("tool_name") for item in executed if item.get("tool_name")}
        ),
        "error_code": query_run.error_code or None,
        "started_at": query_run.started_at.isoformat() if query_run.started_at else None,
        "completed_at": query_run.completed_at.isoformat() if query_run.completed_at else None,
        "elapsed_ms": max(0, round((ended - started).total_seconds() * 1000)),
    }


@require_GET
def analysis_status(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": {"code": "authentication_required", "message": "Authentication required."}},
            status=401,
        )
    if request.user.role not in {UserRole.ANALYST, UserRole.ADMIN}:
        return JsonResponse(
            {"error": {"code": "permission_denied", "message": "Analysis access is not allowed."}},
            status=403,
        )
    idempotency_key = request.GET.get("idempotency_key", "").strip()
    query_run_code = request.GET.get("query_run_code", "").strip()
    if not idempotency_key and not query_run_code:
        return JsonResponse(
            {"error": {"code": "validation_error", "message": "A run reference is required."}},
            status=400,
        )
    query = QueryRun.objects.filter(owner=request.user)
    query = (
        query.filter(idempotency_key=idempotency_key)
        if idempotency_key
        else query.filter(query_run_code=query_run_code)
    )
    query_run = query.first()
    if query_run is None:
        return JsonResponse(
            {"error": {"code": "not_found", "message": "Analysis run was not found."}},
            status=404,
        )
    return JsonResponse(_status_payload(query_run))


@require_GET
def topology_summary(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": {"code": "authentication_required", "message": "Authentication required."}},
            status=401,
        )
    if request.user.role not in {UserRole.ANALYST, UserRole.ADMIN}:
        return JsonResponse(
            {"error": {"code": "permission_denied", "message": "Analysis access is not allowed."}},
            status=403,
        )

    snapshot_identifier = request.GET.get("snapshot_identifier", "").strip()
    device_code = request.GET.get("device_code", "").strip()
    causal_event_code = request.GET.get("causal_event_code", "").strip()
    if not snapshot_identifier or not device_code:
        return JsonResponse(
            {"error": {"code": "validation_error", "message": "Snapshot and device are required."}},
            status=400,
        )
    snapshot = DataSnapshot.objects.filter(snapshot_key=snapshot_identifier).first()
    if snapshot is None:
        return JsonResponse(
            {"error": {"code": "not_found", "message": "Snapshot was not found."}},
            status=404,
        )
    device = NetworkDevice.objects.select_related("city", "district", "neighborhood").filter(
        data_snapshot=snapshot,
        code=device_code,
    ).first()
    if device is None:
        return JsonResponse(
            {"error": {"code": "not_found", "message": "Device was not found in the snapshot."}},
            status=404,
        )
    causal_event = None
    if causal_event_code:
        causal_event = CausalEvent.objects.filter(
            data_snapshot=snapshot,
            event_code=causal_event_code,
        ).first()
        if causal_event is None:
            return JsonResponse(
                {
                    "error": {
                        "code": "not_found",
                        "message": "Causal event was not found in the snapshot.",
                    }
                },
                status=404,
            )
    try:
        payload = TopologySummaryService().build(
            snapshot=snapshot,
            device=device,
            causal_event=causal_event,
        ).to_payload()
    except TopologySummaryInputError as exc:
        return JsonResponse(
            {"error": {"code": "validation_error", "message": str(exc)}},
            status=400,
        )
    return JsonResponse({"data": payload})


@require_GET
def decision_evidence_detail(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": {"code": "authentication_required", "message": "Authentication required."}},
            status=401,
        )
    if request.user.role not in {UserRole.ANALYST, UserRole.ADMIN}:
        return JsonResponse(
            {"error": {"code": "permission_denied", "message": "Evidence access is not allowed."}},
            status=403,
        )

    snapshot_identifier = request.GET.get("snapshot_identifier", "").strip()
    evidence_hash = request.GET.get("evidence_hash", "").strip()
    if not snapshot_identifier or not evidence_hash:
        return JsonResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Snapshot and evidence reference are required.",
                }
            },
            status=400,
        )

    snapshot = DataSnapshot.objects.filter(snapshot_key=snapshot_identifier).first()
    if snapshot is None:
        return JsonResponse(
            {"error": {"code": "not_found", "message": "Evidence record was not found."}},
            status=404,
        )
    evidence = (
        DecisionEvidence.objects.filter(data_snapshot=snapshot, evidence_hash=evidence_hash)
        .select_related(
            "rule_set",
            "selected_rule_version",
            "selected_rule_version__rule",
            "selected_rule_version__rule__rule_set",
            "compensation_evaluation",
            "compensation_evaluation__outage",
            "compensation_evaluation__subscription",
            "compensation_evaluation__customer",
        )
        .first()
    )
    if evidence is None:
        return JsonResponse(
            {"error": {"code": "not_found", "message": "Evidence record was not found."}},
            status=404,
        )
    detail = decision_evidence_summary(evidence)
    evaluation = detail.get("compensation_evaluation")
    if evaluation:
        detail["compensation_evaluation"] = {
            key: evaluation[key]
            for key in ("evaluation_code", "result_type", "status", "outage_code")
        }
    return JsonResponse(
        {"data": {"snapshot_key": snapshot.snapshot_key, "decision_evidence": detail}}
    )


@require_GET
def evidence_record_detail(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": {"code": "authentication_required", "message": "Authentication required."}},
            status=401,
        )
    if request.user.role not in {UserRole.ANALYST, UserRole.ADMIN}:
        return JsonResponse(
            {"error": {"code": "permission_denied", "message": "Evidence access is not allowed."}},
            status=403,
        )

    snapshot_identifier = request.GET.get("snapshot_identifier", "").strip()
    evidence_code = request.GET.get("evidence_code", "").strip()
    if not snapshot_identifier or not evidence_code:
        return JsonResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Snapshot and evidence reference are required.",
                }
            },
            status=400,
        )

    evidence = (
        EvidenceRecord.objects.filter(
            data_snapshot__snapshot_key=snapshot_identifier,
            evidence_code=evidence_code,
            finalized=True,
            query_run__status__in=(QueryRunStatus.COMPLETED, QueryRunStatus.FAILED),
        )
        .select_related("data_snapshot", "query_run")
        .prefetch_related(
            "evidencetoolcall_records",
            "evidencecalculation_records",
            "evidencerulereference_records__rule_version__rule",
            "evidenceragreference_records__source_document",
            "evidenceragreference_records__document_chunk",
        )
        .first()
    )
    if evidence is None:
        return JsonResponse(
            {"error": {"code": "not_found", "message": "Evidence record was not found."}},
            status=404,
        )
    return JsonResponse({"data": {"evidence_record": serialize_evidence_record(evidence)}})
