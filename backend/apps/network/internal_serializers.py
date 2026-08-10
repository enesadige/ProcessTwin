from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet

from apps.datasets.models import DataSnapshot
from apps.network.models import (
    FailureDomain,
    LineConnection,
    NetworkDevice,
    NetworkLink,
    NetworkPort,
)
from apps.operations.models import Alarm, Incident, MaintenanceWindow, Outage


def iso_or_none(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def snapshot_summary(snapshot: DataSnapshot) -> dict[str, Any]:
    return {
        "dataset_slug": snapshot.dataset_version.slug,
        "snapshot_key": snapshot.snapshot_key,
        "snapshot_name": snapshot.name,
        "snapshot_status": snapshot.status,
        "is_active": snapshot.is_active,
        "reference_datetime": snapshot.dataset_version.config.get("reference_datetime"),
    }


def location_summary(obj) -> dict[str, str | None]:
    return {
        "city": getattr(getattr(obj, "city", None), "name", None),
        "district": getattr(getattr(obj, "district", None), "name", None),
        "neighborhood": getattr(getattr(obj, "neighborhood", None), "name", None),
    }


def device_summary(device: NetworkDevice | None) -> dict[str, Any] | None:
    if device is None:
        return None
    return {
        "code": device.code,
        "name": device.name,
        "device_type": device.device_type,
        "inventory_status": device.inventory_status,
        "access_role": device.access_role,
        "vendor": device.vendor,
        "model_name": device.model_name,
        "software_version": device.software_version,
        "management_ip": str(device.management_ip) if device.management_ip else None,
        "location": location_summary(device),
    }


def link_summary(link: NetworkLink | None) -> dict[str, Any] | None:
    if link is None:
        return None
    return {
        "link_code": link.link_code,
        "source_device_code": link.source_device.code,
        "target_device_code": link.target_device.code,
        "status": link.status,
        "capacity_mbps": link.capacity_mbps,
    }


def port_summary(port: NetworkPort | None) -> dict[str, Any] | None:
    if port is None:
        return None
    return {
        "port_code": port.port_code,
        "device_code": port.device.code,
        "port_type": port.port_type,
        "inventory_status": port.inventory_status,
        "capacity_mbps": port.capacity_mbps,
    }


def line_summary(line: LineConnection | None) -> dict[str, Any] | None:
    if line is None:
        return None
    return {
        "line_code": line.line_code,
        "technology": line.technology,
        "status": line.status,
        "is_active": line.is_active,
        "valid_from": iso_or_none(line.valid_from),
        "valid_to": iso_or_none(line.valid_to),
        "port": port_summary(line.port),
        "access_segment_code": line.access_segment.segment_code,
    }


def failure_domain_summary(domain: FailureDomain | None) -> dict[str, Any] | None:
    if domain is None:
        return None
    return {
        "code": domain.code,
        "name": domain.name,
        "domain_type": domain.domain_type,
        "description": domain.description,
    }


def failure_domain_list(
    domains: QuerySet[FailureDomain] | list[FailureDomain],
) -> list[dict[str, Any]]:
    return [failure_domain_summary(domain) for domain in domains]


def alarm_type_summary(alarm: Alarm) -> dict[str, Any]:
    alarm_type = alarm.alarm_type
    return {
        "code": alarm_type.code,
        "name": alarm_type.name,
        "category": alarm_type.category,
        "severity": alarm_type.severity,
        "probable_cause_family": alarm_type.probable_cause_family,
        "service_impact_class": alarm_type.service_impact_class,
        "correlation_family": alarm_type.correlation_family,
        "is_root_candidate": alarm_type.is_root_candidate,
    }


def alarm_source_summary(alarm: Alarm) -> dict[str, Any]:
    source_kind = alarm.get_source_kind()
    source = alarm.get_source()
    return {
        "source_kind": source_kind,
        "source_label": alarm.source_label,
        "source_device": device_summary(alarm.get_source_device()),
        "network_link": link_summary(source if source_kind == "network_link" else None),
        "network_port": port_summary(source if source_kind == "network_port" else None),
        "line_connection": line_summary(source if source_kind == "line_connection" else None),
        "failure_domain": failure_domain_summary(
            source if source_kind == "failure_domain" else None
        ),
    }


def alarm_summary(alarm: Alarm) -> dict[str, Any]:
    incident_links = list(
        alarm.incident_alarms.select_related("incident").order_by("incident__incident_number")
    )
    return {
        "alarm_id": alarm.alarm_id,
        "alarm_type": alarm_type_summary(alarm),
        "severity": alarm.severity,
        "status": alarm.status,
        "source": alarm_source_summary(alarm),
        "incident_links": [
            {"incident_code": item.incident.incident_number, "role": item.role}
            for item in incident_links
        ],
        "detected_at": iso_or_none(alarm.detected_at),
        "received_at": iso_or_none(alarm.received_at),
        "acknowledged_at": iso_or_none(alarm.acknowledged_at),
        "cleared_at": iso_or_none(alarm.cleared_at),
        "last_seen_at": iso_or_none(alarm.last_seen_at),
        "occurrence_count": alarm.occurrence_count,
        "deduplication_key": alarm.deduplication_key,
        "recurrence_group_key": alarm.recurrence_group_key,
    }


def incident_summary(incident: Incident | None) -> dict[str, Any] | None:
    if incident is None:
        return None
    return {
        "incident_code": incident.incident_number,
        "title": incident.title,
        "status": incident.status,
        "severity": incident.severity,
        "incident_type": incident.incident_type,
        "service_impact_class": incident.service_impact_class,
        "correlation_method": incident.correlation_method,
        "failover_result": incident.failover_result,
        "transition_duration_seconds": incident.transition_duration_seconds,
        "primary_device": device_summary(incident.primary_device),
        "root_cause_category": incident.root_cause_category,
        "root_cause_summary": incident.root_cause_summary,
        "started_at": iso_or_none(incident.started_at),
        "resolved_at": iso_or_none(incident.resolved_at),
        "restored_at": iso_or_none(incident.restored_at),
    }


def outage_summary(outage: Outage, *, duration: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "outage_code": outage.outage_code,
        "causal_event_code": (outage.causal_event.event_code if outage.causal_event_id else None),
        "status": outage.status,
        "outage_type": outage.outage_type,
        "impact_class": outage.impact_type,
        "incident": incident_summary(outage.incident),
        "source_device": device_summary(outage.source_device),
        "root_cause_category": outage.root_cause_category,
        "root_cause_summary": outage.root_cause_summary,
        "root_cause_classification": outage.metadata.get("ground_truth_root_classification"),
        "detected_at": iso_or_none(outage.detected_at),
        "started_at": iso_or_none(outage.started_at),
        "ended_at": iso_or_none(outage.ended_at),
        "resolved_at": iso_or_none(outage.resolved_at),
        "restored_at": iso_or_none(outage.restored_at),
        "transition_duration_seconds": outage.transition_duration_seconds,
        "duration": duration,
    }


def maintenance_summary(window: MaintenanceWindow | None) -> dict[str, Any] | None:
    if window is None:
        return None
    return {
        "reference_code": window.reference_code,
        "status": window.status,
        "planned_start_at": iso_or_none(window.planned_start_at),
        "planned_end_at": iso_or_none(window.planned_end_at),
        "actual_start_at": iso_or_none(window.actual_start_at),
        "actual_end_at": iso_or_none(window.actual_end_at),
        "expected_impact_class": window.expected_impact_class,
        "actual_impact_class": window.actual_impact_class,
        "overrun_minutes": window.overrun_minutes,
        "linked_incident_code": (
            window.linked_incident.incident_number if window.linked_incident_id else None
        ),
    }


def status_counts(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))
