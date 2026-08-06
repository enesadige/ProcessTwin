"""Synchronous allowlisted MCP stdio runner for local acceptance use."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django.conf import settings
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_servers.shared.contracts import MCPError, MCPErrorCode, MCPMetadata, MCPToolResponse

from apps.orchestration.tool_plan import MCPServer

_MODULES = {
    MCPServer.NETWORK: "mcp_servers.network",
    MCPServer.CUSTOMER: "mcp_servers.customer",
    MCPServer.RULE: "mcp_servers.rules",
    MCPServer.COMPENSATION: "mcp_servers.compensation",
}


class StdioMCPToolRunner:
    """Invoke one allowlisted MCP tool through a fresh local stdio process."""

    def __init__(self, server: MCPServer, *, timeout_seconds: float = 15.0) -> None:
        self.server = server
        self.timeout_seconds = timeout_seconds

    def run(
        self, tool_name: str, arguments: dict[str, Any] | None
    ) -> MCPToolResponse[dict[str, Any]]:
        return asyncio.run(self._run_async(tool_name, arguments or {}))

    async def _run_async(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> MCPToolResponse[dict[str, Any]]:
        root = Path(__file__).resolve().parents[3]
        backend_base_url = os.environ.get("MCP_BACKEND_BASE_URL", "http://127.0.0.1:8000")
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", _MODULES[self.server]],
            cwd=str(root),
            env={
                **os.environ,
                "MCP_BACKEND_BASE_URL": backend_base_url,
                "MCP_BACKEND_SERVICE_TOKEN": settings.INTERNAL_API_SERVICE_TOKEN,
            },
        )
        try:
            with open(os.devnull, "w", encoding="utf-8") as errlog:
                async with stdio_client(server, errlog=errlog) as (read_stream, write_stream):
                    session = ClientSession(read_stream, write_stream)
                    async with session:
                        await asyncio.wait_for(session.initialize(), self.timeout_seconds)
                        result = await asyncio.wait_for(
                            session.call_tool(tool_name, dict(arguments)), self.timeout_seconds
                        )
        except TimeoutError:
            return self._error(
                tool_name,
                arguments,
                MCPErrorCode.TIMEOUT,
                "MCP process timed out.",
                True,
            )
        except Exception:
            return self._error(
                tool_name,
                arguments,
                MCPErrorCode.UPSTREAM_ERROR,
                "MCP process could not complete the request.",
                True,
            )

        payload = getattr(result, "structuredContent", None)
        if not isinstance(payload, Mapping):
            try:
                payload = json.loads(result.content[0].text)
            except (AttributeError, IndexError, TypeError, json.JSONDecodeError):
                return self._error(
                    tool_name,
                    arguments,
                    MCPErrorCode.INTERNAL_ERROR,
                    "MCP process returned an invalid response.",
                    False,
                )
        try:
            return MCPToolResponse[dict[str, Any]].model_validate(payload)
        except ValueError:
            return self._error(
                tool_name,
                arguments,
                MCPErrorCode.INTERNAL_ERROR,
                "MCP process returned an invalid response.",
                False,
            )

    def _error(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        code: MCPErrorCode,
        message: str,
        retryable: bool,
    ) -> MCPToolResponse[dict[str, Any]]:
        return MCPToolResponse(
            success=False,
            error=MCPError(code=code, message=message, retryable=retryable),
            metadata=MCPMetadata(
                tool_name=f"{self.server.value}.{tool_name}",
                tool_version="stdio-acceptance-v1",
                request_id=arguments.get("request_id"),
                deterministic=True,
                snapshot_identifier=arguments.get("snapshot_identifier"),
            ),
        )
