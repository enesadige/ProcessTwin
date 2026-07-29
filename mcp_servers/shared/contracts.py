from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MCPErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    INTERNAL_ERROR = "internal_error"


class MCPError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: MCPErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class MCPWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class MCPEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: str
    reference: str
    description: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class MCPMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "mcp.tool_response.v1"
    tool_name: str
    tool_version: str
    request_id: str | None = None
    deterministic: bool
    snapshot_identifier: str | None = None
    reference_datetime: datetime | None = None
    evaluation_time: datetime | None = None

    @field_validator("reference_datetime", "evaluation_time")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        return value


class MCPToolResponse[DataT](BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    data: DataT | None = None
    error: MCPError | None = None
    metadata: MCPMetadata
    warnings: list[MCPWarning] = Field(default_factory=list)
    evidence: list[MCPEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def success_and_error_contract_is_consistent(self):
        if self.success:
            if self.data is None:
                raise ValueError("successful MCP responses must include data")
            if self.error is not None:
                raise ValueError("successful MCP responses cannot include error")
        else:
            if self.data is not None:
                raise ValueError("failed MCP responses cannot include data")
            if self.error is None:
                raise ValueError("failed MCP responses must include error")
        return self


class BaseMCPInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    snapshot_identifier: str | None = None


class TemporalMCPInput(BaseMCPInput):
    evaluation_time: datetime | None = None

    @field_validator("evaluation_time")
    @classmethod
    def evaluation_time_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluation_time must be timezone-aware")
        return value
