"""Stable, model-independent contracts for the causal operations revision."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from django.utils import timezone

from apps.core.exceptions import DomainValidationError


class CausalEventType(StrEnum):
    DEVICE_FAILURE = "device_failure"
    LINK_FAILURE = "link_failure"
    PORT_FAILURE = "port_failure"
    ACCESS_SEGMENT_FAILURE = "access_segment_failure"
    ENVIRONMENTAL_ANOMALY = "environmental_anomaly"
    POWER_EVENT = "power_event"
    DEGRADATION = "degradation"
    MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"


class CausalEventStatus(StrEnum):
    DETECTED = "detected"
    CORRELATING = "correlating"
    ACTIVE = "active"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class EventOrigin(StrEnum):
    SYNTHETIC = "synthetic"
    IMPORTED = "imported"


class SessionEventType(StrEnum):
    START = "start"
    CONTINUE = "continue"
    STOP = "stop"


class CustomerImpactStatus(StrEnum):
    POTENTIAL_IMPACT = "potential_impact"
    VERIFIED_IMPACT = "verified_impact"
    VERIFIED_NO_IMPACT = "verified_no_impact"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ImpactReason(StrEnum):
    TOPOLOGY_MATCH = "topology_match"
    SESSION_STOP_AND_RECOVERY_MATCH = "session_stop_and_recovery_match"
    SESSION_REMAINED_ACTIVE = "session_remained_active"
    FAILOVER_PROTECTED = "failover_protected"
    SHARED_UPSTREAM = "shared_upstream"
    SHARED_FAILURE_DOMAIN = "shared_failure_domain"
    MISSING_SESSION_EVIDENCE = "missing_session_evidence"
    EVENT_OUTSIDE_ASSESSMENT_WINDOW = "event_outside_assessment_window"
    UNRELATED_SESSION_DROP = "unrelated_session_drop"
    PRE_EXISTING_OFFLINE = "pre_existing_offline"


class CorrelationRole(StrEnum):
    ROOT = "root"
    CHILD = "child"
    SYMPTOM = "symptom"
    SUPPORTING = "supporting"
    UNRELATED = "unrelated"
    NOISE = "noise"


class CorrelationReason(StrEnum):
    SAME_RESOURCE = "same_resource"
    TOPOLOGY_PARENT_CHILD = "topology_parent_child"
    SHARED_UPSTREAM = "shared_upstream"
    SHARED_FAILURE_DOMAIN = "shared_failure_domain"
    TEMPORAL_PROPAGATION = "temporal_propagation"
    MATCHING_CUSTOMER_SESSION_IMPACT = "matching_customer_session_impact"
    MATCHING_CLEAR_RECOVERY_SEQUENCE = "matching_clear_recovery_sequence"


class ResourceType(StrEnum):
    DEVICE = "device"
    NETWORK_LINK = "network_link"
    NETWORK_PORT = "network_port"
    LINE_CONNECTION = "line_connection"
    ACCESS_SEGMENT = "access_segment"
    FAILURE_DOMAIN = "failure_domain"
    SUBSCRIPTION_CONNECTION = "subscription_connection"


RESOLVED_EVENT_STATUSES = frozenset(
    {CausalEventStatus.RESOLVED, CausalEventStatus.CLOSED, CausalEventStatus.CANCELLED}
)


def _require_aware(value: datetime, *, field_name: str) -> None:
    if timezone.is_naive(value):
        raise DomainValidationError(
            f"{field_name} must be timezone-aware.", details={"field": field_name}
        )


def _require_code(value: str | None, *, field_name: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise DomainValidationError(f"{field_name} is required.", details={"field": field_name})
    return normalized


def _coerce_enum(value: Any, enum_type: type[StrEnum], *, field_name: str) -> StrEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            f"{field_name} is invalid.", details={"field": field_name, "value": value}
        ) from exc


@dataclass(frozen=True)
class ResourceReference:
    resource_type: ResourceType | str
    business_code: str
    parent_code: str | None = None
    resource_subtype: str | None = None
    technology: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resource_type",
            _coerce_enum(self.resource_type, ResourceType, field_name="resource_type"),
        )
        object.__setattr__(
            self, "business_code", _require_code(self.business_code, field_name="business_code")
        )
        object.__setattr__(self, "parent_code", _optional_code(self.parent_code))
        object.__setattr__(self, "resource_subtype", _optional_value(self.resource_subtype))
        object.__setattr__(self, "technology", _optional_value(self.technology))

    def to_public_dict(self) -> dict[str, str | None]:
        return {
            "resource_type": self.resource_type.value,
            "business_code": self.business_code,
            "parent_code": self.parent_code,
            "resource_subtype": self.resource_subtype,
            "technology": self.technology,
        }


@dataclass(frozen=True)
class CausalEventContract:
    event_code: str
    event_type: CausalEventType | str
    status: CausalEventStatus | str
    started_at: datetime
    source_system: str
    origin: EventOrigin | str
    root_resource: ResourceReference | None = None
    ended_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "event_code",
            _require_code(self.event_code, field_name="event_code"),
        )
        object.__setattr__(
            self,
            "event_type",
            _coerce_enum(self.event_type, CausalEventType, field_name="event_type"),
        )
        object.__setattr__(
            self, "status", _coerce_enum(self.status, CausalEventStatus, field_name="status")
        )
        object.__setattr__(
            self,
            "origin",
            _coerce_enum(self.origin, EventOrigin, field_name="origin"),
        )
        object.__setattr__(
            self, "source_system", _require_code(self.source_system, field_name="source_system")
        )
        _require_aware(self.started_at, field_name="started_at")
        if self.ended_at is not None:
            _require_aware(self.ended_at, field_name="ended_at")
            if self.ended_at < self.started_at:
                raise DomainValidationError(
                    "ended_at cannot be earlier than started_at.",
                    details={"field": "ended_at"},
                )
        if self.status in RESOLVED_EVENT_STATUSES and self.ended_at is None:
            raise DomainValidationError(
                "Resolved, closed, and cancelled events require ended_at.",
                details={"field": "ended_at", "status": self.status.value},
            )
        if not isinstance(self.metadata, Mapping):
            raise DomainValidationError(
                "metadata must be an object.", details={"field": "metadata"}
            )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_code": self.event_code,
            "event_type": self.event_type.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "source_system": self.source_system,
            "origin": self.origin.value,
            "root_resource": self.root_resource.to_public_dict() if self.root_resource else None,
        }


@dataclass(frozen=True)
class SessionEventContract:
    external_event_id: str
    event_type: SessionEventType | str
    occurred_at: datetime
    source_system: str
    subscription_code: str | None = None
    subscription_connection_code: str | None = None
    received_at: datetime | None = None
    nas_identifier: str | None = None
    service_identifier: str | None = None
    session_identifier: str | None = field(default=None, repr=False, compare=False)
    subscriber_reference: str | None = field(default=None, repr=False, compare=False)
    raw_payload: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "external_event_id",
            _require_code(self.external_event_id, field_name="external_event_id"),
        )
        object.__setattr__(
            self,
            "event_type",
            _coerce_enum(self.event_type, SessionEventType, field_name="event_type"),
        )
        object.__setattr__(
            self, "source_system", _require_code(self.source_system, field_name="source_system")
        )
        object.__setattr__(self, "subscription_code", _optional_code(self.subscription_code))
        object.__setattr__(
            self, "subscription_connection_code", _optional_code(self.subscription_connection_code)
        )
        if not self.subscription_code and not self.subscription_connection_code:
            raise DomainValidationError(
                "A subscription or subscription connection reference is required.",
                details={"fields": ["subscription_code", "subscription_connection_code"]},
            )
        _require_aware(self.occurred_at, field_name="occurred_at")
        if self.received_at is not None:
            _require_aware(self.received_at, field_name="received_at")
            if self.received_at < self.occurred_at:
                raise DomainValidationError(
                    "received_at cannot be earlier than occurred_at.",
                    details={"field": "received_at"},
                )
        for field_name in ("raw_payload", "metadata"):
            if not isinstance(getattr(self, field_name), Mapping):
                raise DomainValidationError(
                    f"{field_name} must be an object.", details={"field": field_name}
                )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "external_event_id": self.external_event_id,
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at.isoformat(),
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "source_system": self.source_system,
            "subscription_code": self.subscription_code,
            "subscription_connection_code": self.subscription_connection_code,
            "nas_identifier": self.nas_identifier,
            "service_identifier": self.service_identifier,
        }


@dataclass(frozen=True)
class CustomerImpactAssessmentContract:
    causal_event_code: str
    status: CustomerImpactStatus | str
    potential_impact: bool
    reasons: tuple[ImpactReason | str, ...]
    assessment_started_at: datetime
    subscription_code: str | None = None
    subscription_connection_code: str | None = None
    assessment_ended_at: datetime | None = None
    connection_role: str | None = None
    evidence_event_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "causal_event_code",
            _require_code(self.causal_event_code, field_name="causal_event_code"),
        )
        object.__setattr__(
            self, "status", _coerce_enum(self.status, CustomerImpactStatus, field_name="status")
        )
        object.__setattr__(self, "subscription_code", _optional_code(self.subscription_code))
        object.__setattr__(
            self, "subscription_connection_code", _optional_code(self.subscription_connection_code)
        )
        if not self.subscription_code and not self.subscription_connection_code:
            raise DomainValidationError(
                "An assessment requires a subscription or subscription connection reference.",
                details={"fields": ["subscription_code", "subscription_connection_code"]},
            )
        if not isinstance(self.potential_impact, bool):
            raise DomainValidationError(
                "potential_impact must be boolean.", details={"field": "potential_impact"}
            )
        reasons = tuple(
            _coerce_enum(reason, ImpactReason, field_name="reasons") for reason in self.reasons
        )
        object.__setattr__(self, "reasons", reasons)
        _require_aware(self.assessment_started_at, field_name="assessment_started_at")
        if self.assessment_ended_at is not None:
            _require_aware(self.assessment_ended_at, field_name="assessment_ended_at")
            if self.assessment_ended_at < self.assessment_started_at:
                raise DomainValidationError(
                    "assessment_ended_at cannot be earlier than assessment_started_at.",
                    details={"field": "assessment_ended_at"},
                )
        if (
            self.status
            in {
                CustomerImpactStatus.VERIFIED_IMPACT,
                CustomerImpactStatus.VERIFIED_NO_IMPACT,
                CustomerImpactStatus.INSUFFICIENT_EVIDENCE,
            }
            and not self.potential_impact
        ):
            raise DomainValidationError(
                "A verified or insufficient assessment must originate from potential impact.",
                details={"field": "potential_impact", "status": self.status.value},
            )
        if self.status == CustomerImpactStatus.POTENTIAL_IMPACT and not self.potential_impact:
            raise DomainValidationError(
                "potential_impact status requires potential_impact=true.",
                details={"field": "potential_impact"},
            )
        if self.status == CustomerImpactStatus.VERIFIED_NO_IMPACT and not reasons:
            raise DomainValidationError(
                "Verified no-impact requires at least one reason.", details={"field": "reasons"}
            )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "causal_event_code": self.causal_event_code,
            "status": self.status.value,
            "potential_impact": self.potential_impact,
            "subscription_code": self.subscription_code,
            "subscription_connection_code": self.subscription_connection_code,
            "connection_role": self.connection_role,
            "assessment_started_at": self.assessment_started_at.isoformat(),
            "assessment_ended_at": (
                self.assessment_ended_at.isoformat() if self.assessment_ended_at else None
            ),
            "reasons": [reason.value for reason in self.reasons],
            "evidence_event_codes": sorted(set(self.evidence_event_codes)),
        }


@dataclass(frozen=True)
class AlarmCorrelationContract:
    alarm_code: str
    role: CorrelationRole | str
    reasons: tuple[CorrelationReason | str, ...]
    resource: ResourceReference | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "alarm_code",
            _require_code(self.alarm_code, field_name="alarm_code"),
        )
        object.__setattr__(
            self, "role", _coerce_enum(self.role, CorrelationRole, field_name="role")
        )
        reasons = tuple(
            _coerce_enum(reason, CorrelationReason, field_name="reasons") for reason in self.reasons
        )
        if self.role not in {CorrelationRole.UNRELATED, CorrelationRole.NOISE} and not reasons:
            raise DomainValidationError(
                "Correlated alarm roles require at least one reason.", details={"field": "reasons"}
            )
        object.__setattr__(self, "reasons", reasons)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "alarm_code": self.alarm_code,
            "role": self.role.value,
            "reasons": [reason.value for reason in self.reasons],
            "resource": self.resource.to_public_dict() if self.resource else None,
        }


def legacy_incident_alarm_role_mapping() -> dict[str, str]:
    """Map current IncidentAlarm values to the additive causal role contract."""
    return {"primary": "root", "supporting": "supporting", "correlated": "child"}


def _optional_code(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _optional_value(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
