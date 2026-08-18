from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from mcp_servers.shared.backend_client import InternalAPIClient, InternalAPIClientError
from mcp_servers.shared.contracts import (
    MCPError,
    MCPErrorCode,
    MCPEvidence,
    MCPMetadata,
    MCPToolResponse,
    MCPWarning,
)
from mcp_servers.simulation_mcp import SIMULATION_MCP_VERSION
from mcp_servers.simulation_mcp.models import SimulationEventsInput, SimulationRunInput


class SimulationToolDefinition:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_model: type[BaseModel],
        path_suffix: str,
        params_builder: Callable[[BaseModel], dict[str, Any]],
    ) -> None:
        self.name = name
        self.description = description
        self.input_model = input_model
        self.path_suffix = path_suffix
        self.params_builder = params_builder

    def path(self, model: BaseModel) -> str:
        return f"/api/internal/v1/simulation/runs/{model.simulation_run_code}/{self.path_suffix}/"


def _params(model: BaseModel) -> dict[str, Any]:
    payload = model.model_dump(mode="json", exclude_none=True)
    payload.pop("request_id", None)
    payload.pop("simulation_run_code", None)
    return payload


SIMULATION_TOOL_DEFINITIONS: dict[str, SimulationToolDefinition] = {
    "get_simulation_run_status": SimulationToolDefinition(
        name="get_simulation_run_status",
        description="Return persisted simulation-local run status and safe metadata.",
        input_model=SimulationRunInput,
        path_suffix="status",
        params_builder=_params,
    ),
    "get_simulation_result": SimulationToolDefinition(
        name="get_simulation_result",
        description="Return the already-persisted canonical simulation result without execution.",
        input_model=SimulationRunInput,
        path_suffix="result",
        params_builder=_params,
    ),
    "get_simulation_events": SimulationToolDefinition(
        name="get_simulation_events",
        description="Return persisted simulation timeline events using cursor pagination.",
        input_model=SimulationEventsInput,
        path_suffix="events",
        params_builder=_params,
    ),
    "get_simulation_evidence": SimulationToolDefinition(
        name="get_simulation_evidence",
        description=(
            "Return finalized persisted hypothetical simulation evidence without materialization."
        ),
        input_model=SimulationRunInput,
        path_suffix="evidence",
        params_builder=_params,
    ),
}


class SimulationMCPTools:
    def __init__(self, client: InternalAPIClient) -> None:
        self.client = client

    def run(
        self, tool_name: str, arguments: dict[str, Any] | None
    ) -> MCPToolResponse[dict[str, Any]]:
        definition = SIMULATION_TOOL_DEFINITIONS.get(tool_name)
        if definition is None:
            return self._failure(
                tool_name=tool_name,
                request_id=None,
                snapshot_identifier=None,
                error=MCPError(code=MCPErrorCode.NOT_FOUND, message="Unknown Simulation MCP tool."),
            )
        try:
            model = definition.input_model.model_validate(arguments or {})
        except ValidationError as exc:
            raw = arguments or {}
            return self._failure(
                tool_name=tool_name,
                request_id=raw.get("request_id"),
                snapshot_identifier=raw.get("snapshot_identifier"),
                error=MCPError(
                    code=MCPErrorCode.VALIDATION_ERROR,
                    message="Invalid Simulation MCP tool input.",
                    details={"errors": exc.errors(include_url=False)},
                ),
            )
        try:
            payload = self.client.request_json(
                "GET",
                definition.path(model),
                request_id=model.request_id,
                params=definition.params_builder(model),
            )
        except InternalAPIClientError as exc:
            return self._failure(
                tool_name=tool_name,
                request_id=model.request_id,
                snapshot_identifier=model.snapshot_identifier,
                error=exc.mcp_error,
            )
        metadata = payload.get("metadata", {})
        return MCPToolResponse[dict[str, Any]](
            success=True,
            data=payload.get("data", {}),
            metadata=MCPMetadata(
                tool_name=f"simulation.{tool_name}",
                tool_version=SIMULATION_MCP_VERSION,
                request_id=metadata.get("correlation_id") or model.request_id or str(uuid4()),
                deterministic=True,
                snapshot_identifier=model.snapshot_identifier,
                snapshot_details=metadata.get("snapshot", {}),
            ),
            warnings=[MCPWarning.model_validate(item) for item in payload.get("warnings", [])],
            evidence=[MCPEvidence.model_validate(item) for item in payload.get("evidence", [])],
        )

    @staticmethod
    def _failure(
        *,
        tool_name: str,
        request_id: str | None,
        snapshot_identifier: str | None,
        error: MCPError,
    ) -> MCPToolResponse[dict[str, Any]]:
        return MCPToolResponse[dict[str, Any]](
            success=False,
            error=error,
            metadata=MCPMetadata(
                tool_name=f"simulation.{tool_name}",
                tool_version=SIMULATION_MCP_VERSION,
                request_id=request_id,
                deterministic=True,
                snapshot_identifier=snapshot_identifier,
            ),
        )
