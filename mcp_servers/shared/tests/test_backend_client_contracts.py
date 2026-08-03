from __future__ import annotations

import httpx
import pytest

from mcp_servers.shared.backend_client import (
    InternalAPIClient,
    InternalAPIClientConfig,
    InternalAPIClientError,
)
from mcp_servers.shared.contracts import MCPErrorCode


def make_client(handler):
    config = InternalAPIClientConfig(
        base_url="http://backend.test",
        service_token="contract-token",
        timeout=httpx.Timeout(1.0),
    )
    return InternalAPIClient(
        config=config,
        client=httpx.Client(
            base_url=config.base_url,
            transport=httpx.MockTransport(handler),
        ),
    )


def test_authenticated_request_and_correlation_id_round_trip():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer contract-token"
        assert request.headers["X-Correlation-ID"] == "contract-request-1"
        return httpx.Response(200, json={"ok": True})

    response = make_client(handler).request_json(
        "GET", "/api/internal/v1/health/", request_id="contract-request-1"
    )

    assert response == {"ok": True}


def test_invalid_correlation_id_does_not_call_backend():
    called = False

    def handler(_request):
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    with pytest.raises(InternalAPIClientError) as exc_info:
        make_client(handler).request_json("GET", "/health/", request_id="bad id")

    assert exc_info.value.mcp_error.code == MCPErrorCode.VALIDATION_ERROR
    assert called is False


@pytest.mark.parametrize(
    "status_code,expected_code",
    [
        (400, MCPErrorCode.VALIDATION_ERROR),
        (401, MCPErrorCode.AUTHENTICATION_ERROR),
        (403, MCPErrorCode.AUTHORIZATION_ERROR),
        (404, MCPErrorCode.NOT_FOUND),
        (409, MCPErrorCode.CONFLICT),
        (500, MCPErrorCode.INTERNAL_ERROR),
    ],
)
def test_http_error_mapping_is_shared(status_code, expected_code):
    def handler(_request):
        return httpx.Response(status_code, json={"secret": "should-not-be-exposed"})

    with pytest.raises(InternalAPIClientError) as exc_info:
        make_client(handler).request_json("GET", "/failure/")

    error = exc_info.value.mcp_error
    assert error.code == expected_code
    assert "should-not-be-exposed" not in error.message
    assert "traceback" not in str(error).lower()


def test_timeout_maps_to_common_timeout_error():
    def handler(_request):
        raise httpx.ReadTimeout("secret backend timeout detail")

    with pytest.raises(InternalAPIClientError) as exc_info:
        make_client(handler).request_json("GET", "/timeout/")

    error = exc_info.value.mcp_error
    assert error.code == MCPErrorCode.TIMEOUT
    assert error.details == {"reason": "timeout"}
    assert "secret" not in str(error).lower()


@pytest.mark.parametrize(
    ("upstream_code", "expected_code"),
    [
        ("provider_unavailable", MCPErrorCode.PROVIDER_UNAVAILABLE),
        ("provider_error", MCPErrorCode.PROVIDER_ERROR),
    ],
)
def test_embedding_provider_errors_are_safely_preserved(upstream_code, expected_code):
    def handler(_request):
        return httpx.Response(
            503,
            json={
                "error": {
                    "code": upstream_code,
                    "message": "secret provider detail",
                }
            },
        )

    with pytest.raises(InternalAPIClientError) as exc_info:
        make_client(handler).request_json("POST", "/api/internal/v1/rag/search/")

    error = exc_info.value.mcp_error
    assert error.code == expected_code
    assert "secret provider detail" not in str(error)
