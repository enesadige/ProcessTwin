"""Safe read/write contracts for the ProcessTwin public API."""

from __future__ import annotations

from typing import Any

from apps.network.models import LineConnection, NetworkDevice, NetworkDeviceType, NetworkLink
from apps.simulation.models import (
    SimulationEvidence,
    SimulationRun,
    SimulationRunEvent,
    SimulationRunStatus,
)

SUPPORTED_ANCHOR_TYPES = frozenset({"network_device", "network_link", "line_connection"})
MAX_EVENT_PAGE_SIZE = 100
DEFAULT_EVENT_PAGE_SIZE = 50


class SimulationAPIError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def validate_anchor(
    *, snapshot, anchor_type: str, anchor_code: str
) -> tuple[str, str, str]:
    if anchor_type not in SUPPORTED_ANCHOR_TYPES:
        raise SimulationAPIError(
            "unsupported_anchor_type",
            "Supported anchor types are network_device, network_link, and line_connection.",
        )
    if not anchor_code:
        raise SimulationAPIError("invalid_anchor", "An anchor code is required.")

    if anchor_type == "network_device":
        device = NetworkDevice.objects.filter(data_snapshot=snapshot, code=anchor_code).first()
        if device is None:
            raise SimulationAPIError(
                "invalid_anchor", "Device anchor was not found in the snapshot."
            )
        if device.device_type not in {
            NetworkDeviceType.BNG,
            NetworkDeviceType.OLT,
            NetworkDeviceType.METRO_AGGREGATION,
            NetworkDeviceType.ACCESS_NODE,
        }:
            raise SimulationAPIError(
                "unsupported_anchor_type",
                "This device type is not supported by the ProcessTwin failure runtime.",
            )
    elif anchor_type == "network_link":
        if not NetworkLink.objects.filter(
            data_snapshot=snapshot, link_code=anchor_code
        ).exists():
            raise SimulationAPIError(
                "invalid_anchor", "Network link anchor was not found in the snapshot."
            )
    elif not LineConnection.objects.filter(data_snapshot=snapshot, line_code=anchor_code).exists():
        raise SimulationAPIError(
            "invalid_anchor", "Line connection anchor was not found in the snapshot."
        )

    return anchor_type, anchor_code, f"{anchor_type}_failure"


def validate_parameters(parameters: object, *, candidate: bool = False) -> dict[str, Any]:
    if parameters is None:
        return {}
    if not isinstance(parameters, dict):
        raise SimulationAPIError("invalid_override", "Simulation parameters must be an object.")
    forbidden = {
        "anchor_type",
        "anchor_code",
        "source_snapshot_identifier",
        "source_device_code",
        "source_event_code",
    }
    if candidate and forbidden.intersection(parameters):
        raise SimulationAPIError(
            "invalid_candidate_override",
            "Candidate overrides cannot change the source anchor or snapshot.",
        )
    duration = parameters.get("duration_seconds")
    if duration is not None and (not isinstance(duration, int) or duration <= 0):
        raise SimulationAPIError(
            "invalid_override", "duration_seconds must be a positive integer."
        )
    sla_target = parameters.get("sla_target_seconds")
    if sla_target is not None and (not isinstance(sla_target, int) or sla_target <= 0):
        raise SimulationAPIError(
            "invalid_override", "sla_target_seconds must be a positive integer."
        )
    classification = parameters.get("outage_classification")
    if classification is not None and classification not in {"full_outage", "degradation"}:
        raise SimulationAPIError(
            "invalid_override", "outage_classification must be full_outage or degradation."
        )
    rule_code = parameters.get("rule_code")
    if rule_code is not None and (not isinstance(rule_code, str) or not rule_code.strip()):
        raise SimulationAPIError("invalid_override", "rule_code must be a non-empty string.")
    return parameters.copy()


def serialize_run(run: SimulationRun) -> dict[str, Any]:
    result = run.lifecycle_context.get("canonical_failure_result")
    if not isinstance(result, dict):
        result = run.lifecycle_context.get("canonical_bng_result")
    return {
        "run_code": run.run_code,
        "comparison_role": run.comparison_role,
        "status": run.status,
        "source_snapshot": {
            "id": run.source_snapshot_id,
            "snapshot_key": run.source_snapshot.snapshot_key,
        },
        "scenario_code": run.scenario.scenario_code,
        "baseline_run_code": run.baseline_run.run_code if run.baseline_run_id else None,
        "replay_of_run_code": run.replay_of.run_code if run.replay_of_id else None,
        "replay_identity": run.replay_identity,
        "virtual_clock": run.virtual_clock.isoformat(),
        "speed_multiplier": run.speed_multiplier,
        "event_count": run.events.count(),
        "result_ready": isinstance(result, dict)
        and run.status in {SimulationRunStatus.COMPLETED, SimulationRunStatus.FAILED},
        "error_code": run.lifecycle_context.get("error_code") or None,
        "evidence": _evidence_reference(run),
    }


def serialize_result(run: SimulationRun, result: dict[str, Any], comparison: dict[str, Any] | None):
    projection = result.get("projection", {})
    event = result.get("event", {})
    compensation = result.get("compensation", {})
    rule = event.get("selected_rule_version")
    return {
        "source": result.get("source_snapshot", {}),
        "scenario": result.get("scenario", {}),
        "run": result.get("run", {}),
        "effective_input": result.get("effective_input", {}),
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
                "outage_classification",
            )
        },
        "historical_evidence": result.get("historical_evidence", {}),
        "projection": {
            "basis": projection.get("basis"),
            "connection_basis": projection.get("connection_basis"),
            "assumptions": projection.get("assumptions", {}),
            "potential_subscription_scope": projection.get("potential_subscription_scope"),
            "potential_customer_scope": projection.get("potential_customer_scope"),
            "projected_affected_subscriptions": projection.get("projected_affected_subscriptions"),
            "projected_affected_customers": projection.get("projected_affected_customers"),
            "projected_protected_no_impact_subscriptions": projection.get(
                "projected_protected_no_impact_subscriptions"
            ),
            "projected_unknown_subscriptions": projection.get(
                "projected_unknown_subscriptions"
            ),
            "failover_classification": projection.get("failover_classification"),
        },
        "rule_selection": rule,
        "compensation": {
            key: compensation.get(key)
            for key in (
                "status",
                "eligibility",
                "amount",
                "currency",
                "eligible_subscription_count",
                "manual_review_reason",
                "selected_rule_version",
            )
        },
        "operational": result.get("operational", {}),
        "comparison": comparison,
        "evidence": _evidence_reference(run),
    }


def serialize_evidence(evidence: SimulationEvidence) -> dict[str, Any]:
    """Return the finalized, already-persisted simulation evidence contract."""
    return {
        "evidence_code": evidence.evidence_code,
        "evidence_hash": evidence.evidence_hash,
        "finalized": evidence.finalized,
        "finalized_at": evidence.finalized_at.isoformat() if evidence.finalized_at else None,
        "snapshot": {
            "id": evidence.source_snapshot_id,
            "key": evidence.source_snapshot.snapshot_key,
        },
        "payload": evidence.payload,
    }


def _evidence_reference(run: SimulationRun) -> dict[str, Any] | None:
    try:
        evidence = run.simulation_evidence
    except SimulationEvidence.DoesNotExist:
        return None
    return {
        "evidence_code": evidence.evidence_code,
        "evidence_hash": evidence.evidence_hash,
        "finalized": evidence.finalized,
    }


def serialize_event(event: SimulationRunEvent) -> dict[str, Any]:
    context = event.event_context if isinstance(event.event_context, dict) else {}
    safe_context = {
        key: context[key]
        for key in (
            "runtime",
            "contract",
            "simulation_local",
            "source_event_code",
            "anchor_type",
            "anchor_code",
            "duration_seconds",
            "effective_input_fingerprint",
            "base_step_microseconds",
            "speed_multiplier",
        )
        if key in context
    }
    if "result" in context:
        safe_context["canonical_result_available"] = True
    return {
        "sequence": event.sequence,
        "event_code": event.event_code,
        "event_type": event.event_type,
        "virtual_occurred_at": event.virtual_occurred_at.isoformat(),
        "context": safe_context,
    }
