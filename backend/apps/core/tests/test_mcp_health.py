import pytest
from django.test import override_settings

from apps.core.mcp_health import ProbeError, probe_descriptor, validate_timeout
from apps.core.mcp_registry import get_descriptor

SERVICE_TOKEN = "test-internal-service-token"


def active_probe():
    return {
        "key": "network",
        "display_name": "Network MCP",
        "configured": True,
        "enabled": True,
        "status": "active",
        "server_name": "processtwin-network",
        "version": "0.1.0",
        "tools": ["get_device_details"] * 9,
        "tool_count": 9,
        "expected_tool_count": 9,
        "tool_count_matches": True,
        "last_response_time_ms": 12.5,
        "last_checked_at": "2026-07-31T10:00:00+00:00",
        "warning": None,
        "error": None,
    }


@pytest.mark.parametrize("value", [None, "", "0.25", "10"])
def test_timeout_bounds_accept_valid_values(value):
    assert validate_timeout(value) >= 0.25


@pytest.mark.parametrize("value", ["nope", "0.1", "10.1"])
def test_timeout_bounds_reject_invalid_values(value):
    with pytest.raises(ProbeError) as exc_info:
        validate_timeout(value)
    assert exc_info.value.code == "validation_error"


def test_disabled_probe_does_not_start_process(monkeypatch):
    descriptor = get_descriptor("network")
    assert descriptor is not None
    disabled = descriptor.__class__(
        key=descriptor.key,
        display_name=descriptor.display_name,
        module=descriptor.module,
        expected_tool_count=descriptor.expected_tool_count,
        enabled=False,
    )
    monkeypatch.setattr("apps.core.mcp_health.asyncio.run", lambda *_args: pytest.fail("started"))

    result = probe_descriptor(disabled, 1.0)

    assert result["status"] == "disabled"
    assert result["enabled"] is False


def test_probe_process_failure_is_safe(monkeypatch):
    descriptor = get_descriptor("network")
    assert descriptor is not None

    async def fail(*_args, **_kwargs):
        raise ProbeError("process_start_failed", "MCP process could not be started.")

    monkeypatch.setattr("apps.core.mcp_health._probe_async", fail)
    result = probe_descriptor(descriptor, 1.0)

    assert result["status"] == "unavailable"
    assert result["error"] == {
        "code": "process_start_failed",
        "message": "MCP process could not be started.",
    }
    assert "traceback" not in str(result).lower()


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_health_unknown_service_and_timeout_validation(client):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {SERVICE_TOKEN}"}
    unknown = client.get("/api/internal/v1/mcp/health/?service=unknown", **headers)
    timeout = client.get("/api/internal/v1/mcp/health/?timeout_seconds=0.1", **headers)

    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "validation_error"
    assert timeout.status_code == 400
    assert timeout.json()["error"]["code"] == "validation_error"


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_health_uses_probe_and_preserves_correlation(client, monkeypatch):
    monkeypatch.setattr(
        "apps.core.internal_views.probe_descriptor",
        lambda *_args, **_kwargs: active_probe(),
    )

    response = client.get(
        "/api/internal/v1/mcp/health/?service=network",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-health-1",
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "req-health-1"
    assert response.json()["services"][0]["status"] == "active"
    assert response.json()["services"][0]["last_response_time_ms"] > 0


@override_settings(INTERNAL_API_SERVICE_TOKEN=SERVICE_TOKEN)
def test_health_requires_internal_auth(client):
    response = client.get("/api/internal/v1/mcp/health/")

    assert response.status_code == 401
