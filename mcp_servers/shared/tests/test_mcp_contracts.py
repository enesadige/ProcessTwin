from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from mcp_servers.compensation import COMPENSATION_MCP_VERSION
from mcp_servers.compensation.tools import COMPENSATION_TOOL_DEFINITIONS, CompensationMCPTools
from mcp_servers.customer import CUSTOMER_MCP_VERSION
from mcp_servers.customer.tools import CUSTOMER_TOOL_DEFINITIONS, CustomerMCPTools
from mcp_servers.network import NETWORK_MCP_VERSION
from mcp_servers.network.tools import NETWORK_TOOL_DEFINITIONS, NetworkMCPTools
from mcp_servers.rules import RULE_MCP_VERSION
from mcp_servers.rules.tools import RULE_TOOL_DEFINITIONS, RuleMCPTools
from mcp_servers.shared.contracts import MCPErrorCode, MCPToolResponse


class RecordingClient:
    def __init__(self, payload: dict | None = None):
        self.calls: list[dict] = []
        self.payload = payload or {
            "data": {"ok": True},
            "metadata": {
                "correlation_id": "contract-request-1",
                "snapshot": {
                    "snapshot_key": "snapshot-1",
                    "dataset_slug": "dataset-1",
                    "reference_datetime": "2026-08-01T00:00:00+03:00",
                },
            },
        }

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
        return self.payload


COMMON_MCP_MATRIX = [
    pytest.param(
        "network",
        NETWORK_TOOL_DEFINITIONS,
        NetworkMCPTools,
        NETWORK_MCP_VERSION,
        9,
        {
            "get_device_details": {"device_code": "BNG-001"},
            "get_device_topology": {"device_code": "BNG-001"},
            "search_alarms": {},
            "search_outages": {},
            "get_outage_details": {"outage_code": "OUT-001"},
            "calculate_customer_impact": {"outage_code": "OUT-001"},
            "correlate_alarms": {"anchor_alarm_id": "ALM-001"},
            "rank_root_cause_candidates": {"outage_code": "OUT-001"},
            "get_longest_outage": {},
        },
        id="network",
    ),
    pytest.param(
        "customer",
        CUSTOMER_TOOL_DEFINITIONS,
        CustomerMCPTools,
        CUSTOMER_MCP_VERSION,
        7,
        {
            "get_customer_profile": {"customer_number": "CUST-001"},
            "get_customer_subscription": {"subscription_number": "SUB-001"},
            "get_customer_payment_status": {"subscription_number": "SUB-001"},
            "get_customer_outage_history": {"subscription_number": "SUB-001"},
            "get_customer_compensation_history": {"subscription_number": "SUB-001"},
            "list_customers_by_device": {"device_code": "BNG-001"},
            "list_customers_by_location": {"city": "Istanbul"},
        },
        id="customer",
    ),
    pytest.param(
        "rules",
        RULE_TOOL_DEFINITIONS,
        RuleMCPTools,
        RULE_MCP_VERSION,
        7,
        {
            "search_rules": {},
            "get_rule": {"rule_code": "REFUND-001"},
            "get_rules_effective_at": {
                "evaluation_time": "2026-08-01T00:00:00+03:00",
            },
            "get_rule_version_history": {"rule_code": "REFUND-001"},
            "find_related_rules": {"family": "broadband"},
            "detect_rule_conflicts": {"conflict_group": "broadband_base"},
            "get_rule_evidence": {"rule_code": "REFUND-001"},
        },
        id="rules",
    ),
    pytest.param(
        "compensation",
        COMPENSATION_TOOL_DEFINITIONS,
        CompensationMCPTools,
        COMPENSATION_MCP_VERSION,
        6,
        {
            "evaluate_refund_eligibility": {
                "outage_code": "OUT-001",
                "subscription_number": "SUB-001",
                "rule_code": "REFUND-001",
            },
            "calculate_refund_amount": {
                "outage_code": "OUT-001",
                "subscription_number": "SUB-001",
                "rule_code": "REFUND-001",
                "evaluation_time": "2026-08-01T00:00:00+03:00",
            },
            "evaluate_compensation_options": {
                "outage_code": "OUT-001",
                "subscription_number": "SUB-001",
                "rule_set_code": "SYN-COMP-2026",
            },
            "check_campaign_eligibility": {"subscription_number": "SUB-001"},
            "rank_compensation_options": {
                "outage_code": "OUT-001",
                "subscription_number": "SUB-001",
                "rule_set_code": "SYN-COMP-2026",
            },
            "get_compensation_evidence": {"rule_code": "REFUND-001"},
        },
        id="compensation",
    ),
]


@pytest.mark.parametrize(
    "_key,definitions,_tools,_version,expected_count,samples",
    COMMON_MCP_MATRIX,
)
def test_each_mcp_has_expected_tool_catalog(
    _key, definitions, _tools, _version, expected_count, samples
):
    assert len(definitions) == expected_count
    assert set(definitions) == set(samples)


@pytest.mark.parametrize(
    "_key,definitions,tools_class,version,_count,samples",
    COMMON_MCP_MATRIX,
)
def test_each_tool_returns_shared_success_envelope(
    _key, definitions, tools_class, version, _count, samples
):
    client = RecordingClient()
    tools = tools_class(client)

    for tool_name, sample in samples.items():
        response = tools.run(
            tool_name,
            {
                **sample,
                "snapshot_identifier": "snapshot-1",
                "request_id": "contract-request-1",
            },
        )
        assert isinstance(response, MCPToolResponse)
        assert response.success is True
        assert response.error is None
        assert response.metadata.tool_version == version
        assert response.metadata.request_id == "contract-request-1"
        assert response.metadata.snapshot_identifier == "snapshot-1"
        assert response.metadata.snapshot_details["snapshot_key"] == "snapshot-1"
        assert response.metadata.deterministic is True


@pytest.mark.parametrize(
    "_key,definitions,tools_class,_version,_count,samples",
    COMMON_MCP_MATRIX,
)
def test_snapshot_identifier_is_required_for_every_tool(
    _key, definitions, tools_class, _version, _count, samples
):
    client = RecordingClient()
    tools = tools_class(client)

    for tool_name, sample in samples.items():
        response = tools.run(tool_name, sample)
        assert response.success is False
        assert response.error is not None
        assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


@pytest.mark.parametrize(
    "_key,definitions,tools_class,_version,_count,samples",
    COMMON_MCP_MATRIX,
)
def test_timezone_naive_datetime_is_rejected_consistently(
    _key, definitions, tools_class, _version, _count, samples
):
    temporal_tools = [
        name
        for name, definition in definitions.items()
        if "evaluation_time" in definition.input_model.model_fields
    ]
    client = RecordingClient()
    tools = tools_class(client)

    for tool_name in temporal_tools:
        sample = {**samples[tool_name], "snapshot_identifier": "snapshot-1"}
        sample["evaluation_time"] = datetime(2026, 8, 1)
        response = tools.run(tool_name, sample)
        assert response.success is False
        assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_shared_response_model_rejects_inconsistent_success_and_error():
    with pytest.raises(ValidationError):
        MCPToolResponse(
            success=True,
            data={"ok": True},
            error={
                "code": MCPErrorCode.INTERNAL_ERROR,
                "message": "invalid",
            },
            metadata={
                "tool_name": "test.tool",
                "tool_version": "0.1.0",
                "deterministic": True,
            },
        )
