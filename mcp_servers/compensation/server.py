from __future__ import annotations

import json
from importlib.metadata import version
from typing import Any

import anyio
import mcp_types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from mcp_servers.compensation import COMPENSATION_MCP_VERSION
from mcp_servers.compensation.tools import (
    COMPENSATION_TOOL_DEFINITIONS,
    CompensationMCPTools,
)
from mcp_servers.shared.backend_client import InternalAPIClient, InternalAPIClientConfig
from mcp_servers.shared.contracts import MCPToolResponse

SERVER_NAME = "processtwin-compensation"


def build_server(tools: CompensationMCPTools) -> Server:
    async def list_tools(_ctx, _params) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=definition.name,
                    description=definition.description,
                    inputSchema=definition.input_model.model_json_schema(),
                    outputSchema=MCPToolResponse[dict[str, Any]].model_json_schema(),
                )
                for definition in COMPENSATION_TOOL_DEFINITIONS.values()
            ]
        )

    async def call_tool(
        _ctx,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        response = await anyio.to_thread.run_sync(
            tools.run,
            params.name,
            params.arguments or {},
        )
        payload = response.model_dump(mode="json")
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                )
            ],
            structuredContent=payload,
            isError=not response.success,
        )

    return Server(
        SERVER_NAME,
        version=COMPENSATION_MCP_VERSION,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


async def run_stdio() -> None:
    config = InternalAPIClientConfig.from_env()
    client = InternalAPIClient(config=config)
    server = build_server(CompensationMCPTools(client))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
            raise_exceptions=False,
        )


def main() -> None:
    sdk_version = version("mcp")
    if sdk_version != "2.0.0":
        raise SystemExit(f"mcp==2.0.0 is required, found {sdk_version}.")
    try:
        anyio.run(run_stdio)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
