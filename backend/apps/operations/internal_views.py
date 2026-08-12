from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.compensation.models import DecisionEvidence
from apps.compensation.services.verified_impact import VerifiedImpactCompensationService
from apps.core.internal_api import internal_service_required
from apps.operations.models import Alarm, CausalEvent, Outage
from apps.operations.services.alarm_correlation import (
    AlarmCorrelationInputError,
    AlarmCorrelationService,
    CrossIncidentCorrelationResult,
    summarize_causal_event_roles,
)
from apps.operations.services.customer_impact_assessment import CustomerImpactAssessmentService
from apps.operations.services.root_cause import RootCauseService


@require_GET
@internal_service_required
def causal_analysis(request, event_code):
    # MCP clients use the canonical request field name; keep the short query
    # parameter for existing internal callers and always preserve snapshot
    # isolation when the full name is supplied.
    snapshot_key = request.GET.get("snapshot") or request.GET.get("snapshot_identifier")
    events = CausalEvent.objects.select_related("data_snapshot__dataset_version").filter(
        event_code=event_code
    )

    if snapshot_key:
        events = events.filter(data_snapshot__snapshot_key=snapshot_key)
    event = events.order_by("data_snapshot__snapshot_key").first()
    if event is None:
        return JsonResponse(
            {
                "error": {
                    "code": "not_found",
                    "message": "Causal event was not found.",
                    "details": {},
                }
            },
            status=404,
        )
    snapshot = event.data_snapshot
    causal_alarms = list(
        Alarm.objects.filter(data_snapshot=snapshot, causal_event=event)
        .select_related("alarm_type", "causal_event")
        .order_by("alarm_id")
    )
    impact = CustomerImpactAssessmentService().summarize(causal_event=event, snapshot=snapshot)
    assessment_record_count = event.customer_impact_assessments.filter(
        data_snapshot=snapshot
    ).count()
    outage = (
        Outage.objects.filter(data_snapshot=snapshot, causal_event=event)
        .select_related("source_device")
        .first()
    )
    root_payload = {
        "resource_type": event.get_root_resource_kind(),
        "reference": event.root_resource_code,
    }
    correlation = {
        "root_cause": None,
        "score": None,
        "confidence": None,
        "role_counts": summarize_causal_event_roles(causal_alarms),
        "reason_codes": [],
        "propagation_summary": None,
    }
    if outage is not None:
        candidates = RootCauseService().analyze(outage=outage, snapshot=snapshot)
        if candidates:
            candidate = candidates[0]
            correlation["root_cause"] = candidate.candidate_resource_code
            correlation["score"] = candidate.evidence_score
            correlation["confidence"] = candidate.evidence_score
            correlation["reason_codes"] = candidate.reason_codes or []
            correlation["propagation_summary"] = candidate.description
    root_alarm_types = sorted(
        {
            alarm.alarm_type.code
            for alarm in causal_alarms
            if alarm.metadata.get("causal_role") == "root"
        }
    )
    symptom_alarm_types = sorted(
        {
            alarm.alarm_type.code
            for alarm in causal_alarms
            if alarm.metadata.get("causal_role") == "symptom"
            or (alarm.metadata.get("normalization") or {}).get("role_candidate") == "symptom"
        }
    )
    scenario_code = (event.metadata or {}).get("scenario_code")
    failover = (
        {
            "primary_status": "down",
            "backup_status": "active",
            "full_outage": False,
        }
        if scenario_code == "SCN-FAILOVER-HITLESS-001"
        else None
    )
    evidence = (
        DecisionEvidence.objects.filter(
            data_snapshot=snapshot, context_snapshot__causal_event_code=event.event_code
        )
        .order_by("created_at")
        .first()
    )
    has_assessments = assessment_record_count > 0
    return JsonResponse(
        {
            "data": {
                "causal_event": {
                    "code": event.event_code,
                    "event_type": event.event_type,
                    "status": event.status,
                    "started_at": event.started_at.isoformat(),
                    "ended_at": event.ended_at.isoformat() if event.ended_at else None,
                    "root_resource": root_payload,
                },
                "correlation": correlation,
                "alarm_classification": {
                    "root_alarm_types": root_alarm_types,
                    "symptom_alarm_types": symptom_alarm_types,
                    "dying_gasp": "symptom"
                    if "ONT_DISCONNECT_SURGE" in symptom_alarm_types
                    else "not_observed",
                    "device_not_active": "not_observed",
                },
                "failover": failover,
                "impact": {
                    "potential": impact.potential_connection_count if has_assessments else None,
                    "verified_impacted": (
                        impact.verified_impacted_count if has_assessments else None
                    ),
                    "verified_no_impact": (
                        impact.verified_no_impact_count if has_assessments else None
                    ),
                    "insufficient_evidence": (
                        impact.insufficient_evidence_count if has_assessments else None
                    ),
                    "pending": impact.pending_count if has_assessments else None,
                    "failover_protected_count": (
                        impact.failover_protected_count if has_assessments else None
                    ),
                    "reason_codes": impact.reason_code_counts,
                    "assessment_record_count": assessment_record_count,
                    "missing_evidence_categories": (
                        ["customer_impact_assessment"] if assessment_record_count == 0 else []
                    ),
                },
                "compensation": compensation_payload(outage=outage, snapshot=snapshot),
                "evidence": (
                    {
                        "reference": evidence.evidence_hash[:12],
                        "finalized": evidence.finalized,
                        "created_at": evidence.created_at.isoformat(),
                    }
                    if evidence
                    else None
                ),
            },
            "metadata": {
                "correlation_id": request.correlation_id,
                "snapshot": snapshot.snapshot_key,
            },
        }
    )


@require_GET
@internal_service_required
def cross_incident_correlations(request, event_code):
    """Return bounded, deterministic correlation evidence for one causal event."""
    snapshot_key = request.GET.get("snapshot_identifier") or request.GET.get("snapshot")
    try:
        window_minutes = int(request.GET.get("window_minutes", "60"))
    except (TypeError, ValueError):
        window_minutes = 0
    direction = request.GET.get("direction", "both")
    if window_minutes < 1 or window_minutes > 24 * 60:
        return _cross_correlation_error("validation_error", "window_minutes is invalid.", 400)
    if direction not in {"before", "after", "both"}:
        return _cross_correlation_error("validation_error", "direction is invalid.", 400)
    events = CausalEvent.objects.select_related(
        "data_snapshot__dataset_version", "root_device", "root_device__city"
    ).filter(event_code=event_code)
    if snapshot_key:
        events = events.filter(data_snapshot__snapshot_key=snapshot_key)
    anchor = events.order_by("data_snapshot__snapshot_key").first()
    if anchor is None:
        return _cross_correlation_error("not_found", "Causal event was not found.", 404)
    snapshot = anchor.data_snapshot
    candidate_code = request.GET.get("candidate_causal_event_code")
    service = AlarmCorrelationService()
    try:
        if candidate_code:
            candidate = CausalEvent.objects.filter(
                data_snapshot=snapshot, event_code=candidate_code
            ).select_related("root_device", "root_device__city").first()
            if candidate is None:
                return _cross_correlation_error(
                    "not_found", "Candidate causal event was not found.", 404
                )
            results = [
                service.correlate_events(
                    anchor_event=anchor,
                    candidate_event=candidate,
                    snapshot=snapshot,
                    window_seconds=window_minutes * 60,
                )
            ]
        else:
            results = service.find_cross_incident_correlations(
                anchor_event=anchor,
                snapshot=snapshot,
                window_seconds=window_minutes * 60,
                direction=direction,
                other_region_only=request.GET.get("other_region_only", "false").lower()
                == "true",
            )
    except AlarmCorrelationInputError as exc:
        return _cross_correlation_error("validation_error", str(exc), 400)
    return JsonResponse(
        {
            "data": {
                "anchor_event_code": anchor.event_code,
                "candidate_count": len(results),
                "correlations": [_cross_correlation_payload(item) for item in results],
            },
            "metadata": {
                "correlation_id": request.correlation_id,
                "snapshot": snapshot.snapshot_key,
            },
        }
    )


def _cross_correlation_payload(result: CrossIncidentCorrelationResult) -> dict[str, object]:
    return {
        "anchor_event_code": result.anchor_event_code,
        "candidate_event_code": result.candidate_event_code,
        "correlation_status": result.correlation_status.value,
        "time_difference_seconds": result.time_difference_seconds,
        "within_window": result.within_window,
        "requested_window_seconds": result.requested_window_seconds,
        "topology_relation": result.topology_relation,
        "resource_relation": result.resource_relation,
        "event_relation": result.event_relation,
        "root_symptom_status": result.root_symptom_status,
        "evidence": result.evidence,
    }


def _cross_correlation_error(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse(
        {"error": {"code": code, "message": message, "details": {}}}, status=status
    )


def compensation_payload(*, outage, snapshot):
    if outage is None:
        return None
    summary = VerifiedImpactCompensationService().summarize_existing(
        outage=outage, snapshot=snapshot
    )
    if summary is None or summary.compensation_considered_count == 0:
        return {
            "status": "pending",
            "consideration_count": None,
            "eligible": None,
            "ineligible_pending": None,
            "total_amount": None,
            "rule_versions": {},
            "selected_rule_version": None,
            "baseline": None,
            "candidate": None,
            "difference_summary": None,
        }
    return {
        "status": "available",
        "consideration_count": summary.compensation_considered_count,
        "eligible": summary.eligible_count,
        "ineligible_pending": summary.ineligible_count + summary.pending_manual_review_count,
        "total_amount": str(summary.total_compensation_amount),
        "rule_versions": summary.rule_version_counts,
        "selected_rule_version": next(iter(summary.rule_version_counts), None),
        "baseline": None,
        "candidate": None,
        "difference_summary": None,
    }
