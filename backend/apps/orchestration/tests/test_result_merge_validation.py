from __future__ import annotations

import pytest

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.executor import (
    ExecutorResult,
    ExecutorStatus,
    ToolExecutionResult,
    ToolExecutionStatus,
)
from apps.orchestration.models import QueryRunStatus
from apps.orchestration.result_merge import (
    EvidenceCategory,
    ResultMergerValidator,
    ValidationStatus,
    _customer_causal_impact,
    _document_retrieval,
    _network_outage_impact,
    _operational_analytics,
)
from apps.orchestration.services import QueryRunError, QueryRunService
from apps.orchestration.structured_query import (
    StructuredQuery,
    requires_customer_impact_evidence,
)
from apps.orchestration.tool_plan import ToolPlan


def make_plan(
    snapshot_identifier: str, *, requested_outputs=None, calls=None, customer_impact_requested=False
) -> ToolPlan:
    requested_outputs = requested_outputs or ["summary", "root_cause", "impact", "evidence"]
    causal_args = {"snapshot_identifier": snapshot_identifier, "causal_event_code": "CE-GPON-001"}
    calls = calls or [
        {
            "call_id": "correlate",
            "server": "network",
            "tool_name": "correlate_alarms",
            "arguments": causal_args,
            "execution_order": 1,
            "parallel_group": "evidence",
        },
        {
            "call_id": "impact",
            "server": "customer",
            "tool_name": "get_customer_outage_history",
            "arguments": causal_args,
            "execution_order": 1,
            "parallel_group": "evidence",
        },
        {
            "call_id": "rule",
            "server": "rule",
            "tool_name": "get_rule_evidence",
            "arguments": causal_args,
            "execution_order": 1,
            "parallel_group": "evidence",
        },
        {
            "call_id": "compensation",
            "server": "compensation",
            "tool_name": "get_compensation_evidence",
            "arguments": causal_args,
            "execution_order": 1,
            "parallel_group": "evidence",
        },
    ]
    return ToolPlan.model_validate(
        {
            "snapshot_identifier": snapshot_identifier,
            "structured_query_context": {
                "intent": "network_investigation",
                "requested_outputs": requested_outputs,
                "snapshot_identifier": snapshot_identifier,
                "causal_event_code": "CE-GPON-001",
                "customer_impact_requested": customer_impact_requested,
            },
            "calls": calls,
        }
    )


def create_executing_run(snapshot, plan: ToolPlan):
    service = QueryRunService()
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key=f"merge-{snapshot.snapshot_key}-run",
        original_query="Nedensel olay sonucu.",
    )
    service.save_structured_query(run, structured_query=plan.structured_query_context)
    service.save_tool_plan(run, tool_plan=plan)
    service.transition(run, target_status=QueryRunStatus.EXECUTING)
    return run


def success(call_id: str, server: str, tool_name: str, data: dict) -> ToolExecutionResult:
    return ToolExecutionResult(
        call_id=call_id,
        server=server,
        tool_name=tool_name,
        status=ToolExecutionStatus.SUCCEEDED,
        correlation_id=f"merge-request:{call_id}",
        attempt_count=1,
        duration_ms=1,
        result_fingerprint=f"fingerprint-{call_id}",
        normalized_response={"data": data, "raw_payload": {"token": "not-persisted"}},
    )


def failed(call_id: str, server: str, tool_name: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        call_id=call_id,
        server=server,
        tool_name=tool_name,
        status=ToolExecutionStatus.FAILED,
        correlation_id=f"merge-request:{call_id}",
        attempt_count=1,
        duration_ms=1,
        error_code="timeout",
        error_summary="secret transport detail",
    )


def full_result(snapshot_identifier: str, *, impact=None, compensation=None) -> ExecutorResult:
    impact = impact or {
        "outage_count": 2,
        "causal_event_code": "CE-GPON-001",
        "potential_connection_count": 3,
        "verified_impacted_count": 1,
        "verified_no_impact_count": 1,
        "insufficient_evidence_count": 1,
        "failover_protected_count": 1,
        "reason_code_distribution": {"session_stop_and_recovery_match": 1},
    }
    compensation = compensation or {
        "causal_event_code": "CE-GPON-001",
        "status": "available",
        "consideration_count": 1,
        "eligible": 1,
        "ineligible_pending": 0,
        "total_amount": "10.00",
        "currency": "TRY",
        "rule_versions": {"REFUND-001:v2": 1},
        "evidence": {"reference": "evidence-public-01"},
        "customer_number": "CUST-DO-NOT-PERSIST",
    }
    calls = [
        success(
            "correlate",
            "network",
            "correlate_alarms",
            {
                "causal_event_code": "CE-GPON-001",
                "root_resource_type": "device",
                "root_resource_reference": "OLT-001",
                "reason_codes": ["shared_upstream"],
                "role_counts": {"root": 1, "symptom": 2},
                "propagation_summary": "Upstream propagation.",
            },
        ),
        success("impact", "customer", "get_customer_outage_history", impact),
        success(
            "rule",
            "rule",
            "get_rule_evidence",
            {
                "causal_event_code": "CE-GPON-001",
                "selected_rule_version": "REFUND-001:v2",
                "evidence": {"reference": "evidence-public-01"},
            },
        ),
        success("compensation", "compensation", "get_compensation_evidence", compensation),
    ]
    return ExecutorResult(
        status=ExecutorStatus.SUCCEEDED,
        snapshot_identifier=snapshot_identifier,
        call_results=calls,
        succeeded_count=4,
        failed_count=0,
        skipped_count=0,
    )


@pytest.mark.django_db
def test_merge_validates_safe_result_and_completes_query_run():
    snapshot = create_snapshot("merge-valid-001")
    plan = make_plan(snapshot.snapshot_key, customer_impact_requested=True)
    run = create_executing_run(snapshot, plan)
    merged = ResultMergerValidator().validate_and_merge(
        run, plan, full_result(run.data_snapshot.snapshot_key)
    )
    completed = ResultMergerValidator().finalize_query_run(run, merged)

    completed.refresh_from_db()
    assert merged.validation_status == ValidationStatus.VALID
    assert completed.status == QueryRunStatus.COMPLETED
    assert completed.final_result["impact_summary"]["verified_impacted"] == 1
    assert completed.final_result["compensation_summary"]["scope"] == "verified_impact"
    serialized = str(completed.final_result)
    assert "CUST-DO-NOT-PERSIST" not in serialized
    assert "not-persisted" not in serialized


def test_missing_protected_failover_preserves_unknown_quantities():
    extracted = _network_outage_impact(
        {
            "outage_code": "OUT-GPON-001",
            "affected_subscription_count": 0,
            "affected_customer_count": 0,
        }
    )

    assert extracted.impact["failover_protected"] is None
    assert extracted.impact["potential"] is None
    assert extracted.impact["verified_impacted"] == 0


def test_missing_customer_assessment_counts_remain_unknown():
    extracted = _customer_causal_impact({"causal_event_code": "CE-MCR-0010"})

    assert extracted.impact["potential"] is None
    assert extracted.impact["verified_impacted"] is None
    assert extracted.impact["verified_no_impact"] is None
    assert extracted.impact["insufficient_evidence"] is None
    assert extracted.impact["failover_protected"] is None


def test_customer_history_without_aggregate_counters_is_safe_unknown_impact():
    extracted = _customer_causal_impact(
        {"outages": [], "result_count": 0, "next_cursor": None}
    )

    assert extracted.causal["causal_event_code"] is None
    assert extracted.impact["verified_impacted"] is None
    assert extracted.impact["failover_protected"] is None


def test_compensation_reason_without_documentary_dimension_does_not_require_rule_evidence():
    query = StructuredQuery.model_validate(
        {
            "intent": "outage_impact",
            "decision_type": "compensation",
            "requested_outputs": ["summary", "impact", "evidence"],
            "semantic_dimensions": ["compensation_reason", "evidence_gap"],
            "snapshot_identifier": "merge-evidence-optional-001",
            "causal_event_code": "CE-MCR-0010",
        }
    )

    assert EvidenceCategory.RULE_EVIDENCE not in ResultMergerValidator.required_categories(query)


@pytest.mark.django_db
def test_required_failure_and_audit_only_runtime_result_fail_query_run():
    snapshot = create_snapshot("merge-required-001")
    plan = make_plan(snapshot.snapshot_key, customer_impact_requested=True)
    run = create_executing_run(snapshot, plan)
    result = full_result(run.data_snapshot.snapshot_key)
    result.call_results[1] = failed("impact", "customer", "get_customer_outage_history")
    result.status = ExecutorStatus.PARTIAL
    result.succeeded_count = 3
    result.failed_count = 1

    merged = ResultMergerValidator().validate_and_merge(run, plan, result)
    failed_run = ResultMergerValidator().finalize_query_run(run, merged)

    failed_run.refresh_from_db()
    assert merged.validation_status == ValidationStatus.INVALID
    assert any(item.code == "required_tool_failed" for item in merged.validation_errors)
    assert failed_run.status == QueryRunStatus.FAILED
    assert failed_run.error_code == "required_tool_failed"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing_runtime", "runtime_result_unavailable"),
        ("malformed_response", "invalid_response_contract"),
        ("snapshot_mismatch", "snapshot_mismatch"),
    ],
)
def test_merge_rejects_audit_only_malformed_and_snapshot_mismatch(mutation, expected):
    snapshot = create_snapshot(f"merge-runtime-{mutation.replace('_', '-')}")
    plan = make_plan(snapshot.snapshot_key)
    run = create_executing_run(snapshot, plan)
    result = full_result(snapshot.snapshot_key)

    if mutation == "missing_runtime":
        result.call_results[0].normalized_response = None
    elif mutation == "malformed_response":
        result.call_results[0].normalized_response = {"data": {"unexpected": "value"}}
    else:
        result.snapshot_identifier = "other-snapshot-001"

    merged = ResultMergerValidator().validate_and_merge(run, plan, result)

    assert merged.validation_status == ValidationStatus.INVALID
    assert any(item.code == expected for item in merged.validation_errors)


@pytest.mark.django_db
def test_optional_retrieval_failure_can_complete_partial_execution():
    snapshot = create_snapshot("merge-partial-001")
    args = {"snapshot_identifier": snapshot.snapshot_key, "causal_event_code": "CE-GPON-001"}
    plan = make_plan(
        snapshot.snapshot_key,
        requested_outputs=["summary", "root_cause"],
        calls=[
            {
                "call_id": "correlate",
                "server": "network",
                "tool_name": "correlate_alarms",
                "arguments": args,
                "execution_order": 1,
                "parallel_group": "optional",
            },
            {
                "call_id": "documents",
                "server": "rule",
                "tool_name": "search_rule_documents",
                "arguments": {"snapshot_identifier": snapshot.snapshot_key, "query": "GPON"},
                "execution_order": 1,
                "parallel_group": "optional",
            },
        ],
    )
    run = create_executing_run(snapshot, plan)
    result = ExecutorResult(
        status=ExecutorStatus.PARTIAL,
        snapshot_identifier=run.data_snapshot.snapshot_key,
        call_results=[
            full_result(run.data_snapshot.snapshot_key).call_results[0],
            failed("documents", "rule", "search_rule_documents"),
        ],
        succeeded_count=1,
        failed_count=1,
        skipped_count=0,
    )

    merged = ResultMergerValidator().validate_and_merge(run, plan, result)

    assert merged.validation_status == ValidationStatus.VALID
    assert merged.execution_status == ExecutorStatus.PARTIAL
    assert merged.warnings == ["optional_tool_failed:documents"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("impact", "compensation", "expected"),
    [
        (
            {
                "causal_event_code": "CE-GPON-001",
                "potential_connection_count": 1,
                "verified_impacted_count": 2,
                "verified_no_impact_count": 0,
                "insufficient_evidence_count": 0,
                "failover_protected_count": 0,
                "reason_code_distribution": {},
            },
            None,
            "impact_invariant_failed",
        ),
        (None, {"status": "available", "consideration_count": 2}, "compensation_scope_mismatch"),
    ],
)
def test_merge_rejects_cross_tool_invariant_failures(impact, compensation, expected):
    snapshot = create_snapshot(
        "merge-invariant-impact"
        if expected == "impact_invariant_failed"
        else "merge-invariant-scope"
    )
    plan = make_plan(snapshot.snapshot_key)
    run = create_executing_run(snapshot, plan)
    merged = ResultMergerValidator().validate_and_merge(
        run,
        plan,
        full_result(run.data_snapshot.snapshot_key, impact=impact, compensation=compensation),
    )

    assert merged.validation_status == ValidationStatus.INVALID
    assert any(item.code == expected for item in merged.validation_errors)


@pytest.mark.django_db
def test_merge_deduplicates_equal_facts_and_rejects_conflicting_public_references():
    snapshot = create_snapshot("merge-conflict-001")
    plan = make_plan(
        snapshot.snapshot_key,
        calls=[
            {
                "call_id": "correlate",
                "server": "network",
                "tool_name": "correlate_alarms",
                "arguments": {
                    "snapshot_identifier": snapshot.snapshot_key,
                    "causal_event_code": "CE-GPON-001",
                },
                "execution_order": 1,
                "parallel_group": "causal",
            },
            {
                "call_id": "root",
                "server": "network",
                "tool_name": "rank_root_cause_candidates",
                "arguments": {
                    "snapshot_identifier": snapshot.snapshot_key,
                    "causal_event_code": "CE-GPON-001",
                },
                "execution_order": 1,
                "parallel_group": "causal",
            },
        ],
        requested_outputs=["summary", "root_cause"],
    )
    run = create_executing_run(snapshot, plan)
    first = full_result(run.data_snapshot.snapshot_key).call_results[0]
    duplicate = first.model_copy(
        update={"call_id": "root", "tool_name": "rank_root_cause_candidates"}
    )
    result = ExecutorResult(
        status=ExecutorStatus.SUCCEEDED,
        snapshot_identifier=run.data_snapshot.snapshot_key,
        call_results=[first, duplicate],
        succeeded_count=2,
        failed_count=0,
        skipped_count=0,
    )

    merged = ResultMergerValidator().validate_and_merge(run, plan, result)
    assert merged.validation_status == ValidationStatus.VALID
    assert merged.causal_summary.root_cause_reason_codes == ["shared_upstream"]

    duplicate.normalized_response["data"]["causal_event_code"] = "CE-OTHER-001"
    conflicting = ResultMergerValidator().validate_and_merge(run, plan, result)
    assert any(
        item.code in {"conflicting_fact", "public_reference_conflict"}
        for item in conflicting.validation_errors
    )


@pytest.mark.django_db
def test_terminal_query_run_cannot_be_finalized_twice():
    snapshot = create_snapshot("merge-terminal-001")
    plan = make_plan(snapshot.snapshot_key)
    run = create_executing_run(snapshot, plan)
    validator = ResultMergerValidator()
    merged = validator.validate_and_merge(run, plan, full_result(snapshot.snapshot_key))
    validator.finalize_query_run(run, merged)

    with pytest.raises(QueryRunError) as exc_info:
        validator.finalize_query_run(run, merged)

    assert getattr(exc_info.value, "code", None) == "query_run_finalization_requires_execution"


def test_rule_document_retrieval_requires_only_document_retrieval_evidence():
    query = StructuredQuery.model_validate(
        {
            "intent": "rule_document_retrieval",
            "requested_outputs": ["summary", "evidence"],
            "snapshot_identifier": "multi-city-realism-v2-causal-r1",
            "retrieval_query": "failover protected bağlantı",
        }
    )

    categories = ResultMergerValidator.required_categories(query)

    assert {category.value for category in categories} == {"document_retrieval"}


def test_document_retrieval_preserves_existing_score_with_source_metadata():
    extracted = _document_retrieval(
        {
            "source_kind": "rule_document",
            "results": [
                {
                    "document_code": "RULE-DOC-001",
                    "document_version": 3,
                    "heading": "Uygunluk",
                    "section_path": "Telafi / Uygunluk",
                    "hybrid_score": 0.81234,
                    "semantic_score": 0.71,
                    "text": "Doğrulanmış kural metni.",
                }
            ],
        }
    )

    source = extracted.retrieval_sources[0]
    assert source.source_code == "RULE-DOC-001"
    assert source.version == 3
    assert source.section == "Uygunluk"
    assert source.section_path == "Telafi / Uygunluk"
    assert source.score == pytest.approx(0.81234)
    assert source.score_source == "hybrid_score"


def test_rule_document_retrieval_with_public_event_requires_rule_evidence_too():
    query = StructuredQuery.model_validate(
        {
            "intent": "rule_document_retrieval",
            "requested_outputs": ["summary", "evidence"],
            "snapshot_identifier": "multi-city-realism-v2-causal-r1",
            "causal_event_code": "CE-GPON-001",
            "retrieval_query": "failover protected bağlantı",
        }
    )

    categories = ResultMergerValidator.required_categories(query)

    assert {category.value for category in categories} == {
        "document_retrieval",
        "rule_evidence",
    }


def test_analytics_normalizer_preserves_rows_and_unknown_exclusion_count():
    extracted = _operational_analytics(
        {
            "metric": "affected_customers",
            "aggregation": "sum",
            "group_by": "city",
            "ranking_direction": "desc",
            "limit": 3,
            "time_grain": None,
            "filters": {"city": "İzmir"},
            "rows": [{"label": "İzmir", "value": 42, "event_count": 2}],
            "included_event_count": 2,
            "excluded_unknown_count": 1,
            "deduplication_grain": "causal_event",
        }
    )

    assert extracted.category == EvidenceCategory.ANALYTICS
    assert extracted.analytics["rows"] == [
        {"label": "İzmir", "value": 42, "event_count": 2}
    ]
    assert extracted.analytics["excluded_unknown_count"] == 1


def test_analytics_normalizer_preserves_grouped_comparison_period_values():
    extracted = _operational_analytics(
        {
            "metric": "affected_customers",
            "aggregation": "sum",
            "group_by": "city",
            "comparison": True,
            "ranking_direction": "desc",
            "time_grain": "month",
            "filters": {},
            "rows": [
                {
                    "label": "İzmir",
                    "value": -10,
                    "event_count": 3,
                    "absolute_change": 10,
                    "signed_change": -10,
                    "trend_direction": "decrease",
                    "period_values": [
                        {
                            "label": "2026-06",
                            "value": 30,
                            "event_count": 2,
                            "included_event_count": 2,
                            "excluded_unknown_count": 0,
                        },
                        {
                            "label": "2026-07",
                            "value": 20,
                            "event_count": 1,
                            "included_event_count": 1,
                            "excluded_unknown_count": 1,
                        },
                    ],
                    "included_event_count": 3,
                    "excluded_unknown_count": 1,
                }
            ],
            "included_event_count": 3,
            "excluded_unknown_count": 1,
            "deduplication_grain": "causal_event",
        }
    )

    assert extracted.analytics["comparison"] is True
    assert extracted.analytics["rows"][0]["period_values"][1]["value"] == 20
    assert extracted.analytics["rows"][0]["absolute_change"] == 10
    assert extracted.analytics["rows"][0]["signed_change"] == -10
    assert extracted.analytics["rows"][0]["period_values"][1]["excluded_unknown_count"] == 1
    assert extracted.analytics["rows"][0]["excluded_unknown_count"] == 1


def test_ranked_analytics_mapping_rows_keep_backend_order_through_merge():
    extracted = _operational_analytics(
        {
            "metric": "affected_customers",
            "aggregation": "sum",
            "group_by": "event",
            "ranking_direction": "desc",
            "limit": 3,
            "time_grain": None,
            "filters": {},
            "rows": [
                {"label": "CE-RANK-300", "value": 300, "event_count": 1},
                {"label": "CE-RANK-200", "value": 200, "event_count": 1},
                {"label": "CE-RANK-100", "value": 100, "event_count": 1},
            ],
            "included_event_count": 3,
            "excluded_unknown_count": 0,
            "deduplication_grain": "causal_event",
        }
    )

    *_, analytics, _sources, errors = ResultMergerValidator._merge_sections(
        {EvidenceCategory.ANALYTICS: [extracted]}
    )

    assert errors == []
    assert [row["label"] for row in analytics["rows"]] == [
        "CE-RANK-300",
        "CE-RANK-200",
        "CE-RANK-100",
    ]


def test_analytics_requires_only_its_backend_owned_evidence_category():
    query = StructuredQuery.model_validate(
        {
            "intent": "operational_analytics",
            "requested_outputs": ["summary", "analytics"],
            "snapshot_identifier": "multi-city-realism-v2-causal-r1",
            "analytics": {
                "metric": "full_outage_count",
                "aggregation": "count",
                "group_by": "city",
            },
            "semantic_dimensions": ["verified_customer_impact"],
        }
    )

    assert ResultMergerValidator.required_categories(query) == {EvidenceCategory.ANALYTICS}


def test_compensation_evaluation_uses_its_authoritative_evidence_without_impact_tool():
    query = StructuredQuery.model_validate(
        {
            "intent": "compensation_evaluation",
            "requested_outputs": ["summary", "eligibility", "evidence"],
            "snapshot_identifier": "multi-city-realism-v3-repair-r1",
            "outage_code": "OUT-MCR-0052",
            "decision_type": "compensation",
            "semantic_dimensions": ["compensation_result", "rule_version"],
        }
    )

    assert requires_customer_impact_evidence(query) is False
    assert ResultMergerValidator.required_categories(query) == {EvidenceCategory.COMPENSATION}
