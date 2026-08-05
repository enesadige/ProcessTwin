"""Deterministic alarm-to-resource compatibility rules.

The persistent AlarmType relations remain the source of truth for allowed
source kinds and device types.  This module adds the technology and
resource-level semantics that the current schema cannot persist without a
migration, and is shared by generation and future ingestion paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.network.models import AccessTechnology, NetworkDeviceType

if TYPE_CHECKING:
    from apps.operations.models import Alarm


VALID = "valid"
MISSING_SOURCE = "missing_source"
UNSUPPORTED_SOURCE_KIND = "unsupported_source_kind"
UNSUPPORTED_DEVICE_TYPE = "unsupported_device_type"
UNSUPPORTED_TECHNOLOGY = "unsupported_technology"
INVALID_PON_PORT_SOURCE = "invalid_pon_port_source"
INVALID_DSL_PORT_SOURCE = "invalid_dsl_port_source"
INVALID_DSL_LINE_SOURCE = "invalid_dsl_line_source"
INVALID_DEDICATED_PORT_SOURCE = "invalid_dedicated_port_source"
INVALID_DEVICE_SOURCE = "invalid_device_source"
INVALID_LINK_SOURCE = "invalid_link_source"


@dataclass(frozen=True)
class AlarmTopologyPolicy:
    allowed_technologies: tuple[str, ...] = ()
    can_be_symptom: bool = True
    direct_outage: bool = False
    session_verification_required: bool = True

    def to_metadata(self) -> dict[str, object]:
        return {
            "allowed_technologies": list(self.allowed_technologies),
            "can_be_symptom": self.can_be_symptom,
            "direct_outage": self.direct_outage,
            "session_verification_required": self.session_verification_required,
        }


@dataclass(frozen=True)
class AlarmTopologyValidationResult:
    valid: bool
    reason_code: str
    description: str
    alarm_code: str
    source_kind: str | None
    source_technology: str | None
    expected_source_kinds: tuple[str, ...]
    expected_technologies: tuple[str, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "reason_code": self.reason_code,
            "description": self.description,
            "alarm_code": self.alarm_code,
            "source_kind": self.source_kind,
            "source_technology": self.source_technology,
            "expected_source_kinds": list(self.expected_source_kinds),
            "expected_technologies": list(self.expected_technologies),
        }


_FIBER = AccessTechnology.FIBER
_GPON = AccessTechnology.GPON
_XDSL = (AccessTechnology.VDSL, AccessTechnology.ADSL)

# These policies supplement AlarmType's persisted source-kind/device-type
# relations. They intentionally contain no case, customer, or snapshot data.
ALARM_TOPOLOGY_POLICIES: dict[str, AlarmTopologyPolicy] = {
    "BNG_UNREACHABLE": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "METRO_AGG_UNREACHABLE": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "OLT_UNREACHABLE": AlarmTopologyPolicy((_GPON,)),
    "DSLAM_UNREACHABLE": AlarmTopologyPolicy(_XDSL),
    "ACCESS_NODE_UNREACHABLE": AlarmTopologyPolicy((_FIBER,)),
    "UPLINK_DOWN": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "FIBER_CUT_SUSPECTED": AlarmTopologyPolicy((_FIBER, _GPON)),
    "LINK_PACKET_LOSS_HIGH": AlarmTopologyPolicy((_FIBER, _GPON)),
    "LINK_FLAPPING": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "BACKUP_LINK_UNAVAILABLE": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "PON_PORT_DOWN": AlarmTopologyPolicy((_GPON,)),
    "OPTICAL_SIGNAL_LOW": AlarmTopologyPolicy((_FIBER, _GPON)),
    "OPTICAL_SIGNAL_LOSS": AlarmTopologyPolicy((_FIBER, _GPON)),
    "ONT_DISCONNECT_SURGE": AlarmTopologyPolicy((_GPON,)),
    "PON_CAPACITY_THRESHOLD": AlarmTopologyPolicy((_GPON,)),
    "DSL_PORT_DOWN": AlarmTopologyPolicy(_XDSL),
    "DSL_LINE_QUALITY_DEGRADED": AlarmTopologyPolicy(_XDSL),
    "DSL_RETRAIN_FREQUENT": AlarmTopologyPolicy(_XDSL),
    "DSLAM_PORT_SATURATION": AlarmTopologyPolicy(_XDSL),
    "DEDICATED_PORT_DOWN": AlarmTopologyPolicy((_FIBER,)),
    "SLA_LATENCY_BREACH": AlarmTopologyPolicy((_FIBER,)),
    "SLA_PACKET_LOSS_BREACH": AlarmTopologyPolicy((_FIBER,)),
    "PRIMARY_PATH_DOWN": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "FAILOVER_UNSUCCESSFUL": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "COMMERCIAL_POWER_LOSS": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "BACKUP_POWER_DEGRADED": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "HIGH_TEMPERATURE": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "COOLING_FAILURE": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "DEVICE_RESOURCE_HIGH": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "BANDWIDTH_UTIL_HIGH": AlarmTopologyPolicy((_FIBER, _GPON, *_XDSL)),
    "DISTRIBUTION_CABLE_DOWN": AlarmTopologyPolicy((_FIBER, _GPON)),
}


def topology_policy_for(alarm_code: str) -> AlarmTopologyPolicy:
    return ALARM_TOPOLOGY_POLICIES.get(alarm_code, AlarmTopologyPolicy())


def topology_metadata_for(alarm_code: str) -> dict[str, object]:
    """Return serializable catalog metadata for an AlarmType seed row."""
    return topology_policy_for(alarm_code).to_metadata()


def validate_alarm_topology(alarm: Alarm) -> AlarmTopologyValidationResult:
    """Validate a normalized alarm against its type and actual topology source."""
    source_kind = alarm.get_source_kind()
    alarm_code = alarm.alarm_type.code if alarm.alarm_type_id else ""
    policy = topology_policy_for(alarm_code)
    expected_source_kinds = _allowed_source_kinds(alarm)

    if source_kind is None:
        return _invalid(
            MISSING_SOURCE,
            "Alarm requires exactly one structured source.",
            alarm_code,
            source_kind,
            None,
            expected_source_kinds,
            policy,
        )
    special_result = _validate_special_source(alarm, policy, expected_source_kinds)
    if special_result is not None:
        return special_result
    if expected_source_kinds and source_kind not in expected_source_kinds:
        return _invalid(
            UNSUPPORTED_SOURCE_KIND,
            "Alarm type does not support this source kind.",
            alarm_code,
            source_kind,
            None,
            expected_source_kinds,
            policy,
        )

    source_device = alarm.get_source_device()
    supported_device_types = _supported_device_types(alarm)
    if (
        source_device is not None
        and supported_device_types
        and source_device.device_type not in supported_device_types
    ):
        return _invalid(
            UNSUPPORTED_DEVICE_TYPE,
            "Alarm type does not support the source device type.",
            alarm_code,
            source_kind,
            _source_technology(alarm),
            expected_source_kinds,
            policy,
        )

    source_technology = _source_technology(alarm)
    if source_technology and policy.allowed_technologies:
        if source_technology not in policy.allowed_technologies:
            return _invalid(
                UNSUPPORTED_TECHNOLOGY,
                "Alarm type is not compatible with the source technology.",
                alarm_code,
                source_kind,
                source_technology,
                expected_source_kinds,
                policy,
            )

    return AlarmTopologyValidationResult(
        valid=True,
        reason_code=VALID,
        description="Alarm type and topology source are compatible.",
        alarm_code=alarm_code,
        source_kind=source_kind,
        source_technology=source_technology,
        expected_source_kinds=expected_source_kinds,
        expected_technologies=policy.allowed_technologies,
    )


def _allowed_source_kinds(alarm: Alarm) -> tuple[str, ...]:
    if not alarm.alarm_type_id:
        return ()
    return tuple(
        sorted(alarm.alarm_type.allowed_source_kinds.values_list("source_kind", flat=True))
    )


def _supported_device_types(alarm: Alarm) -> tuple[str, ...]:
    if not alarm.alarm_type_id:
        return ()
    return tuple(
        sorted(alarm.alarm_type.supported_device_types.values_list("device_type", flat=True))
    )


def _source_technology(alarm: Alarm) -> str | None:
    if alarm.line_connection_id:
        return alarm.line_connection.technology
    if alarm.subscription_connection_id:
        return alarm.subscription_connection.line_connection.technology
    if alarm.network_port_id:
        return _device_technology(alarm.network_port.device)
    if alarm.device_id:
        return _device_technology(alarm.device)
    if alarm.network_link_id:
        source = _device_technology(alarm.network_link.source_device)
        target = _device_technology(alarm.network_link.target_device)
        return source if source == target else None
    return None


def _device_technology(device) -> str | None:
    if device.device_type == NetworkDeviceType.OLT:
        return AccessTechnology.GPON
    if device.device_type == NetworkDeviceType.DSLAM:
        return AccessTechnology.VDSL
    if device.device_type == NetworkDeviceType.ACCESS_NODE:
        return AccessTechnology.FIBER
    return None


def _validate_special_source(
    alarm: Alarm,
    policy: AlarmTopologyPolicy,
    expected_source_kinds: tuple[str, ...],
) -> AlarmTopologyValidationResult | None:
    alarm_code = alarm.alarm_type.code if alarm.alarm_type_id else ""
    source_kind = alarm.get_source_kind()
    source_technology = _source_technology(alarm)
    source_device = alarm.get_source_device()

    checks = {
        "PON_PORT_DOWN": ("network_port", NetworkDeviceType.OLT, INVALID_PON_PORT_SOURCE),
        "ONT_DISCONNECT_SURGE": ("network_port", NetworkDeviceType.OLT, INVALID_PON_PORT_SOURCE),
        "PON_CAPACITY_THRESHOLD": ("network_port", NetworkDeviceType.OLT, INVALID_PON_PORT_SOURCE),
        "DSL_PORT_DOWN": ("network_port", NetworkDeviceType.DSLAM, INVALID_DSL_PORT_SOURCE),
        "DEDICATED_PORT_DOWN": (
            "network_port",
            NetworkDeviceType.ACCESS_NODE,
            INVALID_DEDICATED_PORT_SOURCE,
        ),
        "DSL_LINE_QUALITY_DEGRADED": (
            "line_connection",
            NetworkDeviceType.DSLAM,
            INVALID_DSL_LINE_SOURCE,
        ),
        "DSL_RETRAIN_FREQUENT": (
            "line_connection",
            NetworkDeviceType.DSLAM,
            INVALID_DSL_LINE_SOURCE,
        ),
    }
    expected = checks.get(alarm_code)
    if expected and (
        source_kind != expected[0]
        or source_device is None
        or source_device.device_type != expected[1]
    ):
        return _invalid(
            expected[2],
            "Alarm type requires its documented source level and device type.",
            alarm_code,
            source_kind,
            source_technology,
            expected_source_kinds,
            policy,
        )
    if alarm_code == "HIGH_TEMPERATURE" and source_kind != "device":
        return _invalid(
            INVALID_DEVICE_SOURCE,
            "High-temperature alarms are device-level anomalies.",
            alarm_code,
            source_kind,
            source_technology,
            expected_source_kinds,
            policy,
        )
    if alarm_code == "UPLINK_DOWN" and source_kind != "network_link":
        return _invalid(
            INVALID_LINK_SOURCE,
            "Uplink alarms are link-level events.",
            alarm_code,
            source_kind,
            source_technology,
            expected_source_kinds,
            policy,
        )
    return None


def _invalid(
    reason_code: str,
    description: str,
    alarm_code: str,
    source_kind: str | None,
    source_technology: str | None,
    expected_source_kinds: tuple[str, ...],
    policy: AlarmTopologyPolicy,
) -> AlarmTopologyValidationResult:
    return AlarmTopologyValidationResult(
        valid=False,
        reason_code=reason_code,
        description=description,
        alarm_code=alarm_code,
        source_kind=source_kind,
        source_technology=source_technology,
        expected_source_kinds=expected_source_kinds,
        expected_technologies=policy.allowed_technologies,
    )
