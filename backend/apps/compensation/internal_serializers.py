from __future__ import annotations

from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any

from apps.compensation.models import CompensationEvaluation, DecisionEvidence
from apps.compensation.services.calculation import (
    CompensationCalculationResult,
    PolicyAmountResult,
)
from apps.customers.models import CampaignEnrollment, Subscription
from apps.network.internal_serializers import iso_or_none, json_safe, snapshot_summary
from apps.operations.models import Outage
from apps.rules.internal_serializers import (
    decision_evidence_summary,
    rule_set_summary,
    version_summary,
)
from apps.rules.models import RuleVersion


def safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json_safe(payload)


def decimal_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def snapshot_payload(snapshot) -> dict[str, Any]:
    return snapshot_summary(snapshot)


def outage_summary(outage: Outage) -> dict[str, Any]:
    return {
        "outage_code": outage.outage_code,
        "incident_code": outage.incident.incident_number if outage.incident_id else None,
        "status": outage.status,
        "impact_class": outage.impact_type,
        "started_at": iso_or_none(outage.started_at),
        "ended_at": iso_or_none(outage.ended_at),
        "source_device_code": outage.source_device.code,
    }


def subscription_summary(subscription: Subscription) -> dict[str, Any]:
    return {
        "subscription_number": subscription.subscription_number,
        "customer_number": subscription.customer.customer_number,
        "status": subscription.status,
        "suspension_reason": subscription.suspension_reason,
        "service_type": subscription.service_package.service_type,
        "technology": subscription.service_package.technology,
        "package_code": subscription.service_package.package_code,
        "sla_profile": subscription.sla_profile.code if subscription.sla_profile_id else None,
        "contracted_monthly_price": decimal_or_none(subscription.monthly_price),
    }


def rule_version_selection_summary(version: RuleVersion | None) -> dict[str, Any] | None:
    return version_summary(version)


def compensation_result_summary(result: CompensationCalculationResult) -> dict[str, Any]:
    return {
        "decision": result.status,
        "reason_code": result.reason_code,
        "selected_rule": {
            "rule_code": result.rule_code,
            "version": result.rule_version,
        },
        "matched_conditions": result.matched_conditions,
        "failed_conditions": result.unmatched_conditions,
        "missing_fields": result.missing_fields,
        "deferred_checks": result.deferred_checks,
        "manual_review_reasons": (
            result.missing_fields if result.status == "manual_review" else []
        ),
        "price_basis": "contracted_monthly_price",
        "selected_price": decimal_or_none(result.monthly_price),
        "refund_rate": decimal_or_none(result.refund_rate),
        "final_amount": str(result.compensation_amount),
        "currency": result.currency,
        "calculation_trace": result.calculation_trace,
        "snapshot": result.snapshot,
    }


def policy_result_summary(result: PolicyAmountResult) -> dict[str, Any]:
    return {
        "decision": result.status,
        "reason_code": result.reason_code,
        "unrounded_amount": str(result.unrounded_amount),
        "final_amount": str(result.final_amount),
        "currency": result.currency,
        "calculation_trace": result.calculation_trace,
        "manual_review_reasons": result.manual_review_reasons,
    }


def evaluation_summary(evaluation: CompensationEvaluation | None) -> dict[str, Any] | None:
    if evaluation is None:
        return None
    return {
        "evaluation_code": evaluation.evaluation_code,
        "outage_code": evaluation.outage.outage_code,
        "incident_code": (
            evaluation.outage.incident.incident_number if evaluation.outage.incident_id else None
        ),
        "subscription_number": evaluation.subscription.subscription_number,
        "customer_number": evaluation.customer.customer_number,
        "rule_code": evaluation.rule_version.rule.code,
        "rule_version": evaluation.rule_version.version,
        "result_type": evaluation.result_type,
        "status": evaluation.status,
        "proposed_amount": str(evaluation.proposed_amount),
        "currency": evaluation.currency,
        "explanation": evaluation.explanation,
        "calculation_trace": evaluation.calculation_trace,
        "metadata": evaluation.metadata,
        "created_at": iso_or_none(evaluation.created_at),
    }


def evidence_summary(evidence: DecisionEvidence | None) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return decision_evidence_summary(evidence)


def campaign_enrollment_summary(
    enrollment: CampaignEnrollment,
    *,
    evaluation_time=None,
) -> dict[str, Any]:
    campaign = enrollment.campaign
    active_at_time = (
        enrollment.valid_from <= evaluation_time
        and (enrollment.valid_to is None or evaluation_time < enrollment.valid_to)
        if evaluation_time
        else None
    )
    return {
        "campaign_code": enrollment.campaign_code,
        "name": enrollment.name,
        "status": enrollment.status,
        "valid_from": iso_or_none(enrollment.valid_from),
        "valid_to": iso_or_none(enrollment.valid_to),
        "active_at_evaluation_time": active_at_time,
        "campaign": (
            {
                "code": campaign.code,
                "name": campaign.name,
                "status": campaign.status,
                "discount_type": campaign.discount_type,
                "discount_value": str(campaign.discount_value),
                "duration_months": campaign.duration_months,
                "valid_from": iso_or_none(campaign.valid_from),
                "valid_to": iso_or_none(campaign.valid_to),
                "stackable": campaign.stackable,
            }
            if campaign
            else None
        ),
    }


def dataclass_or_dict(value) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    return value or {}


def rule_set_payload(rule_set) -> dict[str, Any] | None:
    return rule_set_summary(rule_set)
