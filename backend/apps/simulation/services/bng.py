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
from apps.network.models import LineConnection, NetworkDevice, NetworkDeviceType, NetworkLink
from apps.operations.contracts import CustomerImpactStatus, ImpactReason
from apps.operations.models import CausalEvent
from apps.operations.services.customer_impact_assessment import CustomerImpactAssessmentService
from apps.rules.services.evaluation import RuleEvaluationService
from apps.rules.services.version_selection import select_rule_version_for_moment
from apps.simulation.models import SimulationComparisonRole, SimulationRun, SimulationRunStatus
from apps.simulation.services.evidence import SimulationEvidenceService
from apps.simulation.services.runtime import SimulationRuntimeError, SimulationService


class CanonicalFailureSimulationError(SimulationRuntimeError):
    """Raised for invalid generic failure scenario inputs."""


@dataclass(frozen=True)
class CanonicalFailureResult:
    source_snapshot: dict[str, Any]
    scenario: dict[str, Any]
    run: dict[str, Any]
    effective_input: dict[str, Any]
    event: dict[str, Any]
    projection: dict[str, Any]
    historical_evidence: dict[str, Any]
    compensation: dict[str, Any]
    operational: dict[str, Any]

    def validate(self) -> None:
        if self.run["comparison_role"] not in SimulationComparisonRole.values:
            raise CanonicalFailureSimulationError("Invalid comparison role in canonical result.")
        for section, fields in {
            "projection": (
                "potential_subscription_scope",
                "potential_customer_scope",
                "projected_affected_subscriptions",
                "projected_affected_customers",
                "projected_protected_no_impact_subscriptions",
                "projected_unknown_subscriptions",
            ),
            "compensation": ("eligible_subscription_count",),
        }.items():
            for field in fields:
                if self.__dict__[section][field] < 0:
                    raise CanonicalFailureSimulationError(
                        f"Canonical {section}.{field} cannot be negative."
                    )
        if Decimal(self.compensation["amount"]) < Decimal("0.00"):
            raise CanonicalFailureSimulationError(
                "Canonical compensation.amount cannot be negative."
            )
        if (
            self.projection["projected_affected_subscriptions"]
            > self.projection["potential_subscription_scope"]
        ):
            raise CanonicalFailureSimulationError("Projected impact cannot exceed potential scope.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CanonicalFailureSimulationService:
    """Runs one deterministic, simulation-local failure against a source snapshot."""

    SOURCE_EVENT_KEY = "source_event_code"
    SOURCE_DEVICE_KEY = "source_device_code"
    ANCHOR_TYPE_KEY = "anchor_type"
    ANCHOR_CODE_KEY = "anchor_code"
    FAILURE_TYPE_KEY = "failure_type"
    SUPPORTED_ANCHOR_TYPES = {"network_device", "network_link", "line_connection"}
    SUPPORTED_DEVICE_TYPES = {
        NetworkDeviceType.BNG,
        NetworkDeviceType.OLT,
        NetworkDeviceType.METRO_AGGREGATION,
        NetworkDeviceType.ACCESS_NODE,
    }

    def __init__(
        self,
        *,
        runtime: SimulationService | None = None,
        impact_service: CustomerImpactAssessmentService | None = None,
        rule_service: RuleEvaluationService | None = None,
        compensation_service: CompensationService | None = None,
        evidence_service: SimulationEvidenceService | None = None,
    ) -> None:
        self.runtime = runtime or SimulationService()
        self.impact_service = impact_service or CustomerImpactAssessmentService()
        self.rule_service = rule_service or RuleEvaluationService()
        self.compensation_service = compensation_service or CompensationService(
            rule_evaluation_service=self.rule_service
        )
        self.evidence_service = evidence_service or SimulationEvidenceService()

    def execute(self, simulation_run: SimulationRun) -> CanonicalFailureResult:
        run = self.runtime._load_run(simulation_run)
        if run.status not in {SimulationRunStatus.DRAFT, SimulationRunStatus.READY}:
            raise CanonicalFailureSimulationError(
                "Canonical execution requires a draft or ready run."
            )
        if run.scenario.scenario_type not in {
            "bng_failure",
            "network_device_failure",
            "network_link_failure",
            "line_connection_failure",
        }:
            raise CanonicalFailureSimulationError(
                "Scenario must be a supported canonical failure scenario."
            )
        definition = copy.deepcopy(run.scenario.definition)
        inputs = self.runtime.effective_inputs(run)
        source_event, anchor_type, anchor = self._resolve_anchor(run, definition)
        duration_seconds = self._duration_seconds(inputs, source_event)
        classification = inputs.get("outage_classification", "full_outage")
        if classification not in {"full_outage", "degradation"}:
            raise CanonicalFailureSimulationError(
                "outage_classification must be full_outage or degradation."
            )
        rule_code = inputs.get("rule_code")
        started_at = run.virtual_clock
        ended_at = started_at + timedelta(seconds=duration_seconds)

        run = self.runtime.start(run)
        self._record_chain(
            run,
            started_at,
            ended_at,
            duration_seconds,
            classification,
            source_event=source_event,
            anchor_type=anchor_type,
            anchor=anchor,
        )
        projection = self._projection(
            source_event=source_event,
            anchor_type=anchor_type,
            anchor=anchor,
            snapshot=run.source_snapshot,
            window_start=started_at,
            window_end=ended_at,
        )
        historical_evidence = self._historical_evidence(source_event, run.source_snapshot)
        rule = self._select_rule(run, rule_code, started_at)
        compensation = self._compensation(
            snapshot=run.source_snapshot,
            projection=projection,
            rule=rule,
            event_datetime=started_at,
            duration_seconds=duration_seconds,
            classification=classification,
        )
        result = CanonicalFailureResult(
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
                "source_event_code": source_event.event_code if source_event else None,
                "anchor_type": anchor_type,
                "anchor_code": self._anchor_code(anchor),
                "source_device_code": anchor.code if anchor_type == "network_device" else None,
                "failure_type": inputs.get(self.FAILURE_TYPE_KEY, f"{anchor_type}_failure"),
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "duration_seconds": duration_seconds,
                "classification": classification,
                "failover_classification": projection["failover_classification"],
                "selected_rule_version": rule,
            },
            projection=projection,
            historical_evidence=historical_evidence,
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
        context["canonical_failure_result"] = result.to_dict()
        # Kept for the existing BNG caller contract during the transition.
        context["canonical_bng_result"] = result.to_dict()
        run.lifecycle_context = context
        run.save(update_fields=["lifecycle_context", "updated_at"])
        self.runtime.record_domain_event(
            run,
            event_type="simulation_result",
            occurred_at=ended_at,
            context={"contract": "canonical_failure_projection_v1", "result": result.to_dict()},
        )
        completed_run = self.runtime.complete(run, completed_at=ended_at)
        self.evidence_service.materialize(completed_run)
        return result

    def compare(
        self, *, baseline_run: SimulationRun, candidate_run: SimulationRun
    ) -> dict[str, Any]:
        baseline = self._result_for(baseline_run)
        candidate = self._result_for(candidate_run)
        if candidate_run.baseline_run_id != baseline_run.id:
            raise CanonicalFailureSimulationError(
                "Candidate must reference the supplied baseline run."
            )
        if baseline["source_snapshot"] != candidate["source_snapshot"]:
            raise CanonicalFailureSimulationError("Comparison crosses a snapshot boundary.")
        baseline_sla_target = baseline["operational"].get("sla_target_seconds")
        candidate_sla_target = candidate["operational"].get("sla_target_seconds")
        return {
            "baseline_run_code": baseline_run.run_code,
            "candidate_run_code": candidate_run.run_code,
            "projected_affected_customer_delta": candidate["projection"][
                "projected_affected_customers"
            ]
            - baseline["projection"]["projected_affected_customers"],
            "projected_affected_subscription_delta": candidate["projection"][
                "projected_affected_subscriptions"
            ]
            - baseline["projection"]["projected_affected_subscriptions"],
            "projected_unknown_delta": candidate["projection"]["projected_unknown_subscriptions"]
            - baseline["projection"]["projected_unknown_subscriptions"],
            "projected_protected_no_impact_delta": candidate["projection"][
                "projected_protected_no_impact_subscriptions"
            ]
            - baseline["projection"]["projected_protected_no_impact_subscriptions"],
            "compensation_amount_delta": str(
                Decimal(candidate["compensation"]["amount"])
                - Decimal(baseline["compensation"]["amount"])
            ),
            "duration_seconds_delta": candidate["event"]["duration_seconds"]
            - baseline["event"]["duration_seconds"],
            "sla_target_seconds_delta": (
                candidate_sla_target - baseline_sla_target
                if isinstance(baseline_sla_target, int) and isinstance(candidate_sla_target, int)
                else None
            ),
            "sla_breached": {
                "baseline": baseline["operational"].get("sla_breached"),
                "candidate": candidate["operational"].get("sla_breached"),
                "changed": baseline["operational"].get("sla_breached")
                != candidate["operational"].get("sla_breached"),
            },
        }

    def _source_event(self, run: SimulationRun, event_code: str) -> CausalEvent:
        try:
            return CausalEvent.objects.select_related(
                "root_device", "root_network_link", "root_line_connection"
            ).get(data_snapshot=run.source_snapshot, event_code=event_code)
        except CausalEvent.DoesNotExist as exc:
            raise CanonicalFailureSimulationError(
                "Canonical source event is not in the source snapshot."
            ) from exc

    def _resolve_anchor(self, run, definition):
        source_event = None
        if definition.get(self.SOURCE_EVENT_KEY):
            if any(
                definition.get(key)
                for key in (self.SOURCE_DEVICE_KEY, self.ANCHOR_TYPE_KEY, self.ANCHOR_CODE_KEY)
            ):
                raise CanonicalFailureSimulationError(
                    "Source event and explicit anchor cannot be combined."
                )
            source_event = self._source_event(run, definition[self.SOURCE_EVENT_KEY])
            for anchor_type, field in (
                ("network_device", "root_device"),
                ("network_link", "root_network_link"),
                ("line_connection", "root_line_connection"),
            ):
                anchor = getattr(source_event, field)
                if anchor is not None:
                    return source_event, anchor_type, anchor
            raise CanonicalFailureSimulationError(
                "Source event has no supported simulation anchor."
            )
        if definition.get(self.SOURCE_DEVICE_KEY):
            if definition.get(self.ANCHOR_TYPE_KEY) or definition.get(self.ANCHOR_CODE_KEY):
                raise CanonicalFailureSimulationError(
                    "Legacy source device and generic anchor cannot be combined."
                )
            return (
                None,
                "network_device",
                self._source_device(run, definition[self.SOURCE_DEVICE_KEY]),
            )
        anchor_type = definition.get(self.ANCHOR_TYPE_KEY)
        anchor_code = definition.get(self.ANCHOR_CODE_KEY)
        if (
            anchor_type not in self.SUPPORTED_ANCHOR_TYPES
            or not isinstance(anchor_code, str)
            or not anchor_code
        ):
            raise CanonicalFailureSimulationError(
                "Scenario requires a source event, source device, or supported "
                "anchor_type/anchor_code."
            )
        return None, anchor_type, self._anchor_by_code(run, anchor_type, anchor_code)

    def _source_device(self, run: SimulationRun, device_code: str) -> NetworkDevice:
        try:
            device = NetworkDevice.objects.get(
                data_snapshot=run.source_snapshot,
                code=device_code,
            )
            if device.device_type not in self.SUPPORTED_DEVICE_TYPES:
                raise NetworkDevice.DoesNotExist
            return device
        except NetworkDevice.DoesNotExist as exc:
            raise CanonicalFailureSimulationError(
                "Canonical source network device is unsupported or not in the source snapshot."
            ) from exc

    def _anchor_by_code(self, run, anchor_type: str, anchor_code: str):
        lookup = {
            "network_device": (NetworkDevice, "code"),
            "network_link": (NetworkLink, "link_code"),
            "line_connection": (LineConnection, "line_code"),
        }[anchor_type]
        model, code_field = lookup
        try:
            anchor = model.objects.select_related(
                *("target_device",) if anchor_type == "network_link" else ()
            ).get(data_snapshot=run.source_snapshot, **{code_field: anchor_code})
        except model.DoesNotExist as exc:
            raise CanonicalFailureSimulationError(
                "Canonical anchor is not in the source snapshot."
            ) from exc
        if (
            anchor_type == "network_device"
            and anchor.device_type not in self.SUPPORTED_DEVICE_TYPES
        ):
            raise CanonicalFailureSimulationError(
                "Network device type is not supported by the canonical runtime."
            )
        return anchor

    @staticmethod
    def _anchor_code(anchor) -> str:
        return (
            getattr(anchor, "code", None) or getattr(anchor, "link_code", None) or anchor.line_code
        )

    @staticmethod
    def _duration_seconds(inputs: dict[str, Any], source_event: CausalEvent | None) -> int:
        value = inputs.get("duration_seconds")
        if value is None and source_event and source_event.ended_at:
            value = int((source_event.ended_at - source_event.started_at).total_seconds())
        if not isinstance(value, int) or value <= 0:
            raise CanonicalFailureSimulationError("A positive duration_seconds value is required.")
        return value

    def _record_chain(
        self,
        run,
        started_at,
        ended_at,
        duration,
        classification,
        *,
        source_event,
        anchor_type,
        anchor,
    ) -> None:
        failure_event_type = (
            "bng_failure"
            if anchor_type == "network_device" and anchor.device_type == NetworkDeviceType.BNG
            else f"{anchor_type}_failure"
        )
        chain = (
            (failure_event_type, started_at),
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
                    "source_event_code": source_event.event_code if source_event else None,
                    "anchor_type": anchor_type,
                    "anchor_code": self._anchor_code(anchor),
                    "duration_seconds": duration,
                },
            )

    def _projection(
        self, *, source_event, anchor_type, anchor, snapshot, window_start, window_end
    ) -> dict[str, Any]:
        if anchor_type == "network_device":
            projection = self.impact_service.project_device_failure(
                snapshot=snapshot,
                source_device=anchor,
                window_start=window_start,
                window_end=window_end,
            )
            connection_basis = "snapshot_topology_active_connections"
        elif anchor_type == "network_link":
            projection = self.impact_service.project_network_link_failure(
                snapshot=snapshot,
                source_link=anchor,
                window_start=window_start,
                window_end=window_end,
            )
            connection_basis = "snapshot_link_target_subgraph_active_connections"
        else:
            projection = self.impact_service.project_line_connection_failure(
                snapshot=snapshot,
                source_line=anchor,
                window_start=window_start,
                window_end=window_end,
            )
            connection_basis = "snapshot_line_active_connections"
        potential_subscription_ids = projection["potential_subscription_ids"]
        affected_subscription_ids = projection["projected_affected_subscription_ids"]
        protected_subscription_ids = projection["projected_protected_no_impact_subscription_ids"]
        unknown_subscription_ids = projection["projected_unknown_subscription_ids"]
        from apps.customers.models import Subscription

        potential_customer_scope = (
            Subscription.objects.filter(id__in=potential_subscription_ids)
            .values("customer_id")
            .distinct()
            .count()
        )
        return {
            "basis": "simulation_projection",
            "connection_basis": connection_basis,
            "assumptions": {
                "failure_mode": f"{anchor_type}_failure",
                "protection_policy": projection["failover_basis"]["protection_policy"],
            },
            "potential_subscription_scope": len(potential_subscription_ids),
            "potential_customer_scope": potential_customer_scope,
            "projected_affected_subscriptions": len(affected_subscription_ids),
            "projected_affected_customers": len(projection["projected_affected_customer_ids"]),
            "projected_protected_no_impact_subscriptions": len(protected_subscription_ids),
            "projected_unknown_subscriptions": len(unknown_subscription_ids),
            "failover_classification": projection["failover_basis"]["classification"],
            "failover_basis": projection["failover_basis"],
            "projected_affected_subscription_ids": affected_subscription_ids,
        }

    def _historical_evidence(self, source_event, snapshot) -> dict[str, Any]:
        if source_event is None:
            return {"basis": "not_used_for_device_anchor"}
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
            "basis": "persisted_session_evidence",
            "potential_subscription_scope": len(potential_subscriptions),
            "verified_affected_subscriptions": len(impacted_subscriptions),
            "verified_affected_customers": len(impacted_customers),
            "verified_protected_subscriptions": len(protected_subscriptions),
            "unknown_or_insufficient_subscriptions": len(unknown_subscriptions),
            "failover_classification": (
                "verified_protected" if protected_subscriptions else "not_verified"
            ),
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
        snapshot,
        projection,
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
            id__in=projection["projected_affected_subscription_ids"]
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
            result = run.lifecycle_context.get("canonical_failure_result")
        if not isinstance(result, dict):
            raise CanonicalFailureSimulationError("Run has no canonical failure result.")
        return result


# Backward-compatible public names. BNG is now a network-device anchor subtype.
CanonicalBNGSimulationService = CanonicalFailureSimulationService
CanonicalBNGSimulationError = CanonicalFailureSimulationError
CanonicalBNGResult = CanonicalFailureResult
