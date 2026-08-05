from datetime import timedelta

import pytest
from django.utils import timezone

from apps.customers.models import SubscriptionConnection, SubscriptionConnectionRole
from apps.network.models import AccessTechnology, LineConnection, NetworkPort
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


def setup_context():
    snapshot = create_snapshot()
    snapshot.dataset_version.config = {"reference_datetime": timezone.now().isoformat()}
    snapshot.dataset_version.save(update_fields=["config"])
    root, child, _, _, line = create_access_line(snapshot)
    connection = create_subscription_connection(snapshot, line)
    started_at = timezone.now() - timedelta(hours=1)
    event = CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-SESSION-001",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=30),
        source_system="synthetic",
        origin=EventOrigin.SYNTHETIC,
        root_device=root,
    )
    return snapshot, event, connection, child, started_at


def session(connection, event, external_id, event_type, occurred_at, *, received_at=None):
    return SessionEvent.objects.create(
        data_snapshot=connection.data_snapshot,
        causal_event=event,
        external_event_id=external_id,
        event_type=event_type,
        occurred_at=occurred_at,
        received_at=received_at or occurred_at,
        source_system="test-session-source",
        subscription=connection.subscription,
        subscription_connection=connection,
    )


@pytest.mark.django_db
def test_stop_and_recovery_verifies_only_topology_scoped_connection_idempotently():
    snapshot, event, connection, _, started_at = setup_context()
    session(
        connection, event, "SES-1", SessionEventType.CONTINUE, started_at - timedelta(minutes=5)
    )
    session(connection, event, "SES-2", SessionEventType.STOP, started_at + timedelta(minutes=5))
    session(connection, event, "SES-3", SessionEventType.START, started_at + timedelta(minutes=35))

    assessments, summary = CustomerImpactAssessmentService().evaluate(
        causal_event=event, snapshot=snapshot
    )
    repeated, repeated_summary = CustomerImpactAssessmentService().evaluate(
        causal_event=event, snapshot=snapshot
    )

    assert assessments[0].status == "verified_impact"
    assert len(repeated) == 1
    assert summary == repeated_summary
    assert summary.verified_impacted_count == 1


@pytest.mark.django_db
def test_continue_without_stop_verifies_no_impact_and_public_output_is_safe():
    snapshot, event, connection, _, started_at = setup_context()
    session(connection, event, "SES-1", SessionEventType.START, started_at - timedelta(minutes=2))
    session(
        connection, event, "SES-2", SessionEventType.CONTINUE, started_at + timedelta(minutes=5)
    )

    assessments, summary = CustomerImpactAssessmentService().evaluate(
        causal_event=event, snapshot=snapshot
    )

    assert assessments[0].status == "verified_no_impact"
    assert "session_remained_active" in assessments[0].reasons
    assert "raw_payload" not in assessments[0].to_public_dict()
    assert summary.verified_no_impact_count == 1


@pytest.mark.django_db
def test_stop_without_prior_activity_or_late_record_is_insufficient():
    snapshot, event, connection, _, started_at = setup_context()
    session(connection, event, "SES-STOP", SessionEventType.STOP, started_at + timedelta(minutes=5))

    assessments, _ = CustomerImpactAssessmentService().evaluate(
        causal_event=event, snapshot=snapshot
    )

    assert assessments[0].status == "insufficient_evidence"
    assert "missing_session_evidence" in assessments[0].reasons


@pytest.mark.django_db
def test_active_backup_prevents_primary_full_impact():
    snapshot, event, primary, child, started_at = setup_context()
    backup_port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=child,
        port_code="BACKUP-PORT-001",
        capacity_mbps=1000,
    )
    backup_line = LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code="BACKUP-LINE-001",
        port=backup_port,
        access_segment=primary.line_connection.access_segment,
        technology=AccessTechnology.FIBER,
        valid_from=primary.line_connection.valid_from,
    )
    backup = SubscriptionConnection.objects.create(
        data_snapshot=snapshot,
        subscription=primary.subscription,
        line_connection=backup_line,
        connection_role=SubscriptionConnectionRole.BACKUP,
        valid_from=primary.valid_from,
    )
    session(primary, event, "SES-PRE", SessionEventType.CONTINUE, started_at - timedelta(minutes=5))
    session(primary, event, "SES-PSTOP", SessionEventType.STOP, started_at + timedelta(minutes=5))
    session(backup, event, "SES-BPRE", SessionEventType.CONTINUE, started_at - timedelta(minutes=5))
    session(backup, event, "SES-BON", SessionEventType.CONTINUE, started_at + timedelta(minutes=5))

    assessments, summary = CustomerImpactAssessmentService().evaluate(
        causal_event=event, snapshot=snapshot
    )

    primary_assessment = next(
        item for item in assessments if item.subscription_connection_id == primary.id
    )
    assert primary_assessment.status == "verified_no_impact"
    assert "failover_protected" in primary_assessment.reasons
    assert summary.verified_impacted_count == 0
