"""Privacy-safe, deterministic structured-query contract for future orchestration."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_PUBLIC_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}(?:-[A-Z0-9][A-Z0-9_-]{0,63})+$")
_SNAPSHOT_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,159}$")


class StructuredQueryIntent(StrEnum):
    OPERATIONAL_ANALYTICS = "operational_analytics"
    ALARM_CORRELATION = "alarm_correlation"
    NETWORK_INVESTIGATION = "network_investigation"
    OUTAGE_IMPACT = "outage_impact"
    CUSTOMER_HISTORY = "customer_history"
    RULE_RETRIEVAL = "rule_retrieval"
    RULE_EVIDENCE = "rule_evidence"
    COMPENSATION_EVALUATION = "compensation_evaluation"
    RULE_DOCUMENT_RETRIEVAL = "rule_document_retrieval"


class RequestedOutput(StrEnum):
    ANALYTICS = "analytics"
    CORRELATION = "correlation"
    SUMMARY = "summary"
    DETAILS = "details"
    ROOT_CAUSE = "root_cause"
    IMPACT = "impact"
    ELIGIBILITY = "eligibility"
    COMPENSATION_AMOUNT = "compensation_amount"
    EVIDENCE = "evidence"


class SemanticDimension(StrEnum):
    """Allowlisted concepts the LLM may add to a deterministic query scope."""

    OUTAGE_CLASSIFICATION = "outage_classification"
    VERIFIED_CUSTOMER_IMPACT = "verified_customer_impact"
    VERIFIED_SUBSCRIPTION_IMPACT = "verified_subscription_impact"
    POTENTIAL_SCOPE = "potential_scope"
    FAILOVER_STATUS = "failover_status"
    FAILOVER_PROTECTION = "failover_protection"
    ROOT_RESOURCE = "root_resource"
    PHYSICAL_ROOT_CAUSE = "physical_root_cause"
    EVIDENCE_GAP = "evidence_gap"
    COMPENSATION_RESULT = "compensation_result"
    COMPENSATION_REASON = "compensation_reason"
    RULE_VERSION = "rule_version"
    DECISION_EVIDENCE = "decision_evidence"
    RAG_EVIDENCE = "rag_evidence"
    SOURCE_VERSION_SECTION = "source_version_section"
    MANUAL_REVIEW_REASON = "manual_review_reason"
    ALARM_CORRELATION = "alarm_correlation"
    SUMMARY = "summary"


_DOCUMENTARY_EVIDENCE_DIMENSIONS = frozenset(
    {
        SemanticDimension.RULE_VERSION,
        SemanticDimension.DECISION_EVIDENCE,
        SemanticDimension.RAG_EVIDENCE,
        SemanticDimension.SOURCE_VERSION_SECTION,
    }
)

_CUSTOMER_IMPACT_DIMENSIONS = frozenset(
    {
        SemanticDimension.VERIFIED_CUSTOMER_IMPACT,
        SemanticDimension.VERIFIED_SUBSCRIPTION_IMPACT,
        SemanticDimension.POTENTIAL_SCOPE,
    }
)


def requires_customer_impact_evidence(query: StructuredQuery) -> bool:
    """Return whether the query explicitly needs customer-impact evidence."""
    if query.intent == StructuredQueryIntent.OPERATIONAL_ANALYTICS:
        # The analytics tool owns its scoped, event-grain evidence policy.
        return False
    if query.customer_impact_requested:
        return True
    if _CUSTOMER_IMPACT_DIMENSIONS.intersection(query.semantic_dimensions):
        return True
    # A deterministic outage-impact query with no semantic decomposition is
    # already an explicit impact request. Other dimensions such as failover,
    # root cause, or evidence gap must not be widened into customer impact.
    return query.intent == StructuredQueryIntent.OUTAGE_IMPACT and not query.semantic_dimensions


def requires_documentary_evidence(query: StructuredQuery) -> bool:
    """Return whether the query explicitly needs a rule/evidence document lookup."""
    if query.intent == StructuredQueryIntent.ALARM_CORRELATION:
        return False
    if query.intent in {
        StructuredQueryIntent.RULE_EVIDENCE,
        StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL,
        StructuredQueryIntent.COMPENSATION_EVALUATION,
    }:
        return True
    if query.intent == StructuredQueryIntent.NETWORK_INVESTIGATION and query.causal_event_code:
        return bool(_DOCUMENTARY_EVIDENCE_DIMENSIONS.intersection(query.semantic_dimensions))
    if query.decision_type != "compensation":
        return RequestedOutput.EVIDENCE in query.requested_outputs
    if not query.semantic_dimensions:
        return RequestedOutput.EVIDENCE in query.requested_outputs
    return bool(_DOCUMENTARY_EVIDENCE_DIMENSIONS.intersection(query.semantic_dimensions))


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


class AnalyticsSpecification(BaseModel):
    """Validated, provider-independent analytical operation."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    metric: Literal[
        "affected_customers",
        "affected_subscriptions",
        "potential_subscriptions",
        "outage_count",
        "event_count",
        "alarm_count",
        "compensation_amount",
        "failed_failover_count",
        "full_outage_count",
    ]
    aggregation: Literal["count", "sum", "average", "min", "max"]
    group_by: (
        Literal[
            "event",
            "root_alarm_type",
            "city",
            "district",
            "device_type",
            "event_type",
            "full_outage_status",
            "failover_status",
            "time_bucket",
        ]
        | None
    ) = None
    direction: Literal["asc", "desc"] = "desc"
    limit: int | None = Field(default=None, ge=1, le=100)
    time_grain: Literal["day", "week", "month"] | None = None
    comparison: bool = False
    root_alarm_type: str | None = Field(default=None, max_length=100)
    event_type: str | None = Field(default=None, max_length=80)
    device_type: str | None = Field(default=None, max_length=80)
    full_outage: bool | None = None
    failed_failover: bool | None = None

    @model_validator(mode="after")
    def validate_semantics(self):
        count_only = {
            "outage_count",
            "event_count",
            "alarm_count",
            "failed_failover_count",
            "full_outage_count",
        }
        if self.metric in count_only and self.aggregation != "count":
            raise ValueError("count metric requires count aggregation")
        if self.group_by == "time_bucket" and self.time_grain is None:
            raise ValueError("time_bucket requires time_grain")
        return self


class StructuredQuery(BaseModel):
    """Validated query intent and filters; no tool plan or raw user data."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    schema_version: str = "structured-query.v1"
    intent: StructuredQueryIntent
    requested_outputs: list[RequestedOutput] = Field(default_factory=list)
    analytics: AnalyticsSpecification | None = None
    semantic_dimensions: list[SemanticDimension] = Field(default_factory=list)
    customer_impact_requested: bool = False
    semantic_decomposition_status: Literal["not_attempted", "accepted", "fallback"] = (
        "not_attempted"
    )
    semantic_decomposition_failure: str | None = Field(default=None, max_length=80)
    snapshot_identifier: str = Field(min_length=3, max_length=160)
    causal_event_code: str | None = Field(default=None, max_length=80)
    comparison_causal_event_code: str | None = Field(default=None, max_length=80)
    correlation_window_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    correlation_direction: Literal["before", "after", "both"] = "both"
    correlation_other_region_only: bool = False
    incident_code: str | None = Field(default=None, max_length=80)
    outage_code: str | None = Field(default=None, max_length=80)
    device_code: str | None = Field(default=None, max_length=80)
    subscription_reference: str | None = Field(default=None, max_length=80)
    decision_type: str | None = Field(default=None, max_length=40)
    embedding_provider: Literal["ollama", "gemini"] | None = None
    retrieval_query: str | None = Field(default=None, max_length=500)
    location: StructuredQueryLocation | None = None
    technology: Technology | None = None
    time_window: StructuredQueryTimeWindow | None = None
    clarification_required: bool = False
    clarification_reasons: list[ClarificationReason] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_analytics_intent(self):
        if self.intent == StructuredQueryIntent.OPERATIONAL_ANALYTICS and self.analytics is None:
            raise ValueError("analytics intent requires analytics specification")
        if (
            self.intent != StructuredQueryIntent.OPERATIONAL_ANALYTICS
            and self.analytics is not None
        ):
            raise ValueError("analytics specification requires analytics intent")
        return self

    @field_validator("snapshot_identifier")
    @classmethod
    def validate_snapshot_identifier(cls, value: str) -> str:
        normalized = _normalized_text(value, field_name="snapshot_identifier", max_length=160)
        if not _SNAPSHOT_IDENTIFIER_RE.fullmatch(normalized):
            raise ValueError("snapshot_identifier is invalid")
        return normalized

    @field_validator(
        "causal_event_code",
        "comparison_causal_event_code",
        "incident_code",
        "outage_code",
        "subscription_reference",
    )
    @classmethod
    def validate_public_code(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        normalized = _normalized_text(value, field_name=info.field_name, max_length=80).upper()
        if not _PUBLIC_CODE_RE.fullmatch(normalized):
            raise ValueError(f"{info.field_name} is invalid")
        return normalized

    @field_validator("device_code")
    @classmethod
    def validate_device_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalized_text(value, field_name="device_code", max_length=80)
        if (
            not normalized[0].isalnum()
            or any(not (character.isalnum() or character in "-_") for character in normalized)
            or "-" not in normalized
        ):
            raise ValueError("device_code is invalid")
        return normalized

    @field_validator("decision_type")
    @classmethod
    def validate_decision_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalized_text(value, field_name="decision_type", max_length=40)
        if normalized not in {"eligibility", "compensation"}:
            raise ValueError("decision_type is invalid")
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
        self.semantic_dimensions = sorted(
            set(self.semantic_dimensions), key=lambda value: value.value
        )
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
        if self.comparison_causal_event_code:
            if self.intent != StructuredQueryIntent.ALARM_CORRELATION:
                raise ValueError("comparison event requires alarm correlation intent")
            if self.comparison_causal_event_code == self.causal_event_code:
                raise ValueError("correlation events must be different")
        if self.intent == StructuredQueryIntent.ALARM_CORRELATION and not self.causal_event_code:
            raise ValueError("alarm correlation requires a causal event anchor")
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
        if (
            self.intent
            in {
                StructuredQueryIntent.ALARM_CORRELATION,
                StructuredQueryIntent.NETWORK_INVESTIGATION,
                StructuredQueryIntent.OUTAGE_IMPACT,
                StructuredQueryIntent.CUSTOMER_HISTORY,
                StructuredQueryIntent.RULE_EVIDENCE,
            }
            and not anchors
            and not any((self.device_code, self.location, self.technology, self.time_window))
        ):
            raise ValueError("The query requires an operational reference or scope filter")
        return self

    def to_audit_dict(self) -> dict[str, object]:
        """Stable JSON-ready representation suitable for QueryRun audit storage."""
        return self.model_dump(mode="json", exclude_none=True)
