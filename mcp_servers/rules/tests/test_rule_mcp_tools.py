from __future__ import annotations

import inspect

import pytest

from mcp_servers.rules import server as rule_server
from mcp_servers.rules.tools import RULE_TOOL_DEFINITIONS, RuleMCPTools
from mcp_servers.shared.backend_client import InternalAPIClientError
from mcp_servers.shared.contracts import MCPError, MCPErrorCode


def test_all_seven_rule_tools_are_registered():
    assert sorted(RULE_TOOL_DEFINITIONS) == [
        "detect_rule_conflicts",
        "find_related_rules",
        "get_rule",
        "get_rule_evidence",
        "get_rule_version_history",
        "get_rules_effective_at",
        "search_rules",
    ]


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
    assert client.calls[0]["params"]["snapshot_identifier"] == "snapshot-1"
    assert response.metadata.snapshot_details["snapshot_key"] == "snapshot-1"
    assert response.metadata.request_id == "req-from-backend"


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


class FakeBackendClient:
    def __init__(self, *, data: dict | None = None, error: Exception | None = None) -> None:
        self.data = data or {"ok": True}
        self.error = error
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
            "warnings": [],
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
