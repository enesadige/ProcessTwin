from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from mcp_servers.network import NETWORK_MCP_VERSION
from mcp_servers.network.models import (
    AggregateLocationImpactInput,
    CalculateCustomerImpactInput,
    CorrelateAlarmsInput,
    GetDeviceDetailsInput,
    GetDeviceTopologyInput,
    GetLongestOutageInput,
    GetOutageDetailsInput,
    RankRootCauseCandidatesInput,
    SearchAlarmsInput,
    SearchOutagesInput,
)
from mcp_servers.shared.backend_client import InternalAPIClient, InternalAPIClientError
from mcp_servers.shared.contracts import (
    MCPError,
    MCPErrorCode,
    MCPEvidence,
    MCPMetadata,
    MCPToolResponse,
    MCPWarning,
)


class NetworkToolDefinition:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_model: type[BaseModel],
        method: str,
        path_builder: Callable[[BaseModel], str],
        params_builder: Callable[[BaseModel], dict[str, Any]],
    ) -> None:
        self.name = name
        self.description = description
        self.input_model = input_model
        self.method = method
        self.path_builder = path_builder
        self.params_builder = params_builder


def _path(template: str, field_name: str | None = None):
    def build(model: BaseModel) -> str:
        if field_name is None:
            return template
        return template.format(value=getattr(model, field_name))

    return build


def _params(model: BaseModel, *, rename: dict[str, str] | None = None) -> dict[str, Any]:
    rename = rename or {}
    raw = model.model_dump(mode="json", exclude_none=True)
    raw.pop("request_id", None)
    result: dict[str, Any] = {}
    for key, value in raw.items():
        result[rename.get(key, key)] = value
    return result


def _causal_or_path(path: str, field_name: str):
    def build(model: BaseModel) -> str:
        code = getattr(model, "causal_event_code", None)
        return (
            f"/api/internal/v1/operations/causal-events/{code}/analysis/"
            if code
            else path.format(value=getattr(model, field_name))
        )

    return build


NETWORK_TOOL_DEFINITIONS: dict[str, NetworkToolDefinition] = {
    "aggregate_location_impact": NetworkToolDefinition(
        name="aggregate_location_impact",
        description="Return canonical aggregate impact counts for an explicit date/location scope.",
        input_model=AggregateLocationImpactInput,
        method="GET",
        path_builder=_path("/api/internal/v1/network/outages/aggregate-impact/"),
        params_builder=_params,
    ),
    "get_device_details": NetworkToolDefinition(
        name="get_device_details",
        description=(
            "Return deterministic details, links, ports, and risk domains for one network device."
        ),
        input_model=GetDeviceDetailsInput,
        method="GET",
        path_builder=_path("/api/internal/v1/network/devices/{value}/", "device_code"),
        params_builder=_params,
    ),
    "get_device_topology": NetworkToolDefinition(
        name="get_device_topology",
        description=(
            "Traverse deterministic network topology ancestors, descendants, "
            "or subgraph for one device."
        ),
        input_model=GetDeviceTopologyInput,
        method="GET",
        path_builder=_path("/api/internal/v1/network/devices/{value}/topology/", "device_code"),
        params_builder=lambda model: _params(model, rename={"result_limit": "limit"}),
    ),
    "search_alarms": NetworkToolDefinition(
        name="search_alarms",
        description=(
            "Search alarms with explicit structured filters and deterministic cursor pagination."
        ),
        input_model=SearchAlarmsInput,
        method="GET",
        path_builder=_path("/api/internal/v1/network/alarms/"),
        params_builder=_params,
    ),
    "search_outages": NetworkToolDefinition(
        name="search_outages",
        description=(
            "Search outage records with explicit structured filters and deterministic durations."
        ),
        input_model=SearchOutagesInput,
        method="GET",
        path_builder=_path("/api/internal/v1/network/outages/"),
        params_builder=_params,
    ),
    "get_outage_details": NetworkToolDefinition(
        name="get_outage_details",
        description=(
            "Return deterministic outage details, related incident, alarms, "
            "and maintenance context."
        ),
        input_model=GetOutageDetailsInput,
        method="GET",
        path_builder=_path("/api/internal/v1/network/outages/{value}/", "outage_code"),
        params_builder=_params,
    ),
    "calculate_customer_impact": NetworkToolDefinition(
        name="calculate_customer_impact",
        description=(
            "Return aggregate customer-impact counts without personal or commercial details."
        ),
        input_model=CalculateCustomerImpactInput,
        method="GET",
        path_builder=_path(
            "/api/internal/v1/network/outages/{value}/customer-impact/",
            "outage_code",
        ),
        params_builder=_params,
    ),
    "correlate_alarms": NetworkToolDefinition(
        name="correlate_alarms",
        description="Return deterministic alarm-correlation candidates for one anchor alarm.",
        input_model=CorrelateAlarmsInput,
        method="GET",
        path_builder=_causal_or_path(
            "/api/internal/v1/network/alarms/{value}/correlations/",
            "anchor_alarm_id",
        ),
        params_builder=_params,
    ),
    "rank_root_cause_candidates": NetworkToolDefinition(
        name="rank_root_cause_candidates",
        description=(
            "Rank deterministic root-cause candidates for an outage using backend evidence."
        ),
        input_model=RankRootCauseCandidatesInput,
        method="GET",
        path_builder=_causal_or_path(
            "/api/internal/v1/network/outages/{value}/root-cause-candidates/",
            "outage_code",
        ),
        params_builder=_params,
    ),
    "get_longest_outage": NetworkToolDefinition(
        name="get_longest_outage",
        description="Return ranked longest outages for explicit time/location/device filters.",
        input_model=GetLongestOutageInput,
        method="GET",
        path_builder=_path("/api/internal/v1/network/outages/longest/"),
        params_builder=_params,
    ),
}


class NetworkMCPTools:
    def __init__(self, client: InternalAPIClient) -> None:
        self.client = client

    def run(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> MCPToolResponse[dict[str, Any]]:
        definition = NETWORK_TOOL_DEFINITIONS.get(tool_name)
        if definition is None:
            return self._failure(
                tool_name=tool_name,
                request_id=None,
                snapshot_identifier=None,
                error=MCPError(
                    code=MCPErrorCode.NOT_FOUND,
                    message="Unknown Network MCP tool.",
                    details={"tool_name": tool_name},
                ),
            )
        try:
            model = definition.input_model.model_validate(arguments or {})
        except ValidationError as exc:
            request_id = (arguments or {}).get("request_id")
            snapshot_identifier = (arguments or {}).get("snapshot_identifier")
            return self._failure(
                tool_name=tool_name,
                request_id=request_id,
                snapshot_identifier=snapshot_identifier,
                error=MCPError(
                    code=MCPErrorCode.VALIDATION_ERROR,
                    message="Invalid Network MCP tool input.",
                    details={"errors": exc.errors(include_url=False)},
                ),
            )
        try:
            payload = self.client.request_json(
                definition.method,
                definition.path_builder(model),
                request_id=model.request_id,
                params=definition.params_builder(model),
            )
        except InternalAPIClientError as exc:
            return self._failure(
                tool_name=tool_name,
                request_id=model.request_id,
                snapshot_identifier=model.snapshot_identifier,
                error=exc.mcp_error,
                evaluation_time=getattr(model, "evaluation_time", None),
            )
        return self._success(
            tool_name=tool_name,
            model=model,
            payload=payload,
        )

    def _success(
        self,
        *,
        tool_name: str,
        model: BaseModel,
        payload: dict[str, Any],
    ) -> MCPToolResponse[dict[str, Any]]:
        backend_metadata = payload.get("metadata", {})
        snapshot_details = backend_metadata.get("snapshot", {})
        if not isinstance(snapshot_details, dict):
            snapshot_details = {"snapshot_key": snapshot_details}
        metadata = MCPMetadata(
            tool_name=f"network.{tool_name}",
            tool_version=NETWORK_MCP_VERSION,
            request_id=backend_metadata.get("correlation_id") or model.request_id or str(uuid4()),
            deterministic=True,
            snapshot_identifier=model.snapshot_identifier,
            reference_datetime=snapshot_details.get("reference_datetime"),
            evaluation_time=getattr(model, "evaluation_time", None),
            snapshot_details=snapshot_details,
        )
        data = payload.get("data", {})
        if tool_name in {"correlate_alarms", "rank_root_cause_candidates"} and getattr(
            model, "causal_event_code", None
        ):
            causal = data.get("causal_event", {})
            correlation = data.get("correlation", {})
            data = {
                "causal_event_code": causal.get("code"),
                "root_resource_type": causal.get("root_resource", {}).get("resource_type"),
                "root_resource_reference": causal.get("root_resource", {}).get("reference"),
                "root_cause_score": correlation.get("score"),
                "root_cause_confidence": correlation.get("confidence"),
                "reason_codes": correlation.get("reason_codes", []),
                "role_counts": correlation.get("role_counts", {}),
                "propagation_summary": correlation.get("propagation_summary"),
            }
        elif tool_name == "rank_root_cause_candidates" and getattr(model, "outage_code", None):
            candidates = data.get("candidates", [])
            candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
            data = {
                "outage_code": data.get("outage_code"),
                "root_resource_type": candidate.get("candidate_resource_kind")
                or candidate.get("candidate_device_type"),
                "root_resource_reference": candidate.get("candidate_resource_code")
                or candidate.get("candidate_device_code"),
                "reason_codes": candidate.get("reason_codes", []),
                "role_counts": {},
                "propagation_summary": candidate.get("description"),
            }
        return MCPToolResponse[dict[str, Any]](
            success=True,
            data=data,
            metadata=metadata,
            warnings=[
                MCPWarning.model_validate(warning) for warning in payload.get("warnings", [])
            ],
            evidence=[
                MCPEvidence.model_validate(evidence) for evidence in payload.get("evidence", [])
            ],
        )

    def _failure(
        self,
        *,
        tool_name: str,
        request_id: str | None,
        snapshot_identifier: str | None,
        error: MCPError,
        evaluation_time=None,
    ) -> MCPToolResponse[dict[str, Any]]:
        return MCPToolResponse[dict[str, Any]](
            success=False,
            error=error,
            metadata=MCPMetadata(
                tool_name=f"network.{tool_name}",
                tool_version=NETWORK_MCP_VERSION,
                request_id=request_id,
                deterministic=True,
                snapshot_identifier=snapshot_identifier,
                evaluation_time=evaluation_time,
            ),
        )
