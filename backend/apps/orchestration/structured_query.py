"""Privacy-safe, deterministic structured-query contract for future orchestration."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_PUBLIC_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}(?:-[A-Z0-9][A-Z0-9_-]{0,63})+$")
_SNAPSHOT_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,159}$")


class StructuredQueryIntent(StrEnum):
    NETWORK_INVESTIGATION = "network_investigation"
    OUTAGE_IMPACT = "outage_impact"
    CUSTOMER_HISTORY = "customer_history"
    RULE_RETRIEVAL = "rule_retrieval"
    RULE_EVIDENCE = "rule_evidence"
    COMPENSATION_EVALUATION = "compensation_evaluation"
    RULE_DOCUMENT_RETRIEVAL = "rule_document_retrieval"


class RequestedOutput(StrEnum):
    SUMMARY = "summary"
    DETAILS = "details"
    ROOT_CAUSE = "root_cause"
    IMPACT = "impact"
    ELIGIBILITY = "eligibility"
    COMPENSATION_AMOUNT = "compensation_amount"
    EVIDENCE = "evidence"


class Technology(StrEnum):
    GPON = "GPON"
    XDSL = "xDSL"
    METRO_ETHERNET = "Metro Ethernet"
    BNG = "BNG"
    AGGREGATION = "aggregation"


class ClarificationReason(StrEnum):
    MISSING_OPERATIONAL_ANCHOR = "missing_operational_anchor"
    MISSING_SCOPE_FILTER = "missing_scope_filter"
    MISSING_REQUESTED_OUTPUT = "missing_requested_output"
    COMPENSATION_ANCHOR_REQUIRED = "compensation_anchor_required"
    QUERY_SCOPE_TOO_BROAD = "query_scope_too_broad"


def _normalized_text(value: str, *, field_name: str, max_length: int = 100) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > max_length or _CONTROL_CHARACTER_RE.search(normalized):
        raise ValueError(f"{field_name} is invalid")
    return normalized


class StructuredQueryLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    city: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    neighborhood: str | None = Field(default=None, max_length=100)

    @field_validator("city", "district", "neighborhood")
    @classmethod
    def normalize_location_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        max_lengths = {"city": 80, "district": 80, "neighborhood": 100}
        return _normalized_text(
            value,
            field_name=info.field_name,
            max_length=max_lengths[info.field_name],
        )

    @model_validator(mode="after")
    def require_a_location_value(self):
        if not any((self.city, self.district, self.neighborhood)):
            raise ValueError("location must contain at least one value")
        return self


class StructuredQueryTimeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    from_time: datetime | None = None
    to_time: datetime | None = None

    @field_validator("from_time", "to_time")
    @classmethod
    def require_timezone_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("time window values must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_time_order(self):
        if self.from_time and self.to_time and self.from_time > self.to_time:
            raise ValueError("time window start must not be after its end")
        return self


class StructuredQuery(BaseModel):
    """Validated query intent and filters; no tool plan or raw user data."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    schema_version: str = "structured-query.v1"
    intent: StructuredQueryIntent
    requested_outputs: list[RequestedOutput] = Field(default_factory=list)
    snapshot_identifier: str = Field(min_length=3, max_length=160)
    causal_event_code: str | None = Field(default=None, max_length=80)
    incident_code: str | None = Field(default=None, max_length=80)
    outage_code: str | None = Field(default=None, max_length=80)
    retrieval_query: str | None = Field(default=None, max_length=500)
    location: StructuredQueryLocation | None = None
    technology: Technology | None = None
    time_window: StructuredQueryTimeWindow | None = None
    clarification_required: bool = False
    clarification_reasons: list[ClarificationReason] = Field(default_factory=list)

    @field_validator("snapshot_identifier")
    @classmethod
    def validate_snapshot_identifier(cls, value: str) -> str:
        normalized = _normalized_text(value, field_name="snapshot_identifier", max_length=160)
        if not _SNAPSHOT_IDENTIFIER_RE.fullmatch(normalized):
            raise ValueError("snapshot_identifier is invalid")
        return normalized

    @field_validator("causal_event_code", "incident_code", "outage_code")
    @classmethod
    def validate_public_code(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        normalized = _normalized_text(value, field_name=info.field_name, max_length=80).upper()
        if not _PUBLIC_CODE_RE.fullmatch(normalized):
            raise ValueError(f"{info.field_name} is invalid")
        return normalized

    @field_validator("retrieval_query")
    @classmethod
    def validate_retrieval_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_text(value, field_name="retrieval_query", max_length=500)

    @model_validator(mode="after")
    def normalize_and_validate_scope(self):
        self.requested_outputs = sorted(set(self.requested_outputs), key=lambda value: value.value)
        self.clarification_reasons = sorted(
            set(self.clarification_reasons), key=lambda value: value.value
        )
        anchors = [
            code
            for code in (self.causal_event_code, self.incident_code, self.outage_code)
            if code is not None
        ]
        if len(anchors) > 1:
            raise ValueError("Only one operational reference may be supplied")
        if self.clarification_required:
            if not self.clarification_reasons:
                raise ValueError("clarification_required needs at least one reason")
            return self
        if self.clarification_reasons:
            raise ValueError("clarification reasons require clarification_required")
        if not self.requested_outputs:
            raise ValueError("requested_outputs cannot be empty without clarification")
        if self.intent == StructuredQueryIntent.COMPENSATION_EVALUATION and not anchors:
            raise ValueError("compensation evaluation requires an operational reference")
        if self.intent in {
            StructuredQueryIntent.NETWORK_INVESTIGATION,
            StructuredQueryIntent.OUTAGE_IMPACT,
            StructuredQueryIntent.CUSTOMER_HISTORY,
            StructuredQueryIntent.RULE_EVIDENCE,
        } and not anchors and not any((self.location, self.technology, self.time_window)):
            raise ValueError("The query requires an operational reference or scope filter")
        return self

    def to_audit_dict(self) -> dict[str, object]:
        """Stable JSON-ready representation suitable for QueryRun audit storage."""
        return self.model_dump(mode="json", exclude_none=True)
