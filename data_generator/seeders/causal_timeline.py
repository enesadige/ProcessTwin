"""Deterministic causal operation timelines for the multi-city dataset.

This module deliberately creates related operation records from one scenario
instance. It does not perform correlation or customer-impact verification.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from apps.customers.models import SubscriptionConnection
from apps.network.models import LineConnection, NetworkDeviceType
from apps.operations.alarm_normalization import normalize_alarm_title, resolve_alarm_severity
from apps.operations.alarm_topology import validate_alarm_topology
from apps.operations.contracts import (
    CausalEventStatus,
    CausalEventType,
    EventOrigin,
    SessionEventType,
)
from apps.operations.models import (
    Alarm,
    AlarmStatus,
    CausalEvent,
    Incident,
    IncidentAlarm,
    IncidentAlarmRole,
    IncidentStatus,
    IncidentType,
    OperationalEvent,
    OperationalEventType,
    Outage,
    OutageStatus,
    OutageType,
    QualityMeasurement,
    QualityMetricType,
    RootCauseCategory,
    ServiceImpactClass,
    SessionEvent,
)
from data_generator.configs import multicity_ground_truth_v1 as ground_truth_config
from data_generator.configs import realistic_alarm_catalog_v1 as alarm_config


class CausalGenerationError(ValueError):
    """A deterministic scenario could not produce a topology-compatible record."""


@dataclass(frozen=True)
class CausalScenario:
    code: str
    weight: int
    event_type: str
    root_mode: str
    alarm_codes: tuple[str, ...]
    incident_type: str
    impact_class: str
    creates_incident: bool = True
    creates_outage: bool = False
    session_pattern: str = "insufficient_evidence"
    quality_metric: str = QualityMetricType.AVAILABILITY_PERCENT
    allows_ongoing: bool = False


@dataclass
class CausalTimelineContext:
    snapshot: object
    devices: dict[str, object]
    links: dict[str, object]
    ports_by_role: dict[str, list]
    failure_domains: dict[str, object]
    primary_connections: list
    backup_connections: list
    alarm_types: dict[str, object]
    reference_datetime: datetime
    batch_size: int

    def __post_init__(self) -> None:
        self.devices_by_type = {
            device_type: [
                device for device in self.devices.values() if device.device_type == device_type
            ]
            for device_type in NetworkDeviceType.values
        }
        self.gpon_ports = list(self.ports_by_role["gpon_pon"])
        self.xdsl_ports = list(self.ports_by_role["xdsl"])
        self.dedicated_ports = list(self.ports_by_role["dedicated_fiber"])
        self.gpon_lines = list(
            LineConnection.objects.filter(
                data_snapshot=self.snapshot,
                technology="gpon",
                is_active=True,
            ).select_related("port__device")
        )
        self.xdsl_lines = list(
            LineConnection.objects.filter(
                data_snapshot=self.snapshot,
                technology__in=["vdsl", "adsl"],
                is_active=True,
            ).select_related("port__device")
        )
        self.links_to_olt = [
            link
            for link in self.links.values()
            if link.target_device.device_type == NetworkDeviceType.OLT
        ]
        self.failure_domain_pool = list(self.failure_domains.values())
        self.connection_pool = list(self.primary_connections) + list(self.backup_connections)
        self.metro_connections = [
            connection
            for connection in self.connection_pool
            if connection.subscription.service_package.service_type == "metro_ethernet"
        ]


# These are synthetic calibration choices, not a real operator frequency model.
GPON_SCENARIOS: tuple[CausalScenario, ...] = (
    CausalScenario(
        "SCN-GPON-OLT-UNREACHABLE-001",
        5,
        CausalEventType.DEVICE_FAILURE,
        "olt_device",
        ("OLT_UNREACHABLE", "ONT_DISCONNECT_SURGE", "OPTICAL_SIGNAL_LOSS"),
        IncidentType.NETWORK_OUTAGE,
        ServiceImpactClass.PARTIAL_OUTAGE,
        creates_outage=True,
        session_pattern="interruption_candidate",
        quality_metric=QualityMetricType.AVAILABILITY_PERCENT,
    ),
    CausalScenario(
        "SCN-PON-PORT-001",
        10,
        CausalEventType.PORT_FAILURE,
        "olt_port",
        ("PON_PORT_DOWN", "ONT_DISCONNECT_SURGE", "OPTICAL_SIGNAL_LOSS"),
        IncidentType.NETWORK_OUTAGE,
        ServiceImpactClass.PARTIAL_OUTAGE,
        creates_outage=True,
        session_pattern="interruption_candidate",
        quality_metric=QualityMetricType.AVAILABILITY_PERCENT,
    ),
    CausalScenario(
        "SCN-GPON-DISTRIBUTION-CABLE-001",
        7,
        CausalEventType.ACCESS_SEGMENT_FAILURE,
        "failure_domain",
        ("DISTRIBUTION_CABLE_DOWN", "OPTICAL_SIGNAL_LOSS", "ONT_DISCONNECT_SURGE"),
        IncidentType.NETWORK_OUTAGE,
        ServiceImpactClass.PARTIAL_OUTAGE,
        creates_outage=True,
        session_pattern="interruption_candidate",
        quality_metric=QualityMetricType.AVAILABILITY_PERCENT,
    ),
    CausalScenario(
        "SCN-GPON-TEMPERATURE-DEGRADATION-001",
        4,
        CausalEventType.ENVIRONMENTAL_ANOMALY,
        "olt_device",
        ("HIGH_TEMPERATURE", "DEVICE_RESOURCE_HIGH", "PON_CAPACITY_THRESHOLD"),
        IncidentType.SERVICE_DEGRADATION,
        ServiceImpactClass.DEGRADATION,
        creates_outage=False,
        session_pattern="insufficient_evidence",
        quality_metric=QualityMetricType.BANDWIDTH_UTILIZATION_PERCENT,
    ),
    CausalScenario(
        "SCN-GPON-UPLINK-PROPAGATION-001",
        4,
        CausalEventType.LINK_FAILURE,
        "olt_uplink",
        ("UPLINK_DOWN", "OLT_UNREACHABLE", "PON_PORT_DOWN"),
        IncidentType.NETWORK_OUTAGE,
        ServiceImpactClass.PARTIAL_OUTAGE,
        creates_outage=True,
        session_pattern="interruption_candidate",
        quality_metric=QualityMetricType.PACKET_LOSS_PERCENT,
    ),
    CausalScenario(
        "SCN-GPON-NO-IMPACT-001",
        3,
        CausalEventType.DEGRADATION,
        "olt_port",
        ("PON_CAPACITY_THRESHOLD", "ONT_DISCONNECT_SURGE"),
        IncidentType.SERVICE_DEGRADATION,
        ServiceImpactClass.NO_DIRECT_CUSTOMER_IMPACT,
        creates_incident=False,
        creates_outage=False,
        session_pattern="no_impact_candidate",
        quality_metric=QualityMetricType.BANDWIDTH_UTILIZATION_PERCENT,
    ),
    CausalScenario(
        "SCN-GPON-OPTICAL-INTERMITTENT-001",
        6,
        CausalEventType.DEGRADATION,
        "gpon_line",
        ("OPTICAL_SIGNAL_LOW", "OPTICAL_SIGNAL_LOSS"),
        IncidentType.INTERMITTENT,
        ServiceImpactClass.DEGRADATION,
        creates_outage=False,
        session_pattern="insufficient_evidence",
        quality_metric=QualityMetricType.PACKET_LOSS_PERCENT,
        allows_ongoing=True,
    ),
)


def seed_causal_timeline(context: CausalTimelineContext) -> tuple[list[Incident], list[Outage]]:
    """Create scenario-owned operation records with stable seed-derived variance."""
    rng = random.Random(f"{context.snapshot.dataset_version.seed}:causal-timeline-v1")
    scenario_count = 198 + rng.randrange(
        context.snapshot.dataset_version.config["timeline_targets"]["causal_event_variance"] * 2 + 1
    )
    scenarios = _scenario_sequence(rng, scenario_count)
    timeline_start = context.reference_datetime - timedelta(days=60)
    incidents: list[Incident] = []
    outages: list[Outage] = []

    for index, scenario in enumerate(scenarios, start=1):
        started_at = timeline_start + timedelta(hours=index * 6, minutes=rng.randrange(45))
        result = _create_scenario_instance(
            context=context,
            scenario=scenario,
            index=index,
            started_at=started_at,
            rng=rng,
        )
        if result["incident"] is not None:
            incidents.append(result["incident"])
        if result["outage"] is not None:
            outages.append(result["outage"])
    return incidents, outages


def _scenario_sequence(rng: random.Random, scenario_count: int) -> list[CausalScenario]:
    legacy = tuple(_legacy_scenarios())
    # Retain one canonical legacy pass for compatibility, then make all new
    # GPON chains observable. Remaining events are weighted, never equalized.
    selected = [*legacy, *GPON_SCENARIOS]
    weighted = [*GPON_SCENARIOS, *legacy]
    weights = [scenario.weight for scenario in weighted]
    selected.extend(
        rng.choices(
            weighted,
            weights=weights,
            k=max(0, scenario_count - len(selected)),
        )
    )
    return selected


def _legacy_scenarios() -> list[CausalScenario]:
    event_type_by_source = {
        "device": CausalEventType.DEVICE_FAILURE,
        "network_link": CausalEventType.LINK_FAILURE,
        "network_port": CausalEventType.PORT_FAILURE,
        "failure_domain": CausalEventType.ACCESS_SEGMENT_FAILURE,
        "subscription_connection": CausalEventType.LINK_FAILURE,
        "maintenance_window": CausalEventType.MAINTENANCE,
        "unknown": CausalEventType.UNKNOWN,
    }
    scenarios = []
    for item in alarm_config.SCENARIO_TEMPLATES:
        impact = item["service_impact_class"]
        creates_outage = item.get("creates_outage")
        if creates_outage is None:
            creates_outage = impact in {
                ServiceImpactClass.FULL_OUTAGE,
                ServiceImpactClass.PARTIAL_OUTAGE,
                ServiceImpactClass.SHORT_INTERRUPTION,
            }
        if item["code"] == "SCN-PLANNED-MAINT-001":
            creates_outage = False
        ground_truth = next(
            (
                case
                for case in ground_truth_config.GROUND_TRUTH_CASES
                if case.get("scenario_code") == item["code"]
            ),
            None,
        )
        if ground_truth and ground_truth.get("expected_outage_exists") is True:
            creates_outage = True
        scenarios.append(
            CausalScenario(
                code=item["code"],
                weight=1 if item["code"] in {"SCN-BNG-DOWN-001", "SCN-METRO-AGG-001"} else 2,
                event_type=event_type_by_source.get(item["source"], CausalEventType.UNKNOWN),
                root_mode="catalog",
                alarm_codes=tuple(item["alarm_codes"]),
                incident_type=item.get("incident_type", IncidentType.UNKNOWN),
                impact_class=impact,
                creates_incident=item.get("creates_incident", True),
                creates_outage=creates_outage,
                session_pattern=(
                    "no_impact_candidate" if not creates_outage else "interruption_candidate"
                ),
                quality_metric=(
                    QualityMetricType.PACKET_LOSS_PERCENT
                    if impact == ServiceImpactClass.DEGRADATION
                    else QualityMetricType.AVAILABILITY_PERCENT
                ),
                allows_ongoing=item["code"] in {"SCN-NOISE-001", "SCN-UNKNOWN-RCA-001"},
            )
        )
    return scenarios


def _create_scenario_instance(*, context, scenario, index, started_at, rng) -> dict:
    anchor = _select_anchor(context, scenario.root_mode, scenario.alarm_codes[0], index)
    duration = timedelta(minutes=35 + rng.randrange(145))
    ongoing = scenario.allows_ongoing and rng.randrange(7) == 0
    recovery_at = started_at + duration
    root_kwargs = _source_kwargs_for_alarm(
        context=context,
        alarm_code=scenario.alarm_codes[0],
        index=index,
        anchor=anchor,
    )
    causal_event = _save_causal_event(
        context=context,
        scenario=scenario,
        index=index,
        started_at=started_at,
        ended_at=None if ongoing else recovery_at + timedelta(minutes=20),
        root_kwargs=root_kwargs,
        anchor=anchor,
        ongoing=ongoing,
    )
    _apply_ground_truth_device_link(context, scenario, causal_event)
    alarms = _create_alarms(
        context=context,
        scenario=scenario,
        causal_event=causal_event,
        index=index,
        started_at=started_at,
        recovery_at=recovery_at,
        anchor=anchor,
        ongoing=ongoing,
        rng=rng,
    )
    incident = None
    if scenario.creates_incident:
        incident = _create_incident(
            context=context,
            scenario=scenario,
            causal_event=causal_event,
            index=index,
            started_at=started_at,
            recovery_at=recovery_at,
            root_kwargs=root_kwargs,
            anchor=anchor,
            ongoing=ongoing,
        )
        _apply_ground_truth_incident_device(context, scenario, incident)
        _link_incident_alarms(context.snapshot, incident, alarms)
    outage = None
    if scenario.creates_outage and not ongoing and incident is not None:
        outage = _create_outage(
            context=context,
            scenario=scenario,
            causal_event=causal_event,
            incident=incident,
            index=index,
            started_at=started_at + timedelta(minutes=10),
            recovery_at=recovery_at,
            root_kwargs=root_kwargs,
            anchor=anchor,
        )
        _apply_ground_truth_outage_device(context, scenario, outage)
    operational_events = _create_operational_events(
        context=context,
        causal_event=causal_event,
        incident=incident,
        index=index,
        started_at=started_at,
        recovery_at=recovery_at,
        anchor=anchor,
        ongoing=ongoing,
    )
    measurements = _create_quality_measurements(
        context=context,
        scenario=scenario,
        causal_event=causal_event,
        index=index,
        started_at=started_at,
        anchor=anchor,
        rng=rng,
    )
    session_events = _create_session_events(
        context=context,
        scenario=scenario,
        causal_event=causal_event,
        index=index,
        started_at=started_at,
        recovery_at=recovery_at,
        anchor=anchor,
        ongoing=ongoing,
    )
    causal_event.metadata = {
        **causal_event.metadata,
        "record_references": {
            "alarm_ids": [alarm.alarm_id for alarm in alarms],
            "incident_number": incident.incident_number if incident else None,
            "outage_code": outage.outage_code if outage else None,
            "operational_event_codes": [event.event_code for event in operational_events],
            "quality_measurement_count": len(measurements),
            "session_event_ids": [event.external_event_id for event in session_events],
        },
    }
    causal_event.save(update_fields=["metadata", "updated_at"])
    return {"incident": incident, "outage": outage}


def _ground_truth_device(context, scenario):
    """Resolve configured synthetic scenario linkage without fixture-specific app logic."""
    case = next(
        (
            item
            for item in ground_truth_config.GROUND_TRUTH_CASES
            if item.get("scenario_code") == scenario.code
        ),
        None,
    )
    code = case.get("expected_root_cause") if case else None
    if not code or not isinstance(code, str):
        return None
    return next((device for device in context.devices.values() if device.code == code), None)


def _apply_ground_truth_device_link(context, scenario, causal_event) -> None:
    device = _ground_truth_device(context, scenario)
    if device is None:
        return
    for field in (
        "root_network_link_id",
        "root_network_port_id",
        "root_line_connection_id",
        "root_access_segment_id",
        "root_failure_domain_id",
        "root_subscription_connection_id",
    ):
        setattr(causal_event, field, None)
    causal_event.root_device = device
    causal_event.save(
        update_fields=[
            "root_device",
            "root_network_link",
            "root_network_port",
            "root_line_connection",
            "root_access_segment",
            "root_failure_domain",
            "root_subscription_connection",
            "updated_at",
        ]
    )


def _apply_ground_truth_incident_device(context, scenario, incident) -> None:
    device = _ground_truth_device(context, scenario)
    if device is not None:
        incident.primary_device = device
        incident.save(update_fields=["primary_device", "updated_at"])


def _apply_ground_truth_outage_device(context, scenario, outage) -> None:
    device = _ground_truth_device(context, scenario)
    if device is not None:
        outage.source_device = device
        outage.save(update_fields=["source_device", "updated_at"])


def _select_anchor(context, mode, alarm_code, index):
    if mode == "olt_device":
        return {"device": _pick(context.devices_by_type[NetworkDeviceType.OLT], index)}
    if mode == "olt_port":
        port = _pick(context.gpon_ports, index)
        return {
            "network_port": port,
            "device": port.device,
            "line": _line_for_port(context, port, index),
        }
    if mode == "gpon_line":
        line = _pick(context.gpon_lines, index)
        return {"line": line, "network_port": line.port, "device": line.port.device}
    if mode == "olt_uplink":
        link = _pick(context.links_to_olt or list(context.links.values()), index)
        olt = (
            link.target_device if link.target_device.device_type == NetworkDeviceType.OLT else None
        )
        port = (
            _pick(context.gpon_ports, index)
            if olt is None
            else _port_for_device(context, olt, index)
        )
        return {
            "network_link": link,
            "device": olt or port.device,
            "network_port": port,
            "line": _line_for_port(context, port, index),
        }
    if mode == "failure_domain":
        line = _pick(context.gpon_lines, index)
        return {
            "failure_domain": _pick(context.failure_domain_pool, index),
            "line": line,
            "device": line.port.device,
            "network_port": line.port,
        }
    return _catalog_anchor(context, alarm_code, index)


def _catalog_anchor(context, alarm_code, index):
    kwargs = _source_kwargs_for_alarm(
        context=context,
        alarm_code=alarm_code,
        index=index,
        anchor={},
    )
    source = next(iter(kwargs.values()))
    if "network_port" in kwargs:
        return {**kwargs, "device": source.device, "line": _line_for_port(context, source, index)}
    if "line_connection" in kwargs:
        return {**kwargs, "line": source, "device": source.port.device, "network_port": source.port}
    if "network_link" in kwargs:
        return {**kwargs, "device": source.target_device}
    if "subscription_connection" in kwargs:
        return {
            **kwargs,
            "device": source.line_connection.port.device,
            "line": source.line_connection,
        }
    if "failure_domain" in kwargs:
        return {
            **kwargs,
            "device": _pick(context.devices_by_type[NetworkDeviceType.OLT], index),
        }
    return kwargs


def _source_kwargs_for_alarm(*, context, alarm_code, index, anchor):
    if alarm_code in {"PON_PORT_DOWN", "ONT_DISCONNECT_SURGE", "PON_CAPACITY_THRESHOLD"}:
        return {"network_port": anchor.get("network_port") or _pick(context.gpon_ports, index)}
    if alarm_code in {"OPTICAL_SIGNAL_LOW", "OPTICAL_SIGNAL_LOSS"}:
        return {"line_connection": anchor.get("line") or _pick(context.gpon_lines, index)}
    if alarm_code == "DISTRIBUTION_CABLE_DOWN":
        return {
            "failure_domain": anchor.get("failure_domain")
            or _pick(context.failure_domain_pool, index)
        }
    if alarm_code in {
        "OLT_UNREACHABLE",
        "HIGH_TEMPERATURE",
        "DEVICE_RESOURCE_HIGH",
        "COOLING_FAILURE",
    }:
        return {
            "device": anchor.get("device")
            or _pick(context.devices_by_type[NetworkDeviceType.OLT], index)
        }
    if alarm_code == "UPLINK_DOWN":
        return {
            "network_link": anchor.get("network_link") or _pick(list(context.links.values()), index)
        }
    if alarm_code in {"DSL_PORT_DOWN"}:
        return {"network_port": _pick(context.xdsl_ports, index)}
    if alarm_code in {"DSL_LINE_QUALITY_DEGRADED", "DSL_RETRAIN_FREQUENT"}:
        return {"line_connection": _pick(context.xdsl_lines, index)}
    if alarm_code == "DEDICATED_PORT_DOWN":
        return {"network_port": _pick(context.dedicated_ports, index)}
    if alarm_code == "DSLAM_UNREACHABLE" or alarm_code == "DSLAM_PORT_SATURATION":
        return {"device": _pick(context.devices_by_type[NetworkDeviceType.DSLAM], index)}
    if alarm_code == "BNG_UNREACHABLE":
        return {"device": _pick(context.devices_by_type[NetworkDeviceType.BNG], index)}
    if alarm_code == "METRO_AGG_UNREACHABLE":
        return {
            "device": _pick(context.devices_by_type[NetworkDeviceType.METRO_AGGREGATION], index)
        }
    if alarm_code == "ACCESS_NODE_UNREACHABLE":
        return {"device": _pick(context.devices_by_type[NetworkDeviceType.ACCESS_NODE], index)}
    if alarm_code in {"FIBER_CUT_SUSPECTED", "COMMERCIAL_POWER_LOSS", "BACKUP_POWER_DEGRADED"}:
        return {"failure_domain": _pick(context.failure_domain_pool, index)}
    if alarm_code in {"LINK_PACKET_LOSS_HIGH", "LINK_FLAPPING", "BANDWIDTH_UTIL_HIGH"}:
        return {"network_link": _pick(list(context.links.values()), index)}
    if alarm_code in {
        "BACKUP_LINK_UNAVAILABLE",
        "PRIMARY_PATH_DOWN",
        "FAILOVER_UNSUCCESSFUL",
    }:
        return {"subscription_connection": _pick(context.connection_pool, index)}
    if alarm_code in {"SLA_LATENCY_BREACH", "SLA_PACKET_LOSS_BREACH"}:
        return {
            "subscription_connection": _pick(
                context.metro_connections or context.connection_pool,
                index,
            )
        }
    raise CausalGenerationError(f"Unsupported catalog alarm source: {alarm_code}.")


def _save_causal_event(
    *, context, scenario, index, started_at, ended_at, root_kwargs, anchor, ongoing
):
    root_field = {
        "device": "root_device",
        "network_link": "root_network_link",
        "network_port": "root_network_port",
        "line_connection": "root_line_connection",
        "failure_domain": "root_failure_domain",
        "subscription_connection": "root_subscription_connection",
    }[next(iter(root_kwargs))]
    event = CausalEvent(
        data_snapshot=context.snapshot,
        event_code=f"CE-MCR-{index:04d}",
        event_type=scenario.event_type,
        status=CausalEventStatus.ACTIVE if ongoing else CausalEventStatus.RESOLVED,
        started_at=started_at,
        ended_at=ended_at,
        source_system="synthetic_multicity_causal_v1",
        origin=EventOrigin.SYNTHETIC,
        metadata={
            "synthetic": True,
            "scenario_code": scenario.code,
            "seed_context": context.snapshot.dataset_version.seed,
            "topology_scope": _topology_scope(anchor),
            "expected_operational_result": scenario.impact_class,
            "session_pattern": scenario.session_pattern,
        },
        **{root_field: next(iter(root_kwargs.values()))},
    )
    event.full_clean()
    event.save()
    return event


def _create_alarms(
    *, context, scenario, causal_event, index, started_at, recovery_at, anchor, ongoing, rng
):
    codes = list(scenario.alarm_codes)
    if len(codes) > 1:
        codes.extend(rng.choices(codes[1:], k=rng.randrange(1, 5)))
    codes.extend(_calibrated_symptom_codes(scenario, rng, len(context.gpon_lines)))
    alarms = []
    for alarm_index, code in enumerate(codes, start=1):
        source_kwargs = _source_kwargs_for_alarm(
            context=context,
            alarm_code=code,
            index=index + alarm_index,
            anchor=anchor,
        )
        detected_at = started_at + timedelta(minutes=alarm_index * 4)
        cleared_at = None if ongoing else recovery_at + timedelta(minutes=alarm_index + 1)
        raw_title = _synthetic_raw_title(scenario, code, alarm_index)
        normalization = (
            normalize_alarm_title(raw_title, resource_level=next(iter(source_kwargs)))
            if raw_title
            else None
        )
        alarm = Alarm(
            data_snapshot=context.snapshot,
            causal_event=causal_event,
            alarm_id=f"ALM-MCR-{index:04d}-{alarm_index:02d}",
            alarm_type=context.alarm_types[code],
            severity=resolve_alarm_severity(None, context.alarm_types[code].severity),
            status=AlarmStatus.OPEN if ongoing else AlarmStatus.CLEARED,
            detected_at=detected_at,
            received_at=detected_at + timedelta(seconds=5),
            cleared_at=cleared_at,
            last_seen_at=cleared_at or detected_at,
            occurrence_count=1 + (alarm_index % 3),
            deduplication_key=f"CE-{index:04d}-{code}-{alarm_index:02d}",
            raw_payload={
                "synthetic": True,
                **({"raw_alarm_title": raw_title} if raw_title else {}),
            },
            metadata={
                "synthetic": True,
                "scenario_code": scenario.code,
                "causal_role": "root" if alarm_index == 1 else "child",
                **({"normalization": normalization.to_metadata()} if normalization else {}),
            },
            **source_kwargs,
        )
        compatibility = validate_alarm_topology(alarm)
        if not compatibility.valid:
            raise CausalGenerationError(
                f"{scenario.code}: {code} failed topology validation ({compatibility.reason_code})."
            )
        alarm.full_clean()
        alarm.save()
        alarms.append(alarm)
    return alarms


def _calibrated_symptom_codes(scenario, rng, topology_capacity):
    """Add bounded, variable symptom fanout only to optical/cable chains."""
    if scenario.code not in {
        "SCN-GPON-DISTRIBUTION-CABLE-001",
        "SCN-GPON-OLT-UNREACHABLE-001",
    }:
        return []
    max_symptoms = min(3, max(0, topology_capacity - 1))
    if max_symptoms == 0:
        return []
    # Dying Gasp is represented by the compatible ONT-disconnect alarm type;
    # its raw-title metadata preserves the more precise sampled symptom.
    symptoms = ["ONT_DISCONNECT_SURGE"] * (1 + rng.randrange(max_symptoms))
    if len(symptoms) < max_symptoms and rng.randrange(3) == 0:
        symptoms.append("OLT_UNREACHABLE")
    return symptoms


def _synthetic_raw_title(scenario, code, alarm_index):
    if code == "ONT_DISCONNECT_SURGE" and scenario.code in {
        "SCN-GPON-DISTRIBUTION-CABLE-001",
        "SCN-GPON-OLT-UNREACHABLE-001",
    }:
        return "Dying Gasp" if alarm_index % 2 else "The dying-gasp of GPON ONTi (DGi) is generated"
    if code == "OLT_UNREACHABLE" and scenario.code == "SCN-GPON-DISTRIBUTION-CABLE-001":
        return "Device Not Active"
    return None


def _create_incident(
    *,
    context,
    scenario,
    causal_event,
    index,
    started_at,
    recovery_at,
    root_kwargs,
    anchor,
    ongoing,
):
    primary_device = _primary_device(root_kwargs, anchor)
    incident = Incident(
        data_snapshot=context.snapshot,
        causal_event=causal_event,
        incident_number=f"INC-MCR-{index:04d}",
        title=f"Synthetic causal {scenario.code}",
        status=IncidentStatus.OPEN if ongoing else IncidentStatus.RESOLVED,
        severity="critical" if scenario.creates_outage else "major",
        incident_type=scenario.incident_type,
        service_impact_class=scenario.impact_class,
        correlation_method="causal_scenario_generator_v1",
        primary_device=primary_device,
        root_cause_category=RootCauseCategory.UNKNOWN,
        root_cause_summary=scenario.code,
        detected_at=started_at,
        started_at=started_at,
        resolved_at=None if ongoing else recovery_at + timedelta(minutes=2),
        restored_at=None if ongoing else recovery_at,
        closed_at=None if ongoing else recovery_at + timedelta(minutes=5),
        metadata={"synthetic": True, "scenario_code": scenario.code},
    )
    incident.full_clean()
    incident.save()
    return incident


def _link_incident_alarms(snapshot, incident, alarms):
    for alarm_index, alarm in enumerate(alarms):
        relation = IncidentAlarm(
            data_snapshot=snapshot,
            incident=incident,
            alarm=alarm,
            role=IncidentAlarmRole.PRIMARY if alarm_index == 0 else IncidentAlarmRole.SUPPORTING,
            metadata={"synthetic": True, "causal_event_code": alarm.causal_event.event_code},
        )
        relation.full_clean()
        relation.save()


def _create_outage(
    *,
    context,
    scenario,
    causal_event,
    incident,
    index,
    started_at,
    recovery_at,
    root_kwargs,
    anchor,
):
    outage = Outage(
        data_snapshot=context.snapshot,
        causal_event=causal_event,
        outage_code=f"OUT-MCR-{index:04d}",
        incident=incident,
        source_device=_primary_device(root_kwargs, anchor),
        outage_type=_outage_type(root_kwargs),
        impact_type=scenario.impact_class,
        status=OutageStatus.RESOLVED,
        root_cause_category=RootCauseCategory.UNKNOWN,
        root_cause_summary=scenario.code,
        detected_at=started_at,
        started_at=started_at,
        ended_at=recovery_at,
        resolved_at=recovery_at,
        restored_at=recovery_at,
        impact_scope={"synthetic": True, "scenario_code": scenario.code},
        metadata={"synthetic": True, "scenario_code": scenario.code},
    )
    outage.full_clean()
    outage.save()
    return outage


def _create_operational_events(
    *, context, causal_event, incident, index, started_at, recovery_at, anchor, ongoing
):
    device = anchor.get("device")
    events = [
        _save_operational_event(
            context.snapshot,
            causal_event,
            incident,
            f"EVT-MCR-{index:04d}-DETECTED",
            OperationalEventType.NOTE,
            started_at + timedelta(minutes=1),
            device,
            "Synthetic causal event detected.",
        )
    ]
    if not ongoing:
        events.append(
            _save_operational_event(
                context.snapshot,
                causal_event,
                incident,
                f"EVT-MCR-{index:04d}-RECOVERY",
                OperationalEventType.AUTO_RECOVERY,
                recovery_at + timedelta(minutes=3),
                device,
                "Synthetic causal event recovery recorded.",
            )
        )
    return events


def _save_operational_event(
    snapshot, causal_event, incident, code, event_type, occurred_at, device, summary
):
    event = OperationalEvent(
        data_snapshot=snapshot,
        causal_event=causal_event,
        incident=incident,
        event_code=code,
        event_type=event_type,
        occurred_at=occurred_at,
        device=device,
        source="synthetic_causal_generator",
        summary=summary,
        metadata={"synthetic": True, "scenario_code": causal_event.metadata["scenario_code"]},
    )
    event.full_clean()
    event.save()
    return event


def _create_quality_measurements(
    *, context, scenario, causal_event, index, started_at, anchor, rng
):
    count = 38 + rng.randrange(25)
    measurements = []
    source_kwargs = _quality_source_kwargs(anchor, context, index)
    for offset in range(count):
        metric_type = scenario.quality_metric if offset % 3 == 0 else QualityMetricType.LATENCY_MS
        value, unit = _quality_value(metric_type, offset)
        measurement = QualityMeasurement(
            data_snapshot=context.snapshot,
            causal_event=causal_event,
            metric_type=metric_type,
            measured_at=started_at + timedelta(minutes=offset),
            value=value,
            unit=unit,
            metadata={"synthetic": True, "scenario_code": scenario.code},
            **source_kwargs,
        )
        measurement.full_clean()
        measurement.save()
        measurements.append(measurement)
    return measurements


def _quality_source_kwargs(anchor, context, index):
    if anchor.get("line") is not None:
        return {"line_connection": anchor["line"]}
    if anchor.get("network_link") is not None:
        return {"network_link": anchor["network_link"]}
    if anchor.get("device") is not None:
        return {"device": anchor["device"]}
    return {"subscription_connection": _pick(context.connection_pool, index)}


def _quality_value(metric_type, offset):
    if metric_type == QualityMetricType.AVAILABILITY_PERCENT:
        return Decimal("97.5000") - Decimal(offset % 5) / Decimal("10"), "percent"
    if metric_type == QualityMetricType.PACKET_LOSS_PERCENT:
        return Decimal("1.2500") + Decimal(offset % 9) / Decimal("10"), "percent"
    if metric_type == QualityMetricType.BANDWIDTH_UTILIZATION_PERCENT:
        return Decimal("82.0000") + Decimal(offset % 11), "percent"
    return Decimal("35.0000") + Decimal(offset % 7), "ms"


def _create_session_events(
    *, context, scenario, causal_event, index, started_at, recovery_at, anchor, ongoing
):
    connection = _connection_for_anchor(context, anchor, index)
    if connection is None:
        return []
    entries = [(SessionEventType.CONTINUE, started_at - timedelta(minutes=5), {})]
    if scenario.session_pattern == "interruption_candidate" and not ongoing:
        entries.extend(
            [
                (SessionEventType.STOP, started_at + timedelta(minutes=12), {}),
                (SessionEventType.START, recovery_at, {}),
            ]
        )
    elif scenario.session_pattern == "no_impact_candidate":
        entries.append((SessionEventType.CONTINUE, started_at + timedelta(minutes=12), {}))
    else:
        entries.append(
            (
                SessionEventType.CONTINUE,
                started_at + timedelta(minutes=12),
                {"evidence_completeness": "partial"},
            )
        )
    events = []
    for event_index, (event_type, occurred_at, metadata) in enumerate(entries, start=1):
        external_id = f"SES-MCR-{index:04d}-{event_index:02d}"
        event = SessionEvent(
            data_snapshot=context.snapshot,
            causal_event=causal_event,
            external_event_id=external_id,
            event_type=event_type,
            occurred_at=occurred_at,
            received_at=occurred_at + timedelta(seconds=10),
            source_system="synthetic_session_adapter",
            subscription=connection.subscription,
            subscription_connection=connection,
            external_service_reference_hash=_hash_reference(
                connection.subscription.subscription_number
            ),
            nas_identifier="synthetic-nas",
            service_identifier_hash=_hash_reference(connection.line_connection.line_code),
            session_identifier_hash=_hash_reference(external_id),
            subscriber_reference_hash=_hash_reference(connection.subscription.subscription_number),
            raw_payload={"synthetic": True},
            metadata={
                "synthetic": True,
                "scenario_code": scenario.code,
                "evidence_pattern": scenario.session_pattern,
                **metadata,
            },
        )
        event.full_clean()
        event.save()
        events.append(event)
    return events


def _connection_for_anchor(context, anchor, index):
    if anchor.get("line") is not None:
        connection = (
            SubscriptionConnection.objects.filter(
                data_snapshot=context.snapshot,
                line_connection=anchor["line"],
                is_active=True,
            )
            .select_related("subscription", "line_connection")
            .order_by("subscription__subscription_number")
            .first()
        )
        if connection is not None:
            return connection
    return _pick(context.primary_connections, index) if context.primary_connections else None


def _primary_device(root_kwargs, anchor):
    if "device" in root_kwargs:
        return root_kwargs["device"]
    if "network_link" in root_kwargs:
        return root_kwargs["network_link"].target_device
    if "network_port" in root_kwargs:
        return root_kwargs["network_port"].device
    if "line_connection" in root_kwargs:
        return root_kwargs["line_connection"].port.device
    if "subscription_connection" in root_kwargs:
        return root_kwargs["subscription_connection"].line_connection.port.device
    return anchor["device"]


def _outage_type(root_kwargs):
    if "network_link" in root_kwargs:
        return OutageType.LINK
    if "device" in root_kwargs:
        return OutageType.DEVICE
    return OutageType.ACCESS


def _topology_scope(anchor):
    return {
        key: (
            getattr(value, "code", None)
            or getattr(value, "link_code", None)
            or getattr(value, "port_code", None)
            or getattr(value, "line_code", None)
        )
        for key, value in anchor.items()
        if key in {"device", "network_link", "network_port", "line", "failure_domain"}
    }


def _line_for_port(context, port, index):
    candidates = [line for line in context.gpon_lines if line.port_id == port.id]
    return _pick(candidates or context.gpon_lines, index)


def _port_for_device(context, device, index):
    candidates = [port for port in context.gpon_ports if port.device_id == device.id]
    return _pick(candidates or context.gpon_ports, index)


def _pick(items, index):
    if not items:
        raise CausalGenerationError("Causal scenario source pool is empty.")
    return items[index % len(items)]


def _hash_reference(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
