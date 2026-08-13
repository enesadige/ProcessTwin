from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.network.models import (
    DeviceFailureDomainMembership,
    FailureDomain,
    FailureDomainType,
    LineConnection,
    LineConnectionFailureDomainMembership,
)
from apps.operations.contracts import (
    CausalEventStatus,
    CausalEventType,
    EventOrigin,
    SessionEventType,
)
from apps.operations.models import CausalEvent, SessionEvent
from apps.operations.services.customer_impact_assessment import CustomerImpactAssessmentService
from apps.operations.tests.test_operations_models import (
    create_access_line,
    create_snapshot,
    create_subscription_connection,
)


def _legacy_failure_domain_ids(*, service, causal_event, snapshot):
    window_end = causal_event.ended_at
    valid_connections = service._potential_service._get_valid_connections(
        snapshot=snapshot,
        window_start=causal_event.started_at,
        window_end=window_end,
        lightweight=True,
    )
    connection_ids = []
    for candidate in valid_connections:
        line_member = LineConnectionFailureDomainMembership.objects.filter(
            data_snapshot=snapshot,
            failure_domain_id=causal_event.root_failure_domain_id,
            line_connection_id=candidate.line_connection_id,
        ).exists()
        device_member = False
        if not line_member:
            device_member = DeviceFailureDomainMembership.objects.filter(
                data_snapshot=snapshot,
                failure_domain_id=causal_event.root_failure_domain_id,
                device_id=candidate.line_connection.port.device_id,
            ).exists()
        if line_member or device_member:
            connection_ids.append(candidate.id)
    return connection_ids


@pytest.mark.django_db
def test_failure_domain_fast_scope_preserves_legacy_order_and_removes_membership_n_plus_one():
    snapshot = create_snapshot("fast-scope")
    root, _child, _link, _port, line = create_access_line(snapshot)
    first = create_subscription_connection(snapshot, line)
    second_line = LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code="LINE-MAL-FAST-002",
        port=line.port,
        access_segment=line.access_segment,
        technology=line.technology,
        valid_from=line.valid_from,
    )
    second = create_subscription_connection(snapshot, second_line)
    domain = FailureDomain.objects.create(
        data_snapshot=snapshot,
        code="FD-FAST-001",
        name="Fast-path test domain",
        domain_type=FailureDomainType.FIBER_ROUTE,
    )
    LineConnectionFailureDomainMembership.objects.create(
        data_snapshot=snapshot,
        line_connection=line,
        failure_domain=domain,
    )
    LineConnectionFailureDomainMembership.objects.create(
        data_snapshot=snapshot,
        line_connection=second_line,
        failure_domain=domain,
    )
    DeviceFailureDomainMembership.objects.create(
        data_snapshot=snapshot,
        device=root,
        failure_domain=domain,
    )
    started_at = timezone.now() - timedelta(hours=1)
    causal_event = CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-FAST-SCOPE-001",
        event_type=CausalEventType.ACCESS_SEGMENT_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=30),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_failure_domain=domain,
    )
    service = CustomerImpactAssessmentService()

    legacy_ids = _legacy_failure_domain_ids(
        service=service,
        causal_event=causal_event,
        snapshot=snapshot,
    )
    with CaptureQueriesContext(connection) as queries:
        fast_ids = [
            item.id
            for item in service._get_potential_connections(
                causal_event=causal_event,
                snapshot=snapshot,
                window_end=causal_event.ended_at,
            )
        ]

    assert legacy_ids == fast_ids == [first.id, second.id]
    assert len(queries) <= 2


@pytest.mark.django_db
def test_fast_evaluation_marks_non_continuing_backup_as_failed_failover_impact():
    snapshot = create_snapshot("fast-evidence")
    _root, child, _link, _port, line = create_access_line(snapshot)
    primary = create_subscription_connection(snapshot, line)
    backup_line = LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code="LINE-MAL-FAST-BACKUP",
        port=line.port,
        access_segment=line.access_segment,
        technology=line.technology,
        valid_from=line.valid_from,
    )
    backup = primary.__class__.objects.create(
        data_snapshot=snapshot,
        subscription=primary.subscription,
        line_connection=backup_line,
        connection_role="backup",
        valid_from=primary.valid_from,
    )
    started_at = timezone.now() - timedelta(hours=1)
    causal_event = CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-FAST-EVIDENCE-001",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=30),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=child,
    )

    def evidence(connection, suffix, event_type, occurred_at):
        return SessionEvent.objects.create(
            data_snapshot=snapshot,
            causal_event=causal_event,
            external_event_id=f"SES-FAST-{connection.id}-{suffix}",
            event_type=event_type,
            occurred_at=occurred_at,
            received_at=occurred_at,
            source_system="test",
            subscription=connection.subscription,
            subscription_connection=connection,
        )

    events = [
        evidence(primary, "PRE", SessionEventType.CONTINUE, started_at - timedelta(minutes=5)),
        evidence(primary, "STOP", SessionEventType.STOP, started_at + timedelta(minutes=5)),
        evidence(primary, "REC", SessionEventType.START, started_at + timedelta(minutes=25)),
        evidence(backup, "PRE", SessionEventType.CONTINUE, started_at - timedelta(minutes=5)),
        # This falls after the legacy backup query boundary and must not turn
        # the primary into a protected/no-impact assessment.
        evidence(backup, "POST", SessionEventType.CONTINUE, started_at + timedelta(minutes=35)),
    ]

    with CaptureQueriesContext(connection) as queries:
        assessments, summary = CustomerImpactAssessmentService().evaluate(
            causal_event=causal_event,
            snapshot=snapshot,
            potential_connections=[primary],
            session_events=events,
        )

    assert assessments[0].status == "verified_impact"
    assert summary.verified_impacted_count == 1
    assert summary.failover_protected_count == 0
    assert len(queries) <= 6
