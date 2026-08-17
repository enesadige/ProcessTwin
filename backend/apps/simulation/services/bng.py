"""Canonical, simulation-local BNG failure execution.

This module consumes the existing read-only topology, impact, rule, and policy
calculation behaviour.  It never materializes operational records.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from apps.compensation.services.calculation import CompensationService
from apps.operations.contracts import CustomerImpactStatus, ImpactReason
from apps.operations.models import CausalEvent
from apps.operations.services.customer_impact_assessment import CustomerImpactAssessmentService
from apps.rules.services.evaluation import RuleEvaluationService
from apps.rules.services.version_selection import select_rule_version_for_moment
from apps.simulation.models import SimulationComparisonRole, SimulationRun, SimulationRunStatus
from apps.simulation.services.runtime import SimulationRuntimeError, SimulationService


class CanonicalBNGSimulationError(SimulationRuntimeError):
    """Raised for invalid canonical BNG scenario inputs."""


@dataclass(frozen=True)
class CanonicalBNGResult:
    source_snapshot: dict[str, Any]
    scenario: dict[str, Any]
    run: dict[str, Any]
    effective_input: dict[str, Any]
    event: dict[str, Any]
    impact: dict[str, Any]
    compensation: dict[str, Any]
    operational: dict[str, Any]

    def validate(self) -> None:
        if self.run["comparison_role"] not in SimulationComparisonRole.values:
            raise CanonicalBNGSimulationError("Invalid comparison role in canonical result.")
        for section, fields in {
            "impact": (
                "potential_subscription_scope",
                "verified_affected_subscriptions",
                "verified_affected_customers",
                "verified_protected_subscriptions",
                "unknown_or_insufficient_subscriptions",
            ),
            "compensation": ("eligible_subscription_count",),
        }.items():
            for field in fields:
                if self.__dict__[section][field] < 0:
                    raise CanonicalBNGSimulationError(
                        f"Canonical {section}.{field} cannot be negative."
                    )
        if Decimal(self.compensation["amount"]) < Decimal("0.00"):
            raise CanonicalBNGSimulationError("Canonical compensation.amount cannot be negative.")
        if (
            self.impact["verified_affected_subscriptions"]
            > self.impact["potential_subscription_scope"]
        ):
            raise CanonicalBNGSimulationError("Verified impact cannot exceed potential scope.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CanonicalBNGSimulationService:
    """Runs one deterministic BNG failure against a source snapshot read-only."""

    REQUIRED_DEFINITION = frozenset({"source_event_code"})

    def __init__(
        self,
        *,
        runtime: SimulationService | None = None,
        impact_service: CustomerImpactAssessmentService | None = None,
        rule_service: RuleEvaluationService | None = None,
        compensation_service: CompensationService | None = None,
    ) -> None:
        self.runtime = runtime or SimulationService()
        self.impact_service = impact_service or CustomerImpactAssessmentService()
        self.rule_service = rule_service or RuleEvaluationService()
        self.compensation_service = compensation_service or CompensationService(
            rule_evaluation_service=self.rule_service
        )

    def execute(self, simulation_run: SimulationRun) -> CanonicalBNGResult:
        run = self.runtime._load_run(simulation_run)
        if run.status not in {SimulationRunStatus.DRAFT, SimulationRunStatus.READY}:
            raise CanonicalBNGSimulationError("Canonical execution requires a draft or ready run.")
        if run.scenario.scenario_type != "bng_failure":
            raise CanonicalBNGSimulationError("Scenario must be a canonical bng_failure scenario.")
        definition = copy.deepcopy(run.scenario.definition)
        missing = self.REQUIRED_DEFINITION - definition.keys()
        if missing:
            raise CanonicalBNGSimulationError(
                f"Scenario definition is missing: {', '.join(sorted(missing))}."
            )
        inputs = self.runtime.effective_inputs(run)
        source_event = self._source_event(run, definition["source_event_code"])
        duration_seconds = self._duration_seconds(inputs, source_event)
        classification = inputs.get("outage_classification", "full_outage")
        if classification not in {"full_outage", "degradation"}:
            raise CanonicalBNGSimulationError(
                "outage_classification must be full_outage or degradation."
            )
        rule_code = inputs.get("rule_code")
        started_at = run.virtual_clock
        ended_at = started_at + timedelta(seconds=duration_seconds)

        run = self.runtime.start(run)
        self._record_chain(
            run, started_at, ended_at, duration_seconds, classification, source_event
        )
        impact = self._impact(source_event, run.source_snapshot)
        rule = self._select_rule(run, rule_code, started_at)
        compensation = self._compensation(
            source_event=source_event,
            snapshot=run.source_snapshot,
            impact=impact,
            rule=rule,
            event_datetime=started_at,
            duration_seconds=duration_seconds,
            classification=classification,
        )
        result = CanonicalBNGResult(
            source_snapshot={
                "id": run.source_snapshot_id,
                "snapshot_key": run.source_snapshot.snapshot_key,
            },
            scenario={"code": run.scenario.scenario_code, "type": run.scenario.scenario_type},
            run={
                "code": run.run_code,
                "comparison_role": run.comparison_role,
                "seed": run.deterministic_seed,
            },
            effective_input=inputs,
            event={
                "source_event_code": source_event.event_code,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "duration_seconds": duration_seconds,
                "classification": classification,
                "failover_classification": impact["failover_classification"],
                "selected_rule_version": rule,
            },
            impact=impact,
            compensation=compensation,
            operational={
                "sla_target_seconds": inputs.get("sla_target_seconds"),
                "sla_breached": (
                    duration_seconds > inputs["sla_target_seconds"]
                    if isinstance(inputs.get("sla_target_seconds"), int)
                    else None
                ),
            },
        )
        result.validate()
        context = copy.deepcopy(run.lifecycle_context)
        context["canonical_bng_result"] = result.to_dict()
        run.lifecycle_context = context
        run.save(update_fields=["lifecycle_context", "updated_at"])
        self.runtime.record_domain_event(
            run,
            event_type="simulation_result",
            occurred_at=ended_at,
            context={"contract": "canonical_bng_v1", "result": result.to_dict()},
        )
        self.runtime.complete(run, completed_at=ended_at)
        return result

    def compare(
        self, *, baseline_run: SimulationRun, candidate_run: SimulationRun
    ) -> dict[str, Any]:
        baseline = self._result_for(baseline_run)
        candidate = self._result_for(candidate_run)
        if candidate_run.baseline_run_id != baseline_run.id:
            raise CanonicalBNGSimulationError("Candidate must reference the supplied baseline run.")
        if baseline["source_snapshot"] != candidate["source_snapshot"]:
            raise CanonicalBNGSimulationError("Comparison crosses a snapshot boundary.")
        return {
            "baseline_run_code": baseline_run.run_code,
            "candidate_run_code": candidate_run.run_code,
            "affected_customer_delta": candidate["impact"]["verified_affected_customers"]
            - baseline["impact"]["verified_affected_customers"],
            "affected_subscription_delta": candidate["impact"]["verified_affected_subscriptions"]
            - baseline["impact"]["verified_affected_subscriptions"],
            "unknown_impact_delta": candidate["impact"]["unknown_or_insufficient_subscriptions"]
            - baseline["impact"]["unknown_or_insufficient_subscriptions"],
            "protected_subscription_delta": candidate["impact"]["verified_protected_subscriptions"]
            - baseline["impact"]["verified_protected_subscriptions"],
            "compensation_amount_delta": str(
                Decimal(candidate["compensation"]["amount"])
                - Decimal(baseline["compensation"]["amount"])
            ),
            "duration_seconds_delta": candidate["event"]["duration_seconds"]
            - baseline["event"]["duration_seconds"],
        }

    def _source_event(self, run: SimulationRun, event_code: str) -> CausalEvent:
        try:
            return CausalEvent.objects.select_related("root_device").get(
                data_snapshot=run.source_snapshot, event_code=event_code
            )
        except CausalEvent.DoesNotExist as exc:
            raise CanonicalBNGSimulationError(
                "Canonical source event is not in the source snapshot."
            ) from exc

    @staticmethod
    def _duration_seconds(inputs: dict[str, Any], source_event: CausalEvent) -> int:
        value = inputs.get("duration_seconds")
        if value is None and source_event.ended_at:
            value = int((source_event.ended_at - source_event.started_at).total_seconds())
        if not isinstance(value, int) or value <= 0:
            raise CanonicalBNGSimulationError("A positive duration_seconds value is required.")
        return value

    def _record_chain(
        self, run, started_at, ended_at, duration, classification, source_event
    ) -> None:
        chain = (
            ("bng_failure", started_at),
            ("alarm", started_at + timedelta(seconds=30)),
            ("incident", started_at + timedelta(seconds=60)),
            (
                "outage" if classification == "full_outage" else "degradation",
                started_at + timedelta(seconds=90),
            ),
            ("customer_impact", ended_at),
            ("compensation_evaluation", ended_at),
        )
        for event_type, occurred_at in chain:
            self.runtime.record_domain_event(
                run,
                event_type=event_type,
                occurred_at=occurred_at,
                context={
                    "simulation_local": True,
                    "source_event_code": source_event.event_code,
                    "duration_seconds": duration,
                },
            )

    def _impact(self, source_event, snapshot) -> dict[str, Any]:
        assessments = self.impact_service.evaluate_read_only(
            causal_event=source_event, snapshot=snapshot, evaluation_time=source_event.ended_at
        )
        potential_subscriptions = {item.subscription_id for item in assessments}
        impacted_subscriptions = {
            item.subscription_id
            for item in assessments
            if item.status == CustomerImpactStatus.VERIFIED_IMPACT.value
        }
        impacted_customers = {
            item.customer_id
            for item in assessments
            if item.status == CustomerImpactStatus.VERIFIED_IMPACT.value
        }
        protected_subscriptions = {
            item.subscription_id
            for item in assessments
            if item.status == CustomerImpactStatus.VERIFIED_NO_IMPACT.value
            and ImpactReason.FAILOVER_PROTECTED.value in item.reasons
        }
        unknown_subscriptions = {
            item.subscription_id
            for item in assessments
            if item.status
            in {
                CustomerImpactStatus.INSUFFICIENT_EVIDENCE.value,
                CustomerImpactStatus.POTENTIAL_IMPACT.value,
            }
        }
        return {
            "potential_subscription_scope": len(potential_subscriptions),
            "verified_affected_subscriptions": len(impacted_subscriptions),
            "verified_affected_customers": len(impacted_customers),
            "verified_protected_subscriptions": len(protected_subscriptions),
            "unknown_or_insufficient_subscriptions": len(unknown_subscriptions),
            "failover_classification": (
                "verified_protected" if protected_subscriptions else "not_verified"
            ),
            "affected_subscription_ids": sorted(impacted_subscriptions),
        }

    def _select_rule(self, run, rule_code, event_datetime) -> dict[str, Any] | None:
        if not rule_code:
            return None
        selected = select_rule_version_for_moment(
            snapshot=run.source_snapshot, rule_code=rule_code, moment=event_datetime
        )
        if selected.status != "selected" or selected.selected_version is None:
            return {"status": "manual_review", "rule_code": rule_code, "reason": selected.reason}
        version = selected.selected_version
        return {"status": "selected", "rule_code": rule_code, "version": version.version}

    def _compensation(
        self,
        *,
        source_event,
        snapshot,
        impact,
        rule,
        event_datetime,
        duration_seconds,
        classification,
    ) -> dict[str, Any]:
        if not rule or rule["status"] != "selected":
            return {
                "status": "manual_review",
                "eligibility": "unknown",
                "amount": "0.00",
                "currency": "TRY",
                "eligible_subscription_count": 0,
                "manual_review_reason": "no_single_rule_version",
            }
        selected = self.rule_service.evaluate(
            snapshot=snapshot,
            rule_code=rule["rule_code"],
            event_datetime=event_datetime,
            context={
                "outage_type": classification,
                "outage_duration_seconds": duration_seconds,
                "subscription_active_during_outage": True,
                "connection_active_during_outage": True,
            },
        )
        if selected.evaluation_status != "matched":
            return {
                "status": selected.evaluation_status,
                "eligibility": "not_eligible",
                "amount": "0.00",
                "currency": "TRY",
                "eligible_subscription_count": 0,
                "manual_review_reason": selected.errors or None,
            }
        version = select_rule_version_for_moment(
            snapshot=snapshot,
            rule_code=rule["rule_code"],
            moment=event_datetime,
        ).selected_version
        from apps.customers.models import Subscription

        total = Decimal("0.00")
        count = 0
        subscriptions = Subscription.objects.filter(
            id__in=impact["affected_subscription_ids"]
        ).order_by("id")
        for subscription in subscriptions:
            policy = self.compensation_service.calculate_policy_amount(
                action_type=version.action_type,
                action_config=version.action_config,
                price_basis_amount=subscription.monthly_price,
                context={"outage_duration_seconds": duration_seconds},
            )
            if policy.status == "eligible":
                count += 1
                total += policy.final_amount
        return {
            "status": "calculated",
            "eligibility": "eligible" if count else "not_eligible",
            "amount": str(total),
            "currency": "TRY",
            "eligible_subscription_count": count,
            "selected_rule_version": rule,
        }

    @staticmethod
    def _result_for(run: SimulationRun) -> dict[str, Any]:
        run.refresh_from_db()
        result = run.lifecycle_context.get("canonical_bng_result")
        if not isinstance(result, dict):
            raise CanonicalBNGSimulationError("Run has no canonical BNG result.")
        return result
