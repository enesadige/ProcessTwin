from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .mcp_registry import MCPDescriptor

MIN_TIMEOUT_SECONDS = 0.25
MAX_TIMEOUT_SECONDS = 10.0
DEFAULT_TIMEOUT_SECONDS = 3.0


class ProbeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def validate_timeout(value: str | None) -> float:
    if value in (None, ""):
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(value)
    except ValueError as exc:
        raise ProbeError("validation_error", "timeout_seconds must be numeric.") from exc
    if not MIN_TIMEOUT_SECONDS <= timeout <= MAX_TIMEOUT_SECONDS:
        raise ProbeError(
            "validation_error",
            f"timeout_seconds must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}.",
        )
    return timeout


async def _probe_async(
    descriptor: MCPDescriptor,
    timeout_seconds: float,
    *,
    backend_base_url: str,
) -> dict:
    root = Path(__file__).resolve().parents[3]
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", descriptor.module],
        cwd=str(root),
        env={
            **os.environ,
            "MCP_BACKEND_BASE_URL": backend_base_url,
            "MCP_BACKEND_SERVICE_TOKEN": settings.INTERNAL_API_SERVICE_TOKEN,
        },
    )
    started = time.perf_counter()
    try:
        with open(os.devnull, "w", encoding="utf-8") as errlog:
            async with stdio_client(server, errlog=errlog) as (read_stream, write_stream):
                session = ClientSession(read_stream, write_stream)
                async with session:
                    try:
                        initialized = await asyncio.wait_for(session.initialize(), timeout_seconds)
                    except TimeoutError as exc:
                        raise ProbeError("timeout", "MCP initialize timed out.") from exc
                    except Exception as exc:
                        raise ProbeError("initialize_failed", "MCP initialize failed.") from exc

                    try:
                        listed = await asyncio.wait_for(session.list_tools(), timeout_seconds)
                    except TimeoutError as exc:
                        raise ProbeError("timeout", "MCP list_tools timed out.") from exc
                    except Exception as exc:
                        raise ProbeError("list_tools_failed", "MCP list_tools failed.") from exc
    except ProbeError:
        raise
    except TimeoutError as exc:
        raise ProbeError("timeout", "MCP probe timed out.") from exc
    except Exception as exc:
        raise ProbeError("process_start_failed", "MCP process could not be started.") from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    tools = [tool.name for tool in listed.tools]
    return {
        "key": descriptor.key,
        "display_name": descriptor.display_name,
        "configured": True,
        "enabled": descriptor.enabled,
        "status": "active",
        "server_name": initialized.server_info.name,
        "version": initialized.server_info.version,
        "tools": tools,
        "tool_count": len(tools),
        "expected_tool_count": descriptor.expected_tool_count,
        "tool_count_matches": len(tools) == descriptor.expected_tool_count,
        "last_response_time_ms": elapsed_ms,
        "last_checked_at": datetime.now(UTC).isoformat(),
        "warning": (
            None
            if len(tools) == descriptor.expected_tool_count
            else "Tool count differs from registry expectation."
        ),
        "error": None,
    }


def probe_descriptor(
    descriptor: MCPDescriptor,
    timeout_seconds: float,
    *,
    backend_base_url: str = "http://127.0.0.1:8000",
) -> dict:
    if not descriptor.enabled:
        return {
            "key": descriptor.key,
            "display_name": descriptor.display_name,
            "configured": True,
            "enabled": False,
            "status": "disabled",
            "server_name": None,
            "version": None,
            "tools": [],
            "tool_count": None,
            "expected_tool_count": descriptor.expected_tool_count,
            "tool_count_matches": None,
            "last_response_time_ms": None,
            "last_checked_at": datetime.now(UTC).isoformat(),
            "warning": None,
            "error": None,
        }
    try:
        return asyncio.run(
            _probe_async(
                descriptor,
                timeout_seconds,
                backend_base_url=backend_base_url,
            )
        )
    except ProbeError as exc:
        return {
            "key": descriptor.key,
            "display_name": descriptor.display_name,
            "configured": True,
            "enabled": True,
            "status": "unavailable",
            "server_name": None,
            "version": None,
            "tools": [],
            "tool_count": 0,
            "expected_tool_count": descriptor.expected_tool_count,
            "tool_count_matches": False,
            "last_response_time_ms": None,
            "last_checked_at": datetime.now(UTC).isoformat(),
            "warning": None,
            "error": {"code": exc.code, "message": exc.message},
        }
