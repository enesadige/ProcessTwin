from __future__ import annotations

import socket

import pytest

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.models import QueryRunStatus
from apps.orchestration.planner import (
    DeterministicToolPlanner,
    PlannerReasonCode,
    PlannerResultStatus,
)
from apps.orchestration.services import QueryRunService
from apps.orchestration.structured_query import StructuredQuery
from apps.orchestration.tool_plan import MCP_TOOL_REGISTRIES, ToolPlan


def query_payload(**overrides):
    payload = {
        "intent": "network_investigation",
        "requested_outputs": ["summary", "root_cause"],
        "snapshot_identifier": "multi-city-realism-v2-causal-r1",
        "causal_event_code": "CE-GPON-001",
    }
    payload.update(overrides)
    return payload


def test_same_structured_query_produces_the_same_validated_plan_without_network(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("Planner must not make network calls.")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    planner = DeterministicToolPlanner()
    query = StructuredQuery.model_validate(query_payload())

    first = planner.plan(query)
    second = planner.plan(query)

    assert first.status == PlannerResultStatus.PLANNED
    assert first.tool_plan is not None
    assert first.tool_plan.to_planned_tools() == second.tool_plan.to_planned_tools()
    assert ToolPlan.model_validate(first.tool_plan.model_dump(mode="json")) == first.tool_plan


def test_query_clarification_does_not_produce_a_plan():
    result = DeterministicToolPlanner().plan(
        query_payload(
            causal_event_code=None,
            requested_outputs=[],
            clarification_required=True,
            clarification_reasons=["missing_scope_filter"],
        )
    )

    assert result.status == PlannerResultStatus.CLARIFICATION_REQUIRED
    assert result.tool_plan is None
    assert result.reason_codes == ("missing_scope_filter",)


def test_network_causal_plan_preserves_reference_and_uses_parallel_causal_tools():
    result = DeterministicToolPlanner().plan(query_payload())

    assert result.status == PlannerResultStatus.PLANNED
    assert [(call.server.value, call.tool_name) for call in result.tool_plan.calls] == [
        ("network", "correlate_alarms"),
        ("network", "rank_root_cause_candidates"),
    ]
    assert {call.arguments["causal_event_code"] for call in result.tool_plan.calls} == {
        "CE-GPON-001"
    }
    assert {call.parallel_group for call in result.tool_plan.calls} == {"causal_analysis"}


def test_outage_impact_has_deterministic_details_then_customer_impact_dependency():
    result = DeterministicToolPlanner().plan(
        query_payload(
            intent="outage_impact",
            requested_outputs=["summary", "impact"],
            causal_event_code=None,
            outage_code="OUT-MAL-001",
        )
    )

    assert result.status == PlannerResultStatus.PLANNED
    details, impact = result.tool_plan.calls
    assert (details.tool_name, details.execution_order) == ("get_outage_details", 1)
    assert (impact.tool_name, impact.depends_on, impact.execution_order) == (
        "calculate_customer_impact",
        ["outage_details"],
        2,
    )


def test_outage_impact_device_scope_uses_device_and_customer_tools_when_unresolved():
    result = DeterministicToolPlanner().plan(
        query_payload(
            intent="outage_impact",
            requested_outputs=["summary", "impact"],
            causal_event_code=None,
            device_code="AGG-ANK-002",
        )
    )

    assert result.status == PlannerResultStatus.PLANNED
    device, customers = result.tool_plan.calls
    assert (device.server.value, device.tool_name, device.arguments["device_code"]) == (
        "network",
        "get_device_details",
        "AGG-ANK-002",
    )
    assert (customers.server.value, customers.tool_name, customers.depends_on) == (
        "customer",
        "list_customers_by_device",
        ["device_details"],
    )


def test_rule_evidence_and_rule_document_retrieval_remain_separate():
    evidence = DeterministicToolPlanner().plan(
        query_payload(
            intent="rule_evidence",
            requested_outputs=["evidence"],
        )
    )
    documents = DeterministicToolPlanner().plan(
        query_payload(
            intent="rule_document_retrieval",
            requested_outputs=["summary"],
        )
    )

    assert evidence.status == PlannerResultStatus.PLANNED
    assert evidence.tool_plan.calls[0].tool_name == "get_rule_evidence"
    assert documents.status == PlannerResultStatus.CLARIFICATION_REQUIRED
    assert documents.reason_codes == (PlannerReasonCode.MISSING_DOCUMENT_RETRIEVAL_QUERY.value,)


def test_rule_document_retrieval_plans_the_existing_rule_mcp_tool_with_safe_query():
    query = query_payload(
        intent="rule_document_retrieval",
        requested_outputs=["summary", "evidence"],
        retrieval_query="failover protected bağlantı",
    )

    result = DeterministicToolPlanner().plan(query)

    assert result.status == PlannerResultStatus.PLANNED
    assert {(call.server.value, call.tool_name) for call in result.tool_plan.calls} == {
        ("rule", "search_rule_documents"),
        ("rule", "get_rule_evidence"),
        ("compensation", "get_compensation_evidence"),
    }
    document_call = next(
        call for call in result.tool_plan.calls if call.tool_name == "search_rule_documents"
    )
    evidence_call = next(
        call for call in result.tool_plan.calls if call.tool_name == "get_rule_evidence"
    )
    assert document_call.arguments["query"] == "failover protected bağlantı"
    assert evidence_call.arguments["causal_event_code"] == "CE-GPON-001"


def test_compensation_prefers_safe_causal_evidence_path_without_personal_identifiers():
    result = DeterministicToolPlanner().plan(
        query_payload(
            intent="compensation_evaluation",
            requested_outputs=["eligibility", "evidence"],
        )
    )

    assert result.status == PlannerResultStatus.PLANNED
    call = result.tool_plan.calls[0]
    assert (call.server.value, call.tool_name) == ("compensation", "get_compensation_evidence")
    assert call.arguments["causal_event_code"] == "CE-GPON-001"
    assert "subscription_number" not in call.arguments
    assert "customer_number" not in call.arguments


def test_compensation_uses_validated_public_subscription_reference_when_supplied():
    result = DeterministicToolPlanner().plan(
        query_payload(
            intent="compensation_evaluation",
            requested_outputs=["eligibility", "evidence"],
            subscription_reference="SUB-GPON-001",
        )
    )

    assert result.status == PlannerResultStatus.PLANNED
    assert result.tool_plan.calls[0].arguments["subscription_number"] == "SUB-GPON-001"
    assert "causal_event_code" not in result.tool_plan.calls[0].arguments


def test_compensation_without_safe_reference_returns_clarification():
    result = DeterministicToolPlanner().plan(
        query_payload(
            intent="compensation_evaluation",
            requested_outputs=["eligibility"],
            causal_event_code=None,
            clarification_required=True,
            clarification_reasons=["compensation_anchor_required"],
        )
    )

    assert result.status == PlannerResultStatus.CLARIFICATION_REQUIRED
    assert result.tool_plan is None


def test_invalid_query_or_unsupported_output_never_produces_a_plan():
    planner = DeterministicToolPlanner()

    invalid = planner.plan(query_payload(intent="unknown"))
    unsupported = planner.plan(
        query_payload(intent="rule_retrieval", requested_outputs=["compensation_amount"])
    )

    assert invalid.status == PlannerResultStatus.UNPLANNABLE
    assert invalid.reason_codes == (PlannerReasonCode.INVALID_STRUCTURED_QUERY.value,)
    assert unsupported.status == PlannerResultStatus.UNPLANNABLE
    assert unsupported.reason_codes == (PlannerReasonCode.UNSUPPORTED_REQUESTED_OUTPUT.value,)


@pytest.mark.django_db
def test_plan_and_save_records_only_successful_plan_and_keeps_run_planned():
    service = QueryRunService()
    snapshot = create_snapshot("planner-service-001")
    query = query_payload(snapshot_identifier=snapshot.snapshot_key)
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="planner-service-001",
        original_query="Kok nedeni incele.",
    )
    service.save_structured_query(run, structured_query=query)
    planner = DeterministicToolPlanner()

    first = planner.plan_and_save(run, query)
    repeated = planner.plan_and_save(run, StructuredQuery.model_validate(query))

    run.refresh_from_db()
    assert first.status == repeated.status == PlannerResultStatus.PLANNED
    assert run.status == QueryRunStatus.PLANNED
    assert run.planned_tools == first.tool_plan.to_planned_tools()


@pytest.mark.django_db
def test_clarification_does_not_change_a_planned_query_run():
    service = QueryRunService()
    snapshot = create_snapshot("planner-service-002")
    query = query_payload(snapshot_identifier=snapshot.snapshot_key)
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="planner-service-002",
        original_query="Kok nedeni incele.",
    )
    service.save_structured_query(run, structured_query=query)

    result = DeterministicToolPlanner().plan_and_save(
        run,
        query_payload(
            snapshot_identifier=snapshot.snapshot_key,
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


def test_planner_output_uses_only_current_registry_tools():
    result = DeterministicToolPlanner().plan(query_payload())

    for call in result.tool_plan.calls:
        assert call.tool_name in MCP_TOOL_REGISTRIES[call.server]
