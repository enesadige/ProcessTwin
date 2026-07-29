from datetime import datetime
from typing import Literal

import pytest
from mcp_servers.shared import (
    BaseMCPInput,
    MCPError,
    MCPErrorCode,
    MCPEvidence,
    MCPMetadata,
    MCPToolResponse,
    MCPWarning,
    TemporalMCPInput,
)
from pydantic import BaseModel, ValidationError


class SamplePayload(BaseModel):
    outage_code: str
    affected_subscription_count: int
    status: Literal["eligible", "ineligible", "manual_review"]


def test_successful_response_accepts_data_without_error():
    response = MCPToolResponse[SamplePayload](
        success=True,
        data=SamplePayload(
            outage_code="OUT-MAL-BNG-001",
            affected_subscription_count=150,
            status="eligible",
        ),
        metadata=metadata(),
    )

    assert response.success is True
    assert response.error is None
    assert response.data.outage_code == "OUT-MAL-BNG-001"
    assert response.metadata.deterministic is True


def test_error_response_accepts_error_without_data():
    response = MCPToolResponse[SamplePayload](
        success=False,
        error=MCPError(
            code=MCPErrorCode.NOT_FOUND,
            message="Outage was not found.",
            details={"outage_code": "OUT-MAL-UNKNOWN"},
            retryable=False,
        ),
        metadata=metadata(),
    )

    assert response.success is False
    assert response.data is None
    assert response.error.code == MCPErrorCode.NOT_FOUND
    assert response.error.details == {"outage_code": "OUT-MAL-UNKNOWN"}


def test_successful_response_rejects_error_or_missing_data():
    with pytest.raises(ValidationError, match="successful MCP responses cannot include error"):
        MCPToolResponse[SamplePayload](
            success=True,
            data=SamplePayload(
                outage_code="OUT-MAL-BNG-001",
                affected_subscription_count=150,
                status="eligible",
            ),
            error=MCPError(code=MCPErrorCode.INTERNAL_ERROR, message="Unexpected error."),
            metadata=metadata(),
        )

    with pytest.raises(ValidationError, match="successful MCP responses must include data"):
        MCPToolResponse[SamplePayload](
            success=True,
            metadata=metadata(),
        )


def test_failed_response_rejects_data_or_missing_error():
    with pytest.raises(ValidationError, match="failed MCP responses cannot include data"):
        MCPToolResponse[SamplePayload](
            success=False,
            data=SamplePayload(
                outage_code="OUT-MAL-BNG-001",
                affected_subscription_count=150,
                status="eligible",
            ),
            error=MCPError(code=MCPErrorCode.INTERNAL_ERROR, message="Unexpected error."),
            metadata=metadata(),
        )

    with pytest.raises(ValidationError, match="failed MCP responses must include error"):
        MCPToolResponse[SamplePayload](
            success=False,
            metadata=metadata(),
        )


def test_json_serialize_deserialize_round_trip_with_generic_payload():
    original = MCPToolResponse[SamplePayload](
        success=True,
        data=SamplePayload(
            outage_code="OUT-MAL-BNG-001",
            affected_subscription_count=150,
            status="eligible",
        ),
        metadata=metadata(),
        warnings=[
            MCPWarning(
                code="deferred_check",
                message="Payment history is outside MVP scope.",
                details={"deferred_model": "PaymentRecord"},
            )
        ],
        evidence=[
            MCPEvidence(
                evidence_type="outage",
                reference="OUT-MAL-BNG-001",
                description="Main BNG outage.",
                attributes={"duration_seconds": 12000},
            )
        ],
    )

    payload = original.model_dump_json()
    restored = MCPToolResponse[SamplePayload].model_validate_json(payload)

    assert restored == original
    assert restored.warnings[0].details["deferred_model"] == "PaymentRecord"
    assert restored.evidence[0].attributes["duration_seconds"] == 12000


def test_metadata_accepts_timezone_aware_datetime_and_rejects_naive_datetime():
    aware = datetime.fromisoformat("2026-07-20T10:15:00+03:00")

    accepted = MCPMetadata(
        tool_name="network.get_longest_outage",
        tool_version="0.1.0",
        deterministic=True,
        reference_datetime=aware,
        evaluation_time=aware,
    )

    assert accepted.reference_datetime == aware
    assert accepted.evaluation_time == aware
    with pytest.raises(ValidationError, match="timezone-aware"):
        MCPMetadata(
            tool_name="network.get_longest_outage",
            tool_version="0.1.0",
            deterministic=True,
            evaluation_time=datetime(2026, 7, 20, 10, 15),
        )


def test_temporal_input_accepts_timezone_aware_datetime_and_rejects_naive_datetime():
    aware = datetime.fromisoformat("2026-07-20T10:15:00+03:00")

    accepted = TemporalMCPInput(
        request_id="req-001",
        snapshot_identifier="maltepe-mvp-v1",
        evaluation_time=aware,
    )

    assert accepted.evaluation_time == aware
    with pytest.raises(ValidationError, match="timezone-aware"):
        TemporalMCPInput(evaluation_time=datetime(2026, 7, 20, 10, 15))


def test_base_input_allows_optional_request_and_snapshot_identifiers():
    empty = BaseMCPInput()
    populated = BaseMCPInput(request_id="req-001", snapshot_identifier="maltepe-mvp-v1")

    assert empty.request_id is None
    assert empty.snapshot_identifier is None
    assert populated.request_id == "req-001"
    assert populated.snapshot_identifier == "maltepe-mvp-v1"


def test_metadata_error_warning_and_evidence_schema_validation():
    error = MCPError(
        code="validation_error",
        message="Invalid input.",
        details={"field": "evaluation_time"},
        retryable=False,
    )
    warning = MCPWarning(code="partial_evidence", message="Some evidence is deferred.")
    evidence = MCPEvidence(
        evidence_type="rule_version",
        reference="REFUND-001:v2",
        description="Rule version selected at outage start.",
        attributes={"selected_at": "2026-07-20T10:15:00+03:00"},
    )

    assert error.code == MCPErrorCode.VALIDATION_ERROR
    assert warning.details == {}
    assert evidence.reference == "REFUND-001:v2"
    assert evidence.attributes["selected_at"] == "2026-07-20T10:15:00+03:00"


def test_all_shared_models_generate_json_schema():
    models = [
        BaseMCPInput,
        TemporalMCPInput,
        MCPError,
        MCPWarning,
        MCPEvidence,
        MCPMetadata,
        MCPToolResponse[SamplePayload],
    ]

    for model in models:
        schema = model.model_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema


def metadata() -> MCPMetadata:
    return MCPMetadata(
        tool_name="network.get_customer_impact",
        tool_version="0.1.0",
        request_id="req-001",
        deterministic=True,
        snapshot_identifier="maltepe-mvp-v1",
        reference_datetime=datetime.fromisoformat("2026-08-01T00:00:00+03:00"),
        evaluation_time=datetime.fromisoformat("2026-07-20T10:15:00+03:00"),
    )
