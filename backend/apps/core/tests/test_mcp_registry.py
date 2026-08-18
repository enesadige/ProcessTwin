from django.test import override_settings

SERVICE_TOKEN = "test-internal-service-token"


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_registry_lists_static_descriptors_without_probing(client, monkeypatch):
    called = False

    def probe(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("apps.core.internal_views.probe_descriptor", probe)

    response = client.get(
        "/api/internal/v1/mcp/registry/",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-registry-1",
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "req-registry-1"
    services = response.json()["services"]
    actual = [
        (service["key"], service["module"], service["expected_tool_count"]) for service in services
    ]
    assert actual == [
        ("network", "mcp_servers.network", 9),
        ("customer", "mcp_servers.customer", 7),
        ("rules", "mcp_servers.rules", 8),
        ("compensation", "mcp_servers.compensation", 6),
        ("simulation", "mcp_servers.simulation_mcp", 4),
    ]
    assert all(service["status"] == "not_checked" for service in services)
    assert called is False


def test_registry_requires_internal_auth(client):
    response = client.get("/api/internal/v1/mcp/registry/")

    assert response.status_code == 401


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_registry_exposes_enabled_configuration(client, monkeypatch):
    monkeypatch.setenv("MCP_NETWORK_ENABLED", "false")
    response = client.get(
        "/api/internal/v1/mcp/registry/",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
    )

    network = response.json()["services"][0]
    assert network["configured"] is True
    assert network["enabled"] is False
    assert network["status"] == "not_checked"
