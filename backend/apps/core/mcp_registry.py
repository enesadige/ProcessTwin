from __future__ import annotations

import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MCPDescriptor:
    key: str
    display_name: str
    module: str
    expected_tool_count: int
    enabled: bool = True


_DESCRIPTORS = (
    MCPDescriptor("network", "Network MCP", "mcp_servers.network", 9),
    MCPDescriptor("customer", "Customer MCP", "mcp_servers.customer", 7),
    MCPDescriptor("rules", "Rule MCP", "mcp_servers.rules", 8),
    MCPDescriptor("compensation", "Compensation MCP", "mcp_servers.compensation", 6),
    MCPDescriptor("simulation", "Simulation MCP", "mcp_servers.simulation_mcp", 4),
)


def _is_enabled(key: str) -> bool:
    value = os.environ.get(f"MCP_{key.upper()}_ENABLED")
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def get_descriptors() -> tuple[MCPDescriptor, ...]:
    return tuple(
        MCPDescriptor(
            key=descriptor.key,
            display_name=descriptor.display_name,
            module=descriptor.module,
            expected_tool_count=descriptor.expected_tool_count,
            enabled=_is_enabled(descriptor.key),
        )
        for descriptor in _DESCRIPTORS
    )


def get_descriptor(key: str) -> MCPDescriptor | None:
    return next((descriptor for descriptor in get_descriptors() if descriptor.key == key), None)


def descriptor_payload(descriptor: MCPDescriptor) -> dict:
    payload = asdict(descriptor)
    payload.update(
        {
            "configured": True,
            "status": "not_checked",
            "server_name": None,
            "version": None,
            "tools": [],
            "tool_count": None,
            "tool_count_matches": None,
            "last_response_time_ms": None,
            "last_checked_at": None,
            "warning": None,
            "error": None,
        }
    )
    return payload
