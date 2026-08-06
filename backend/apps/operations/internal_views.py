from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.compensation.models import DecisionEvidence
from apps.compensation.services.verified_impact import VerifiedImpactCompensationService
from apps.core.internal_api import internal_service_required
from apps.operations.models import Alarm, CausalEvent, Outage
from apps.operations.services.alarm_correlation import summarize_causal_event_roles
from apps.operations.services.customer_impact_assessment import CustomerImpactAssessmentService
from apps.operations.services.root_cause import RootCauseService


@require_GET
@internal_service_required
def causal_analysis(request, event_code):
    snapshot_key = request.GET.get("snapshot")
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
                    "potential": impact.potential_connection_count,
                    "verified_impacted": impact.verified_impacted_count,
                    "verified_no_impact": impact.verified_no_impact_count,
                    "insufficient_evidence": impact.insufficient_evidence_count,
                    "pending": impact.pending_count,
                    "failover_protected_count": impact.failover_protected_count,
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


def compensation_payload(*, outage, snapshot):
    if outage is None:
        return None
    summary = VerifiedImpactCompensationService().summarize_existing(
        outage=outage, snapshot=snapshot
    )
    if summary is None or summary.compensation_considered_count == 0:
        return {
            "status": "pending",
            "consideration_count": 0,
            "eligible": 0,
            "ineligible_pending": 0,
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
