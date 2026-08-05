from __future__ import annotations

import inspect

import pytest

from mcp_servers.network import server as network_server
from mcp_servers.network.tools import NETWORK_TOOL_DEFINITIONS, NetworkMCPTools
from mcp_servers.shared.backend_client import InternalAPIClientError
from mcp_servers.shared.contracts import MCPError, MCPErrorCode


def test_all_nine_network_tools_are_registered():
    assert sorted(NETWORK_TOOL_DEFINITIONS) == [
        "calculate_customer_impact",
        "correlate_alarms",
        "get_device_details",
        "get_device_topology",
        "get_longest_outage",
        "get_outage_details",
        "rank_root_cause_candidates",
        "search_alarms",
        "search_outages",
    ]


def test_causal_network_call_requires_no_legacy_identifier_and_maps_analysis():
    client = FakeBackendClient(
        data={
            "causal_event": {"code": "CE-001", "root_resource": {"resource_type": "network_link", "reference": "LINK-1"}},
            "correlation": {"score": 88, "confidence": 88, "reason_codes": ["shared_failure_domain"], "role_counts": {"root": 1, "child": 2, "symptom": 3, "supporting": 0, "unrelated": 0, "noise": 0}, "propagation_summary": "Delayed downstream propagation."},
        }
    )
    response = NetworkMCPTools(client).run(
        "correlate_alarms", {"snapshot_identifier": "snapshot-1", "causal_event_code": "CE-001"}
    )
    assert response.success is True
    assert client.calls[0]["path"].endswith("/CE-001/analysis/")
    assert response.data["role_counts"]["symptom"] == 3
    assert response.data["propagation_summary"] == "Delayed downstream propagation."


def test_network_correlation_rejects_missing_or_ambiguous_scope():
    client = FakeBackendClient()
    for arguments in (
        {"snapshot_identifier": "snapshot-1"},
        {"snapshot_identifier": "snapshot-1", "anchor_alarm_id": "ALM-1", "causal_event_code": "CE-1"},
    ):
        assert NetworkMCPTools(client).run("correlate_alarms", arguments).success is False


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_path"),
    [
        (
            "get_device_details",
            {"snapshot_identifier": "snapshot-1", "device_code": "BNG-001"},
            "/api/internal/v1/network/devices/BNG-001/",
        ),
        (
            "get_device_topology",
            {
                "snapshot_identifier": "snapshot-1",
                "device_code": "BNG-001",
                "mode": "descendants",
                "result_limit": 10,
            },
            "/api/internal/v1/network/devices/BNG-001/topology/",
        ),
        (
            "search_alarms",
            {"snapshot_identifier": "snapshot-1", "limit": 10},
            "/api/internal/v1/network/alarms/",
        ),
        (
            "search_outages",
            {"snapshot_identifier": "snapshot-1", "limit": 10},
            "/api/internal/v1/network/outages/",
        ),
        (
            "get_outage_details",
            {"snapshot_identifier": "snapshot-1", "outage_code": "OUT-001"},
            "/api/internal/v1/network/outages/OUT-001/",
        ),
        (
            "calculate_customer_impact",
            {"snapshot_identifier": "snapshot-1", "outage_code": "OUT-001"},
            "/api/internal/v1/network/outages/OUT-001/customer-impact/",
        ),
        (
            "correlate_alarms",
            {"snapshot_identifier": "snapshot-1", "anchor_alarm_id": "ALM-001"},
            "/api/internal/v1/network/alarms/ALM-001/correlations/",
        ),
        (
            "rank_root_cause_candidates",
            {"snapshot_identifier": "snapshot-1", "outage_code": "OUT-001"},
            "/api/internal/v1/network/outages/OUT-001/root-cause-candidates/",
        ),
        (
            "get_longest_outage",
            {"snapshot_identifier": "snapshot-1", "limit": 1},
            "/api/internal/v1/network/outages/longest/",
        ),
    ],
)
def test_network_tool_calls_internal_api_path_and_wraps_response(
    tool_name,
    arguments,
    expected_path,
):
    client = FakeBackendClient()
    response = NetworkMCPTools(client).run(tool_name, arguments)

    assert response.success is True
    assert client.calls[0]["path"] == expected_path
    assert client.calls[0]["params"]["snapshot_identifier"] == "snapshot-1"
    assert response.metadata.snapshot_details["snapshot_key"] == "snapshot-1"
    assert response.metadata.request_id == "req-from-backend"


def test_topology_result_limit_is_sent_as_backend_limit_param():
    client = FakeBackendClient()

    NetworkMCPTools(client).run(
        "get_device_topology",
        {
            "snapshot_identifier": "snapshot-1",
            "device_code": "BNG-001",
            "result_limit": 17,
        },
    )

    assert client.calls[0]["params"]["limit"] == 17
    assert "result_limit" not in client.calls[0]["params"]


def test_missing_snapshot_identifier_returns_validation_error_without_backend_call():
    client = FakeBackendClient()

    response = NetworkMCPTools(client).run("search_alarms", {"limit": 5})

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_backend_client_errors_are_mapped_to_shared_envelope_without_traceback():
    client = FakeBackendClient(
        error=InternalAPIClientError(
            MCPError(
                code=MCPErrorCode.UPSTREAM_ERROR,
                message="Internal API request failed.",
                details={"reason": "ConnectError"},
            )
        )
    )

    response = NetworkMCPTools(client).run(
        "get_device_details",
        {"snapshot_identifier": "snapshot-1", "device_code": "BNG-001"},
    )

    assert response.success is False
    assert response.error.code == MCPErrorCode.UPSTREAM_ERROR
    assert "Traceback" not in response.model_dump_json()


def test_customer_impact_response_does_not_include_personal_or_commercial_details():
    client = FakeBackendClient(
        data={
            "outage_code": "OUT-001",
            "affected_subscription_count": 2,
            "affected_customer_count": 2,
            "segment_distribution": {"individual": 2},
            "priority_distribution": {"standard": 2},
            "technology_distribution": {"gpon": 2},
        }
    )

    response = NetworkMCPTools(client).run(
        "calculate_customer_impact",
        {"snapshot_identifier": "snapshot-1", "outage_code": "OUT-001"},
    )

    forbidden = {"phone", "email", "payment", "campaign", "compensation"}
    assert response.success is True
    assert forbidden.isdisjoint(response.data.keys())


def test_network_mcp_modules_do_not_import_django_or_backend_apps():
    source = inspect.getsource(network_server) + inspect.getsource(
        __import__("mcp_servers.network.tools", fromlist=[""])
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
