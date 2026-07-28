from datetime import timedelta

from django.utils.dateparse import parse_datetime

from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice
from apps.operations.models import (
    Alarm,
    AlarmStatus,
    AlarmType,
    Incident,
    IncidentAlarm,
    IncidentAlarmRole,
    IncidentStatus,
    OperationalEvent,
    Outage,
    OutageStatus,
    OutageType,
    RootCauseCategory,
)
from data_generator.configs import maltepe_mvp_v1 as seed_config


def seed_operations(*, snapshot: DataSnapshot, reference_datetime) -> dict[str, int]:
    alarm_types = create_alarm_types(snapshot)
    devices = {
        device.code: device
        for device in NetworkDevice.objects.filter(data_snapshot=snapshot).order_by("code")
    }
    incidents_created = 0
    outages_created = 0
    alarms_created = 0
    incident_alarms_created = 0
    operational_events_created = 0

    for scenario in build_outage_scenarios(reference_datetime):
        result = create_outage_scenario(
            snapshot=snapshot,
            devices=devices,
            alarm_types=alarm_types,
            scenario=scenario,
        )
        incidents_created += result["incidents"]
        outages_created += result["outages"]
        alarms_created += result["alarms"]
        incident_alarms_created += result["incident_alarms"]
        operational_events_created += result["operational_events"]

    return {
        "alarm_types": len(alarm_types),
        "alarms": alarms_created,
        "incidents": incidents_created,
        "incident_alarms": incident_alarms_created,
        "outages": outages_created,
        "operational_events": operational_events_created,
        "quality_measurements": 0,
    }


def create_alarm_types(snapshot: DataSnapshot) -> dict[str, AlarmType]:
    alarm_types: dict[str, AlarmType] = {}
    for alarm_config in seed_config.ALARM_CATALOG:
        alarm_type = save_clean(
            AlarmType(
                data_snapshot=snapshot,
                code=alarm_config["code"],
                name=alarm_config["name"],
                severity=alarm_config["severity"],
                category=alarm_config["category"],
                description=alarm_config["description"],
                metadata={"seed_role": "alarm_type", "synthetic": True},
            )
        )
        alarm_types[alarm_type.code] = alarm_type
    return alarm_types


def build_outage_scenarios(reference_datetime) -> list[dict]:
    scenarios = [seed_config.OUTAGE_PLAN["main"], *seed_config.OUTAGE_PLAN["secondary"]]
    return [
        move_scenario_to_reference_previous_month(scenario, reference_datetime)
        for scenario in scenarios
    ]


def move_scenario_to_reference_previous_month(scenario: dict, reference_datetime) -> dict:
    previous_month_year, previous_month = get_previous_month_year_month(reference_datetime)
    return {
        **scenario,
        "started_at": move_datetime_to_year_month(
            scenario["started_at"],
            previous_month_year,
            previous_month,
        ).isoformat(),
        "ended_at": move_datetime_to_year_month(
            scenario["ended_at"],
            previous_month_year,
            previous_month,
        ).isoformat(),
    }


def get_previous_month_year_month(reference_datetime) -> tuple[int, int]:
    if reference_datetime.month == 1:
        return reference_datetime.year - 1, 12
    return reference_datetime.year, reference_datetime.month - 1


def move_datetime_to_year_month(value: str, year: int, month: int):
    parsed = parse_required_datetime(value)
    return parsed.replace(year=year, month=month)


def create_outage_scenario(
    *,
    snapshot: DataSnapshot,
    devices: dict[str, NetworkDevice],
    alarm_types: dict[str, AlarmType],
    scenario: dict,
) -> dict[str, int]:
    source_device = devices[scenario["source_device"]]
    started_at = parse_required_datetime(scenario["started_at"])
    ended_at = parse_required_datetime(scenario["ended_at"])
    alarm_type = alarm_types[scenario["alarm_type"]]
    severity = alarm_type.severity
    root_cause_category = scenario.get("root_cause_category", RootCauseCategory.UNKNOWN)
    root_cause_summary = scenario.get(
        "root_cause_summary",
        f"Synthetic {source_device.device_type} outage for Maltepe MVP.",
    )

    primary_alarm = create_alarm(
        snapshot=snapshot,
        alarm_id=f"ALM-{scenario['outage_code']}-PRIMARY",
        alarm_type=alarm_type,
        device=source_device,
        severity=severity,
        detected_at=started_at,
        cleared_at=ended_at,
        metadata={"seed_role": "primary_outage_alarm", "outage_code": scenario["outage_code"]},
    )
    alarms = [primary_alarm]

    if supporting_alarm_type := scenario.get("supporting_alarm_type"):
        support_alarm_type = alarm_types[supporting_alarm_type]
        alarms.append(
            create_alarm(
                snapshot=snapshot,
                alarm_id=f"ALM-{scenario['outage_code']}-LINK",
                alarm_type=support_alarm_type,
                device=source_device,
                severity=support_alarm_type.severity,
                detected_at=started_at,
                cleared_at=ended_at,
                metadata={
                    "seed_role": "supporting_link_alarm",
                    "outage_code": scenario["outage_code"],
                },
            )
        )

    incident = save_clean(
        Incident(
            data_snapshot=snapshot,
            incident_number=scenario["incident_number"],
            title=f"{source_device.code} synthetic outage",
            status=IncidentStatus.RESOLVED,
            severity=severity,
            primary_device=source_device,
            root_cause_category=root_cause_category,
            root_cause_summary=root_cause_summary,
            detected_at=started_at,
            started_at=started_at,
            resolved_at=ended_at,
            closed_at=ended_at,
            metadata={
                "seed_role": "outage_incident",
                "source_device": source_device.code,
                "synthetic": True,
            },
        )
    )

    incident_alarms = []
    for index, alarm in enumerate(alarms):
        incident_alarms.append(
            save_clean(
                IncidentAlarm(
                    data_snapshot=snapshot,
                    incident=incident,
                    alarm=alarm,
                    role=(
                        IncidentAlarmRole.PRIMARY
                        if index == 0
                        else IncidentAlarmRole.SUPPORTING
                    ),
                    metadata={"seed_role": "incident_alarm"},
                )
            )
        )

    save_clean(
        Outage(
            data_snapshot=snapshot,
            outage_code=scenario["outage_code"],
            incident=incident,
            source_device=source_device,
            outage_type=OutageType.DEVICE,
            status=OutageStatus.RESOLVED,
            root_cause_category=root_cause_category,
            root_cause_summary=root_cause_summary,
            detected_at=started_at,
            started_at=started_at,
            ended_at=ended_at,
            resolved_at=ended_at,
            impact_scope={
                "district": "Maltepe",
                "source_device": source_device.code,
                "customer_impact_calculated": False,
            },
            metadata={
                "seed_role": "outage",
                "duration_minutes": scenario["duration_minutes"],
                "customer_impact_deferred": True,
            },
        )
    )

    events_created = create_operational_events(
        snapshot=snapshot,
        incident=incident,
        device=source_device,
        outage_code=scenario["outage_code"],
        started_at=started_at,
        ended_at=ended_at,
    )

    return {
        "incidents": 1,
        "outages": 1,
        "alarms": len(alarms),
        "incident_alarms": len(incident_alarms),
        "operational_events": events_created,
    }


def create_alarm(
    *,
    snapshot: DataSnapshot,
    alarm_id: str,
    alarm_type: AlarmType,
    device: NetworkDevice,
    severity: str,
    detected_at,
    cleared_at,
    metadata: dict,
) -> Alarm:
    return save_clean(
        Alarm(
            data_snapshot=snapshot,
            alarm_id=alarm_id,
            alarm_type=alarm_type,
            device=device,
            severity=severity,
            status=AlarmStatus.CLEARED,
            detected_at=detected_at,
            cleared_at=cleared_at,
            raw_payload={"synthetic": True, "source": "maltepe_mvp_seed"},
            metadata=metadata,
        )
    )


def create_operational_events(
    *,
    snapshot: DataSnapshot,
    incident: Incident,
    device: NetworkDevice,
    outage_code: str,
    started_at,
    ended_at,
) -> int:
    created = 0
    for template in seed_config.OPERATIONAL_EVENT_TEMPLATES:
        occurred_at = calculate_event_time(template, started_at, ended_at)
        save_clean(
            OperationalEvent(
                data_snapshot=snapshot,
                event_code=f"EVT-{outage_code}-{template['suffix']}",
                event_type=template["event_type"],
                occurred_at=occurred_at,
                device=device,
                incident=incident,
                source=template["source"],
                summary=template["summary"],
                metadata={
                    "seed_role": "operational_event",
                    "outage_code": outage_code,
                    "does_not_change_customer_impact": True,
                    "does_not_claim_partial_restoration": True,
                },
            )
        )
        created += 1
    return created


def calculate_event_time(template: dict, started_at, ended_at):
    if "offset_minutes" in template:
        return started_at + timedelta(minutes=template["offset_minutes"])
    return ended_at + timedelta(minutes=template["offset_minutes_from_end"])


def parse_required_datetime(value: str):
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid datetime value: {value}")
    return parsed


def save_clean(instance):
    instance.full_clean()
    instance.save()
    return instance
