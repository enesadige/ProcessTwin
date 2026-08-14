from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.models import QueryRun, QueryRunStatus
from apps.orchestration.services import QueryRunError, QueryRunService, QueryRunTransitionError
from apps.orchestration.structured_query import (
    ClarificationReason,
    RequestedOutput,
    StructuredQuery,
    StructuredQueryIntent,
    Technology,
)

SNAPSHOT_IDENTIFIER = "multi-city-realism-v2-causal-r1"


def valid_query(**overrides):
    payload = {
        "intent": "network_investigation",
        "requested_outputs": ["summary", "root_cause"],
        "snapshot_identifier": SNAPSHOT_IDENTIFIER,
        "causal_event_code": "CE-GPON-001",
    }
    payload.update(overrides)
    return payload


def test_minimal_valid_query_is_deterministic_and_serializes_without_nulls():
    first = StructuredQuery.model_validate(valid_query())
    second = StructuredQuery.model_validate(
        valid_query(requested_outputs=["root_cause", "summary", "summary"])
    )

    assert first.intent == StructuredQueryIntent.NETWORK_INVESTIGATION
    assert first.requested_outputs == [RequestedOutput.ROOT_CAUSE, RequestedOutput.SUMMARY]
    assert first.to_audit_dict() == second.to_audit_dict()
    assert "incident_code" not in first.to_audit_dict()


@pytest.mark.parametrize("intent", list(StructuredQueryIntent))
def test_all_allowlisted_intents_are_accepted_with_a_safe_scope(intent):
    query = StructuredQuery.model_validate(valid_query(intent=intent.value))

    assert query.intent == intent


@pytest.mark.parametrize("requested_output", list(RequestedOutput))
def test_all_allowlisted_requested_outputs_are_accepted(requested_output):
    query = StructuredQuery.model_validate(
        valid_query(requested_outputs=[requested_output.value])
    )

    assert query.requested_outputs == [requested_output]


@pytest.mark.parametrize("technology", list(Technology))
def test_all_allowlisted_technologies_are_accepted(technology):
    query = StructuredQuery.model_validate(valid_query(technology=technology.value))

    assert query.technology == technology


@pytest.mark.parametrize(
    "payload",
    [
        valid_query(intent="unknown"),
        valid_query(requested_outputs=["summary", "arbitrary_output"]),
        valid_query(technology="unknown"),
        {key: value for key, value in valid_query().items() if key != "snapshot_identifier"},
        valid_query(id=123),
        valid_query(tool_name="network.search_alarms"),
        valid_query(raw_alarm_payload={"private": True}),
    ],
)
def test_invalid_or_sensitive_fields_are_rejected(payload):
    with pytest.raises(ValidationError) as exc_info:
        StructuredQuery.model_validate(payload)
    assert "private" not in str(exc_info.value)


def test_location_text_and_technology_are_normalized_without_control_characters():
    query = StructuredQuery.model_validate(
        valid_query(
            causal_event_code=None,
            location={"city": "  Istanbul ", "district": " Maltepe "},
            technology="GPON",
        )
    )

    assert query.location is not None
    assert query.location.city == "Istanbul"
    assert query.location.district == "Maltepe"
    assert query.technology.value == "GPON"

    with pytest.raises(ValidationError):
        StructuredQuery.model_validate(valid_query(location={"city": "Bad\nvalue"}))


def test_rule_document_retrieval_query_is_normalized_and_control_characters_are_rejected():
    query = StructuredQuery.model_validate(
        valid_query(
            intent="rule_document_retrieval",
            retrieval_query="  failover protected bağlantı  ",
        )
    )
    assert query.retrieval_query == "failover protected bağlantı"

    with pytest.raises(ValidationError):
        StructuredQuery.model_validate(
            valid_query(intent="rule_document_retrieval", retrieval_query="bad\nquery")
        )


def test_operational_anchor_priority_rejects_ambiguous_multiple_references():
    with pytest.raises(ValidationError, match="Only one operational reference"):
        StructuredQuery.model_validate(valid_query(incident_code="INC-MAL-001"))

    query = StructuredQuery.model_validate(
        valid_query(causal_event_code=None, outage_code="OUT-MAL-001")
    )
    assert query.outage_code == "OUT-MAL-001"


@pytest.mark.parametrize(
    "time_window",
    [
        {"from_time": datetime(2026, 1, 1, tzinfo=UTC)},
        {
            "from_time": datetime(2026, 1, 1, tzinfo=UTC),
            "to_time": datetime(2026, 1, 2, tzinfo=UTC),
        },
    ],
)
def test_timezone_aware_time_windows_are_accepted(time_window):
    query = StructuredQuery.model_validate(
        valid_query(causal_event_code=None, time_window=time_window)
    )
    assert query.time_window is not None


@pytest.mark.parametrize(
    "time_window",
    [
        {"from_time": datetime(2026, 1, 1)},
        {
            "from_time": datetime(2026, 1, 2, tzinfo=UTC),
            "to_time": datetime(2026, 1, 1, tzinfo=UTC),
        },
    ],
)
def test_naive_or_reversed_time_windows_are_rejected(time_window):
    with pytest.raises(ValidationError):
        StructuredQuery.model_validate(valid_query(causal_event_code=None, time_window=time_window))


def test_clarification_is_explicit_and_allowlisted():
    query = StructuredQuery.model_validate(
        valid_query(
            causal_event_code=None,
            requested_outputs=[],
            clarification_required=True,
            clarification_reasons=[
                ClarificationReason.MISSING_REQUESTED_OUTPUT,
                ClarificationReason.MISSING_SCOPE_FILTER,
            ],
        )
    )

    assert query.clarification_required is True
    assert query.clarification_reasons == [
        ClarificationReason.MISSING_REQUESTED_OUTPUT,
        ClarificationReason.MISSING_SCOPE_FILTER,
    ]

    with pytest.raises(ValidationError):
        StructuredQuery.model_validate(valid_query(clarification_reasons=["missing_scope_filter"]))


def test_compensation_without_anchor_requires_clarification_or_fails():
    with pytest.raises(ValidationError, match="compensation evaluation requires"):
        StructuredQuery.model_validate(
            valid_query(intent="compensation_evaluation", causal_event_code=None)
        )

    query = StructuredQuery.model_validate(
        valid_query(
            intent="compensation_evaluation",
            causal_event_code=None,
            clarification_required=True,
            clarification_reasons=["compensation_anchor_required"],
        )
    )
    assert query.clarification_required is True


@pytest.mark.django_db
def test_valid_structured_query_moves_pending_run_to_planned_and_is_idempotent():
    service = QueryRunService()
    snapshot = create_snapshot("structured-query-service-001")
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="structured-query-service-001",
        original_query="Kok nedeni incele.",
    )
    input_mapping = valid_query(snapshot_identifier=snapshot.snapshot_key)

    planned = service.save_structured_query(run, structured_query=input_mapping)
    repeated = service.save_structured_query(
        planned,
        structured_query=StructuredQuery.model_validate(input_mapping),
    )

    assert input_mapping == valid_query(snapshot_identifier=snapshot.snapshot_key)
    assert planned.status == QueryRunStatus.PLANNED
    assert planned.planned_tools == []
    assert planned.structured_query["causal_event_code"] == "CE-GPON-001"
    assert repeated.pk == planned.pk


@pytest.mark.django_db
def test_semantic_dimensions_can_replace_planned_query_before_tool_plan():
    service = QueryRunService()
    snapshot = create_snapshot("structured-query-semantic-001")
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="structured-query-semantic-001",
        original_query="Kok neden ve musteri etkisini incele.",
    )
    planned = service.save_structured_query(
        run,
        structured_query=valid_query(snapshot_identifier=snapshot.snapshot_key),
    )
    semantic_query = StructuredQuery.model_validate(
        valid_query(
            snapshot_identifier=snapshot.snapshot_key,
            requested_outputs=["summary", "root_cause", "impact"],
            semantic_dimensions=["verified_customer_impact"],
            semantic_decomposition_status="accepted",
        )
    )

    replaced = service.replace_structured_query_before_plan(
        planned,
        structured_query=semantic_query,
        parser_version="deterministic+semantic",
    )

    assert replaced.status == QueryRunStatus.PLANNED
    assert replaced.planned_tools == []
    assert replaced.structured_query["semantic_decomposition_status"] == "accepted"
    assert replaced.structured_query_parser_version == "deterministic+semantic"


@pytest.mark.django_db
def test_invalid_query_leaves_run_pending_and_terminal_runs_cannot_be_changed():
    service = QueryRunService()
    snapshot = create_snapshot("structured-query-service-002")
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="structured-query-service-002",
        original_query="Kok nedeni incele.",
    )

    with pytest.raises(ValidationError):
        service.save_structured_query(run, structured_query=valid_query(intent="unknown"))
    run.refresh_from_db()
    assert run.status == QueryRunStatus.PENDING
    assert run.structured_query == {}

    failed = service.fail(run, error_code="safe_failure", error_summary="Safe failure")
    with pytest.raises(QueryRunTransitionError):
        service.save_structured_query(
            failed,
            structured_query=valid_query(snapshot_identifier=snapshot.snapshot_key),
        )
    assert QueryRun.objects.get(pk=failed.pk).status == QueryRunStatus.FAILED


@pytest.mark.django_db
def test_query_run_rejects_a_valid_structured_query_for_another_snapshot():
    service = QueryRunService()
    snapshot = create_snapshot("structured-query-service-003")
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="structured-query-service-003",
        original_query="Kok nedeni incele.",
    )

    with pytest.raises(QueryRunError) as exc_info:
        service.save_structured_query(run, structured_query=valid_query())
    assert exc_info.value.code == "structured_query_snapshot_mismatch"
    run.refresh_from_db()
    assert run.status == QueryRunStatus.PENDING
