"""Validated ToolPlan contract backed by the existing MCP tool registries."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from mcp_servers.compensation.tools import COMPENSATION_TOOL_DEFINITIONS
from mcp_servers.customer.tools import CUSTOMER_TOOL_DEFINITIONS
from mcp_servers.network.tools import NETWORK_TOOL_DEFINITIONS
from mcp_servers.rules.tools import RULE_TOOL_DEFINITIONS
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from apps.orchestration.structured_query import StructuredQuery

_CALL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PARALLEL_GROUP_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FORBIDDEN_ARGUMENT_PARTS = frozenset(
    {
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "header",
        "url",
        "endpoint",
        "ip",
        "mac",
        "customer",
        "subscriber",
        "raw_",
        "payload",
        "metadata",
    }
)


class MCPServer(StrEnum):
    NETWORK = "network"
    CUSTOMER = "customer"
    RULE = "rule"
    COMPENSATION = "compensation"


class ToolCallKind(StrEnum):
    DETERMINISTIC = "deterministic"
    DOCUMENT_RETRIEVAL = "document_retrieval"


MCP_TOOL_REGISTRIES = MappingProxyType(
    {
        MCPServer.NETWORK: NETWORK_TOOL_DEFINITIONS,
        MCPServer.CUSTOMER: CUSTOMER_TOOL_DEFINITIONS,
        MCPServer.RULE: RULE_TOOL_DEFINITIONS,
        MCPServer.COMPENSATION: COMPENSATION_TOOL_DEFINITIONS,
    }
)


def get_tool_definition(server: MCPServer, tool_name: str):
    """Resolve a tool from its owning MCP registry without transport details."""
    definition = MCP_TOOL_REGISTRIES[server].get(tool_name)
    if definition is None:
        raise ValueError("tool_name is not allowed for the selected server")
    return definition


def _reject_forbidden_argument_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key != "subscription_number" and any(
                part in normalized_key for part in _FORBIDDEN_ARGUMENT_PARTS
            ):
                raise ValueError("tool arguments contain a forbidden field")
            _reject_forbidden_argument_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden_argument_keys(item)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    call_id: str = Field(min_length=1, max_length=64)
    server: MCPServer
    tool_name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list)
    execution_order: int = Field(ge=1)
    parallel_group: str | None = Field(default=None, max_length=64)
    call_kind: ToolCallKind = ToolCallKind.DETERMINISTIC

    @field_validator("call_id", "parallel_group")
    @classmethod
    def validate_stable_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not _CALL_ID_RE.fullmatch(normalized):
            raise ValueError("call identifier is invalid")
        return normalized

    @field_validator("depends_on")
    @classmethod
    def normalize_dependencies(cls, value: list[str]) -> list[str]:
        normalized = []
        for dependency in value:
            if not isinstance(dependency, str) or not _CALL_ID_RE.fullmatch(dependency.strip()):
                raise ValueError("tool dependency is invalid")
            normalized.append(dependency.strip())
        if len(normalized) != len(set(normalized)):
            raise ValueError("tool dependencies must be unique")
        return sorted(normalized)

    @model_validator(mode="after")
    def normalize_arguments_and_kind(self):
        _reject_forbidden_argument_keys(self.arguments)
        definition = get_tool_definition(self.server, self.tool_name)
        try:
            input_model = definition.input_model.model_validate(self.arguments)
        except ValidationError as exc:
            raise ValueError("tool arguments are invalid") from exc
        self.arguments = input_model.model_dump(mode="json", exclude_none=True)
        self.call_kind = (
            ToolCallKind.DOCUMENT_RETRIEVAL
            if self.server == MCPServer.RULE and self.tool_name == "search_rule_documents"
            else ToolCallKind.DETERMINISTIC
        )
        return self

    def duplicate_key(self) -> str:
        return json.dumps(
            {
                "server": self.server.value,
                "tool_name": self.tool_name,
                "arguments": self.arguments,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_audit_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)


class ToolPlan(BaseModel):
    """A graph-validated, non-executing plan for already structured input."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    schema_version: str = "tool-plan.v1"
    snapshot_identifier: str = Field(min_length=3, max_length=160)
    structured_query_context: StructuredQuery
    calls: list[ToolCall] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan_graph_and_context(self):
        if self.snapshot_identifier != self.structured_query_context.snapshot_identifier:
            raise ValueError("tool plan snapshot does not match structured query context")
        self.calls = sorted(self.calls, key=lambda call: (call.execution_order, call.call_id))
        call_ids = [call.call_id for call in self.calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tool plan call_id values must be unique")
        duplicate_keys = [call.duplicate_key() for call in self.calls]
        if len(duplicate_keys) != len(set(duplicate_keys)):
            raise ValueError("tool plan contains duplicate calls")

        calls_by_id = {call.call_id: call for call in self.calls}
        calls_by_order: dict[int, list[ToolCall]] = {}
        for call in self.calls:
            calls_by_order.setdefault(call.execution_order, []).append(call)
            for dependency_id in call.depends_on:
                if dependency_id == call.call_id:
                    raise ValueError("tool call cannot depend on itself")
                dependency = calls_by_id.get(dependency_id)
                if dependency is None:
                    raise ValueError("tool call dependency is unknown")
                if dependency.execution_order >= call.execution_order:
                    raise ValueError("tool call dependencies must have an earlier execution order")
                if dependency.parallel_group and dependency.parallel_group == call.parallel_group:
                    raise ValueError("dependent tool calls cannot share a parallel group")
            input_fields = get_tool_definition(call.server, call.tool_name).input_model.model_fields
            if "snapshot_identifier" in input_fields:
                if call.arguments.get("snapshot_identifier") != self.snapshot_identifier:
                    raise ValueError("tool call snapshot does not match tool plan")
            causal_event_code = self.structured_query_context.causal_event_code
            if causal_event_code and "causal_event_code" in call.arguments:
                if call.arguments["causal_event_code"] != causal_event_code:
                    raise ValueError(
                        "tool call causal event does not match structured query context"
                    )

        for calls_at_order in calls_by_order.values():
            parallel_groups = {call.parallel_group for call in calls_at_order}
            if len(calls_at_order) > 1 and (None in parallel_groups or len(parallel_groups) != 1):
                raise ValueError("parallel calls need one shared parallel group")
        return self

    def to_planned_tools(self) -> list[dict[str, object]]:
        return [call.to_audit_dict() for call in self.calls]
