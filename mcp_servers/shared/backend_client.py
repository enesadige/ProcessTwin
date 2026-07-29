import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from mcp_servers.shared.contracts import MCPError, MCPErrorCode
from mcp_servers.shared.correlation import is_valid_correlation_id

DEFAULT_CONNECT_TIMEOUT_SECONDS = 2.0
DEFAULT_READ_TIMEOUT_SECONDS = 5.0
DEFAULT_WRITE_TIMEOUT_SECONDS = 5.0
DEFAULT_POOL_TIMEOUT_SECONDS = 2.0


class InternalAPIClientError(Exception):
    """Raised when the shared internal API client cannot complete a safe request."""

    def __init__(self, mcp_error: MCPError) -> None:
        super().__init__(mcp_error.message)
        self.mcp_error = mcp_error


@dataclass(frozen=True)
class InternalAPIClientConfig:
    base_url: str
    service_token: str
    timeout: httpx.Timeout

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "InternalAPIClientConfig":
        source = os.environ if environ is None else environ
        base_url = source.get("MCP_BACKEND_BASE_URL", "").rstrip("/")
        service_token = source.get("MCP_BACKEND_SERVICE_TOKEN", "")
        timeout_seconds = parse_timeout_seconds(
            source.get("MCP_BACKEND_TIMEOUT_SECONDS"),
            default=DEFAULT_READ_TIMEOUT_SECONDS,
        )
        if not base_url:
            raise ValueError("MCP_BACKEND_BASE_URL must be configured.")
        if not service_token:
            raise ValueError("MCP_BACKEND_SERVICE_TOKEN must be configured.")
        return cls(
            base_url=base_url,
            service_token=service_token,
            timeout=httpx.Timeout(
                timeout_seconds,
                connect=DEFAULT_CONNECT_TIMEOUT_SECONDS,
                read=timeout_seconds,
                write=DEFAULT_WRITE_TIMEOUT_SECONDS,
                pool=DEFAULT_POOL_TIMEOUT_SECONDS,
            ),
        )


class InternalAPIClient:
    def __init__(
        self,
        *,
        config: InternalAPIClientConfig,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.client = client or httpx.Client(base_url=config.base_url, timeout=config.timeout)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        request_id: str | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        correlation_id = request_id or str(uuid4())
        if not is_valid_correlation_id(correlation_id):
            raise InternalAPIClientError(
                MCPError(
                    code=MCPErrorCode.VALIDATION_ERROR,
                    message="Invalid correlation id.",
                    details={"header": "X-Correlation-ID"},
                    retryable=False,
                )
            )
        try:
            response = self.client.request(
                method,
                path,
                headers={
                    "Authorization": f"Bearer {self.config.service_token}",
                    "X-Correlation-ID": correlation_id,
                },
                json=json,
                params=params,
            )
        except httpx.TimeoutException as exc:
            raise InternalAPIClientError(
                MCPError(
                    code=MCPErrorCode.INTERNAL_ERROR,
                    message="Internal API request timed out.",
                    details={"reason": "timeout"},
                    retryable=True,
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise InternalAPIClientError(
                MCPError(
                    code=MCPErrorCode.INTERNAL_ERROR,
                    message="Internal API request failed.",
                    details={"reason": exc.__class__.__name__},
                    retryable=False,
                )
            ) from exc

        if response.status_code >= 400:
            raise InternalAPIClientError(map_http_error(response.status_code))
        return response.json()


def parse_timeout_seconds(value: str | None, *, default: float) -> float:
    if value in (None, ""):
        return default
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("MCP_BACKEND_TIMEOUT_SECONDS must be positive.")
    return parsed


def map_http_error(status_code: int) -> MCPError:
    if status_code == 400:
        return MCPError(
            code=MCPErrorCode.VALIDATION_ERROR,
            message="Internal API validation error.",
            details={"status_code": status_code},
            retryable=False,
        )
    if status_code in {401, 403}:
        return MCPError(
            code=MCPErrorCode.UNSUPPORTED_OPERATION,
            message="Internal API authentication or authorization failed.",
            details={"status_code": status_code},
            retryable=False,
        )
    if status_code == 404:
        return MCPError(
            code=MCPErrorCode.NOT_FOUND,
            message="Internal API resource was not found.",
            details={"status_code": status_code},
            retryable=False,
        )
    if status_code == 409:
        return MCPError(
            code=MCPErrorCode.CONFLICT,
            message="Internal API conflict.",
            details={"status_code": status_code},
            retryable=False,
        )
    return MCPError(
        code=MCPErrorCode.INTERNAL_ERROR,
        message="Internal API returned an unexpected server error.",
        details={"status_code": status_code},
        retryable=status_code >= 500,
    )
