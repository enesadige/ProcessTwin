from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.models import QueryRunStatus
from apps.orchestration.services import QueryRunError, QueryRunService, QueryRunTransitionError
from apps.orchestration.tool_plan import (
    MCP_TOOL_REGISTRIES,
    MCPServer,
    ToolCall,
    ToolCallKind,
    ToolPlan,
    get_tool_definition,
)


def structured_context(snapshot_identifier="multi-city-realism-v2-causal-r1"):
    return {
        "intent": "network_investigation",
        "requested_outputs": ["summary", "root_cause"],
        "snapshot_identifier": snapshot_identifier,
        "causal_event_code": "CE-GPON-001",
    }


def valid_calls(snapshot_identifier="multi-city-realism-v2-causal-r1"):
    return [
        {
            "call_id": "correlate",
            "server": "network",
            "tool_name": "correlate_alarms",
            "arguments": {
                "snapshot_identifier": snapshot_identifier,
                "causal_event_code": "CE-GPON-001",
            },
            "execution_order": 1,
        },
        {
            "call_id": "root_cause",
            "server": "network",
            "tool_name": "rank_root_cause_candidates",
            "arguments": {
                "snapshot_identifier": snapshot_identifier,
                "causal_event_code": "CE-GPON-001",
            },
            "depends_on": ["correlate"],
            "execution_order": 2,
        },
    ]


def valid_plan(**overrides):
    payload = {
        "snapshot_identifier": "multi-city-realism-v2-causal-r1",
        "structured_query_context": structured_context(),
        "calls": valid_calls(),
    }
    payload.update(overrides)
    return payload


def test_minimal_tool_plan_is_sorted_and_deterministic_without_mutating_input():
    payload = valid_plan(calls=list(reversed(valid_calls())))
    original = deepcopy(payload)

    plan = ToolPlan.model_validate(payload)

    assert payload == original
    assert [call.call_id for call in plan.calls] == ["correlate", "root_cause"]
    assert plan.to_planned_tools() == ToolPlan.model_validate(payload).to_planned_tools()


def test_current_mcp_registries_are_the_allowlist_source_and_keep_expected_counts():
    assert {server: len(tools) for server, tools in MCP_TOOL_REGISTRIES.items()} == {
        MCPServer.NETWORK: 12,
        MCPServer.CUSTOMER: 7,
        MCPServer.RULE: 8,
        MCPServer.COMPENSATION: 6,
    }
    for server, definitions in MCP_TOOL_REGISTRIES.items():
        for tool_name, definition in definitions.items():
            assert get_tool_definition(server, tool_name) is definition


@pytest.mark.parametrize(
    "payload",
    [
        valid_plan(calls=[]),
        valid_plan(calls=[{**valid_calls()[0], "server": "unknown"}]),
        valid_plan(calls=[{**valid_calls()[0], "tool_name": "unknown"}]),
        valid_plan(calls=[{**valid_calls()[0], "server": "rule"}]),
        valid_plan(calls=[{**valid_calls()[0], "arguments": {"id": 1}}]),
        valid_plan(calls=[{**valid_calls()[0], "arguments": {"raw_payload": {}}}]),
        valid_plan(calls=[{**valid_calls()[0], "arguments": {"authorization": "secret"}}]),
    ],
)
def test_invalid_server_tool_or_arguments_are_rejected_without_raw_input_leaks(payload):
    with pytest.raises(ValidationError) as exc_info:
        ToolPlan.model_validate(payload)
    assert "secret" not in str(exc_info.value)


def test_tool_arguments_use_own_mcp_input_model_and_preserve_snapshot_and_causal_event():
    call = ToolCall.model_validate(valid_calls()[0])

    assert call.arguments == {
        "snapshot_identifier": "multi-city-realism-v2-causal-r1",
        "causal_event_code": "CE-GPON-001",
        "limit": 50,
    }
    with pytest.raises(ValidationError):
        ToolCall.model_validate(
            {
                **valid_calls()[0],
                "arguments": {
                    "snapshot_identifier": "multi-city-realism-v2-causal-r1",
                    "outage_code": "OUT-MAL-001",
                },
            }
        )


def test_tool_plan_rejects_snapshot_or_structured_query_context_mismatch():
    with pytest.raises(ValidationError, match="snapshot"):
        ToolPlan.model_validate(valid_plan(snapshot_identifier="another-snapshot"))
    with pytest.raises(ValidationError, match="causal event"):
        ToolPlan.model_validate(
            valid_plan(
                calls=[
                    {
                        **valid_calls()[0],
                        "arguments": {
                            "snapshot_identifier": "multi-city-realism-v2-causal-r1",
                            "causal_event_code": "CE-OTHER-001",
                        },
                    }
                ]
            )
        )


def test_duplicate_calls_and_invalid_dependency_graphs_are_rejected():
    duplicate = valid_calls()
    duplicate[1] = {**duplicate[1], "call_id": "duplicate", "depends_on": []}
    duplicate.append({**duplicate[0], "call_id": "another_duplicate", "execution_order": 3})
    with pytest.raises(ValidationError, match="duplicate"):
        ToolPlan.model_validate(valid_plan(calls=duplicate))

    for replacement, message in [
        ({"depends_on": ["unknown"]}, "unknown"),
        ({"depends_on": ["correlate"]}, "itself"),
        ({"depends_on": ["root_cause"]}, "earlier"),
    ]:
        calls = valid_calls()
        calls[0] = {**calls[0], **replacement}
        with pytest.raises(ValidationError, match=message):
            ToolPlan.model_validate(valid_plan(calls=calls))


def test_parallel_group_requires_independent_calls_with_one_shared_group():
    calls = valid_calls()
    calls[1] = {**calls[1], "depends_on": [], "execution_order": 1, "parallel_group": "group_a"}
    calls[0] = {**calls[0], "parallel_group": "group_a"}
    plan = ToolPlan.model_validate(valid_plan(calls=calls))
    assert [call.parallel_group for call in plan.calls] == ["group_a", "group_a"]

    calls[1] = {**calls[1], "depends_on": ["correlate"], "execution_order": 2}
    with pytest.raises(ValidationError, match="parallel group"):
        ToolPlan.model_validate(valid_plan(calls=calls))


def test_rule_document_retrieval_is_marked_separately_from_deterministic_calls():
    plan = ToolPlan.model_validate(
        valid_plan(
            calls=[
                {
                    "call_id": "documents",
                    "server": "rule",
                    "tool_name": "search_rule_documents",
                    "arguments": {
                        "snapshot_identifier": "multi-city-realism-v2-causal-r1",
                        "query": "kesinti telafi kosullari",
                    },
                    "execution_order": 1,
                    "call_kind": "deterministic",
                }
            ]
        )
    )

    assert plan.calls[0].call_kind == ToolCallKind.DOCUMENT_RETRIEVAL


@pytest.mark.django_db
def test_valid_plan_is_saved_to_a_planned_query_run_idempotently():
    service = QueryRunService()
    snapshot = create_snapshot("tool-plan-service-001")
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="tool-plan-service-001",
        original_query="Kok nedeni incele.",
    )
    context = structured_context(snapshot.snapshot_key)
    service.save_structured_query(run, structured_query=context)
    plan = ToolPlan.model_validate(
        valid_plan(
            snapshot_identifier=snapshot.snapshot_key,
            structured_query_context=context,
            calls=valid_calls(snapshot.snapshot_key),
        )
    )

    saved = service.save_tool_plan(run, tool_plan=plan)
    repeated = service.save_tool_plan(saved, tool_plan=plan.model_dump(mode="json"))

    assert saved.status == QueryRunStatus.PLANNED
    assert saved.planned_tools == plan.to_planned_tools()
    assert repeated.pk == saved.pk


@pytest.mark.django_db
def test_tool_plan_rejects_overwrite_invalid_state_or_context_mismatch():
    service = QueryRunService()
    snapshot = create_snapshot("tool-plan-service-002")
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="tool-plan-service-002",
        original_query="Kok nedeni incele.",
    )
    context = structured_context(snapshot.snapshot_key)
    service.save_structured_query(run, structured_query=context)
    plan_payload = valid_plan(
        snapshot_identifier=snapshot.snapshot_key,
        structured_query_context=context,
        calls=valid_calls(snapshot.snapshot_key),
    )
    saved = service.save_tool_plan(run, tool_plan=plan_payload)

    changed_plan = deepcopy(plan_payload)
    changed_plan["calls"][1]["arguments"]["limit"] = 10
    with pytest.raises(QueryRunError) as exc_info:
        service.save_tool_plan(saved, tool_plan=changed_plan)
    assert exc_info.value.code == "query_run_tool_plan_immutable"

    pending, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="tool-plan-service-pending",
        original_query="Pending.",
    )
    with pytest.raises(QueryRunTransitionError):
        service.save_tool_plan(pending, tool_plan=plan_payload)

    failed = service.fail(saved, error_code="safe_failure", error_summary="Safe failure")
    with pytest.raises(QueryRunTransitionError):
        service.save_tool_plan(failed, tool_plan=plan_payload)
