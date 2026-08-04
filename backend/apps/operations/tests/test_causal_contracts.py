from datetime import UTC, datetime, timedelta

import pytest

from apps.core.exceptions import DomainValidationError
from apps.operations.contracts import (
    AlarmCorrelationContract,
    CausalEventContract,
    CausalEventStatus,
    CausalEventType,
    CorrelationReason,
    CorrelationRole,
    CustomerImpactAssessmentContract,
    CustomerImpactStatus,
    EventOrigin,
    ImpactReason,
    ResourceReference,
    ResourceType,
    SessionEventContract,
    SessionEventType,
    legacy_incident_alarm_role_mapping,
)

STARTED_AT = datetime(2026, 8, 4, 8, tzinfo=UTC)


def resource_reference():
    return ResourceReference(
        resource_type=ResourceType.NETWORK_PORT,
        business_code="PON-OLT-001-1-1",
        parent_code="OLT-001",
        resource_subtype="pon",
        technology="gpon",
    )


def test_causal_event_serializes_a_valid_ongoing_event_deterministically():
    event = CausalEventContract(
        event_code="CE-GPON-001",
        event_type=CausalEventType.PORT_FAILURE,
        status=CausalEventStatus.ACTIVE,
        started_at=STARTED_AT,
        source_system="synthetic_generator",
        origin=EventOrigin.SYNTHETIC,
        root_resource=resource_reference(),
        metadata={"raw": "internal-only"},
    )

    assert event.to_public_dict() == {
        "event_code": "CE-GPON-001",
        "event_type": "port_failure",
        "status": "active",
        "started_at": "2026-08-04T08:00:00+00:00",
        "ended_at": None,
        "source_system": "synthetic_generator",
        "origin": "synthetic",
        "root_resource": resource_reference().to_public_dict(),
    }


@pytest.mark.parametrize("ended_at", [STARTED_AT - timedelta(seconds=1), None])
def test_causal_event_rejects_invalid_resolved_times(ended_at):
    with pytest.raises(DomainValidationError):
        CausalEventContract(
            event_code="CE-001",
            event_type="device_failure",
            status="resolved",
            started_at=STARTED_AT,
            ended_at=ended_at,
            source_system="source",
            origin="imported",
        )


def test_causal_event_rejects_naive_datetime():
    with pytest.raises(DomainValidationError, match="timezone-aware"):
        CausalEventContract(
            event_code="CE-001",
            event_type="unknown",
            status="active",
            started_at=datetime(2026, 8, 4, 8),
            source_system="source",
            origin="imported",
        )


@pytest.mark.parametrize("event_type", ["start", "continue", "stop"])
def test_session_event_supports_the_three_normalized_event_types(event_type):
    event = SessionEventContract(
        external_event_id=f"SES-{event_type}",
        event_type=event_type,
        occurred_at=STARTED_AT,
        source_system="session_api",
        subscription_connection_code="SC-001",
    )

    assert event.to_public_dict()["event_type"] == event_type


def test_session_event_rejects_missing_reference_and_hides_sensitive_payload():
    with pytest.raises(DomainValidationError, match="reference"):
        SessionEventContract(
            external_event_id="SES-001",
            event_type=SessionEventType.STOP,
            occurred_at=STARTED_AT,
            source_system="session_api",
        )

    event = SessionEventContract(
        external_event_id="SES-002",
        event_type=SessionEventType.CONTINUE,
        occurred_at=STARTED_AT,
        source_system="session_api",
        subscription_code="SUB-001",
        session_identifier="private-session-id",
        subscriber_reference="private-subscriber-ref",
        raw_payload={"ip_address": "192.0.2.10", "token": "private"},
    )
    serialized = event.to_public_dict()
    assert "raw_payload" not in serialized
    assert "session_identifier" not in serialized
    assert "subscriber_reference" not in serialized
    assert "192.0.2.10" not in str(serialized)


def test_session_event_rejects_invalid_type_naive_and_out_of_order_timestamps():
    for event_type in ("invalid", SessionEventType.START):
        kwargs = {"event_type": event_type, "occurred_at": STARTED_AT}
        if event_type == SessionEventType.START:
            kwargs["occurred_at"] = datetime(2026, 8, 4, 8)
        with pytest.raises(DomainValidationError):
            SessionEventContract(
                external_event_id="SES-invalid",
                source_system="session_api",
                subscription_code="SUB-001",
                **kwargs,
            )
    with pytest.raises(DomainValidationError, match="received_at"):
        SessionEventContract(
            external_event_id="SES-order",
            event_type=SessionEventType.STOP,
            occurred_at=STARTED_AT,
            received_at=STARTED_AT - timedelta(seconds=1),
            source_system="session_api",
            subscription_code="SUB-001",
        )


def assessment(*, status="verified_impact", potential=True, reasons=("topology_match",)):
    return CustomerImpactAssessmentContract(
        causal_event_code="CE-001",
        status=status,
        potential_impact=potential,
        reasons=reasons,
        assessment_started_at=STARTED_AT,
        subscription_code="SUB-001",
        subscription_connection_code="SC-001",
        evidence_event_codes=("SES-002", "SES-001"),
    )


def test_impact_assessment_preserves_potential_to_verified_invariant():
    assert assessment().to_public_dict()["status"] == "verified_impact"
    with pytest.raises(DomainValidationError, match="potential impact"):
        assessment(potential=False)
    with pytest.raises(DomainValidationError, match="reference"):
        CustomerImpactAssessmentContract(
            causal_event_code="CE-001",
            status="potential_impact",
            potential_impact=True,
            reasons=("topology_match",),
            assessment_started_at=STARTED_AT,
        )


def test_no_impact_and_insufficient_evidence_are_distinct_assessments():
    no_impact = assessment(
        status=CustomerImpactStatus.VERIFIED_NO_IMPACT,
        reasons=(ImpactReason.SESSION_REMAINED_ACTIVE, ImpactReason.FAILOVER_PROTECTED),
    )
    insufficient = assessment(
        status=CustomerImpactStatus.INSUFFICIENT_EVIDENCE,
        reasons=(ImpactReason.MISSING_SESSION_EVIDENCE,),
    )
    assert no_impact.to_public_dict()["reasons"] == [
        "session_remained_active",
        "failover_protected",
    ]
    assert insufficient.to_public_dict()["status"] == "insufficient_evidence"
    with pytest.raises(DomainValidationError, match="requires at least one reason"):
        assessment(status="verified_no_impact", reasons=())


def test_correlation_contract_validates_roles_reasons_and_legacy_mapping():
    contract = AlarmCorrelationContract(
        alarm_code="ALM-001",
        role=CorrelationRole.CHILD,
        reasons=(CorrelationReason.TOPOLOGY_PARENT_CHILD,),
        resource=resource_reference(),
    )
    assert contract.to_public_dict()["role"] == "child"
    assert legacy_incident_alarm_role_mapping() == {
        "primary": "root",
        "supporting": "supporting",
        "correlated": "child",
    }
    with pytest.raises(DomainValidationError):
        AlarmCorrelationContract(alarm_code="ALM-002", role="invalid", reasons=())
    with pytest.raises(DomainValidationError, match="require at least one reason"):
        AlarmCorrelationContract(alarm_code="ALM-003", role="root", reasons=())


def test_resource_reference_requires_business_code_and_serialization_is_stable():
    with pytest.raises(DomainValidationError, match="business_code"):
        ResourceReference(resource_type="device", business_code="  ")
    first = assessment().to_public_dict()
    second = assessment().to_public_dict()
    assert first == second
    assert first["evidence_event_codes"] == ["SES-001", "SES-002"]
