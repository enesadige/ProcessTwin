from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

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
    anchor_alarm_id: str | None = Field(default=None, min_length=1)
    causal_event_code: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)

    @model_validator(mode="after")
    def exactly_one_correlation_anchor_is_required(self):
        if bool(self.anchor_alarm_id) == bool(self.causal_event_code):
            raise ValueError("Exactly one of anchor_alarm_id or causal_event_code is required")
        return self


class CorrelateCausalEventsInput(SnapshotRequiredInput):
    """Bounded deterministic comparison/discovery for separate causal events."""

    causal_event_code: str = Field(min_length=1)
    candidate_causal_event_code: str | None = Field(default=None, min_length=1)
    window_minutes: int = Field(default=60, ge=1, le=24 * 60)
    direction: str = Field(default="both", pattern="^(before|after|both)$")
    other_region_only: bool = False


class RankRootCauseCandidatesInput(TemporalSnapshotInput):
    outage_code: str | None = Field(default=None, min_length=1)
    causal_event_code: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)

    @model_validator(mode="after")
    def exactly_one_root_cause_scope_is_required(self):
        if bool(self.outage_code) == bool(self.causal_event_code):
            raise ValueError("Exactly one of outage_code or causal_event_code is required")
        return self


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


class AggregateLocationImpactInput(TemporalSnapshotInput):
    from_time: datetime
    to_time: datetime
    city: str | None = None
    district: str | None = None

    @model_validator(mode="after")
    def require_location(self):
        if not self.city and not self.district:
            raise ValueError("city or district is required")
        return self


class AnalyzeOperationalAnalyticsInput(SnapshotRequiredInput):
    """Closed-world aggregation specification for deterministic operational analytics."""

    metric: str = Field(
        pattern="^(affected_customers|affected_subscriptions|potential_subscriptions|outage_count|event_count|alarm_count|compensation_amount|failed_failover_count|full_outage_count)$"
    )
    aggregation: str = Field(pattern="^(count|sum|average|min|max)$")
    group_by: str | None = Field(
        default=None,
        pattern="^(event|alarm_type|root_alarm_type|city|district|device_type|event_type|full_outage_status|failover_status|time_bucket)$",
    )
    direction: str = Field(default="desc", pattern="^(asc|desc)$")
    limit: int | None = Field(default=None, ge=1, le=100)
    time_grain: str | None = Field(default=None, pattern="^(day|week|month)$")
    comparison: bool | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None
    city: str | None = None
    district: str | None = None
    root_alarm_type: str | None = None
    event_type: str | None = None
    device_type: str | None = None
    full_outage: bool | None = None
    failed_failover: bool | None = None

    @model_validator(mode="after")
    def validate_time_bucket(self):
        if self.group_by == "time_bucket" and not self.time_grain:
            raise ValueError("time_bucket requires time_grain")
        return self
