from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from mcp_servers.shared.contracts import BaseMCPInput, TemporalMCPInput

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_TOPOLOGY_DEPTH = 8
MAX_TOPOLOGY_RESULT_LIMIT = 500
MAX_LONGEST_OUTAGE_LIMIT = 10


class TopologyMode(StrEnum):
    ANCESTORS = "ancestors"
    DESCENDANTS = "descendants"
    SUBGRAPH = "subgraph"


class SnapshotRequiredInput(BaseMCPInput):
    snapshot_identifier: str = Field(min_length=1)


class TemporalSnapshotInput(TemporalMCPInput):
    snapshot_identifier: str = Field(min_length=1)


class GetDeviceDetailsInput(SnapshotRequiredInput):
    device_code: str = Field(min_length=1)


class GetDeviceTopologyInput(TemporalSnapshotInput):
    device_code: str = Field(min_length=1)
    mode: TopologyMode = TopologyMode.DESCENDANTS
    max_depth: int = Field(default=4, ge=1, le=MAX_TOPOLOGY_DEPTH)
    include_links: bool = True
    result_limit: int = Field(default=100, ge=1, le=MAX_TOPOLOGY_RESULT_LIMIT)


class SearchAlarmsInput(SnapshotRequiredInput):
    alarm_id: str | None = None
    alarm_type_code: str | None = None
    severity: str | None = None
    status: str | None = None
    source_kind: str | None = None
    device_code: str | None = None
    network_link_code: str | None = None
    incident_code: str | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @field_validator("from_time", "to_time")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime filters must be timezone-aware")
        return value


class SearchOutagesInput(TemporalSnapshotInput):
    outage_type: str | None = None
    status: str | None = None
    source_device_code: str | None = None
    incident_code: str | None = None
    city: str | None = None
    district: str | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @field_validator("from_time", "to_time")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime filters must be timezone-aware")
        return value


class GetOutageDetailsInput(TemporalSnapshotInput):
    outage_code: str = Field(min_length=1)


class CalculateCustomerImpactInput(TemporalSnapshotInput):
    outage_code: str = Field(min_length=1)


class CorrelateAlarmsInput(SnapshotRequiredInput):
    anchor_alarm_id: str = Field(min_length=1)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)


class RankRootCauseCandidatesInput(TemporalSnapshotInput):
    outage_code: str = Field(min_length=1)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)


class GetLongestOutageInput(TemporalSnapshotInput):
    from_time: datetime | None = None
    to_time: datetime | None = None
    city: str | None = None
    district: str | None = None
    device_type: str | None = None
    technology: str | None = None
    status: str | None = None
    limit: int = Field(default=1, ge=1, le=MAX_LONGEST_OUTAGE_LIMIT)

    @field_validator("from_time", "to_time")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime filters must be timezone-aware")
        return value

