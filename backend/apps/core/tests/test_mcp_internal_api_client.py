import httpx
import pytest
from mcp_servers.shared.backend_client import (
    InternalAPIClient,
    InternalAPIClientConfig,
    InternalAPIClientError,
    map_http_error,
)
from mcp_servers.shared.contracts import MCPErrorCode

SERVICE_TOKEN = "test-mcp-service-token"


def test_client_config_loads_from_environment_with_explicit_timeout():
    config = InternalAPIClientConfig.from_env(
        {
            "MCP_BACKEND_BASE_URL": "http://127.0.0.1:8000/",
            "MCP_BACKEND_SERVICE_TOKEN": SERVICE_TOKEN,
            "MCP_BACKEND_TIMEOUT_SECONDS": "4",
        }
    )

    assert config.base_url == "http://127.0.0.1:8000"
    assert config.service_token == SERVICE_TOKEN
    assert config.timeout.connect == 2.0
    assert config.timeout.read == 4.0
    assert config.timeout.write == 5.0
    assert config.timeout.pool == 2.0


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {
            "MCP_BACKEND_BASE_URL": "http://backend.test",
            "MCP_BACKEND_SERVICE_TOKEN": "",
        },
        {
            "MCP_BACKEND_BASE_URL": "",
            "MCP_BACKEND_SERVICE_TOKEN": SERVICE_TOKEN,
        },
    ],
)
def test_client_config_requires_base_url_and_service_token(environ):
    with pytest.raises(ValueError):
        InternalAPIClientConfig.from_env(environ)


def test_client_sends_authorization_and_correlation_headers():
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"status": "ok"})

    client = InternalAPIClient(
        config=config(),
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="http://backend.test",
            timeout=config().timeout,
        ),
    )

    result = client.request_json("GET", "/api/internal/v1/health/", request_id="req-039-client")

    assert result == {"status": "ok"}
    assert seen_headers["authorization"] == f"Bearer {SERVICE_TOKEN}"
    assert seen_headers["x-correlation-id"] == "req-039-client"


def test_client_generates_correlation_id_when_request_id_is_missing():
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"status": "ok"})

    InternalAPIClient(
        config=config(),
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="http://backend.test",
            timeout=config().timeout,
        ),
    ).request_json("GET", "/api/internal/v1/health/")

    assert seen_headers["x-correlation-id"]


def test_client_rejects_invalid_request_id_before_sending():
    sent = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent = True
        return httpx.Response(200, json={"status": "ok"})

    client = InternalAPIClient(
        config=config(),
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="http://backend.test",
            timeout=config().timeout,
        ),
    )

    with pytest.raises(InternalAPIClientError) as exc:
        client.request_json("GET", "/api/internal/v1/health/", request_id="bad id")

    assert sent is False
    assert exc.value.mcp_error.code == MCPErrorCode.VALIDATION_ERROR


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (400, MCPErrorCode.VALIDATION_ERROR),
        (401, MCPErrorCode.AUTHENTICATION_ERROR),
        (403, MCPErrorCode.AUTHORIZATION_ERROR),
        (404, MCPErrorCode.NOT_FOUND),
        (409, MCPErrorCode.CONFLICT),
        (500, MCPErrorCode.INTERNAL_ERROR),
    ],
)
def test_http_status_codes_map_to_common_mcp_errors(status_code, expected_code):
    error = map_http_error(status_code)

    assert error.code == expected_code
    assert error.details == {"status_code": status_code}
    assert error.retryable is (status_code >= 500)


def test_client_maps_timeout_to_retryable_internal_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    client = InternalAPIClient(
        config=config(),
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="http://backend.test",
            timeout=config().timeout,
        ),
    )

    with pytest.raises(InternalAPIClientError) as exc:
        client.request_json("GET", "/api/internal/v1/health/", request_id="req-timeout")

    assert exc.value.mcp_error.code == MCPErrorCode.TIMEOUT
    assert exc.value.mcp_error.retryable is True
    assert exc.value.mcp_error.details == {"reason": "timeout"}


def test_client_does_not_expose_sensitive_response_body_in_error_details():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"traceback": "secret stack"})

    client = InternalAPIClient(
        config=config(),
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="http://backend.test",
            timeout=config().timeout,
        ),
    )

    with pytest.raises(InternalAPIClientError) as exc:
        client.request_json("GET", "/api/internal/v1/health/", request_id="req-500")

    assert exc.value.mcp_error.details == {"status_code": 500}
    assert "secret stack" not in str(exc.value.mcp_error)


def config() -> InternalAPIClientConfig:
    return InternalAPIClientConfig.from_env(
        {
            "MCP_BACKEND_BASE_URL": "http://backend.test",
            "MCP_BACKEND_SERVICE_TOKEN": SERVICE_TOKEN,
            "MCP_BACKEND_TIMEOUT_SECONDS": "5",
        }
    )
