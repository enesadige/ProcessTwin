"""Materialize immutable evidence from persisted ProcessTwin simulation results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.simulation.models import SimulationEvidence, SimulationRun, SimulationRunStatus
from apps.simulation.services.runtime import SimulationRuntimeError


class SimulationEvidenceError(SimulationRuntimeError):
    """Raised when persisted simulation evidence cannot be materialized safely."""


class SimulationEvidenceService:
    """Create one immutable evidence record from an already-completed simulation run."""

    SCHEMA_VERSION = "simulation-evidence.v1"

    def materialize(self, simulation_run: SimulationRun) -> SimulationEvidence:
        with transaction.atomic():
            # PostgreSQL cannot lock nullable outer-joined baseline/replay rows.
            # Lock only the mutable run row, then load its immutable references.
            locked_run = SimulationRun.objects.select_for_update().get(pk=simulation_run.pk)
            run = SimulationRun.objects.select_related(
                "source_snapshot", "scenario", "baseline_run", "replay_of"
            ).get(pk=locked_run.pk)
            if run.status != SimulationRunStatus.COMPLETED:
                raise SimulationEvidenceError(
                    "Simulation evidence requires a completed simulation run."
                )
            result = self._persisted_result(run)
            payload = self._payload(run, result)
            evidence_hash = self._fingerprint(payload)
            evidence, created = SimulationEvidence.objects.get_or_create(
                simulation_run=run,
                defaults={
                    "source_snapshot": run.source_snapshot,
                    "evidence_hash": evidence_hash,
                    "payload": payload,
                    "finalized": True,
                    "finalized_at": timezone.now(),
                },
            )
            if not created and evidence.source_snapshot_id != run.source_snapshot_id:
                raise SimulationEvidenceError(
                    "Simulation evidence snapshot does not match its run."
                )
            return evidence

    @staticmethod
    def _persisted_result(run: SimulationRun) -> dict[str, Any]:
        result = run.lifecycle_context.get("canonical_failure_result")
        if not isinstance(result, Mapping):
            result = run.lifecycle_context.get("canonical_bng_result")
        if not isinstance(result, Mapping):
            raise SimulationEvidenceError(
                "Completed simulation run has no persisted canonical result."
            )
        return dict(result)

    def _payload(self, run: SimulationRun, result: Mapping[str, Any]) -> dict[str, Any]:
        event = self._mapping(result.get("event"))
        projection = self._mapping(result.get("projection"))
        historical_evidence = self._mapping(result.get("historical_evidence"))
        compensation = self._mapping(result.get("compensation"))
        selected_rule_version = event.get("selected_rule_version")
        if (
            not isinstance(selected_rule_version, Mapping)
            or selected_rule_version.get("status") != "selected"
        ):
            selected_rule_version = None
        context = run.lifecycle_context if isinstance(run.lifecycle_context, Mapping) else {}
        return {
            "schema_version": self.SCHEMA_VERSION,
            "source_snapshot": {
                "id": run.source_snapshot_id,
                "snapshot_key": run.source_snapshot.snapshot_key,
            },
            "scenario": {
                "code": run.scenario.scenario_code,
                "type": run.scenario.scenario_type,
            },
            "run": {
                "code": run.run_code,
                "comparison_role": run.comparison_role,
                "baseline_run_code": run.baseline_run.run_code if run.baseline_run_id else None,
                "replay_of_run_code": run.replay_of.run_code if run.replay_of_id else None,
                "replay_identity": run.replay_identity,
            },
            "determinism": {
                "seed_fingerprint": self._fingerprint({"seed": run.deterministic_seed}),
                "effective_input_fingerprint": context.get("effective_input_fingerprint"),
                "initial_virtual_clock": context.get("initial_virtual_clock"),
                "completed_virtual_clock": run.virtual_clock.isoformat(),
            },
            "canonical_result": {
                "fingerprint": self._fingerprint(result),
                "event": {
                    key: event.get(key)
                    for key in (
                        "source_event_code",
                        "anchor_type",
                        "anchor_code",
                        "failure_type",
                        "started_at",
                        "ended_at",
                        "duration_seconds",
                        "classification",
                    )
                },
            },
            "semantics": {
                "result_kind": "hypothetical_simulation_projection",
                "historical_evidence": self._fields(
                    historical_evidence,
                    (
                        "basis",
                        "potential_subscription_scope",
                        "verified_affected_subscriptions",
                        "verified_affected_customers",
                        "verified_protected_subscriptions",
                        "unknown_or_insufficient_subscriptions",
                        "failover_classification",
                    ),
                ),
                "projection": self._fields(
                    projection,
                    (
                        "basis",
                        "connection_basis",
                        "assumptions",
                        "potential_subscription_scope",
                        "potential_customer_scope",
                        "projected_affected_subscriptions",
                        "projected_affected_customers",
                        "projected_protected_no_impact_subscriptions",
                        "projected_unknown_subscriptions",
                        "failover_classification",
                    ),
                ),
                "simulated_compensation": self._fields(
                    compensation,
                    (
                        "status",
                        "eligibility",
                        "amount",
                        "currency",
                        "eligible_subscription_count",
                        "manual_review_reason",
                    ),
                ),
                "selected_rule_version": dict(selected_rule_version)
                if selected_rule_version is not None
                else None,
            },
        }

    @staticmethod
    def _mapping(value: object) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _fields(value: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        return {field: value.get(field) for field in fields if field in value}

    @staticmethod
    def _fingerprint(value: object) -> str:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
