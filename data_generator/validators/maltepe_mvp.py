import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Count, Q
from django.utils.dateparse import parse_datetime

from apps.customers.models import (
    Customer,
    CustomerPriorityLevel,
    ServicePackage,
    Subscription,
    SubscriptionConnection,
    SubscriptionConnectionRole,
)
from apps.datasets.models import DataSnapshot, GroundTruthCase
from apps.geography.models import Neighborhood
from apps.network.models import (
    AccessSegment,
    DeviceFailureDomainMembership,
    FailureDomain,
    LineConnection,
    LineConnectionFailureDomainMembership,
    NetworkDevice,
    NetworkDeviceAccessRole,
    NetworkDeviceType,
    NetworkLink,
    NetworkLinkFailureDomainMembership,
    NetworkPort,
    NetworkPortStatus,
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
from data_generator.configs import maltepe_mvp_v1 as seed_config

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
            name="subscription_connection_role_distribution",
            expected={SubscriptionConnectionRole.PRIMARY: 240},
            actual=collect_subscription_connection_role_distribution(snapshot),
        ),
        build_check(
            name="access_node_role_distribution",
            expected={NetworkDeviceAccessRole.STANDARD_ACCESS: 2},
            actual=collect_access_node_role_distribution(snapshot),
        ),
        build_check(
            name="network_link_topology",
            expected={
                "self_links": 0,
                "has_cycle": False,
            },
            actual=collect_network_link_topology(snapshot),
        ),
        build_check(
            name="snapshot_reference_integrity",
            expected={
                "network_links": True,
                "network_ports": True,
                "access_segments": True,
                "line_connections": True,
                "subscriptions": True,
                "subscription_connections": True,
                "failure_domains": True,
                "device_failure_domain_memberships": True,
                "network_link_failure_domain_memberships": True,
                "line_connection_failure_domain_memberships": True,
            },
            actual=collect_snapshot_reference_integrity(snapshot),
        ),
        build_check(
            name="active_line_port_integrity",
            expected={
                "active_lines": 240,
                "active_lines_with_valid_port": 240,
            },
            actual=collect_active_line_port_integrity(snapshot),
        ),
        build_check(
            name="active_subscription_connection_integrity",
            expected={
                "active_subscriptions": 240,
                "with_exactly_one_active_connection": 240,
                "with_invalid_active_connection_count": 0,
            },
            actual=collect_active_subscription_connection_integrity(snapshot),
        ),
        build_check(
            name="reserved_port_integrity",
            expected={
                "reserved_ports_with_active_lines": 0,
            },
            actual=collect_reserved_port_integrity(snapshot),
        ),
        build_check(
            name="gpon_fan_out_distribution",
            expected=collect_expected_gpon_fan_out_distribution(),
            actual=collect_actual_gpon_fan_out_distribution(snapshot),
        ),
        build_check(
            name="dslam_port_line_cardinality",
            expected={
                "active_dslam_ports_with_more_than_one_active_line": 0,
            },
            actual=collect_dslam_port_line_cardinality(snapshot),
        ),
        build_check(
            name="general_fiber_port_line_cardinality",
            expected={
                "active_general_fiber_ports_with_more_than_one_active_line": 0,
            },
            actual=collect_general_fiber_port_line_cardinality(snapshot),
        ),
        build_check(
            name="alarm_incident_reference_integrity",
            expected={
                "alarms": True,
                "incidents": True,
                "incident_alarms": True,
                "outages": True,
            },
            actual=collect_alarm_incident_reference_integrity(snapshot),
        ),
        build_check(
            name="outage_time_integrity",
            expected={
                "invalid_time_ranges": 0,
                "duration_mismatches": 0,
            },
            actual=collect_outage_time_integrity(snapshot),
        ),
        build_check(
            name="rule_version_overlap_integrity",
            expected={
                "overlapping_rule_version_pairs": 0,
            },
            actual=collect_rule_version_overlap_integrity(snapshot),
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


def collect_subscription_connection_role_distribution(snapshot: DataSnapshot) -> dict[str, int]:
    return normalize_counter(
        Counter(
            SubscriptionConnection.objects.filter(data_snapshot=snapshot, is_active=True)
            .values_list("connection_role", flat=True)
        )
    )


def collect_access_node_role_distribution(snapshot: DataSnapshot) -> dict[str, int]:
    return normalize_counter(
        Counter(
            NetworkDevice.objects.filter(
                data_snapshot=snapshot,
                device_type=NetworkDeviceType.ACCESS_NODE,
            ).values_list("access_role", flat=True)
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


def collect_network_link_topology(snapshot: DataSnapshot) -> dict[str, Any]:
    links = list(
        NetworkLink.objects.filter(data_snapshot=snapshot).values_list(
            "source_device__code",
            "target_device__code",
        )
    )
    graph: dict[str, set[str]] = {}
    for source_code, target_code in links:
        graph.setdefault(source_code, set()).add(target_code)
        graph.setdefault(target_code, set())
    return {
        "self_links": sum(1 for source_code, target_code in links if source_code == target_code),
        "has_cycle": has_directed_cycle(graph),
    }


def collect_snapshot_reference_integrity(snapshot: DataSnapshot) -> dict[str, bool]:
    return {
        "network_links": not NetworkLink.objects.filter(data_snapshot=snapshot)
        .exclude(source_device__data_snapshot=snapshot, target_device__data_snapshot=snapshot)
        .exists(),
        "network_ports": not NetworkPort.objects.filter(data_snapshot=snapshot)
        .exclude(device__data_snapshot=snapshot)
        .exists(),
        "access_segments": not AccessSegment.objects.filter(data_snapshot=snapshot)
        .exclude(serving_device__data_snapshot=snapshot)
        .exists(),
        "line_connections": not LineConnection.objects.filter(data_snapshot=snapshot)
        .exclude(port__data_snapshot=snapshot, access_segment__data_snapshot=snapshot)
        .exists(),
        "subscriptions": not Subscription.objects.filter(data_snapshot=snapshot)
        .exclude(customer__data_snapshot=snapshot, service_package__data_snapshot=snapshot)
        .exists(),
        "subscription_connections": not SubscriptionConnection.objects.filter(
            data_snapshot=snapshot
        )
        .exclude(subscription__data_snapshot=snapshot, line_connection__data_snapshot=snapshot)
        .exists(),
        "failure_domains": not FailureDomain.objects.filter(data_snapshot=snapshot)
        .exclude(data_snapshot=snapshot)
        .exists(),
        "device_failure_domain_memberships": not DeviceFailureDomainMembership.objects.filter(
            data_snapshot=snapshot
        )
        .exclude(device__data_snapshot=snapshot, failure_domain__data_snapshot=snapshot)
        .exists(),
        "network_link_failure_domain_memberships": not (
            NetworkLinkFailureDomainMembership.objects.filter(data_snapshot=snapshot)
            .exclude(network_link__data_snapshot=snapshot, failure_domain__data_snapshot=snapshot)
            .exists()
        ),
        "line_connection_failure_domain_memberships": not (
            LineConnectionFailureDomainMembership.objects.filter(data_snapshot=snapshot)
            .exclude(
                line_connection__data_snapshot=snapshot,
                failure_domain__data_snapshot=snapshot,
            )
            .exists()
        ),
    }


def collect_active_line_port_integrity(snapshot: DataSnapshot) -> dict[str, int]:
    active_lines = LineConnection.objects.filter(data_snapshot=snapshot, is_active=True)
    return {
        "active_lines": active_lines.count(),
        "active_lines_with_valid_port": active_lines.filter(
            port__data_snapshot=snapshot,
        ).count(),
    }


def collect_active_subscription_connection_integrity(snapshot: DataSnapshot) -> dict[str, int]:
    active_subscriptions = Subscription.objects.filter(data_snapshot=snapshot, is_active=True)
    annotated = active_subscriptions.annotate(
        active_connection_count=Count(
            "connections",
            filter=Q(connections__is_active=True, connections__data_snapshot=snapshot),
        )
    )
    return {
        "active_subscriptions": active_subscriptions.count(),
        "with_exactly_one_active_connection": annotated.filter(
            active_connection_count=1
        ).count(),
        "with_invalid_active_connection_count": annotated.exclude(
            active_connection_count=1
        ).count(),
    }


def collect_reserved_port_integrity(snapshot: DataSnapshot) -> dict[str, int]:
    return {
        "reserved_ports_with_active_lines": NetworkPort.objects.filter(
            data_snapshot=snapshot,
            inventory_status=NetworkPortStatus.RESERVED,
            line_connections__is_active=True,
        )
        .distinct()
        .count(),
    }


def collect_expected_gpon_fan_out_distribution() -> dict[str, Any]:
    expected_counts = sorted(
        count
        for fan_out_counts in seed_config.GPON_FAN_OUT_BY_NEIGHBORHOOD.values()
        for count in fan_out_counts
    )
    return {
        "active_pon_ports": seed_config.PORT_CAPACITY_PLAN["gpon"][
            "active_physical_pon_ports"
        ],
        "reserved_pon_ports": seed_config.PORT_CAPACITY_PLAN["gpon"][
            "reserved_physical_pon_ports"
        ],
        "fan_out_counts": expected_counts,
    }


def collect_actual_gpon_fan_out_distribution(snapshot: DataSnapshot) -> dict[str, Any]:
    active_ports = NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.ACTIVE,
        metadata__seed_role="gpon_pon_port",
    ).annotate(
        active_line_count=Count(
            "line_connections",
            filter=Q(line_connections__is_active=True),
        )
    )
    reserved_ports = NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.RESERVED,
        metadata__seed_role="reserved_gpon_pon_port",
    )
    return {
        "active_pon_ports": active_ports.count(),
        "reserved_pon_ports": reserved_ports.count(),
        "fan_out_counts": sorted(port.active_line_count for port in active_ports),
    }


def collect_dslam_port_line_cardinality(snapshot: DataSnapshot) -> dict[str, int]:
    return {
        "active_dslam_ports_with_more_than_one_active_line": NetworkPort.objects.filter(
            data_snapshot=snapshot,
            inventory_status=NetworkPortStatus.ACTIVE,
            device__device_type=NetworkDeviceType.DSLAM,
        )
        .annotate(
            active_line_count=Count(
                "line_connections",
                filter=Q(line_connections__is_active=True),
            )
        )
        .filter(active_line_count__gt=1)
        .count(),
    }


def collect_general_fiber_port_line_cardinality(snapshot: DataSnapshot) -> dict[str, int]:
    return {
        "active_general_fiber_ports_with_more_than_one_active_line": NetworkPort.objects.filter(
            data_snapshot=snapshot,
            inventory_status=NetworkPortStatus.ACTIVE,
            metadata__seed_role="general_fiber_customer_port",
        )
        .annotate(
            active_line_count=Count(
                "line_connections",
                filter=Q(line_connections__is_active=True),
            )
        )
        .filter(active_line_count__gt=1)
        .count(),
    }


def collect_alarm_incident_reference_integrity(snapshot: DataSnapshot) -> dict[str, bool]:
    return {
        "alarms": not Alarm.objects.filter(data_snapshot=snapshot)
        .exclude(alarm_type__data_snapshot=snapshot, device__data_snapshot=snapshot)
        .exists(),
        "incidents": not Incident.objects.filter(data_snapshot=snapshot)
        .exclude(primary_device__data_snapshot=snapshot)
        .exists(),
        "incident_alarms": not IncidentAlarm.objects.filter(data_snapshot=snapshot)
        .exclude(incident__data_snapshot=snapshot, alarm__data_snapshot=snapshot)
        .exists(),
        "outages": not Outage.objects.filter(data_snapshot=snapshot)
        .filter(
            ~Q(source_device__data_snapshot=snapshot)
            | (Q(incident__isnull=False) & ~Q(incident__data_snapshot=snapshot))
        )
        .exists(),
    }


def collect_outage_time_integrity(snapshot: DataSnapshot) -> dict[str, int]:
    invalid_time_ranges = 0
    duration_mismatches = 0
    for outage in Outage.objects.filter(data_snapshot=snapshot):
        if outage.detected_at < outage.started_at:
            invalid_time_ranges += 1
        if outage.ended_at is None or outage.ended_at <= outage.started_at:
            invalid_time_ranges += 1
            continue
        if outage.resolved_at and outage.resolved_at < outage.started_at:
            invalid_time_ranges += 1
        expected_duration_minutes = outage.metadata.get("duration_minutes")
        if expected_duration_minutes is not None:
            actual_duration_minutes = int(
                (outage.ended_at - outage.started_at).total_seconds() // 60
            )
            if actual_duration_minutes != expected_duration_minutes:
                duration_mismatches += 1
    return {
        "invalid_time_ranges": invalid_time_ranges,
        "duration_mismatches": duration_mismatches,
    }


def collect_rule_version_overlap_integrity(snapshot: DataSnapshot) -> dict[str, int]:
    overlap_count = 0
    for rule in Rule.objects.filter(data_snapshot=snapshot):
        versions = list(rule.versions.order_by("valid_from", "version"))
        for index, version in enumerate(versions):
            for other in versions[index + 1 :]:
                if rule_versions_overlap(version, other):
                    overlap_count += 1
    return {"overlapping_rule_version_pairs": overlap_count}


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


def has_directed_cycle(graph: dict[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for neighbor in graph[node]:
            if visit(neighbor):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def rule_versions_overlap(first: RuleVersion, second: RuleVersion) -> bool:
    first_end = first.valid_to
    second_end = second.valid_to
    first_starts_before_second_end = second_end is None or first.valid_from < second_end
    second_starts_before_first_end = first_end is None or second.valid_from < first_end
    return first_starts_before_second_end and second_starts_before_first_end


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
