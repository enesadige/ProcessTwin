"""Bind verified connection impact to existing deterministic compensation services."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from apps.compensation.models import (
    CompensationEvaluation,
    CompensationResultType,
    DecisionEvidenceDecision,
)
from apps.compensation.services.calculation import (
    CompensationService,
    build_decision_evidence_hash,
)
from apps.operations.contracts import CustomerImpactStatus
from apps.operations.models import CustomerImpactAssessment, Outage
from apps.rules.models import RuleVersion


@dataclass(frozen=True)
class VerifiedImpactCompensationSummary:
    potential_count: int
    verified_impacted_count: int
    verified_no_impact_count: int
    insufficient_evidence_count: int
    compensation_considered_count: int
    eligible_count: int
    ineligible_count: int
    pending_manual_review_count: int
    total_compensation_amount: Decimal
    rule_version_counts: dict[str, int]


class _VerifiedAssessmentImpactService:
    """Narrow adapter; existing amount/rule logic remains in CompensationService."""

    def __init__(self, assessments):
        self.assessments = assessments

    def calculate_impact(self, *, outage, snapshot, evaluation_time=None):
        codes = sorted(
            {
                assessment.subscription_connection.subscription.subscription_number
                for assessment in self.assessments
            }
        )
        return type("VerifiedImpactScope", (), {"affected_subscription_codes": codes})()


class VerifiedImpactCompensationService:
    """Evaluate only verified impact; other statuses remain non-compensable evidence."""

    def evaluate_outage(
        self, *, outage: Outage, snapshot, evaluation_time=None, rule_code="REFUND-001"
    ):
        if outage.causal_event_id is None:
            raise ValueError("Outage must have a CausalEvent for verified-impact evaluation.")
        assessments = list(
            CustomerImpactAssessment.objects.filter(
                data_snapshot=snapshot,
                causal_event=outage.causal_event,
                subscription_connection__isnull=False,
            ).select_related("subscription_connection__subscription__customer")
        )
        verified = [
            item
            for item in assessments
            if item.status == CustomerImpactStatus.VERIFIED_IMPACT.value
        ]
        compensation_service = CompensationService(
            impact_service=_VerifiedAssessmentImpactService(verified)
        )
        results = []
        seen_subscriptions = set()
        for assessment in sorted(
            verified,
            key=lambda item: item.subscription_connection.subscription.subscription_number,
        ):
            subscription = assessment.subscription_connection.subscription
            if subscription.id in seen_subscriptions:
                continue
            seen_subscriptions.add(subscription.id)
            results.append(
                compensation_service.evaluate_subscription(
                    outage=outage,
                    subscription=subscription,
                    snapshot=snapshot,
                    evaluation_time=evaluation_time,
                    rule_code=rule_code,
                )
            )
        evidence = self._get_or_create_evidence(
            compensation_service=compensation_service,
            outage=outage,
            snapshot=snapshot,
            assessments=assessments,
            results=results,
        )
        return results, evidence, self._summarize(assessments=assessments, results=results)

    def summarize_existing(self, *, outage: Outage, snapshot):
        """Read-only aggregate for API consumers; it never evaluates or persists."""
        if outage.causal_event_id is None:
            return None
        assessments = list(
            CustomerImpactAssessment.objects.filter(
                data_snapshot=snapshot,
                causal_event=outage.causal_event,
                subscription_connection__isnull=False,
            )
        )
        verified_subscription_ids = {
            assessment.subscription_id
            for assessment in assessments
            if assessment.status == CustomerImpactStatus.VERIFIED_IMPACT.value
        }
        evaluations = list(
            CompensationEvaluation.objects.filter(
                data_snapshot=snapshot,
                outage=outage,
                metadata__ground_truth_operational=True,
            ).select_related("rule_version__rule")
        )
        # Canonical synthetic scenarios carry one explicit event-anchored
        # decision context.  Prefer it over broad historical records, which
        # may legitimately contain several rules for the same outage but are
        # not the selected decision for that outage.
        if not evaluations:
            evaluations = list(
                CompensationEvaluation.objects.filter(
                    data_snapshot=snapshot,
                    outage=outage,
                    subscription_id__in=verified_subscription_ids,
                ).select_related("rule_version__rule")
            )
        return self._summarize_existing_evaluations(
            assessments=assessments, evaluations=evaluations
        )

    def _summarize_existing_evaluations(self, *, assessments, evaluations):
        statuses = Counter(item.status for item in assessments)
        rule_versions = Counter(
            f"{item.rule_version.rule.code}:v{item.rule_version.version}" for item in evaluations
        )
        return VerifiedImpactCompensationSummary(
            potential_count=statuses[CustomerImpactStatus.POTENTIAL_IMPACT.value],
            verified_impacted_count=statuses[CustomerImpactStatus.VERIFIED_IMPACT.value],
            verified_no_impact_count=statuses[CustomerImpactStatus.VERIFIED_NO_IMPACT.value],
            insufficient_evidence_count=statuses[CustomerImpactStatus.INSUFFICIENT_EVIDENCE.value],
            compensation_considered_count=len(evaluations),
            eligible_count=sum(
                item.result_type == CompensationResultType.ELIGIBLE for item in evaluations
            ),
            ineligible_count=sum(
                item.result_type == CompensationResultType.NOT_ELIGIBLE for item in evaluations
            ),
            pending_manual_review_count=sum(
                item.result_type
                in {
                    CompensationResultType.MANUAL_REVIEW,
                    CompensationResultType.INSUFFICIENT_DATA,
                }
                for item in evaluations
            ),
            total_compensation_amount=sum(
                (item.proposed_amount for item in evaluations), Decimal("0.00")
            ),
            rule_version_counts=dict(sorted(rule_versions.items())),
        )

    def _get_or_create_evidence(
        self, *, compensation_service, outage, snapshot, assessments, results
    ):
        status_counts = Counter(item.status for item in assessments)
        reason_codes = sorted({reason for item in assessments for reason in item.reasons})
        context = {
            "causal_event_code": outage.causal_event.event_code,
            "outage_code": outage.outage_code,
            "impact_counts": dict(sorted(status_counts.items())),
            "impact_reason_codes": reason_codes,
            "deterministic_provenance": "services_only_no_model_or_prompt",
        }
        decision = (
            DecisionEvidenceDecision.ELIGIBLE
            if any(result.status == "eligible" for result in results)
            else DecisionEvidenceDecision.EVIDENCE_ONLY
        )
        amount = sum((result.compensation_amount for result in results), Decimal("0.00"))
        payload = {
            "decision": decision,
            "final_amount": str(amount),
            "context_snapshot": context,
            "rule_versions": sorted(
                f"{result.rule_code}:v{result.rule_version}"
                for result in results
                if result.rule_version
            ),
        }
        evidence_hash = build_decision_evidence_hash(payload)
        existing = snapshot.decision_evidence_records.filter(evidence_hash=evidence_hash).first()
        if existing is not None:
            return existing
        selected = None
        if results and results[0].rule_version is not None:
            selected = RuleVersion.objects.filter(
                data_snapshot=snapshot,
                rule__code=results[0].rule_code,
                version=results[0].rule_version,
            ).first()
        return compensation_service.create_decision_evidence(
            data_snapshot=snapshot,
            selected_rule_version=selected,
            final_amount=amount,
            decision=decision,
            context_snapshot=context,
            manual_review_reasons=sorted(
                {result.reason_code for result in results if result.status != "eligible"}
            ),
        )

    def _summarize(self, *, assessments, results):
        statuses = Counter(item.status for item in assessments)
        rule_versions = Counter(
            f"{result.rule_code}:v{result.rule_version}"
            for result in results
            if result.rule_version is not None
        )
        return VerifiedImpactCompensationSummary(
            potential_count=statuses[CustomerImpactStatus.POTENTIAL_IMPACT.value],
            verified_impacted_count=statuses[CustomerImpactStatus.VERIFIED_IMPACT.value],
            verified_no_impact_count=statuses[CustomerImpactStatus.VERIFIED_NO_IMPACT.value],
            insufficient_evidence_count=statuses[CustomerImpactStatus.INSUFFICIENT_EVIDENCE.value],
            compensation_considered_count=len(results),
            eligible_count=sum(result.status == "eligible" for result in results),
            ineligible_count=sum(result.status == "ineligible" for result in results),
            pending_manual_review_count=sum(result.status != "eligible" for result in results),
            total_compensation_amount=sum(
                (result.compensation_amount for result in results), Decimal("0.00")
            ),
            rule_version_counts=dict(sorted(rule_versions.items())),
        )
