from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.operations.contracts import (
    CausalEventStatus,
    CausalEventType,
    CustomerImpactStatus,
    EventOrigin,
    ImpactReason,
    ResourceType,
    SessionEventType,
)
from apps.operations.models import (
    Alarm,
    AlarmStatus,
    CausalEvent,
    CustomerImpactAssessment,
    SessionEvent,
    Severity,
)
from apps.operations.tests.test_operations_models import (
    create_access_line,
    create_alarm_type,
    create_snapshot,
    create_subscription_connection,
)


def create_causal_event(snapshot, *, code="CE-GPON-001", root_device=None, **overrides):
    started_at = overrides.pop("started_at", timezone.now() - timedelta(minutes=10))
    defaults = {
        "data_snapshot": snapshot,
        "event_code": code,
        "event_type": CausalEventType.PORT_FAILURE.value,
        "status": CausalEventStatus.ACTIVE.value,
        "started_at": started_at,
        "source_system": "synthetic_generator",
        "origin": EventOrigin.SYNTHETIC.value,
    }
    if root_device is not None:
        defaults["root_device"] = root_device
    defaults.update(overrides)
    return CausalEvent.objects.create(**defaults)


@pytest.mark.django_db
def test_causal_event_supports_ongoing_resolved_and_root_resource():
    snapshot = create_snapshot()
    root_device, *_ = create_access_line(snapshot)
    started_at = timezone.now() - timedelta(hours=2)
    ended_at = started_at + timedelta(minutes=30)

    ongoing = create_causal_event(snapshot, root_device=root_device, started_at=started_at)
    resolved = create_causal_event(
        snapshot,
        code="CE-GPON-002",
        root_device=root_device,
        status=CausalEventStatus.RESOLVED.value,
        started_at=started_at,
        ended_at=ended_at,
    )

    assert ongoing.get_root_resource_kind() == ResourceType.DEVICE.value
    assert ongoing.root_resource_code == root_device.code
    assert resolved.ended_at == ended_at


@pytest.mark.django_db
def test_causal_event_rejects_duplicate_invalid_time_and_terminal_without_end():
    snapshot = create_snapshot()
    started_at = timezone.now()
    create_causal_event(snapshot, code="CE-DUP", started_at=started_at)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            create_causal_event(snapshot, code="CE-DUP", started_at=started_at)

    invalid_end = CausalEvent(
        data_snapshot=snapshot,
        event_code="CE-BAD-END",
        event_type=CausalEventType.DEVICE_FAILURE.value,
        status=CausalEventStatus.ACTIVE.value,
        started_at=started_at,
        ended_at=started_at - timedelta(seconds=1),
        source_system="synthetic_generator",
        origin=EventOrigin.SYNTHETIC.value,
    )
    terminal_without_end = CausalEvent(
        data_snapshot=snapshot,
        event_code="CE-BAD-STATUS",
        event_type=CausalEventType.DEVICE_FAILURE.value,
        status=CausalEventStatus.CLOSED.value,
        started_at=started_at,
        source_system="synthetic_generator",
        origin=EventOrigin.SYNTHETIC.value,
    )
    naive = CausalEvent(
        data_snapshot=snapshot,
        event_code="CE-NAIVE",
        event_type=CausalEventType.DEVICE_FAILURE.value,
        status=CausalEventStatus.ACTIVE.value,
        started_at=started_at.replace(tzinfo=None),
        source_system="synthetic_generator",
        origin=EventOrigin.SYNTHETIC.value,
    )

    with pytest.raises(ValidationError, match="ended_at"):
        invalid_end.full_clean()
    with pytest.raises(ValidationError, match="Terminal"):
        terminal_without_end.full_clean()
    with pytest.raises(ValidationError, match="timezone-aware"):
        naive.full_clean()


@pytest.mark.django_db
def test_legacy_operation_relations_allow_null_and_set_null_on_delete():
    snapshot = create_snapshot()
    root_device, *_ = create_access_line(snapshot)
    alarm_type = create_alarm_type(snapshot)
    started_at = timezone.now()
    causal_event = create_causal_event(snapshot, root_device=root_device, started_at=started_at)
    alarm = Alarm.objects.create(
        data_snapshot=snapshot,
        causal_event=causal_event,
        alarm_id="ALM-CAUSAL-001",
        alarm_type=alarm_type,
        device=root_device,
        severity=Severity.CRITICAL,
        status=AlarmStatus.OPEN,
        detected_at=started_at,
    )
    legacy_alarm = Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id="ALM-LEGACY-001",
        alarm_type=alarm_type,
        device=root_device,
        severity=Severity.MAJOR,
        status=AlarmStatus.OPEN,
        detected_at=started_at + timedelta(minutes=1),
    )

    assert alarm.causal_event == causal_event
    assert legacy_alarm.causal_event is None
    causal_event.delete()
    alarm.refresh_from_db()
    assert alarm.causal_event is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "event_type",
    [SessionEventType.START, SessionEventType.CONTINUE, SessionEventType.STOP],
)
def test_session_event_supports_normalized_types_and_nullable_causal_event(event_type):
    snapshot = create_snapshot()
    *_line_context, line = create_access_line(snapshot)
    connection = create_subscription_connection(snapshot, line)

    event = SessionEvent.objects.create(
        data_snapshot=snapshot,
        event_type=event_type.value,
        occurred_at=timezone.now(),
        source_system="session_api",
        external_event_id=f"SES-{event_type.value}",
        subscription=connection.subscription,
        subscription_connection=connection,
        raw_payload={"ip_address": "192.0.2.44", "token": "private"},
        session_identifier_hash="hash-session",
    )

    public = event.to_public_dict()
    assert public["event_type"] == event_type.value
    assert "raw_payload" not in public
    assert "session_identifier_hash" not in public
    assert "192.0.2.44" not in str(public)


@pytest.mark.django_db
def test_session_event_rejects_naive_time_bad_order_missing_identity_and_duplicate_source_id():
    snapshot = create_snapshot()
    now = timezone.now()
    valid = SessionEvent.objects.create(
        data_snapshot=snapshot,
        event_type=SessionEventType.STOP.value,
        occurred_at=now,
        source_system="session_api",
        external_event_id="SES-DUP",
        external_service_reference_hash="service-hash",
    )
    assert valid.causal_event is None

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SessionEvent.objects.create(
                data_snapshot=snapshot,
                event_type=SessionEventType.STOP.value,
                occurred_at=now,
                source_system="session_api",
                external_event_id="SES-DUP",
                external_service_reference_hash="service-hash-2",
            )

    missing_identity = SessionEvent(
        data_snapshot=snapshot,
        event_type=SessionEventType.STOP.value,
        occurred_at=now,
        source_system="session_api",
    )
    out_of_order = SessionEvent(
        data_snapshot=snapshot,
        event_type=SessionEventType.START.value,
        occurred_at=now,
        received_at=now - timedelta(seconds=1),
        source_system="session_api",
        external_service_reference_hash="service-hash",
    )
    naive = SessionEvent(
        data_snapshot=snapshot,
        event_type=SessionEventType.START.value,
        occurred_at=now.replace(tzinfo=None),
        source_system="session_api",
        external_service_reference_hash="service-hash",
    )

    with pytest.raises(ValidationError, match="requires"):
        missing_identity.full_clean()
    with pytest.raises(ValidationError, match="received_at"):
        out_of_order.full_clean()
    with pytest.raises(ValidationError, match="timezone-aware"):
        naive.full_clean()


@pytest.mark.django_db
def test_customer_impact_assessment_status_invariants_and_reasons():
    snapshot = create_snapshot()
    root_device, *_line_context, line = create_access_line(snapshot)
    connection = create_subscription_connection(snapshot, line)
    causal_event = create_causal_event(snapshot, root_device=root_device)
    started_at = timezone.now()

    potential = CustomerImpactAssessment.objects.create(
        data_snapshot=snapshot,
        causal_event=causal_event,
        subscription=connection.subscription,
        subscription_connection=connection,
        status=CustomerImpactStatus.POTENTIAL_IMPACT.value,
        potential_impact=True,
        connection_role=connection.connection_role,
        assessment_started_at=started_at,
        reasons=[ImpactReason.TOPOLOGY_MATCH.value],
    )
    public = potential.to_public_dict()
    assert public["status"] == CustomerImpactStatus.POTENTIAL_IMPACT.value
    assert public["reasons"] == [ImpactReason.TOPOLOGY_MATCH.value]

    bad_verified = CustomerImpactAssessment(
        data_snapshot=snapshot,
        causal_event=causal_event,
        subscription=connection.subscription,
        status=CustomerImpactStatus.VERIFIED_IMPACT.value,
        potential_impact=False,
        assessment_started_at=started_at,
        reasons=[ImpactReason.SESSION_STOP_AND_RECOVERY_MATCH.value],
    )
    no_impact_without_reason = CustomerImpactAssessment(
        data_snapshot=snapshot,
        causal_event=causal_event,
        subscription=connection.subscription,
        status=CustomerImpactStatus.VERIFIED_NO_IMPACT.value,
        potential_impact=True,
        assessment_started_at=started_at,
        reasons=[],
    )
    insufficient = CustomerImpactAssessment(
        data_snapshot=snapshot,
        causal_event=causal_event,
        subscription=connection.subscription,
        status=CustomerImpactStatus.INSUFFICIENT_EVIDENCE.value,
        potential_impact=True,
        assessment_started_at=started_at,
        reasons=[ImpactReason.MISSING_SESSION_EVIDENCE.value],
    )

    with pytest.raises(ValidationError, match="potential"):
        bad_verified.full_clean()
    with pytest.raises(ValidationError, match="reason"):
        no_impact_without_reason.full_clean()
    insufficient.full_clean()


@pytest.mark.django_db
def test_customer_impact_assessment_rejects_duplicate_connection_and_protects_event():
    snapshot = create_snapshot()
    root_device, *_line_context, line = create_access_line(snapshot)
    connection = create_subscription_connection(snapshot, line)
    causal_event = create_causal_event(snapshot, root_device=root_device)
    started_at = timezone.now()
    CustomerImpactAssessment.objects.create(
        data_snapshot=snapshot,
        causal_event=causal_event,
        subscription=connection.subscription,
        subscription_connection=connection,
        status=CustomerImpactStatus.VERIFIED_NO_IMPACT.value,
        potential_impact=True,
        assessment_started_at=started_at,
        reasons=[ImpactReason.FAILOVER_PROTECTED.value],
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CustomerImpactAssessment.objects.create(
                data_snapshot=snapshot,
                causal_event=causal_event,
                subscription=connection.subscription,
                subscription_connection=connection,
                status=CustomerImpactStatus.VERIFIED_IMPACT.value,
                potential_impact=True,
                assessment_started_at=started_at,
                reasons=[ImpactReason.SESSION_STOP_AND_RECOVERY_MATCH.value],
            )
    with pytest.raises(ProtectedError):
        causal_event.delete()
