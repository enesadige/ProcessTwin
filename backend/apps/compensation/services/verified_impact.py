"""Bind verified connection impact to existing deterministic compensation services."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q

from apps.compensation.models import (
    CompensationEvaluation,
    CompensationEvaluationStatus,
    CompensationResultType,
    DecisionEvidenceDecision,
)
from apps.compensation.services.calculation import (
    CompensationCalculationResult,
    CompensationService,
    build_decision_evidence_hash,
)
from apps.operations.contracts import CustomerImpactStatus
from apps.operations.models import CustomerImpactAssessment, Outage
from apps.rules.models import RuleSet, RuleVersion


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
            ).select_related(
                "subscription_connection__subscription__customer",
                "subscription_connection__subscription__service_package",
            )
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
        for subscription in self._verified_subscriptions(verified, seen_subscriptions):
            results.append(
                self._evaluate_subscription(
                    compensation_service=compensation_service,
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

    def materialize_outage(
        self, *, outage: Outage, snapshot, evaluation_time=None, rule_code="REFUND-001"
    ):
        """Persist deterministic results for one outage without deriving impact again.

        ``evaluate_outage`` remains the authoritative rule/amount calculation path.
        This method only materializes its returned results under the existing
        snapshot-local uniqueness constraints, then attaches one finalized
        DecisionEvidence row to each persisted evaluation.
        """
        if outage.causal_event_id is None:
            raise ValueError("Outage must have a CausalEvent for verified-impact evaluation.")
        assessments = list(
            CustomerImpactAssessment.objects.filter(
                data_snapshot=snapshot,
                causal_event=outage.causal_event,
                subscription_connection__isnull=False,
            ).select_related(
                "subscription_connection__subscription__customer",
                "subscription_connection__subscription__service_package",
            )
        )
        verified = [
            item
            for item in assessments
            if item.status == CustomerImpactStatus.VERIFIED_IMPACT.value
        ]
        compensation_service = CompensationService(
            impact_service=_VerifiedAssessmentImpactService(verified)
        )
        evaluated: list[tuple[object, object]] = []
        seen_subscriptions = set()
        for subscription in self._verified_subscriptions(verified, seen_subscriptions):
            result = self._evaluate_subscription(
                compensation_service=compensation_service,
                outage=outage,
                subscription=subscription,
                snapshot=snapshot,
                evaluation_time=evaluation_time,
                rule_code=rule_code,
            )
            evaluated.append((subscription, result))

        # Preserve the existing outage-level evidence contract while adding
        # per-evaluation evidence required by CompensationEvaluation consumers.
        aggregate_evidence = self._get_or_create_evidence(
            compensation_service=compensation_service,
            outage=outage,
            snapshot=snapshot,
            assessments=assessments,
            results=[result for _, result in evaluated],
        )
        persisted, created, reused, skipped_unselected = self._persist_results(
            compensation_service=compensation_service,
            outage=outage,
            snapshot=snapshot,
            evaluated=evaluated,
        )
        return {
            "evaluations": persisted,
            "created": created,
            "reused": reused,
            "skipped_unselected": skipped_unselected,
            "aggregate_evidence": aggregate_evidence,
            "summary": self._summarize(
                assessments=assessments,
                results=[result for _, result in evaluated],
            ),
        }

    @staticmethod
    def _verified_subscriptions(verified, seen_subscriptions):
        for assessment in sorted(
            verified,
            key=lambda item: item.subscription_connection.subscription.subscription_number,
        ):
            subscription = assessment.subscription_connection.subscription
            if subscription.id in seen_subscriptions:
                continue
            seen_subscriptions.add(subscription.id)
            yield subscription

    def _evaluate_subscription(
        self,
        *,
        compensation_service,
        outage,
        subscription,
        snapshot,
        evaluation_time,
        rule_code,
    ):
        """Use the snapshot's active policy set when one governs this outage.

        Legacy snapshots retain the original REFUND-001 calculation path.  A
        policy dataset must use the already-authoritative rule-set selection,
        otherwise a synthetic legacy rule code would make every result look
        unselected and no snapshot-local evaluation could be persisted.
        """
        moment = evaluation_time or outage.started_at
        rule_set = (
            RuleSet.objects.filter(
                data_snapshot=snapshot,
                active=True,
                effective_from__lte=moment,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=moment))
            .order_by("code", "-version")
            .first()
        )
        if rule_set is None:
            return compensation_service.evaluate_subscription(
                outage=outage,
                subscription=subscription,
                snapshot=snapshot,
                evaluation_time=evaluation_time,
                rule_code=rule_code,
            )

        duration = compensation_service.outage_service.calculate_duration(
            outage=outage,
            evaluation_time=evaluation_time,
        )
        context = {
            "service_type": subscription.service_package.service_type,
            "impact_class": outage.impact_type,
            "outage_duration_seconds": duration.seconds,
            "affected_duration_seconds": duration.seconds,
            "subscription_active_during_outage": True,
            "connection_active_during_outage": True,
            "customer_impacted": True,
            "price_available": subscription.monthly_price is not None,
            "root_cause_known": outage.root_cause_category != "unknown",
            "subscription_status": subscription.status,
            "suspension_reason": subscription.suspension_reason,
            "protection_loss_only": outage.impact_type == "protection_loss",
            "incident_type": outage.incident.incident_type if outage.incident_id else "",
            "maintenance_overrun_minutes": 0,
        }
        policy = compensation_service.rule_evaluation_service.evaluate_rule_set(
            snapshot=snapshot,
            rule_set_code=rule_set.code,
            event_datetime=moment,
            context=context,
        )
        selected = policy.selected_base_rule
        if selected is None:
            return CompensationCalculationResult(
                outage_code=outage.outage_code,
                subscription_code=subscription.subscription_number,
                customer_code=subscription.customer.customer_number,
                status=(
                    "manual_review"
                    if policy.evaluation_status == "manual_review"
                    else "ineligible"
                ),
                reason_code=(
                    policy.manual_review_reasons[0]
                    if policy.manual_review_reasons
                    else "no_policy_rule_matched"
                ),
                rule_code=rule_set.code,
                rule_version=None,
                monthly_price=subscription.monthly_price,
                refund_rate=None,
                compensation_amount=Decimal("0.00"),
                currency="TRY",
                matched_conditions=[],
                unmatched_conditions=[],
                missing_fields=policy.manual_review_reasons,
                deferred_checks=[],
                calculation_trace=[{"step": "policy_rule_set", "status": policy.evaluation_status}],
                snapshot=compensation_service._snapshot_dict(snapshot),
            )
        amount = compensation_service.calculate_policy_amount(
            action_type=selected.action_type,
            action_config=selected.action_config,
            price_basis_amount=subscription.monthly_price,
            context=context,
        )
        return CompensationCalculationResult(
            outage_code=outage.outage_code,
            subscription_code=subscription.subscription_number,
            customer_code=subscription.customer.customer_number,
            status=amount.status,
            reason_code=amount.reason_code,
            rule_code=selected.rule_code,
            rule_version=selected.rule_version,
            monthly_price=subscription.monthly_price,
            refund_rate=None,
            compensation_amount=amount.final_amount,
            currency=amount.currency,
            matched_conditions=selected.matched_conditions,
            unmatched_conditions=selected.unmatched_conditions,
            missing_fields=amount.manual_review_reasons,
            deferred_checks=[],
            calculation_trace=amount.calculation_trace,
            snapshot=compensation_service._snapshot_dict(snapshot),
        )

    def _persist_results(self, *, compensation_service, outage, snapshot, evaluated):
        persisted = []
        created = 0
        reused = 0
        skipped_unselected = 0
        for subscription, result in evaluated:
            if result.rule_version is None:
                # The model contract forbids a made-up RuleVersion.  The
                # aggregate evidence still records this unselected outcome.
                skipped_unselected += 1
                continue
            version = (
                RuleVersion.objects.filter(
                    data_snapshot=snapshot,
                    rule__code=result.rule_code,
                    version=result.rule_version,
                )
                .select_related("rule__rule_set")
                .first()
            )
            if version is None:
                raise ValueError(
                    "A deterministic compensation result requires a local RuleVersion."
                )
            evaluation_code = self._evaluation_code(
                snapshot=snapshot,
                outage=outage,
                subscription=subscription,
                version=version,
            )
            evaluation, was_created = CompensationEvaluation.objects.get_or_create(
                data_snapshot=snapshot,
                evaluation_code=evaluation_code,
                defaults={
                    "outage": outage,
                    "customer": subscription.customer,
                    "subscription": subscription,
                    "rule_version": version,
                    "result_type": self._result_type(result.status),
                    "status": CompensationEvaluationStatus.CALCULATED,
                    "proposed_amount": result.compensation_amount,
                    "currency": result.currency,
                    "explanation": result.reason_code,
                    "calculation_trace": {
                        "calculation_trace": result.calculation_trace,
                        "matched_conditions": result.matched_conditions,
                        "unmatched_conditions": result.unmatched_conditions,
                        "missing_fields": result.missing_fields,
                    },
                    "metadata": {
                        "source": "verified_impact_materialization",
                        "conflict_group": version.rule.conflict_group,
                    },
                },
            )
            if not was_created and (
                evaluation.outage_id != outage.id
                or evaluation.subscription_id != subscription.id
                or evaluation.rule_version_id != version.id
            ):
                raise ValueError("Compensation evaluation idempotency key resolved incompatibly.")
            created += int(was_created)
            reused += int(not was_created)
            self._get_or_create_evaluation_evidence(
                compensation_service=compensation_service,
                snapshot=snapshot,
                evaluation=evaluation,
                result=result,
                version=version,
            )
            persisted.append(evaluation)
        return persisted, created, reused, skipped_unselected

    @staticmethod
    def _result_type(status):
        if status == "eligible":
            return CompensationResultType.ELIGIBLE
        if status == "ineligible":
            return CompensationResultType.NOT_ELIGIBLE
        if status == "manual_review":
            return CompensationResultType.MANUAL_REVIEW
        return CompensationResultType.INSUFFICIENT_DATA

    @staticmethod
    def _evidence_decision(status):
        if status in {"eligible", "ineligible", "manual_review"}:
            return status
        return DecisionEvidenceDecision.EVIDENCE_ONLY

    @staticmethod
    def _evaluation_code(*, snapshot, outage, subscription, version):
        payload = {
            "snapshot": snapshot.snapshot_key,
            "outage": outage.outage_code,
            "subscription": subscription.subscription_number,
            "rule": version.rule.code,
            "version": version.version,
        }
        return f"CE-{build_decision_evidence_hash(payload)[:24].upper()}"

    def _get_or_create_evaluation_evidence(
        self, *, compensation_service, snapshot, evaluation, result, version
    ):
        payload = {
            "rule_set": str(version.rule.rule_set) if version.rule.rule_set_id else None,
            "selected_rule_version": f"{version.rule.code}:v{version.version}",
            "price_basis": "contracted_monthly_price",
            "selected_price": str(result.monthly_price)
            if result.monthly_price is not None
            else None,
            "unrounded_amount": str(result.compensation_amount),
            "final_amount": str(result.compensation_amount),
            "currency": result.currency,
            "decision": self._evidence_decision(result.status),
            "matched_conditions": result.matched_conditions,
            "failed_conditions": result.unmatched_conditions,
            "excluded_rules": [],
            "candidate_base_rules": [],
            "applied_modifiers": [],
            "formula_inputs": {
                "refund_rate": str(result.refund_rate) if result.refund_rate is not None else None,
                "monthly_price": (
                    str(result.monthly_price) if result.monthly_price is not None else None
                ),
            },
            "cap_floor_trace": [],
            "manual_review_reasons": result.missing_fields
            if result.status == "manual_review"
            else [],
            "context_snapshot": {
                "outage_code": result.outage_code,
                "subscription_code": result.subscription_code,
                "reason_code": result.reason_code,
                "calculation_trace": result.calculation_trace,
            },
        }
        evidence_hash = build_decision_evidence_hash(payload)
        existing = snapshot.decision_evidence_records.filter(evidence_hash=evidence_hash).first()
        if existing is not None:
            if existing.compensation_evaluation_id != evaluation.id:
                raise ValueError(
                    "Decision evidence hash resolved to another compensation evaluation."
                )
            return existing
        return compensation_service.create_decision_evidence(
            data_snapshot=snapshot,
            compensation_evaluation=evaluation,
            rule_set=version.rule.rule_set if version.rule.rule_set_id else None,
            selected_rule_version=version,
            price_basis="contracted_monthly_price",
            selected_price=result.monthly_price,
            unrounded_amount=result.compensation_amount,
            final_amount=result.compensation_amount,
            currency=result.currency,
            decision=self._evidence_decision(result.status),
            matched_conditions=result.matched_conditions,
            failed_conditions=result.unmatched_conditions,
            formula_inputs=payload["formula_inputs"],
            manual_review_reasons=payload["manual_review_reasons"],
            context_snapshot=payload["context_snapshot"],
        )

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
