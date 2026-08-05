"""Deterministic, connection-level session verification for causal events."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

from apps.customers.models import SubscriptionConnection, SubscriptionConnectionRole
from apps.customers.services.impact import CustomerImpactService
from apps.datasets.models import DataSnapshot
from apps.operations.contracts import CustomerImpactStatus, ImpactReason, SessionEventType
from apps.operations.models import CausalEvent, CustomerImpactAssessment, SessionEvent

# Synthetic calibration only; these windows are not an operational SLA or commercial rule.
SESSION_CONTEXT_WINDOW = timedelta(hours=1)
SESSION_LATE_ARRIVAL_GRACE = timedelta(minutes=30)


class CustomerImpactAssessmentError(Exception):
    """Base error for causal session-impact evaluation."""


class CustomerImpactAssessmentInputError(CustomerImpactAssessmentError):
    """Raised when the causal event or snapshot is invalid."""


@dataclass(frozen=True)
class CustomerImpactAssessmentSummary:
    causal_event_code: str
    potential_connection_count: int
    verified_impacted_count: int
    verified_no_impact_count: int
    insufficient_evidence_count: int
    pending_count: int
    reason_code_counts: dict[str, int]


class CustomerImpactAssessmentService:
    """Persist one idempotent assessment per CausalEvent and connection."""

    def __init__(self, *, topology_service=None) -> None:
        self._potential_service = CustomerImpactService(topology_service=topology_service)
        self.topology_service = self._potential_service.topology_service

    def evaluate(self, *, causal_event: CausalEvent, snapshot: DataSnapshot, evaluation_time=None):
        self._validate_inputs(causal_event=causal_event, snapshot=snapshot)
        window_end = causal_event.ended_at or evaluation_time or causal_event.started_at
        potential_connections = self._get_potential_connections(
            causal_event=causal_event, snapshot=snapshot, window_end=window_end
        )
        assessments = []
        for connection in potential_connections:
            status, reasons, evidence_codes, metadata = self._evaluate_connection(
                causal_event=causal_event,
                connection=connection,
                window_end=window_end,
            )
            assessment, _ = CustomerImpactAssessment.objects.update_or_create(
                causal_event=causal_event,
                subscription_connection=connection,
                defaults={
                    "data_snapshot": snapshot,
                    "subscription": connection.subscription,
                    "status": status.value,
                    "potential_impact": True,
                    "connection_role": connection.connection_role,
                    "assessment_started_at": causal_event.started_at,
                    "assessment_ended_at": causal_event.ended_at or evaluation_time,
                    "reasons": [reason.value for reason in reasons],
                    "evidence_session_event_codes": evidence_codes,
                    "metadata": metadata,
                },
            )
            assessments.append(assessment)
        return assessments, self.summarize(causal_event=causal_event, snapshot=snapshot)

    def summarize(
        self, *, causal_event: CausalEvent, snapshot: DataSnapshot
    ) -> CustomerImpactAssessmentSummary:
        assessments = CustomerImpactAssessment.objects.filter(
            data_snapshot=snapshot, causal_event=causal_event
        ).order_by("subscription_connection_id")
        statuses = Counter(assessments.values_list("status", flat=True))
        reasons = Counter(
            reason
            for assessment in assessments
            for reason in assessment.reasons
            if reason in {item.value for item in ImpactReason}
        )
        return CustomerImpactAssessmentSummary(
            causal_event_code=causal_event.event_code,
            potential_connection_count=assessments.count(),
            verified_impacted_count=statuses[CustomerImpactStatus.VERIFIED_IMPACT.value],
            verified_no_impact_count=statuses[CustomerImpactStatus.VERIFIED_NO_IMPACT.value],
            insufficient_evidence_count=statuses[CustomerImpactStatus.INSUFFICIENT_EVIDENCE.value],
            pending_count=statuses[CustomerImpactStatus.POTENTIAL_IMPACT.value],
            reason_code_counts=dict(sorted(reasons.items())),
        )

    def _validate_inputs(self, *, causal_event, snapshot) -> None:
        if causal_event is None or not causal_event.pk:
            raise CustomerImpactAssessmentInputError("A persisted CausalEvent is required.")
        if snapshot is None or not snapshot.pk:
            raise CustomerImpactAssessmentInputError("A persisted DataSnapshot is required.")
        if causal_event.data_snapshot_id != snapshot.id:
            raise CustomerImpactAssessmentInputError(
                "Causal event must belong to the supplied snapshot."
            )

    def _get_potential_connections(self, *, causal_event, snapshot, window_end):
        root = causal_event.get_root_resource()
        if root is None:
            return []
        connections = list(
            self._potential_service._get_valid_connections(
                snapshot=snapshot,
                window_start=causal_event.started_at,
                window_end=window_end,
            )
        )
        if causal_event.root_failure_domain_id:
            return [
                connection
                for connection in connections
                if connection.line_connection.failure_domain_memberships.filter(
                    failure_domain_id=causal_event.root_failure_domain_id
                ).exists()
                or connection.line_connection.port.device.failure_domain_memberships.filter(
                    failure_domain_id=causal_event.root_failure_domain_id
                ).exists()
            ]
        root_device = self._root_device(causal_event)
        if root_device is None:
            return []
        subgraph = self.topology_service.get_subgraph(
            device=root_device, snapshot=snapshot, evaluation_time=window_end
        )
        device_ids = {device.id for device in subgraph.devices}
        return [
            connection
            for connection in connections
            if connection.line_connection.port.device_id in device_ids
        ]

    def _root_device(self, causal_event):
        root = causal_event.get_root_resource()
        if hasattr(root, "device_type"):
            return root
        if hasattr(root, "source_device"):
            return root.source_device
        if hasattr(root, "device"):
            return root.device
        if hasattr(root, "port"):
            return root.port.device
        return None

    def _evaluate_connection(self, *, causal_event, connection, window_end):
        events = list(
            SessionEvent.objects.filter(
                data_snapshot=connection.data_snapshot,
                subscription_connection=connection,
                occurred_at__gte=causal_event.started_at - SESSION_CONTEXT_WINDOW,
                occurred_at__lte=window_end + SESSION_CONTEXT_WINDOW,
            ).order_by("occurred_at", "external_event_id", "pk")
        )
        evidence_codes = sorted(
            {event.external_event_id for event in events if event.external_event_id}
        )
        before = [event for event in events if event.occurred_at < causal_event.started_at]
        during = [
            event
            for event in events
            if causal_event.started_at <= event.occurred_at <= window_end
        ]
        active_before = any(
            event.event_type in {SessionEventType.START, SessionEventType.CONTINUE}
            for event in before
        )
        stops = [event for event in during if event.event_type == SessionEventType.STOP]
        recovery = [
            event
            for event in events
            if event.occurred_at > (stops[-1].occurred_at if stops else window_end)
            and event.event_type in {SessionEventType.START, SessionEventType.CONTINUE}
        ]
        contradictory = any(
            start.occurred_at == stop.occurred_at
            for start in events
            if start.event_type in {SessionEventType.START, SessionEventType.CONTINUE}
            for stop in events
            if stop.event_type == SessionEventType.STOP
        )
        late = any(
            event.received_at
            and event.received_at - event.occurred_at > SESSION_LATE_ARRIVAL_GRACE
            for event in events
        )
        if contradictory or late:
            return self._insufficient(evidence_codes)
        if (
            connection.connection_role == SubscriptionConnectionRole.PRIMARY
            and self._backup_remained_active(
                causal_event=causal_event, connection=connection, window_end=window_end
            )
        ):
            return (
                CustomerImpactStatus.VERIFIED_NO_IMPACT,
                [ImpactReason.TOPOLOGY_MATCH, ImpactReason.FAILOVER_PROTECTED],
                evidence_codes,
                {"evidence_state": "backup_session_remained_active"},
            )
        if stops and active_before and (recovery or causal_event.ended_at is None):
            return (
                CustomerImpactStatus.VERIFIED_IMPACT,
                [ImpactReason.TOPOLOGY_MATCH, ImpactReason.SESSION_STOP_AND_RECOVERY_MATCH],
                evidence_codes,
                {"evidence_state": "verified_interruption"},
            )
        if stops:
            return self._insufficient(evidence_codes)
        if active_before and any(event.event_type == SessionEventType.CONTINUE for event in during):
            return (
                CustomerImpactStatus.VERIFIED_NO_IMPACT,
                [ImpactReason.TOPOLOGY_MATCH, ImpactReason.SESSION_REMAINED_ACTIVE],
                evidence_codes,
                {"evidence_state": "session_remained_active"},
            )
        if not events:
            return (
                CustomerImpactStatus.POTENTIAL_IMPACT,
                [ImpactReason.TOPOLOGY_MATCH],
                evidence_codes,
                {"evidence_state": "pending_session_evidence"},
            )
        return self._insufficient(evidence_codes)

    def _backup_remained_active(self, *, causal_event, connection, window_end) -> bool:
        backups = SubscriptionConnection.objects.filter(
            data_snapshot=connection.data_snapshot,
            subscription=connection.subscription,
            connection_role=SubscriptionConnectionRole.BACKUP,
            is_active=True,
        )
        for backup in backups:
            events = SessionEvent.objects.filter(
                data_snapshot=connection.data_snapshot,
                subscription_connection=backup,
                occurred_at__gte=causal_event.started_at - SESSION_CONTEXT_WINDOW,
                occurred_at__lte=window_end,
            )
            active_before = events.filter(
                occurred_at__lt=causal_event.started_at,
                event_type__in=[SessionEventType.START, SessionEventType.CONTINUE],
            ).exists()
            continued = events.filter(
                occurred_at__gte=causal_event.started_at,
                event_type=SessionEventType.CONTINUE,
            ).exists()
            stopped = events.filter(
                occurred_at__gte=causal_event.started_at,
                event_type=SessionEventType.STOP,
            ).exists()
            if active_before and continued and not stopped:
                return True
        return False

    def _insufficient(self, evidence_codes):
        return (
            CustomerImpactStatus.INSUFFICIENT_EVIDENCE,
            [ImpactReason.TOPOLOGY_MATCH, ImpactReason.MISSING_SESSION_EVIDENCE],
            evidence_codes,
            {"evidence_state": "insufficient_session_evidence"},
        )
