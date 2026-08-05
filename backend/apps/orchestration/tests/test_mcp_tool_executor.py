from __future__ import annotations

from copy import deepcopy

import pytest
from mcp_servers.shared.contracts import MCPError, MCPErrorCode, MCPMetadata, MCPToolResponse

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.executor import ExecutorStatus, ToolExecutionStatus, ToolExecutor
from apps.orchestration.models import QueryRunStatus
from apps.orchestration.services import QueryRunError, QueryRunService
from apps.orchestration.tool_plan import MCPServer, ToolPlan


class FakeRunner:
    def __init__(self, *, server: MCPServer, outcomes=None):
        self.server = server
        self.outcomes = outcomes or {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def run(self, tool_name: str, arguments: dict[str, object] | None):
        values = deepcopy(arguments or {})
        self.calls.append((tool_name, values))
        outcome = self.outcomes.get(tool_name, True)
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        request_id = values.get("request_id")
        metadata = MCPMetadata(
            tool_name=f"{self.server.value}.{tool_name}",
            tool_version="test",
            request_id=request_id,
            deterministic=True,
            snapshot_identifier=values.get("snapshot_identifier"),
        )
        if isinstance(outcome, MCPError):
            return MCPToolResponse(success=False, error=outcome, metadata=metadata)
        return MCPToolResponse(
            success=True,
            data={
                "causal_event_code": values.get("causal_event_code"),
                "count": 2,
                "customer_number": "CUST-SECRET",
                "raw_payload": {"token": "never-store"},
            },
            metadata=metadata,
        )


def query_context(snapshot_identifier: str, **overrides: object) -> dict[str, object]:
    context: dict[str, object] = {
        "intent": "network_investigation",
        "requested_outputs": ["summary", "root_cause"],
        "snapshot_identifier": snapshot_identifier,
        "causal_event_code": "CE-GPON-001",
    }
    context.update(overrides)
    return context


def call(
    call_id: str,
    server: str,
    tool_name: str,
    arguments: dict[str, object],
    execution_order: int = 1,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "call_id": call_id,
        "server": server,
        "tool_name": tool_name,
        "arguments": arguments,
        "execution_order": execution_order,
    }
    payload.update(overrides)
    return payload


def build_plan(snapshot_identifier: str, calls: list[dict[str, object]]) -> ToolPlan:
    return ToolPlan.model_validate(
        {
            "snapshot_identifier": snapshot_identifier,
            "structured_query_context": query_context(snapshot_identifier),
            "calls": calls,
        }
    )


def create_planned_run(snapshot, plan: ToolPlan):
    service = QueryRunService()
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key=f"executor-{snapshot.snapshot_key}",
        original_query="Nedensel olayi incele.",
        request_id="executor-request-001",
    )
    service.save_structured_query(run, structured_query=plan.structured_query_context)
    service.save_tool_plan(run, tool_plan=plan)
    return run


def make_runners(outcomes=None):
    outcomes = outcomes or {}
    return {
        server: FakeRunner(server=server, outcomes=outcomes.get(server, {}))
        for server in MCPServer
    }


@pytest.mark.django_db
def test_executor_routes_all_allowlisted_servers_with_safe_audit_records():
    seed = "executor-routing-001"
    snapshot = create_snapshot(seed)
    snapshot_identifier = snapshot.snapshot_key
    arguments = {"snapshot_identifier": snapshot_identifier, "causal_event_code": "CE-GPON-001"}
    plan = build_plan(
        snapshot_identifier,
        [
            call("network", "network", "correlate_alarms", arguments, parallel_group="all"),
            call(
                "customer",
                "customer",
                "get_customer_outage_history",
                arguments,
                parallel_group="all",
            ),
            call("rule", "rule", "get_rule_evidence", arguments, parallel_group="all"),
            call(
                "compensation",
                "compensation",
                "get_compensation_evidence",
                arguments,
                parallel_group="all",
            ),
        ],
    )
    run = create_planned_run(snapshot, plan)
    runners = make_runners()

    result = ToolExecutor(tool_runners=runners).execute(run, plan)

    run.refresh_from_db()
    assert result.status == ExecutorStatus.SUCCEEDED
    assert result.succeeded_count == 4
    assert run.status == QueryRunStatus.EXECUTING
    assert {server: len(runner.calls) for server, runner in runners.items()} == {
        server: 1 for server in MCPServer
    }
    assert all(
        arguments["request_id"].startswith("executor-request-001:")
        for runner in runners.values()
        for _, arguments in runner.calls
    )
    assert len(run.executed_tools) == 4
    serialized_audit = str(run.executed_tools)
    assert "CUST-SECRET" not in serialized_audit
    assert "never-store" not in serialized_audit
    assert all("result_fingerprint" in record for record in run.executed_tools)


@pytest.mark.django_db
def test_executor_honors_dependencies_and_continues_independent_calls():
    seed = "executor-dependency-001"
    snapshot = create_snapshot(seed)
    snapshot_identifier = snapshot.snapshot_key
    outage_args = {"snapshot_identifier": snapshot_identifier, "outage_code": "OUT-MAL-001"}
    plan = build_plan(
        snapshot_identifier,
        [
            call("details", "network", "get_outage_details", outage_args, parallel_group="first"),
            call(
                "root",
                "network",
                "rank_root_cause_candidates",
                outage_args,
                parallel_group="first",
            ),
            call(
                "impact",
                "network",
                "calculate_customer_impact",
                outage_args,
                execution_order=2,
                depends_on=["details"],
            ),
        ],
    )
    run = create_planned_run(snapshot, plan)
    runners = make_runners(
        {
            MCPServer.NETWORK: {
                "get_outage_details": MCPError(
                    code=MCPErrorCode.TIMEOUT,
                    message="secret timeout", retryable=False
                )
            }
        }
    )

    result = ToolExecutor(tool_runners=runners).execute(run, plan)

    by_call = {record.call_id: record for record in result.call_results}
    assert result.status == ExecutorStatus.PARTIAL
    assert by_call["details"].status == ToolExecutionStatus.FAILED
    assert by_call["root"].status == ToolExecutionStatus.SUCCEEDED
    assert by_call["impact"].status == ToolExecutionStatus.SKIPPED_DEPENDENCY_FAILED
    assert [name for name, _ in runners[MCPServer.NETWORK].calls] == [
        "get_outage_details",
        "rank_root_cause_candidates",
    ]


@pytest.mark.django_db
def test_executor_retries_only_explicit_retryable_calls_and_resumes_without_duplicates():
    seed = "executor-retry-001"
    snapshot = create_snapshot(seed)
    snapshot_identifier = snapshot.snapshot_key
    arguments = {"snapshot_identifier": snapshot_identifier, "causal_event_code": "CE-GPON-001"}
    plan = build_plan(
        snapshot_identifier,
        [call("correlate", "network", "correlate_alarms", arguments)],
    )
    run = create_planned_run(snapshot, plan)
    runners = make_runners(
        {
            MCPServer.NETWORK: {
                "correlate_alarms": [
                    MCPError(code=MCPErrorCode.TIMEOUT, message="temporary", retryable=True),
                    True,
                ]
            }
        }
    )
    executor = ToolExecutor(tool_runners=runners, max_attempts=2)

    first = executor.execute(run, plan)
    second = executor.execute(run, plan)

    run.refresh_from_db()
    assert first.status == second.status == ExecutorStatus.SUCCEEDED
    assert first.call_results[0].attempt_count == 2
    assert len(runners[MCPServer.NETWORK].calls) == 2
    assert len(run.executed_tools) == 1


@pytest.mark.django_db
def test_executor_rejects_unpersisted_or_terminal_plan_without_calling_tools():
    seed = "executor-validation-001"
    snapshot = create_snapshot(seed)
    snapshot_identifier = snapshot.snapshot_key
    arguments = {"snapshot_identifier": snapshot_identifier, "causal_event_code": "CE-GPON-001"}
    plan = build_plan(
        snapshot_identifier,
        [call("correlate", "network", "correlate_alarms", arguments)],
    )
    service = QueryRunService()
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="executor-validation-001",
        original_query="Nedensel olayi incele.",
    )
    service.save_structured_query(run, structured_query=plan.structured_query_context)
    runners = make_runners()

    with pytest.raises(QueryRunError, match="audit record"):
        ToolExecutor(tool_runners=runners).execute(run, plan)
    run.refresh_from_db()
    assert run.status == QueryRunStatus.PLANNED
    assert run.executed_tools == []
    assert not any(runner.calls for runner in runners.values())

    service.fail(run, error_code="planned_failure", error_summary="safe")
    with pytest.raises(QueryRunError, match="Terminal"):
        ToolExecutor(tool_runners=runners).execute(run, plan)
    assert not any(runner.calls for runner in runners.values())
