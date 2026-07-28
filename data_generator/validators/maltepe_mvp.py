import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from django.utils.dateparse import parse_datetime

from apps.customers.models import (
    Customer,
    CustomerPriorityLevel,
    ServicePackage,
    Subscription,
    SubscriptionConnection,
)
from apps.datasets.models import DataSnapshot, GroundTruthCase
from apps.geography.models import Neighborhood
from apps.network.models import (
    AccessSegment,
    LineConnection,
    NetworkDevice,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
)
from apps.operations.models import (
    Alarm,
    AlarmType,
    Incident,
    IncidentAlarm,
    OperationalEvent,
    Outage,
    QualityMeasurement,
)
from apps.rules.models import Rule, RuleVersion

EXPECTED_COUNTS = {
    "neighborhoods": 5,
    "network_devices": 14,
    "network_links": 12,
    "network_ports": 177,
    "access_segments": 17,
    "line_connections": 240,
    "customers": 225,
    "service_packages": 8,
    "subscriptions": 240,
    "subscription_connections": 240,
    "alarm_types": 3,
    "alarms": 4,
    "incidents": 3,
    "incident_alarms": 4,
    "outages": 3,
    "operational_events": 12,
    "quality_measurements": 0,
    "rules": 1,
    "rule_versions": 2,
    "ground_truth_cases": 3,
}

EXPECTED_PRIORITY_DISTRIBUTION = {
    CustomerPriorityLevel.VIP: 20,
    CustomerPriorityLevel.STANDARD: 205,
}
EXPECTED_BNG_DISTRIBUTION = {
    "BNG-MAL-001": 150,
    "BNG-MAL-002": 90,
}
EXPECTED_PACKAGE_TECHNOLOGY_DISTRIBUTION = {
    "fiber": 130,
    "vdsl": 90,
    "adsl": 20,
}
MAIN_OUTAGE_CODE = "OUT-MAL-BNG-001"
MAIN_OUTAGE_DURATION_MINUTES = 200


def validate_maltepe_mvp_snapshot(snapshot: DataSnapshot) -> dict[str, Any]:
    checks = [
        build_check(
            name="row_counts",
            expected=EXPECTED_COUNTS,
            actual=collect_row_counts(snapshot),
        ),
        build_check(
            name="customer_priority_distribution",
            expected=EXPECTED_PRIORITY_DISTRIBUTION,
            actual=collect_customer_priority_distribution(snapshot),
        ),
        build_check(
            name="bng_subscription_distribution",
            expected=EXPECTED_BNG_DISTRIBUTION,
            actual=collect_bng_subscription_distribution(snapshot),
        ),
        build_check(
            name="subscription_package_technology_distribution",
            expected=EXPECTED_PACKAGE_TECHNOLOGY_DISTRIBUTION,
            actual=collect_subscription_package_technology_distribution(snapshot),
        ),
        build_check(
            name="active_subscription_connections",
            expected=240,
            actual=SubscriptionConnection.objects.filter(
                data_snapshot=snapshot,
                is_active=True,
            ).count(),
        ),
        build_check(
            name="main_outage_previous_month_longest_duration",
            expected={
                "outage_code": MAIN_OUTAGE_CODE,
                "duration_minutes": MAIN_OUTAGE_DURATION_MINUTES,
                "is_previous_month_longest": True,
            },
            actual=collect_main_outage_previous_month_status(snapshot),
        ),
        build_check(
            name="ground_truth_case_integrity",
            expected={
                "case_count": 3,
                "references_are_valid": True,
                "hashes_are_valid": True,
                "affected_unaffected_counts_are_valid": True,
                "source_devices_are_valid": True,
                "main_bng_affected_subscriptions": 150,
            },
            actual=collect_ground_truth_integrity(snapshot),
        ),
    ]
    row_counts = next(check["actual"] for check in checks if check["name"] == "row_counts")
    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "row_counts": row_counts,
    }


def collect_row_counts(snapshot: DataSnapshot) -> dict[str, int]:
    district = snapshot.dataset_version.config["geography"]["district"]["name"]
    return {
        "neighborhoods": Neighborhood.objects.filter(district__name=district).count(),
        "network_devices": NetworkDevice.objects.filter(data_snapshot=snapshot).count(),
        "network_links": NetworkLink.objects.filter(data_snapshot=snapshot).count(),
        "network_ports": NetworkPort.objects.filter(data_snapshot=snapshot).count(),
        "access_segments": AccessSegment.objects.filter(data_snapshot=snapshot).count(),
        "line_connections": LineConnection.objects.filter(data_snapshot=snapshot).count(),
        "customers": Customer.objects.filter(data_snapshot=snapshot).count(),
        "service_packages": ServicePackage.objects.filter(data_snapshot=snapshot).count(),
        "subscriptions": Subscription.objects.filter(data_snapshot=snapshot).count(),
        "subscription_connections": SubscriptionConnection.objects.filter(
            data_snapshot=snapshot
        ).count(),
        "alarm_types": AlarmType.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "incidents": Incident.objects.filter(data_snapshot=snapshot).count(),
        "incident_alarms": IncidentAlarm.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "operational_events": OperationalEvent.objects.filter(data_snapshot=snapshot).count(),
        "quality_measurements": QualityMeasurement.objects.filter(
            data_snapshot=snapshot
        ).count(),
        "rules": Rule.objects.filter(data_snapshot=snapshot).count(),
        "rule_versions": RuleVersion.objects.filter(data_snapshot=snapshot).count(),
        "ground_truth_cases": GroundTruthCase.objects.filter(data_snapshot=snapshot).count(),
    }


def collect_customer_priority_distribution(snapshot: DataSnapshot) -> dict[str, int]:
    return normalize_counter(
        Counter(
            Customer.objects.filter(data_snapshot=snapshot).values_list(
                "priority_level",
                flat=True,
            )
        )
    )


def collect_bng_subscription_distribution(snapshot: DataSnapshot) -> dict[str, int]:
    connections = (
        SubscriptionConnection.objects.filter(data_snapshot=snapshot, is_active=True)
        .select_related("line_connection__port__device")
        .order_by("id")
    )
    return normalize_counter(
        Counter(get_connection_bng_code(connection) for connection in connections)
    )


def collect_subscription_package_technology_distribution(snapshot: DataSnapshot) -> dict[str, int]:
    return normalize_counter(
        Counter(
            SubscriptionConnection.objects.filter(data_snapshot=snapshot, is_active=True)
            .select_related("subscription__service_package")
            .values_list("subscription__service_package__technology", flat=True)
        )
    )


def collect_main_outage_previous_month_status(snapshot: DataSnapshot) -> dict[str, Any]:
    reference_datetime = parse_reference_datetime(
        snapshot.dataset_version.config["reference_datetime"]
    )
    previous_month_start, current_month_start = get_previous_calendar_month_bounds(
        reference_datetime
    )
    previous_month_outages = Outage.objects.filter(
        data_snapshot=snapshot,
        started_at__gte=previous_month_start,
        started_at__lt=current_month_start,
    )
    main_outage = previous_month_outages.filter(outage_code=MAIN_OUTAGE_CODE).first()
    longest_outage = max(
        previous_month_outages,
        key=lambda outage: outage.duration_seconds or 0,
        default=None,
    )
    duration_minutes = None
    if main_outage and main_outage.duration_seconds is not None:
        duration_minutes = main_outage.duration_seconds // 60
    return {
        "outage_code": main_outage.outage_code if main_outage else None,
        "duration_minutes": duration_minutes,
        "is_previous_month_longest": bool(
            main_outage
            and longest_outage
            and longest_outage.outage_code == main_outage.outage_code
        ),
    }


def collect_ground_truth_integrity(snapshot: DataSnapshot) -> dict[str, Any]:
    cases = list(GroundTruthCase.objects.filter(data_snapshot=snapshot).order_by("outage_code"))
    outage_codes = set(
        Outage.objects.filter(data_snapshot=snapshot).values_list("outage_code", flat=True)
    )
    incident_codes = set(
        Incident.objects.filter(data_snapshot=snapshot).values_list("incident_number", flat=True)
    )
    alarm_type_codes = set(
        AlarmType.objects.filter(data_snapshot=snapshot).values_list("code", flat=True)
    )
    source_device_codes = set(
        NetworkDevice.objects.filter(data_snapshot=snapshot).values_list("code", flat=True)
    )
    customer_codes = set(
        Customer.objects.filter(data_snapshot=snapshot).values_list("customer_number", flat=True)
    )
    subscription_codes = set(
        Subscription.objects.filter(data_snapshot=snapshot).values_list(
            "subscription_number",
            flat=True,
        )
    )
    total_customers = len(customer_codes)
    total_subscriptions = len(subscription_codes)
    references_are_valid = all(
        case.outage_code in outage_codes
        and case.expected_incident_code in incident_codes
        and set(case.expected_alarm_type_codes).issubset(alarm_type_codes)
        and set(case.affected_customer_codes).issubset(customer_codes)
        and set(case.affected_subscription_codes).issubset(subscription_codes)
        for case in cases
    )
    hashes_are_valid = all(
        case.affected_customer_hash == hash_codes(case.affected_customer_codes)
        and case.affected_subscription_hash == hash_codes(case.affected_subscription_codes)
        for case in cases
    )
    affected_unaffected_counts_are_valid = all(
        case.affected_customer_count + case.unaffected_customer_count == total_customers
        and case.affected_subscription_count + case.unaffected_subscription_count
        == total_subscriptions
        and case.affected_subscription_count >= case.affected_customer_count
        for case in cases
    )
    main_case = next((case for case in cases if case.outage_code == MAIN_OUTAGE_CODE), None)
    return {
        "case_count": len(cases),
        "references_are_valid": references_are_valid,
        "hashes_are_valid": hashes_are_valid,
        "affected_unaffected_counts_are_valid": affected_unaffected_counts_are_valid,
        "source_devices_are_valid": all(
            case.expected_source_device_code in source_device_codes for case in cases
        ),
        "main_bng_affected_subscriptions": (
            main_case.affected_subscription_count if main_case else None
        ),
    }


def get_previous_calendar_month_bounds(reference_datetime: datetime) -> tuple[datetime, datetime]:
    current_month_start = reference_datetime.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    previous_month_end = current_month_start - timedelta(microseconds=1)
    previous_month_start = previous_month_end.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return previous_month_start, current_month_start


def parse_reference_datetime(value: str) -> datetime:
    reference_datetime = parse_datetime(value)
    if reference_datetime is None:
        raise ValueError("Dataset config reference_datetime must be a valid ISO datetime.")
    return reference_datetime


def get_connection_bng_code(connection: SubscriptionConnection) -> str:
    device = connection.line_connection.port.device
    if device.device_type == NetworkDeviceType.BNG:
        return device.code
    return device.metadata["parent_bng"]


def build_check(*, name: str, expected, actual) -> dict[str, Any]:
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "passed": actual == expected,
    }


def normalize_counter(counter: Counter) -> dict[str, int]:
    return dict(sorted(counter.items()))


def hash_codes(codes: list[str]) -> str:
    encoded = json.dumps(codes, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
