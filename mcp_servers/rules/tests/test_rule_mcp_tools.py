from __future__ import annotations

import inspect

import pytest

from mcp_servers.rules import server as rule_server
from mcp_servers.rules.tools import RULE_TOOL_DEFINITIONS, RuleMCPTools
from mcp_servers.shared.backend_client import InternalAPIClientError
from mcp_servers.shared.contracts import MCPError, MCPErrorCode


def test_all_eight_rule_tools_are_registered():
    assert sorted(RULE_TOOL_DEFINITIONS) == [
        "detect_rule_conflicts",
        "find_related_rules",
        "get_rule",
        "get_rule_evidence",
        "get_rule_version_history",
        "get_rules_effective_at",
        "search_rule_documents",
        "search_rules",
    ]


def test_causal_rule_evidence_maps_read_only_analysis_contract():
    client = FakeBackendClient(data={"causal_event": {"code": "CE-001"}, "impact": {"verified_impacted": 1, "reason_codes": {"session_stop_and_recovery_match": 1}}, "compensation": {"eligible": 1, "ineligible_pending": 0, "selected_rule_version": "REFUND-001:v1", "baseline": None, "candidate": None, "difference_summary": None}, "evidence": None})
    response = RuleMCPTools(client).run("get_rule_evidence", {"snapshot_identifier": "snapshot-1", "causal_event_code": "CE-001"})
    assert response.success is True
    assert client.calls[0]["path"].endswith("/CE-001/analysis/")
    assert response.data["verified_impacted_count"] == 1
    assert response.data["selected_rule_version"] == "REFUND-001:v1"


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_path"),
    [
        (
            "search_rules",
            {"snapshot_identifier": "snapshot-1", "limit": 10},
            "/api/internal/v1/rules/",
        ),
        (
            "get_rule",
            {"snapshot_identifier": "snapshot-1", "rule_code": "REFUND-001", "version": 2},
            "/api/internal/v1/rules/REFUND-001/",
        ),
        (
            "get_rules_effective_at",
            {
                "snapshot_identifier": "snapshot-1",
                "evaluation_time": "2026-07-20T12:00:00+03:00",
            },
            "/api/internal/v1/rules/effective-at/",
        ),
        (
            "get_rule_version_history",
            {"snapshot_identifier": "snapshot-1", "rule_code": "REFUND-001"},
            "/api/internal/v1/rules/REFUND-001/versions/",
        ),
        (
            "find_related_rules",
            {"snapshot_identifier": "snapshot-1", "conflict_group": "broadband_base"},
            "/api/internal/v1/rules/related/",
        ),
        (
            "detect_rule_conflicts",
            {"snapshot_identifier": "snapshot-1", "conflict_group": "broadband_base"},
            "/api/internal/v1/rules/conflicts/",
        ),
        (
            "get_rule_evidence",
            {"snapshot_identifier": "snapshot-1", "rule_code": "BB-FULL-OUTAGE-TIERED"},
            "/api/internal/v1/rules/evidence/",
        ),
        (
            "search_rule_documents",
            {"snapshot_identifier": "snapshot-1", "query": "REFUND-001 v2"},
            "/api/internal/v1/rag/search/",
        ),
    ],
)
def test_rule_tool_calls_internal_api_path_and_wraps_response(
    tool_name,
    arguments,
    expected_path,
):
    client = FakeBackendClient()
    response = RuleMCPTools(client).run(tool_name, arguments)

    assert response.success is True
    assert client.calls[0]["path"] == expected_path
    request_data = client.calls[0]["json"] or client.calls[0]["params"]
    assert request_data["snapshot_identifier"] == "snapshot-1"
    assert response.metadata.snapshot_details["snapshot_key"] == "snapshot-1"
    assert response.metadata.request_id == "req-from-backend"


def test_search_rule_documents_posts_all_explicit_filters_as_json():
    client = FakeBackendClient()
    response = RuleMCPTools(client).run(
        "search_rule_documents",
        {
            "request_id": "req-rule-rag-1",
            "snapshot_identifier": "snapshot-1",
            "query": "  REFUND-001 v2  ",
            "search_mode": "semantic",
            "top_k": 7,
            "evaluation_time": "2026-07-15T12:00:00+03:00",
            "document_type": "rule_policy",
            "language": "tr",
            "source_kind": "synthetic",
            "rule_code": "REFUND-001",
            "rule_version": 2,
            "include_scores": False,
        },
    )

    call = client.calls[0]
    assert response.success is True
    assert call["method"] == "POST"
    assert call["path"] == "/api/internal/v1/rag/search/"
    assert call["params"] == {}
    assert call["request_id"] == "req-rule-rag-1"
    assert call["json"] == {
        "snapshot_identifier": "snapshot-1",
        "query": "REFUND-001 v2",
        "search_mode": "semantic",
        "top_k": 7,
        "evaluation_time": "2026-07-15T12:00:00+03:00",
        "document_type": "rule_policy",
        "language": "tr",
        "source_kind": "synthetic",
        "rule_code": "REFUND-001",
        "rule_version": 2,
        "include_scores": False,
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {"snapshot_identifier": "snapshot-1"},
        {"snapshot_identifier": "snapshot-1", "query": " "},
        {"snapshot_identifier": "snapshot-1", "query": "x"},
        {"snapshot_identifier": "snapshot-1", "query": "x" * 501},
        {"snapshot_identifier": "snapshot-1", "query": "valid", "top_k": 0},
        {"snapshot_identifier": "snapshot-1", "query": "valid", "top_k": 21},
        {"snapshot_identifier": "snapshot-1", "query": "valid", "search_mode": "other"},
        {"snapshot_identifier": "snapshot-1", "query": "valid", "language": " "},
        {
            "snapshot_identifier": "snapshot-1",
            "query": "valid",
            "evaluation_time": "2026-07-15T12:00:00",
        },
    ],
)
def test_search_rule_documents_rejects_invalid_input(arguments):
    client = FakeBackendClient()
    response = RuleMCPTools(client).run("search_rule_documents", arguments)

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_search_rule_documents_defaults_to_hybrid_and_preserves_empty_results():
    client = FakeBackendClient(
        data={
            "query": "bulunamayan kaynak",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "top_k": 5,
            "result_count": 0,
            "snapshot": {"snapshot_key": "snapshot-1"},
            "embedding": None,
            "ranking_version": "hybrid-section-v2",
            "results": [],
        }
    )
    response = RuleMCPTools(client).run(
        "search_rule_documents",
        {"snapshot_identifier": "snapshot-1", "query": "bulunamayan kaynak"},
    )

    assert response.success is True
    assert response.data["requested_mode"] == "hybrid"
    assert response.data["result_count"] == 0
    assert response.data["results"] == []


def test_search_rule_documents_preserves_versions_sections_scores_and_removes_vectors():
    client = FakeBackendClient(
        data={
            "query": "REFUND-001 v2",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "top_k": 5,
            "result_count": 1,
            "snapshot": {"snapshot_key": "snapshot-1"},
            "embedding": {
                "provider": "mock",
                "model": "mock-embedding-768",
                "dimensions": 768,
                "embedding_version": "asymmetric-retrieval-v1",
                "document_prompt_version": "rag-section-aware-document-v2",
                "query_prompt_version": "gemini-search-query-v1",
            },
            "ranking_version": "hybrid-section-v2",
            "results": [
                {
                    "document_code": "REFUND-001-V2-SOURCE",
                    "document_version": 3,
                    "rule_version": 2,
                    "heading": "Koşullar",
                    "section_path": ["Koşullar"],
                    "text": "Minimum etki süresi 120 dakikadır.",
                    "semantic_score": 0.8,
                    "full_text_score": 0.7,
                    "hybrid_score": 0.016,
                    "embedding": [0.1, 0.2],
                }
            ],
        }
    )
    response = RuleMCPTools(client).run(
        "search_rule_documents",
        {"snapshot_identifier": "snapshot-1", "query": "REFUND-001 v2"},
    )

    result = response.data["results"][0]
    assert result["document_version"] == 3
    assert result["rule_version"] == 2
    assert result["heading"] == "Koşullar"
    assert result["section_path"] == ["Koşullar"]
    assert result["hybrid_score"] == 0.016
    assert response.data["embedding_provider"] == "mock"
    assert response.data["embedding_dimensions"] == 768
    assert response.data["document_prompt_version"] == "rag-section-aware-document-v2"
    assert response.data["query_prompt_version"] == "gemini-search-query-v1"
    assert response.data["correlation_id"] == "req-from-backend"
    assert "embedding" not in result


def test_search_rule_documents_preserves_full_text_fallback_warning():
    warning = {
        "code": "provider_unavailable",
        "message": "Semantic provider unavailable; full-text results returned.",
    }
    client = FakeBackendClient(
        data={
            "query": "failover",
            "requested_mode": "hybrid",
            "effective_mode": "full_text_fallback",
            "result_count": 0,
            "snapshot": {"snapshot_key": "snapshot-1"},
            "results": [],
        },
        warnings=[warning],
    )
    response = RuleMCPTools(client).run(
        "search_rule_documents",
        {"snapshot_identifier": "snapshot-1", "query": "failover"},
    )

    assert response.success is True
    assert response.data["effective_mode"] == "full_text_fallback"
    assert response.warnings[0].code == "provider_unavailable"


def test_path_rule_code_is_not_sent_as_query_param_but_filter_rule_code_is_preserved():
    client = FakeBackendClient()

    RuleMCPTools(client).run(
        "get_rule",
        {"snapshot_identifier": "snapshot-1", "rule_code": "REFUND-001", "version": 2},
    )
    RuleMCPTools(client).run(
        "find_related_rules",
        {"snapshot_identifier": "snapshot-1", "rule_code": "REFUND-001"},
    )

    assert "rule_code" not in client.calls[0]["params"]
    assert client.calls[1]["params"]["rule_code"] == "REFUND-001"


def test_missing_snapshot_identifier_returns_validation_error_without_backend_call():
    client = FakeBackendClient()

    response = RuleMCPTools(client).run("search_rules", {"limit": 5})

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_version_and_effective_at_are_mutually_exclusive():
    client = FakeBackendClient()

    response = RuleMCPTools(client).run(
        "get_rule",
        {
            "snapshot_identifier": "snapshot-1",
            "rule_code": "REFUND-001",
            "version": 2,
            "effective_at": "2026-07-20T12:00:00+03:00",
        },
    )

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "get_rules_effective_at",
            {"snapshot_identifier": "snapshot-1"},
        ),
        (
            "find_related_rules",
            {"snapshot_identifier": "snapshot-1"},
        ),
        (
            "detect_rule_conflicts",
            {"snapshot_identifier": "snapshot-1"},
        ),
        (
            "get_rule_evidence",
            {"snapshot_identifier": "snapshot-1"},
        ),
    ],
)
def test_required_rule_tool_scope_is_enforced(tool_name, arguments):
    client = FakeBackendClient()

    response = RuleMCPTools(client).run(tool_name, arguments)

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_timezone_naive_datetimes_are_rejected():
    client = FakeBackendClient()

    response = RuleMCPTools(client).run(
        "get_rules_effective_at",
        {
            "snapshot_identifier": "snapshot-1",
            "evaluation_time": "2026-07-20T12:00:00",
        },
    )

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_raw_config_defaults_false_and_is_passed_only_when_explicit():
    client = FakeBackendClient()

    RuleMCPTools(client).run(
        "get_rule",
        {"snapshot_identifier": "snapshot-1", "rule_code": "REFUND-001", "version": 2},
    )
    RuleMCPTools(client).run(
        "get_rule",
        {
            "snapshot_identifier": "snapshot-1",
            "rule_code": "REFUND-001",
            "version": 2,
            "include_raw_config": True,
        },
    )

    assert "include_raw_config" not in client.calls[0]["params"]
    assert client.calls[1]["params"]["include_raw_config"] is True


def test_backend_errors_are_mapped_without_traceback_or_secret_leak():
    client = FakeBackendClient(
        error=InternalAPIClientError(
            MCPError(
                code=MCPErrorCode.UPSTREAM_ERROR,
                message="Internal API request failed.",
                details={"reason": "ConnectError"},
            )
        )
    )

    response = RuleMCPTools(client).run(
        "search_rules",
        {"snapshot_identifier": "snapshot-1"},
    )

    serialized = response.model_dump_json()
    assert response.success is False
    assert response.error.code == MCPErrorCode.UPSTREAM_ERROR
    assert "Traceback" not in serialized
    assert "token" not in serialized.lower()
    assert "select " not in serialized.lower()


def test_rule_mcp_modules_do_not_import_django_or_backend_apps():
    source = inspect.getsource(rule_server) + inspect.getsource(
        __import__("mcp_servers.rules.tools", fromlist=[""])
    )

    assert "django" not in source
    assert "apps." not in source
    assert "CosineDistance" not in source
    assert "SearchRank" not in source
    assert "RuleEvaluationService" not in source
    assert "CompensationService" not in source


class FakeBackendClient:
    def __init__(
        self,
        *,
        data: dict | None = None,
        error: Exception | None = None,
        warnings: list[dict] | None = None,
    ) -> None:
        self.data = data or {"ok": True}
        self.error = error
        self.warnings = warnings or []
        self.calls: list[dict] = []

    def request_json(self, method, path, *, request_id=None, json=None, params=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "request_id": request_id,
                "json": json,
                "params": params,
            }
        )
        if self.error:
            raise self.error
        return {
            "data": self.data,
            "warnings": self.warnings,
            "evidence": [],
            "metadata": {
                "correlation_id": "req-from-backend",
                "snapshot": {
                    "dataset_slug": "dataset-1",
                    "snapshot_key": "snapshot-1",
                    "snapshot_name": "Snapshot 1",
                    "snapshot_status": "validated",
                    "is_active": False,
                    "reference_datetime": "2026-08-01T00:00:00+03:00",
                },
            },
        }
