"""Deterministic, connection-level session verification for causal events."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.customers.models import SubscriptionConnection, SubscriptionConnectionRole
from apps.customers.services.impact import CustomerImpactService
from apps.datasets.models import DataSnapshot
from apps.network.models import (
    DeviceFailureDomainMembership,
    LineConnectionFailureDomainMembership,
)
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
    failover_protected_count: int
    reason_code_counts: dict[str, int]


@dataclass(frozen=True)
class ReadOnlyCustomerImpactAssessment:
    """A non-persisted result using the authoritative assessment rules."""

    subscription_connection_id: int
    subscription_id: int
    customer_id: int
    status: str
    reasons: list[str]
    evidence_session_event_codes: list[str]
    metadata: dict


class CustomerImpactAssessmentService:
    """Persist one idempotent assessment per CausalEvent and connection."""

    def __init__(self, *, topology_service=None) -> None:
        self._potential_service = CustomerImpactService(topology_service=topology_service)
        self.topology_service = self._potential_service.topology_service

    def evaluate(
        self,
        *,
        causal_event: CausalEvent,
        snapshot: DataSnapshot,
        evaluation_time=None,
        potential_connections: list[SubscriptionConnection] | None = None,
        session_events: list[SessionEvent] | None = None,
        batch_size: int = 2000,
    ):
        """Persist assessments using one event-level evidence read.

        Callers may supply the already-resolved event scope and newly-created
        session evidence.  That lets the generator reuse authoritative work
        from the event transaction instead of resolving the same scope twice.
        The classification rules below remain identical in either path.
        """
        self._validate_inputs(causal_event=causal_event, snapshot=snapshot)
        window_end = causal_event.ended_at or evaluation_time or causal_event.started_at
        if potential_connections is None:
            potential_connections = self._get_potential_connections(
                causal_event=causal_event, snapshot=snapshot, window_end=window_end
            )
        else:
            potential_connections = list(potential_connections)

        backup_ids_by_subscription = self._backup_ids_by_subscription(
            snapshot=snapshot,
            subscription_ids={connection.subscription_id for connection in potential_connections},
        )
        events_by_connection = self._events_by_connection(
            snapshot=snapshot,
            causal_event=causal_event,
            window_end=window_end,
            connections=potential_connections,
            extra_connection_ids={
                connection_id
                for connection_ids in backup_ids_by_subscription.values()
                for connection_id in connection_ids
            },
            session_events=session_events,
        )
        existing_by_connection = {
            assessment.subscription_connection_id: assessment
            for assessment in CustomerImpactAssessment.objects.filter(
                causal_event=causal_event,
                subscription_connection__in=potential_connections,
            )
        }
        assessments: list[CustomerImpactAssessment] = []
        creates: list[CustomerImpactAssessment] = []
        updates: list[CustomerImpactAssessment] = []
        for connection in potential_connections:
            status, reasons, evidence_codes, metadata = self._evaluate_connection(
                causal_event=causal_event,
                connection=connection,
                window_end=window_end,
                events=events_by_connection.get(connection.id, []),
                events_by_connection=events_by_connection,
                backup_ids_by_subscription=backup_ids_by_subscription,
            )
            values = {
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
            }
            assessment = existing_by_connection.get(connection.id)
            if assessment is None:
                assessment = CustomerImpactAssessment(
                    causal_event=causal_event,
                    subscription_connection=connection,
                    **values,
                )
                creates.append(assessment)
            else:
                for field_name, value in values.items():
                    setattr(assessment, field_name, value)
                assessment.updated_at = timezone.now()
                updates.append(assessment)
            assessments.append(assessment)
        if creates:
            CustomerImpactAssessment.objects.bulk_create(creates, batch_size=batch_size)
        if updates:
            CustomerImpactAssessment.objects.bulk_update(
                updates,
                [
                    "data_snapshot",
                    "subscription",
                    "status",
                    "potential_impact",
                    "connection_role",
                    "assessment_started_at",
                    "assessment_ended_at",
                    "reasons",
                    "evidence_session_event_codes",
                    "metadata",
                    "updated_at",
                ],
                batch_size=batch_size,
            )
        return assessments, self.summarize(causal_event=causal_event, snapshot=snapshot)

    def evaluate_read_only(
        self,
        *,
        causal_event: CausalEvent,
        snapshot: DataSnapshot,
        evaluation_time=None,
    ) -> list[ReadOnlyCustomerImpactAssessment]:
        """Classify an event without materializing assessment rows.

        ProcessTwin uses this deliberately narrow adapter so its simulation
        runtime shares the production session/failover semantics without ever
        writing ``CustomerImpactAssessment`` records.
        """
        self._validate_inputs(causal_event=causal_event, snapshot=snapshot)
        window_end = causal_event.ended_at or evaluation_time or causal_event.started_at
        connections = self._get_potential_connections(
            causal_event=causal_event, snapshot=snapshot, window_end=window_end
        )
        backup_ids_by_subscription = self._backup_ids_by_subscription(
            snapshot=snapshot,
            subscription_ids={connection.subscription_id for connection in connections},
        )
        events_by_connection = self._events_by_connection(
            snapshot=snapshot,
            causal_event=causal_event,
            window_end=window_end,
            connections=connections,
            extra_connection_ids={
                connection_id
                for connection_ids in backup_ids_by_subscription.values()
                for connection_id in connection_ids
            },
            session_events=None,
        )
        results = []
        for connection in connections:
            status, reasons, evidence_codes, metadata = self._evaluate_connection(
                causal_event=causal_event,
                connection=connection,
                window_end=window_end,
                events=events_by_connection.get(connection.id, []),
                events_by_connection=events_by_connection,
                backup_ids_by_subscription=backup_ids_by_subscription,
            )
            results.append(
                ReadOnlyCustomerImpactAssessment(
                    subscription_connection_id=connection.id,
                    subscription_id=connection.subscription_id,
                    customer_id=connection.subscription.customer_id,
                    status=status.value,
                    reasons=[reason.value for reason in reasons],
                    evidence_session_event_codes=evidence_codes,
                    metadata=metadata,
                )
            )
        return results

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
            failover_protected_count=sum(
                ImpactReason.FAILOVER_PROTECTED.value in assessment.reasons
                for assessment in assessments
            ),
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
        valid_connections = self._potential_service._get_valid_connections(
            snapshot=snapshot,
            window_start=causal_event.started_at,
            window_end=window_end,
            lightweight=True,
        )
        if causal_event.root_failure_domain_id:
            line_memberships = LineConnectionFailureDomainMembership.objects.filter(
                data_snapshot=snapshot,
                failure_domain_id=causal_event.root_failure_domain_id,
            ).values("line_connection_id")
            device_memberships = DeviceFailureDomainMembership.objects.filter(
                data_snapshot=snapshot,
                failure_domain_id=causal_event.root_failure_domain_id,
            ).values("device_id")
            return list(
                valid_connections.filter(
                    Q(line_connection_id__in=line_memberships)
                    | Q(line_connection__port__device_id__in=device_memberships)
                )
            )
        root_device = self._root_device(causal_event)
        if root_device is None:
            return []
        subgraph = self.topology_service.get_subgraph(
            device=root_device, snapshot=snapshot, evaluation_time=window_end
        )
        device_ids = {device.id for device in subgraph.devices}
        return list(valid_connections.filter(line_connection__port__device_id__in=device_ids))

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

    def _evaluate_connection(
        self,
        *,
        causal_event,
        connection,
        window_end,
        events,
        events_by_connection,
        backup_ids_by_subscription,
    ):
        evidence_codes = sorted(
            {event.external_event_id for event in events if event.external_event_id}
        )
        before = [event for event in events if event.occurred_at < causal_event.started_at]
        during = [
            event for event in events if causal_event.started_at <= event.occurred_at <= window_end
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
            event.received_at and event.received_at - event.occurred_at > SESSION_LATE_ARRIVAL_GRACE
            for event in events
        )
        if contradictory or late:
            return self._insufficient(evidence_codes)
        if (
            connection.connection_role == SubscriptionConnectionRole.PRIMARY
            and self._backup_remained_active(
                causal_event=causal_event,
                connection=connection,
                window_end=window_end,
                events_by_connection=events_by_connection,
                backup_ids_by_subscription=backup_ids_by_subscription,
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

    def _backup_remained_active(
        self,
        *,
        causal_event,
        connection,
        window_end,
        events_by_connection,
        backup_ids_by_subscription,
    ) -> bool:
        for backup_id in backup_ids_by_subscription.get(connection.subscription_id, []):
            # The legacy per-connection query ended at ``window_end``.  The
            # shared evidence read also includes recovery context after that
            # boundary for primary classification, so retain the original
            # backup-protection window here.
            events = [
                event
                for event in events_by_connection.get(backup_id, [])
                if event.occurred_at <= window_end
            ]
            active_before = any(
                event.occurred_at < causal_event.started_at
                and event.event_type in {SessionEventType.START, SessionEventType.CONTINUE}
                for event in events
            )
            continued = any(
                event.occurred_at >= causal_event.started_at
                and event.event_type == SessionEventType.CONTINUE
                for event in events
            )
            stopped = any(
                event.occurred_at >= causal_event.started_at
                and event.event_type == SessionEventType.STOP
                for event in events
            )
            if active_before and continued and not stopped:
                return True
        return False

    def _events_by_connection(
        self,
        *,
        snapshot,
        causal_event,
        window_end,
        connections,
        extra_connection_ids,
        session_events,
    ) -> dict[int, list[SessionEvent]]:
        connection_ids = {connection.id for connection in connections} | extra_connection_ids
        if not connection_ids:
            return {}
        if session_events is None:
            events = SessionEvent.objects.filter(
                data_snapshot=snapshot,
                subscription_connection_id__in=connection_ids,
                occurred_at__gte=causal_event.started_at - SESSION_CONTEXT_WINDOW,
                occurred_at__lte=window_end + SESSION_CONTEXT_WINDOW,
            ).order_by("subscription_connection_id", "occurred_at", "external_event_id", "pk")
        else:
            events = sorted(
                (
                    event
                    for event in session_events
                    if event.subscription_connection_id in connection_ids
                    and causal_event.started_at - SESSION_CONTEXT_WINDOW
                    <= event.occurred_at
                    <= window_end + SESSION_CONTEXT_WINDOW
                ),
                key=lambda event: (
                    event.subscription_connection_id,
                    event.occurred_at,
                    event.external_event_id,
                    event.pk or 0,
                ),
            )
        grouped: dict[int, list[SessionEvent]] = defaultdict(list)
        for event in events:
            grouped[event.subscription_connection_id].append(event)
        return dict(grouped)

    @staticmethod
    def _backup_ids_by_subscription(*, snapshot, subscription_ids) -> dict[int, list[int]]:
        if not subscription_ids:
            return {}
        grouped: dict[int, list[int]] = defaultdict(list)
        for subscription_id, connection_id in (
            SubscriptionConnection.objects.filter(
                data_snapshot=snapshot,
                subscription_id__in=subscription_ids,
                connection_role=SubscriptionConnectionRole.BACKUP,
                is_active=True,
            )
            .order_by("subscription_id", "pk")
            .values_list("subscription_id", "id")
        ):
            grouped[subscription_id].append(connection_id)
        return dict(grouped)

    def _insufficient(self, evidence_codes):
        return (
            CustomerImpactStatus.INSUFFICIENT_EVIDENCE,
            [ImpactReason.TOPOLOGY_MATCH, ImpactReason.MISSING_SESSION_EVIDENCE],
            evidence_codes,
            {"evidence_state": "insufficient_session_evidence"},
        )
