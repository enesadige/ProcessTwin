from __future__ import annotations

import inspect

import pytest

from mcp_servers.compensation import server as compensation_server
from mcp_servers.compensation.tools import (
    COMPENSATION_TOOL_DEFINITIONS,
    CompensationMCPTools,
)
from mcp_servers.shared.backend_client import InternalAPIClientError
from mcp_servers.shared.contracts import MCPError, MCPErrorCode


def test_all_six_compensation_tools_are_registered():
    assert sorted(COMPENSATION_TOOL_DEFINITIONS) == [
        "calculate_refund_amount",
        "check_campaign_eligibility",
        "evaluate_compensation_options",
        "evaluate_refund_eligibility",
        "get_compensation_evidence",
        "rank_compensation_options",
    ]


@pytest.mark.parametrize(
    ("tool_name", "arguments", "method", "expected_path"),
    [
        (
            "evaluate_refund_eligibility",
            {
                "snapshot_identifier": "snapshot-1",
                "outage_code": "OUT-001",
                "subscription_number": "SUB-001",
                "rule_code": "REFUND-001",
            },
            "POST",
            "/api/internal/v1/compensation/eligibility/",
        ),
        (
            "calculate_refund_amount",
            {
                "snapshot_identifier": "snapshot-1",
                "outage_code": "OUT-001",
                "subscription_number": "SUB-001",
                "rule_code": "REFUND-001",
            },
            "POST",
            "/api/internal/v1/compensation/amount/",
        ),
        (
            "evaluate_compensation_options",
            {
                "snapshot_identifier": "snapshot-1",
                "outage_code": "OUT-001",
                "subscription_number": "SUB-001",
                "rule_set_code": "SYN-COMP-2026",
            },
            "POST",
            "/api/internal/v1/compensation/options/",
        ),
        (
            "check_campaign_eligibility",
            {"snapshot_identifier": "snapshot-1", "subscription_number": "SUB-001"},
            "POST",
            "/api/internal/v1/compensation/campaigns/check/",
        ),
        (
            "rank_compensation_options",
            {
                "snapshot_identifier": "snapshot-1",
                "outage_code": "OUT-001",
                "subscription_number": "SUB-001",
                "rule_set_code": "SYN-COMP-2026",
            },
            "POST",
            "/api/internal/v1/compensation/options/rank/",
        ),
        (
            "get_compensation_evidence",
            {"snapshot_identifier": "snapshot-1", "rule_code": "REFUND-001"},
            "GET",
            "/api/internal/v1/compensation/evidence/",
        ),
    ],
)
def test_compensation_tool_calls_internal_api_path_and_wraps_response(
    tool_name,
    arguments,
    method,
    expected_path,
):
    client = FakeBackendClient()
    response = CompensationMCPTools(client).run(tool_name, arguments)

    assert response.success is True
    assert client.calls[0]["method"] == method
    assert client.calls[0]["path"] == expected_path
    assert response.metadata.snapshot_details["snapshot_key"] == "snapshot-1"
    assert response.metadata.request_id == "req-from-backend"


def test_missing_snapshot_identifier_returns_validation_error_without_backend_call():
    client = FakeBackendClient()

    response = CompensationMCPTools(client).run(
        "calculate_refund_amount",
        {
            "outage_code": "OUT-001",
            "subscription_number": "SUB-001",
            "rule_code": "REFUND-001",
        },
    )

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_rule_code_or_rule_set_code_is_required_for_amount_tools():
    client = FakeBackendClient()

    response = CompensationMCPTools(client).run(
        "calculate_refund_amount",
        {
            "snapshot_identifier": "snapshot-1",
            "outage_code": "OUT-001",
            "subscription_number": "SUB-001",
        },
    )

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_timezone_naive_evaluation_time_is_rejected():
    client = FakeBackendClient()

    response = CompensationMCPTools(client).run(
        "evaluate_refund_eligibility",
        {
            "snapshot_identifier": "snapshot-1",
            "outage_code": "OUT-001",
            "subscription_number": "SUB-001",
            "rule_code": "REFUND-001",
            "evaluation_time": "2026-07-20T12:00:00",
        },
    )

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_evidence_requires_identifier():
    client = FakeBackendClient()

    response = CompensationMCPTools(client).run(
        "get_compensation_evidence",
        {"snapshot_identifier": "snapshot-1"},
    )

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


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

    response = CompensationMCPTools(client).run(
        "calculate_refund_amount",
        {
            "snapshot_identifier": "snapshot-1",
            "outage_code": "OUT-001",
            "subscription_number": "SUB-001",
            "rule_code": "REFUND-001",
        },
    )

    serialized = response.model_dump_json()
    assert response.success is False
    assert response.error.code == MCPErrorCode.UPSTREAM_ERROR
    assert "Traceback" not in serialized
    assert "token" not in serialized.lower()
    assert "select " not in serialized.lower()


def test_compensation_mcp_modules_do_not_import_django_or_backend_apps():
    source = inspect.getsource(compensation_server) + inspect.getsource(
        __import__("mcp_servers.compensation.tools", fromlist=[""])
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
