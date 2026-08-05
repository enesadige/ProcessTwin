from __future__ import annotations

import inspect

import pytest

from mcp_servers.customer import server as customer_server
from mcp_servers.customer.tools import CUSTOMER_TOOL_DEFINITIONS, CustomerMCPTools
from mcp_servers.shared.backend_client import InternalAPIClientError
from mcp_servers.shared.contracts import MCPError, MCPErrorCode


def test_all_seven_customer_tools_are_registered():
    assert sorted(CUSTOMER_TOOL_DEFINITIONS) == [
        "get_customer_compensation_history",
        "get_customer_outage_history",
        "get_customer_payment_status",
        "get_customer_profile",
        "get_customer_subscription",
        "list_customers_by_device",
        "list_customers_by_location",
    ]


def test_causal_customer_history_maps_real_impact_aggregate():
    client = FakeBackendClient(data={"causal_event": {"code": "CE-001"}, "impact": {"potential": 5, "verified_impacted": 1, "verified_no_impact": 2, "insufficient_evidence": 1, "pending": 1, "failover_protected_count": 2, "reason_codes": {"failover_protected": 2}}})
    response = CustomerMCPTools(client).run("get_customer_outage_history", {"snapshot_identifier": "snapshot-1", "causal_event_code": "CE-001"})
    assert response.success is True
    assert client.calls[0]["path"].endswith("/CE-001/analysis/")
    assert response.data["failover_protected_count"] == 2
    assert response.data["verified_no_impact_count"] == 2


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_path"),
    [
        (
            "get_customer_profile",
            {"snapshot_identifier": "snapshot-1", "customer_number": "CUST-001"},
            "/api/internal/v1/customer/customers/CUST-001/profile/",
        ),
        (
            "get_customer_subscription",
            {"snapshot_identifier": "snapshot-1", "subscription_number": "SUB-001"},
            "/api/internal/v1/customer/subscriptions/",
        ),
        (
            "get_customer_payment_status",
            {"snapshot_identifier": "snapshot-1", "customer_number": "CUST-001"},
            "/api/internal/v1/customer/payments/",
        ),
        (
            "get_customer_outage_history",
            {"snapshot_identifier": "snapshot-1", "subscription_number": "SUB-001"},
            "/api/internal/v1/customer/outages/history/",
        ),
        (
            "get_customer_compensation_history",
            {"snapshot_identifier": "snapshot-1", "customer_number": "CUST-001"},
            "/api/internal/v1/customer/compensation/history/",
        ),
        (
            "list_customers_by_device",
            {"snapshot_identifier": "snapshot-1", "device_code": "BNG-001"},
            "/api/internal/v1/customer/customers/by-device/BNG-001/",
        ),
        (
            "list_customers_by_location",
            {"snapshot_identifier": "snapshot-1", "city": "İstanbul"},
            "/api/internal/v1/customer/customers/by-location/",
        ),
    ],
)
def test_customer_tool_calls_internal_api_path_and_wraps_response(
    tool_name,
    arguments,
    expected_path,
):
    client = FakeBackendClient()
    response = CustomerMCPTools(client).run(tool_name, arguments)

    assert response.success is True
    assert client.calls[0]["path"] == expected_path
    assert client.calls[0]["params"]["snapshot_identifier"] == "snapshot-1"
    assert response.metadata.snapshot_details["snapshot_key"] == "snapshot-1"
    assert response.metadata.request_id == "req-from-backend"


def test_missing_snapshot_identifier_returns_validation_error_without_backend_call():
    client = FakeBackendClient()

    response = CustomerMCPTools(client).run(
        "get_customer_profile",
        {"customer_number": "CUST-001"},
    )

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_one_of_customer_or_subscription_validation_is_enforced():
    client = FakeBackendClient()

    missing = CustomerMCPTools(client).run(
        "get_customer_subscription",
        {"snapshot_identifier": "snapshot-1"},
    )
    duplicate = CustomerMCPTools(client).run(
        "get_customer_subscription",
        {
            "snapshot_identifier": "snapshot-1",
            "customer_number": "CUST-001",
            "subscription_number": "SUB-001",
        },
    )

    assert missing.success is False
    assert duplicate.success is False
    assert missing.error.code == MCPErrorCode.VALIDATION_ERROR
    assert duplicate.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_location_listing_without_location_filter_is_rejected():
    client = FakeBackendClient()

    response = CustomerMCPTools(client).run(
        "list_customers_by_location",
        {"snapshot_identifier": "snapshot-1"},
    )

    assert response.success is False
    assert response.error.code == MCPErrorCode.VALIDATION_ERROR
    assert client.calls == []


def test_include_display_name_flag_is_passed_explicitly_to_backend():
    client = FakeBackendClient()

    CustomerMCPTools(client).run(
        "get_customer_profile",
        {
            "snapshot_identifier": "snapshot-1",
            "customer_number": "CUST-001",
            "include_display_name": True,
        },
    )

    assert client.calls[0]["params"]["include_display_name"] is True


def test_customer_backend_errors_are_mapped_without_traceback_or_secret_leak():
    client = FakeBackendClient(
        error=InternalAPIClientError(
            MCPError(
                code=MCPErrorCode.UPSTREAM_ERROR,
                message="Internal API request failed.",
                details={"reason": "ConnectError"},
            )
        )
    )

    response = CustomerMCPTools(client).run(
        "get_customer_profile",
        {"snapshot_identifier": "snapshot-1", "customer_number": "CUST-001"},
    )

    serialized = response.model_dump_json()
    assert response.success is False
    assert response.error.code == MCPErrorCode.UPSTREAM_ERROR
    assert "Traceback" not in serialized
    assert "token" not in serialized.lower()


def test_customer_mcp_modules_do_not_import_django_or_backend_apps():
    source = inspect.getsource(customer_server) + inspect.getsource(
        __import__("mcp_servers.customer.tools", fromlist=[""])
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
