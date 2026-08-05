from __future__ import annotations

import socket

import pytest

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.models import QueryRunStatus
from apps.orchestration.planner import DeterministicToolPlanner, PlannerResultStatus
from apps.orchestration.services import QueryRunService
from apps.orchestration.structured_query import StructuredQuery
from apps.orchestration.tool_plan import MCP_TOOL_REGISTRIES, MCPServer


def _query_payload(snapshot_identifier: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "intent": "network_investigation",
        "requested_outputs": ["summary", "root_cause"],
        "snapshot_identifier": snapshot_identifier,
        "causal_event_code": "CE-GPON-001",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_query_run_to_tool_plan_integration_is_idempotent_and_offline(monkeypatch):
    def fail_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("The 052-056 integration chain must not use the network.")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    snapshot = create_snapshot("orchestration-gate-001")
    service = QueryRunService()
    run, created = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="orchestration-gate-001",
        original_query="Nedensel olayi incele.",
    )
    assert created is True

    query = StructuredQuery.model_validate(_query_payload(snapshot.snapshot_key))
    service.save_structured_query(run, structured_query=query)
    first = DeterministicToolPlanner().plan_and_save(run, query)
    repeated = DeterministicToolPlanner().plan_and_save(run, query)

    run.refresh_from_db()
    assert first.status == repeated.status == PlannerResultStatus.PLANNED
    assert first.tool_plan is not None
    assert run.status == QueryRunStatus.PLANNED
    assert run.data_snapshot_id == snapshot.id
    assert run.structured_query["snapshot_identifier"] == snapshot.snapshot_key
    assert run.structured_query["causal_event_code"] == "CE-GPON-001"
    assert run.planned_tools == first.tool_plan.to_planned_tools()

    assert {call["arguments"]["snapshot_identifier"] for call in run.planned_tools} == {
        snapshot.snapshot_key
    }
    assert {call["arguments"]["causal_event_code"] for call in run.planned_tools} == {
        "CE-GPON-001"
    }
    assert {
        server: len(definitions) for server, definitions in MCP_TOOL_REGISTRIES.items()
    } == {
        MCPServer.NETWORK: 9,
        MCPServer.CUSTOMER: 7,
        MCPServer.RULE: 8,
        MCPServer.COMPENSATION: 6,
    }


@pytest.mark.django_db
def test_planner_clarification_leaves_query_run_unchanged():
    snapshot = create_snapshot("orchestration-gate-002")
    service = QueryRunService()
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="orchestration-gate-002",
        original_query="Belirsiz inceleme.",
    )
    valid_query = StructuredQuery.model_validate(_query_payload(snapshot.snapshot_key))
    service.save_structured_query(run, structured_query=valid_query)

    result = DeterministicToolPlanner().plan_and_save(
        run,
        _query_payload(
            snapshot.snapshot_key,
            causal_event_code=None,
            requested_outputs=[],
            clarification_required=True,
            clarification_reasons=["missing_scope_filter"],
        ),
    )

    run.refresh_from_db()
    assert result.status == PlannerResultStatus.CLARIFICATION_REQUIRED
    assert run.status == QueryRunStatus.PLANNED
    assert run.planned_tools == []
