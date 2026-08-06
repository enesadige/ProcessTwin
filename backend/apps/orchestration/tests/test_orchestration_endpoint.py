from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from django.test import Client

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.executor import (
    ExecutorResult,
    ExecutorStatus,
    ToolExecutionResult,
    ToolExecutionStatus,
)
from apps.orchestration.facade import OrchestrationFacade
from apps.orchestration.models import QueryRun, QueryRunStatus
from apps.orchestration.natural_language_intake import ParsedStructuredQuery
from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.mock import MockLLMProvider
from apps.orchestration.services import QueryRunService
from apps.orchestration.tool_plan import MCP_TOOL_REGISTRIES, ToolPlan

ENDPOINT = "/api/internal/v1/orchestration/queries/execute/"


class FakeExecutor:
    def __init__(self, *, fail_required: bool = False) -> None:
        self.calls = 0
        self.fail_required = fail_required

    def execute(self, query_run, tool_plan: ToolPlan) -> ExecutorResult:
        self.calls += 1
        QueryRunService().transition(query_run, target_status=QueryRunStatus.EXECUTING)
        results = []
        for call in tool_plan.calls:
            if self.fail_required and call.call_id == "customer_history":
                results.append(
                    ToolExecutionResult(
                        call_id=call.call_id,
                        server=call.server,
                        tool_name=call.tool_name,
                        status=ToolExecutionStatus.FAILED,
                        correlation_id=f"{query_run.request_id}:{call.call_id}",
                        attempt_count=1,
                        duration_ms=1,
                        error_code="executor_transport_error",
                        error_summary="safe failure",
                    )
                )
                continue
            results.append(self._success(query_run, call))
        succeeded = sum(item.status == ToolExecutionStatus.SUCCEEDED for item in results)
        return ExecutorResult(
            status=ExecutorStatus.SUCCEEDED
            if succeeded == len(results)
            else ExecutorStatus.PARTIAL,
            snapshot_identifier=tool_plan.snapshot_identifier,
            call_results=results,
            succeeded_count=succeeded,
            failed_count=len(results) - succeeded,
            skipped_count=0,
        )

    @staticmethod
    def _success(query_run, call) -> ToolExecutionResult:
        if call.tool_name in {"correlate_alarms", "rank_root_cause_candidates"}:
            data = {
                "causal_event_code": "CE-GPON-001",
                "root_resource_type": "device",
                "root_resource_reference": "OLT-001",
                "reason_codes": ["shared_upstream"],
                "role_counts": {"root": 1},
                "propagation_summary": "Upstream relationship verified.",
            }
        elif call.tool_name == "get_customer_outage_history":
            data = {
                "causal_event_code": "CE-GPON-001",
                "potential_connection_count": 2,
                "verified_impacted_count": 1,
                "verified_no_impact_count": 0,
                "insufficient_evidence_count": 0,
                "failover_protected_count": 1,
                "reason_code_distribution": {"session_stop_and_recovery_match": 1},
            }
        else:
            raise AssertionError(f"Unexpected fake tool call: {call.tool_name}")
        return ToolExecutionResult(
            call_id=call.call_id,
            server=call.server,
            tool_name=call.tool_name,
            status=ToolExecutionStatus.SUCCEEDED,
            correlation_id=f"{query_run.request_id}:{call.call_id}",
            attempt_count=1,
            duration_ms=1,
            safe_result_summary={"causal_event_code": "CE-GPON-001"},
            result_fingerprint=f"test-{call.call_id}",
            normalized_response={"data": data},
        )


class FailingNarrativeProvider(LLMProvider):
    provider_name = "test"
    model_name = "test-v1"
    supports_thinking = False
    thinking_enabled = False

    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        raise RuntimeError("provider must fall back")


class StubIntakeParser:
    def __init__(self, query):
        self.query = query
        self.calls = 0

    def parse(self, *, original_query, snapshot):
        self.calls += 1
        assert original_query
        assert snapshot.snapshot_key == self.query.snapshot_identifier
        return ParsedStructuredQuery(structured_query=self.query, missing_fields=())


def request_payload(snapshot_identifier: str, *, idempotency_key: str = "endpoint-key-001") -> dict:
    return {
        "snapshot_identifier": snapshot_identifier,
        "idempotency_key": idempotency_key,
        "original_query": "CUST-001 198.51.100.10 için kesinti özeti",
        "structured_query": {
            "intent": "outage_impact",
            "requested_outputs": ["summary", "root_cause", "impact"],
            "snapshot_identifier": snapshot_identifier,
            "causal_event_code": "CE-GPON-001",
        },
    }


def client_headers(settings) -> dict[str, str]:
    settings.INTERNAL_API_SERVICE_TOKEN = "test-service-token"
    return {"HTTP_AUTHORIZATION": "Bearer test-service-token", "HTTP_X_CORRELATION_ID": "e2e-060"}


def patch_facade(monkeypatch, facade: OrchestrationFacade) -> None:
    monkeypatch.setattr(
        "apps.orchestration.internal_views.get_orchestration_facade", lambda: facade
    )


@pytest.mark.django_db
def test_endpoint_requires_authentication_and_rejects_extra_fields(settings):
    snapshot = create_snapshot("endpoint-auth")
    payload = request_payload(snapshot.snapshot_key)
    client = Client()

    assert (
        client.post(ENDPOINT, data=json.dumps(payload), content_type="application/json").status_code
        == 401
    )
    payload["provider"] = "ollama"
    response = client.post(
        ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
        **client_headers(settings),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_endpoint_runs_complete_lifecycle_and_replays_without_new_tools(settings, monkeypatch):
    snapshot = create_snapshot("endpoint-success")
    executor = FakeExecutor()
    patch_facade(
        monkeypatch,
        OrchestrationFacade(executor=executor, response_provider=MockLLMProvider()),
    )
    payload = request_payload(snapshot.snapshot_key)
    client = Client()

    first = client.post(
        ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
        **client_headers(settings),
    )
    second = client.post(
        ENDPOINT,
        data=json.dumps({**payload, "response_mode": "llm_assisted"}),
        content_type="application/json",
        **client_headers(settings),
    )

    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    assert first.json()["response"]["generation_mode"] == "deterministic"
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert executor.calls == 1
    run = QueryRun.objects.get(idempotency_key=payload["idempotency_key"])
    assert run.status == QueryRunStatus.COMPLETED
    assert run.request_id == "e2e-060"
    assert run.final_result["validation_status"] == "valid"


@pytest.mark.django_db
def test_original_query_only_uses_intake_once_and_preserves_structured_replay(
    settings, monkeypatch
):
    snapshot = create_snapshot("endpoint-intake")
    query = request_payload(snapshot.snapshot_key)["structured_query"]
    from apps.orchestration.structured_query import StructuredQuery

    intake = StubIntakeParser(StructuredQuery.model_validate(query))
    executor = FakeExecutor()
    patch_facade(monkeypatch, OrchestrationFacade(executor=executor, intake_parser=intake))
    payload = request_payload(snapshot.snapshot_key, idempotency_key="endpoint-intake-001")
    payload.pop("structured_query")
    client = Client()

    first = client.post(
        ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
        **client_headers(settings),
    )
    replay_payload = {**payload, "structured_query": query}
    second = client.post(
        ENDPOINT,
        data=json.dumps(replay_payload),
        content_type="application/json",
        **client_headers(settings),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert intake.calls == 1
    assert executor.calls == 1


@pytest.mark.django_db
def test_intake_failure_never_reaches_executor(settings, monkeypatch):
    snapshot = create_snapshot("endpoint-intake-failure")
    executor = FakeExecutor()

    class FailingIntake:
        def parse(self, *, original_query, snapshot):
            from apps.orchestration.natural_language_intake import NaturalLanguageQueryParseError

            raise NaturalLanguageQueryParseError("query_parse_unavailable")

    patch_facade(monkeypatch, OrchestrationFacade(executor=executor, intake_parser=FailingIntake()))
    payload = request_payload(snapshot.snapshot_key, idempotency_key="endpoint-intake-failure-001")
    payload.pop("structured_query")
    response = Client().post(
        ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
        **client_headers(settings),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "query_parse_unavailable"
    assert executor.calls == 0


@pytest.mark.django_db
def test_llm_fallback_is_successful_and_does_not_leak_query_data(settings, monkeypatch):
    snapshot = create_snapshot("endpoint-fallback")
    patch_facade(
        monkeypatch,
        OrchestrationFacade(executor=FakeExecutor(), response_provider=FailingNarrativeProvider()),
    )
    payload = {**request_payload(snapshot.snapshot_key), "response_mode": "llm_assisted"}
    response = Client().post(
        ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
        **client_headers(settings),
    )

    serialized = json.dumps(response.json())
    assert response.status_code == 200
    assert response.json()["response"]["generation_mode"] == "deterministic_fallback"
    for value in ("CUST-001", "198.51.100.10", "test-service-token", "provider must fall back"):
        assert value not in serialized


@pytest.mark.django_db
def test_clarification_and_unplannable_do_not_execute_tools(settings, monkeypatch):
    snapshot = create_snapshot("endpoint-clarification")
    executor = FakeExecutor()
    patch_facade(monkeypatch, OrchestrationFacade(executor=executor))
    clarification = request_payload(snapshot.snapshot_key, idempotency_key="endpoint-clarify-001")
    clarification["structured_query"] = {
        "intent": "rule_document_retrieval",
        "requested_outputs": ["summary"],
        "snapshot_identifier": snapshot.snapshot_key,
        "clarification_required": True,
        "clarification_reasons": ["missing_scope_filter"],
    }
    unplannable = request_payload(snapshot.snapshot_key, idempotency_key="endpoint-unplannable-001")
    unplannable["structured_query"] = {
        "intent": "compensation_evaluation",
        "requested_outputs": ["compensation_amount"],
        "snapshot_identifier": snapshot.snapshot_key,
        "causal_event_code": "CE-GPON-001",
    }
    client = Client()

    clarification_response = client.post(
        ENDPOINT,
        data=json.dumps(clarification),
        content_type="application/json",
        **client_headers(settings),
    )
    unplannable_response = client.post(
        ENDPOINT,
        data=json.dumps(unplannable),
        content_type="application/json",
        **client_headers(settings),
    )

    assert clarification_response.status_code == 422
    assert clarification_response.json()["clarification"]["code"] == "clarification_required"
    assert unplannable_response.status_code == 422
    assert unplannable_response.json()["error"]["code"] == "planner_unplannable"
    assert executor.calls == 0
    assert (
        QueryRun.objects.get(idempotency_key="endpoint-clarify-001").status
        == QueryRunStatus.PLANNED
    )


@pytest.mark.django_db
def test_failed_and_executing_replays_never_reexecute_or_expose_details(settings, monkeypatch):
    snapshot = create_snapshot("endpoint-replay")
    failing_executor = FakeExecutor(fail_required=True)
    patch_facade(monkeypatch, OrchestrationFacade(executor=failing_executor))
    payload = request_payload(snapshot.snapshot_key, idempotency_key="endpoint-failed-001")
    client = Client()
    failed = client.post(
        ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
        **client_headers(settings),
    )
    replay = client.post(
        ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
        **client_headers(settings),
    )
    assert failed.status_code == 503
    assert replay.status_code == 422
    assert replay.json()["replayed"] is True
    assert replay.json()["error"]["retry_requires_new_idempotency_key"] is True
    assert failing_executor.calls == 1

    run, _ = QueryRunService().create_or_get(
        data_snapshot=snapshot,
        idempotency_key="endpoint-executing-001",
        original_query="safe",
    )
    pending_query = request_payload(snapshot.snapshot_key, idempotency_key="endpoint-executing-001")
    QueryRunService().save_structured_query(run, structured_query=pending_query["structured_query"])
    QueryRunService().transition(run, target_status=QueryRunStatus.EXECUTING)
    payload = pending_query
    in_progress = client.post(
        ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
        **client_headers(settings),
    )
    assert in_progress.status_code == 202


@pytest.mark.django_db
def test_snapshot_and_structured_query_idempotency_conflicts(settings, monkeypatch):
    snapshot = create_snapshot("endpoint-conflict")
    executor = FakeExecutor()
    patch_facade(monkeypatch, OrchestrationFacade(executor=executor))
    payload = request_payload(snapshot.snapshot_key, idempotency_key="endpoint-conflict-001")
    client = Client()
    first = client.post(
        ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
        **client_headers(settings),
    )
    changed = request_payload(snapshot.snapshot_key, idempotency_key="endpoint-conflict-001")
    changed["structured_query"] = {
        **changed["structured_query"],
        "requested_outputs": ["summary", "root_cause"],
    }
    conflict = client.post(
        ENDPOINT,
        data=json.dumps(changed),
        content_type="application/json",
        **client_headers(settings),
    )
    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert executor.calls == 1


def test_mcp_tool_counts_remain_unchanged():
    assert {server.value: len(tools) for server, tools in MCP_TOOL_REGISTRIES.items()} == {
        "network": 9,
        "customer": 7,
        "rule": 8,
        "compensation": 6,
    }
