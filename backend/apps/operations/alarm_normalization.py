"""Safe normalization of sampled raw alarm titles.

The mapping is deliberately independent of a vendor feed.  It preserves raw
source ambiguity instead of inventing a physical resource or a canonical
AlarmType when the required source level is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.operations.models import Severity

RESOLVED = "resolved"
PARTIALLY_RESOLVED = "partially_resolved"
INSUFFICIENT_SOURCE_CONTEXT = "insufficient_source_context"
UNMAPPED_TITLE = "unmapped_title"


@dataclass(frozen=True)
class AlarmNormalization:
    alarm_family: str
    canonical_subtype: str | None
    canonical_alarm_code: str | None
    default_source_level: str | None
    role_candidate: str
    producer_type: str
    observed_node_type: str | None
    physical_resource_expectation: str | None
    resource_resolution_status: str
    reason_code: str

    def to_metadata(self) -> dict[str, object]:
        return {
            "alarm_family": self.alarm_family,
            "canonical_subtype": self.canonical_subtype,
            "canonical_alarm_code": self.canonical_alarm_code,
            "default_source_level": self.default_source_level,
            "role_candidate": self.role_candidate,
            "producer_type": self.producer_type,
            "observed_node_type": self.observed_node_type,
            "physical_resource_expectation": self.physical_resource_expectation,
            "resource_resolution_status": self.resource_resolution_status,
            "normalization_reason_code": self.reason_code,
        }


def normalize_alarm_title(
    raw_title: str | None,
    *,
    observed_node_type: str | None = None,
    resource_level: str | None = None,
) -> AlarmNormalization:
    """Map a raw title without treating producer metadata as physical inventory."""
    title = _normalize_text(raw_title)
    node_type = _clean(observed_node_type)
    producer_type = "correlation_system" if node_type == "aca korelasyon" else "source_feed"
    spec = _TITLE_SPECS.get(title)
    if spec is None:
        return AlarmNormalization(
            "unknown",
            None,
            None,
            None,
            "supporting",
            producer_type,
            node_type,
            None,
            INSUFFICIENT_SOURCE_CONTEXT,
            UNMAPPED_TITLE,
        )
    canonical_code = spec.canonical_alarm_code
    status = RESOLVED
    reason = RESOLVED
    if spec.conditional_source_level and resource_level != spec.conditional_source_level:
        canonical_code = None
        status = INSUFFICIENT_SOURCE_CONTEXT
        reason = INSUFFICIENT_SOURCE_CONTEXT
    elif spec.default_source_level == "unknown":
        status = INSUFFICIENT_SOURCE_CONTEXT
        reason = INSUFFICIENT_SOURCE_CONTEXT
    elif canonical_code is None:
        status = PARTIALLY_RESOLVED
        reason = PARTIALLY_RESOLVED
    return AlarmNormalization(
        spec.alarm_family,
        spec.canonical_subtype,
        canonical_code,
        spec.default_source_level,
        spec.role_candidate,
        producer_type,
        node_type,
        spec.physical_resource_expectation,
        status,
        reason,
    )


def resolve_alarm_severity(raw_severity: str | None, fallback: str) -> str:
    """Preserve a valid raw severity; use catalog severity only as fallback."""
    normalized = _normalize_text(raw_severity)
    lookup = {choice.casefold(): choice for choice in Severity.values}
    return lookup.get(normalized, fallback)


@dataclass(frozen=True)
class _TitleSpec:
    alarm_family: str
    canonical_subtype: str
    canonical_alarm_code: str | None
    default_source_level: str
    role_candidate: str
    physical_resource_expectation: str
    conditional_source_level: str | None = None


def _spec(*args, **kwargs) -> _TitleSpec:
    return _TitleSpec(*args, **kwargs)


_TITLE_SPECS = {
    "the dying-gasp of gpon onti (dgi) is generated": _spec(
        "gpon_access_symptom",
        "ont_dying_gasp",
        "ONT_DISCONNECT_SURGE",
        "network_port",
        "symptom",
        "olt_pon_port",
    ),
    "dying gasp": _spec(
        "gpon_access_symptom",
        "ont_dying_gasp",
        "ONT_DISCONNECT_SURGE",
        "network_port",
        "symptom",
        "olt_pon_port",
    ),
    "[gpon alarm]onu dying-gasp": _spec(
        "gpon_access_symptom",
        "ont_dying_gasp",
        "ONT_DISCONNECT_SURGE",
        "network_port",
        "symptom",
        "olt_pon_port",
    ),
    "the feeder fiber is broken or olt can not receive any expected optical signals(los)": _spec(
        "optical_loss", "feeder_or_olt_los", None, "failure_domain", "child", "fiber_failure_domain"
    ),
    "loss of signal": _spec("optical_loss", "generic_los", None, "unknown", "symptom", "unknown"),
    "[gpon alarm]onu los(loss of signal)": _spec(
        "optical_loss", "onu_los", "OPTICAL_SIGNAL_LOSS", "line_connection", "symptom", "gpon_line"
    ),
    "pon los (last onu dropped)": _spec(
        "optical_loss", "pon_los", None, "network_port", "symptom", "olt_pon_port"
    ),
    "device not active": _spec(
        "device_state", "device_not_active", None, "device", "symptom", "network_device"
    ),
    "the optical transceiver is absence": _spec(
        "hardware", "optical_transceiver_absent", None, "device", "supporting", "network_device"
    ),
    "the optical transceiver of the pon port is absent": _spec(
        "hardware",
        "pon_optical_transceiver_absent",
        None,
        "network_port",
        "supporting",
        "olt_pon_port",
    ),
    "the communication between the board and the control board fails": _spec(
        "hardware", "board_communication_failure", None, "device", "supporting", "network_device"
    ),
    "the board hardware is abnormal": _spec(
        "hardware", "board_hardware_abnormal", None, "device", "supporting", "network_device"
    ),
    "board removed": _spec(
        "hardware", "board_removed", None, "device", "supporting", "network_device"
    ),
    "the upstream ethernet port connection fails or the state of it is abnormal": _spec(
        "uplink",
        "upstream_ethernet_failure",
        "UPLINK_DOWN",
        "network_link",
        "child",
        "network_link",
        "network_link",
    ),
    "physical port link down": _spec(
        "link", "physical_port_link_down", None, "network_port", "child", "network_port"
    ),
    "gpon port flap alarmi": _spec(
        "gpon_access",
        "gpon_port_flap",
        "LINK_FLAPPING",
        "network_link",
        "child",
        "network_link",
        "network_link",
    ),
    "pon communication failure": _spec(
        "gpon_access",
        "pon_communication_failure",
        "PON_PORT_DOWN",
        "network_port",
        "child",
        "olt_pon_port",
        "network_port",
    ),
    "ont provisioning failure": _spec(
        "gpon_access",
        "ont_provisioning_failure",
        None,
        "network_port",
        "supporting",
        "olt_pon_port",
    ),
    "there are illegal incursionary rogue onts under the port": _spec(
        "gpon_access", "rogue_ont", None, "network_port", "supporting", "olt_pon_port"
    ),
    "distribution_cable_down": _spec(
        "distribution_cable",
        "distribution_cable_down",
        "DISTRIBUTION_CABLE_DOWN",
        "failure_domain",
        "root",
        "fiber_failure_domain",
    ),
}


def _clean(value: str | None) -> str | None:
    return _normalize_text(value) or None


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())
