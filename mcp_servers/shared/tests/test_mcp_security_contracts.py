from __future__ import annotations

import ast
from pathlib import Path

import pytest
from django.test import override_settings

from mcp_servers.compensation.tools import COMPENSATION_TOOL_DEFINITIONS
from mcp_servers.customer.tools import CUSTOMER_TOOL_DEFINITIONS
from mcp_servers.network.tools import NETWORK_TOOL_DEFINITIONS
from mcp_servers.rules.tools import RULE_TOOL_DEFINITIONS

ROOT = Path(__file__).resolve().parents[3]
MCP_MATRIX = [
    ("network", "mcp_servers.network", NETWORK_TOOL_DEFINITIONS),
    ("customer", "mcp_servers.customer", CUSTOMER_TOOL_DEFINITIONS),
    ("rules", "mcp_servers.rules", RULE_TOOL_DEFINITIONS),
    ("compensation", "mcp_servers.compensation", COMPENSATION_TOOL_DEFINITIONS),
]


def imported_modules(package_path: Path):
    for source_path in package_path.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                yield from (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                yield node.module


@pytest.mark.parametrize("package,package_name,_definitions", MCP_MATRIX)
def test_mcp_source_does_not_import_django_or_orm(package, package_name, _definitions):
    imported = set(imported_modules(ROOT / "mcp_servers" / package))

    assert not any(module == "django" or module.startswith("django.") for module in imported)
    assert not any(module.startswith("apps") for module in imported)


@pytest.mark.parametrize("package,package_name,_definitions", MCP_MATRIX)
def test_mcp_packages_do_not_import_another_business_mcp(package, package_name, _definitions):
    imported = set(imported_modules(ROOT / "mcp_servers" / package))
    business_packages = {
        "mcp_servers.network",
        "mcp_servers.customer",
        "mcp_servers.rules",
        "mcp_servers.compensation",
    }
    imported_business_packages = {
        module
        for module in imported
        if any(
            module == business or module.startswith(f"{business}.")
            for business in business_packages
        )
    }
    assert all(
        module == package_name or module.startswith(f"{package_name}.")
        for module in imported_business_packages
    )


@override_settings(INTERNAL_API_SERVICE_TOKEN="contract-token")
@pytest.mark.parametrize(
    "path",
    [
        "/api/internal/v1/network/devices/BNG-001/",
        "/api/internal/v1/customer/customers/CUST-001/profile/",
        "/api/internal/v1/rules/",
        "/api/internal/v1/compensation/evidence/",
    ],
)
def test_all_mcp_internal_entrypoints_require_auth(client, path):
    unauthenticated = client.get(path)
    authenticated = client.get(path, HTTP_AUTHORIZATION="Bearer contract-token")

    assert unauthenticated.status_code == 401
    assert authenticated.status_code != 401


@override_settings(INTERNAL_API_SERVICE_TOKEN="contract-token")
def test_rule_document_search_internal_endpoint_requires_auth(client):
    path = "/api/internal/v1/rag/search/"
    payload = {"query": "REFUND-001", "snapshot_identifier": "missing-snapshot"}

    unauthenticated = client.post(path, data=payload, content_type="application/json")
    authenticated = client.post(
        path,
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer contract-token",
    )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code != 401
