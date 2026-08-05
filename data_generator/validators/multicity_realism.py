from __future__ import annotations

from collections import Counter
from typing import Any

from django.db import models
from django.db.models import Count

from apps.core.choices import ResultStatus
from apps.customers.models import (
    Campaign,
    CampaignEnrollment,
    CompensationHistory,
    Customer,
    CustomerSegment,
    PaymentRecord,
    ServicePackage,
    ServicePackagePriceVersion,
    SLAProfile,
    Subscription,
    SubscriptionConnection,
    SubscriptionConnectionRole,
    SubscriptionStatus,
)
from apps.datasets.models import DatasetSnapshotStatus, DataSnapshot, GroundTruthCase
from apps.geography.models import City, District
from apps.network.models import (
    LineConnection,
    NetworkDevice,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
    NetworkPortStatus,
)
from apps.network.services.path_diversity import PathDiversityService
from apps.operations.models import (
    Alarm,
    AlarmType,
    CausalEvent,
    Incident,
    MaintenanceWindow,
    OperationalEvent,
    Outage,
    QualityMeasurement,
    ServiceImpactClass,
    SessionEvent,
)
from apps.rules.models import Rule, RuleSet, RuleVersion
from data_generator.configs import multi_city_realism_v1 as config
from data_generator.configs import realistic_commercial_profile_v1 as commercial_config


def validate_multicity_realism_snapshot(
    snapshot: DataSnapshot,
    *,
    include_final_gate: bool = True,
) -> dict[str, Any]:
    row_counts = collect_row_counts(snapshot)
    checks = [
        check(
            "cities",
            config.EXPECTED_TOTALS["cities"],
            City.objects.filter(name__in=config.CITY_PROFILES).count(),
        ),
        check(
            "districts",
            config.EXPECTED_TOTALS["districts"],
            District.objects.filter(name__in=config.DISTRICT_TECHNOLOGY_DISTRIBUTION).count(),
        ),
        check(
            "neighborhoods",
            config.EXPECTED_TOTALS["neighborhoods"],
            collect_config_neighborhood_count(),
        ),
        check("customers", 14400, row_counts["customers"]),
        check("subscriptions", 16200, row_counts["subscriptions"]),
        check("network_devices", 235, row_counts["network_devices"]),
        check("network_links", 245, row_counts["network_links"]),
        check("service_packages", 27, row_counts["service_packages"]),
        check("sla_profiles", 5, row_counts["sla_profiles"]),
        check("campaigns", 10, row_counts["campaigns"]),
        check("service_package_price_versions", 72, row_counts["service_package_price_versions"]),
        check("payment_records", 59600, row_counts["payment_records"]),
        check("campaign_enrollments", 4050, row_counts["campaign_enrollments"]),
        check("compensation_history", 1100, row_counts["compensation_history"]),
        check("rule_sets", 1, row_counts["rule_sets"]),
        check("rules", 25, row_counts["rules"]),
        check("rule_versions", 25, row_counts["rule_versions"]),
        check("alarm_types", 31, row_counts["alarm_types"]),
        check_at_least("causal_events", 1, row_counts["causal_events"]),
        check_at_least("alarms", row_counts["causal_events"], row_counts["alarms"]),
        check_at_least("incidents", 1, row_counts["incidents"]),
        check_at_least(
            "operational_events",
            row_counts["causal_events"],
            row_counts["operational_events"],
        ),
        check_at_least(
            "quality_measurements",
            row_counts["causal_events"] * 38,
            row_counts["quality_measurements"],
        ),
        check_at_least("session_events", row_counts["causal_events"], row_counts["session_events"]),
        check("snapshot_is_passive", False, snapshot.is_active),
        check("active_snapshot_is_maltepe", True, collect_active_snapshot_is_maltepe(snapshot)),
        check("topology_bng_only_to_aggregation", 0, collect_bad_bng_direct_access_links(snapshot)),
        check(
            "topology_access_devices_have_aggregation_parent",
            0,
            collect_access_devices_without_aggregation_parent(snapshot),
        ),
        check(
            "service_port_capacity_totals",
            {
                "pon_total": 512,
                "pon_active": 322,
                "dsl_total": 9120,
                "dsl_active": 6581,
                "dedicated_fiber_total": 4032,
                "reserved_backup_capacity": 261,
            },
            collect_service_port_capacity_totals(snapshot),
        ),
        check("reserved_ports_without_lines", 0, collect_reserved_port_line_count(snapshot)),
        check("dsl_ports_over_capacity", 0, collect_non_gpon_ports_over_capacity(snapshot, "xdsl")),
        check(
            "dedicated_fiber_ports_over_capacity",
            0,
            collect_non_gpon_ports_over_capacity(snapshot, "dedicated_fiber"),
        ),
        check(
            "customer_segments",
            commercial_config.DATASET_SCALE["segments"],
            collect_customer_segments(snapshot),
        ),
        check(
            "customer_priorities",
            commercial_config.DATASET_SCALE["priority_levels"],
            collect_customer_priorities(snapshot),
        ),
        check(
            "subscription_statuses",
            commercial_config.DATASET_SCALE["subscription_statuses"],
            collect_subscription_statuses(snapshot),
        ),
        check(
            "subscription_connection_roles",
            {"primary": 16027, "backup": 208},
            collect_connection_roles(snapshot),
        ),
        check("pending_without_connections", 173, collect_pending_without_connections(snapshot)),
        check("cancelled_connections_closed", 0, collect_bad_cancelled_connections(snapshot)),
        check(
            "technology_totals",
            {"gpon": 7577, "fiber": 2042, "vdsl": 5894, "adsl": 687},
            collect_subscription_access_technologies(snapshot),
        ),
        check("metro_ethernet_subset", 520, collect_metro_ethernet_count(snapshot)),
        check("individual_metro_ethernet", 0, collect_individual_metro_count(snapshot)),
        check_at_least("alarm_type_coverage", 1, collect_used_alarm_type_count(snapshot)),
        check_at_least("scenario_coverage", 7, collect_scenario_coverage(snapshot)),
        check("causal_alarm_links", 0, collect_alarms_without_causal_event(snapshot)),
        check(
            "incident_alarm_causal_mismatches",
            0,
            collect_incident_alarm_causal_mismatches(snapshot),
        ),
        check("degradation_incident_outages", 0, collect_non_outage_incident_outages(snapshot)),
        check("noise_alarm_incidents", 0, collect_noise_incident_count(snapshot)),
        check("duplicate_final_compensation", 0, collect_duplicate_final_compensation(snapshot)),
        check("cross_snapshot_fk_errors", 0, collect_cross_snapshot_fk_errors(snapshot)),
    ]
    checks.append(
        check(
            "path_diversity_distribution",
            commercial_config.BACKUP_DISTRIBUTION["actual_path_diversity"],
            collect_path_diversity(snapshot),
        )
    )
    checks.append(
        check("path_diversity_service_errors", 0, collect_path_diversity_service_errors(snapshot))
    )
    if include_final_gate:
        checks.extend(
            [
                check("ground_truth_cases", 30, row_counts["ground_truth_cases"]),
                check("snapshot_status", DatasetSnapshotStatus.VALIDATED, snapshot.status),
                check(
                    "snapshot_validation_status",
                    ResultStatus.EXACT,
                    snapshot.validation_status,
                ),
            ]
        )
    return {
        "passed": all(item["passed"] for item in checks),
        "row_counts": row_counts,
        "checks": checks,
    }


def collect_row_counts(snapshot: DataSnapshot) -> dict[str, int]:
    return {
        "customers": Customer.objects.filter(data_snapshot=snapshot).count(),
        "subscriptions": Subscription.objects.filter(data_snapshot=snapshot).count(),
        "subscription_connections": SubscriptionConnection.objects.filter(
            data_snapshot=snapshot
        ).count(),
        "network_devices": NetworkDevice.objects.filter(data_snapshot=snapshot).count(),
        "network_links": NetworkLink.objects.filter(data_snapshot=snapshot).count(),
        "network_ports": NetworkPort.objects.filter(data_snapshot=snapshot).count(),
        "line_connections": LineConnection.objects.filter(data_snapshot=snapshot).count(),
        "service_packages": ServicePackage.objects.filter(data_snapshot=snapshot).count(),
        "sla_profiles": SLAProfile.objects.filter(data_snapshot=snapshot).count(),
        "campaigns": Campaign.objects.filter(data_snapshot=snapshot).count(),
        "service_package_price_versions": ServicePackagePriceVersion.objects.filter(
            data_snapshot=snapshot
        ).count(),
        "payment_records": PaymentRecord.objects.filter(data_snapshot=snapshot).count(),
        "campaign_enrollments": CampaignEnrollment.objects.filter(data_snapshot=snapshot).count(),
        "compensation_history": CompensationHistory.objects.filter(data_snapshot=snapshot).count(),
        "rule_sets": RuleSet.objects.filter(data_snapshot=snapshot).count(),
        "rules": Rule.objects.filter(data_snapshot=snapshot).count(),
        "rule_versions": RuleVersion.objects.filter(data_snapshot=snapshot).count(),
        "alarm_types": AlarmType.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "incidents": Incident.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "maintenance_windows": MaintenanceWindow.objects.filter(data_snapshot=snapshot).count(),
        "operational_events": OperationalEvent.objects.filter(data_snapshot=snapshot).count(),
        "quality_measurements": QualityMeasurement.objects.filter(data_snapshot=snapshot).count(),
        "causal_events": CausalEvent.objects.filter(data_snapshot=snapshot).count(),
        "session_events": SessionEvent.objects.filter(data_snapshot=snapshot).count(),
        "ground_truth_cases": GroundTruthCase.objects.filter(data_snapshot=snapshot).count(),
    }


def collect_config_neighborhood_count() -> int:
    return sum(
        len(names)
        for city_config in config.CITY_PROFILES.values()
        for names in city_config["districts"].values()
    )


def collect_customer_segments(snapshot: DataSnapshot) -> dict[str, int]:
    return normalize_counter(
        Customer.objects.filter(data_snapshot=snapshot).values_list("segment", flat=True)
    )


def collect_customer_priorities(snapshot: DataSnapshot) -> dict[str, int]:
    return normalize_counter(
        Customer.objects.filter(data_snapshot=snapshot).values_list("priority_level", flat=True)
    )


def collect_subscription_statuses(snapshot: DataSnapshot) -> dict[str, int]:
    return normalize_counter(
        Subscription.objects.filter(data_snapshot=snapshot).values_list("status", flat=True)
    )


def collect_connection_roles(snapshot: DataSnapshot) -> dict[str, int]:
    return normalize_counter(
        SubscriptionConnection.objects.filter(data_snapshot=snapshot).values_list(
            "connection_role", flat=True
        )
    )


def collect_pending_without_connections(snapshot: DataSnapshot) -> int:
    return Subscription.objects.filter(
        data_snapshot=snapshot,
        status=SubscriptionStatus.PENDING,
        connections__isnull=True,
    ).count()


def collect_bad_cancelled_connections(snapshot: DataSnapshot) -> int:
    return (
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            subscription__status=SubscriptionStatus.CANCELLED,
            is_active=True,
        ).count()
        + SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            subscription__status=SubscriptionStatus.CANCELLED,
            valid_to__isnull=True,
        ).count()
    )


def collect_subscription_access_technologies(snapshot: DataSnapshot) -> dict[str, int]:
    return normalize_counter(
        Subscription.objects.filter(data_snapshot=snapshot).values_list(
            "metadata__access_technology",
            flat=True,
        )
    )


def collect_metro_ethernet_count(snapshot: DataSnapshot) -> int:
    return Subscription.objects.filter(
        data_snapshot=snapshot,
        service_package__service_type="metro_ethernet",
    ).count()


def collect_individual_metro_count(snapshot: DataSnapshot) -> int:
    return Subscription.objects.filter(
        data_snapshot=snapshot,
        customer__segment=CustomerSegment.INDIVIDUAL,
        service_package__service_type="metro_ethernet",
    ).count()


def collect_alarm_statuses(snapshot: DataSnapshot) -> dict[str, int]:
    return normalize_counter(
        Alarm.objects.filter(data_snapshot=snapshot).values_list("status", flat=True)
    )


def collect_used_alarm_type_count(snapshot: DataSnapshot) -> int:
    return Alarm.objects.filter(data_snapshot=snapshot).values("alarm_type_id").distinct().count()


def collect_scenario_coverage(snapshot: DataSnapshot) -> int:
    scenarios = set(
        Incident.objects.filter(data_snapshot=snapshot).values_list(
            "metadata__scenario_code",
            flat=True,
        )
    )
    scenarios.update(
        Alarm.objects.filter(data_snapshot=snapshot).values_list(
            "metadata__scenario_code", flat=True
        )
    )
    return len({item for item in scenarios if item})


def collect_alarms_without_causal_event(snapshot: DataSnapshot) -> int:
    return Alarm.objects.filter(data_snapshot=snapshot, causal_event__isnull=True).count()


def collect_incident_alarm_causal_mismatches(snapshot: DataSnapshot) -> int:
    return (
        Incident.objects.filter(data_snapshot=snapshot, incident_alarms__isnull=False)
        .exclude(incident_alarms__alarm__causal_event=models.F("causal_event"))
        .count()
    )


def collect_active_snapshot_is_maltepe(snapshot: DataSnapshot) -> bool:
    active = DataSnapshot.objects.filter(is_active=True).select_related("dataset_version").first()
    return bool(active and active.dataset_version.slug.startswith("maltepe-mvp"))


def collect_bad_bng_direct_access_links(snapshot: DataSnapshot) -> int:
    return (
        NetworkLink.objects.filter(
            data_snapshot=snapshot,
            source_device__device_type=NetworkDeviceType.BNG,
        )
        .exclude(target_device__device_type=NetworkDeviceType.METRO_AGGREGATION)
        .count()
    )


def collect_access_devices_without_aggregation_parent(snapshot: DataSnapshot) -> int:
    return (
        NetworkDevice.objects.filter(
            data_snapshot=snapshot,
            device_type__in=[
                NetworkDeviceType.OLT,
                NetworkDeviceType.DSLAM,
                NetworkDeviceType.ACCESS_NODE,
            ],
        )
        .exclude(
            incoming_links__data_snapshot=snapshot,
            incoming_links__source_device__device_type=NetworkDeviceType.METRO_AGGREGATION,
        )
        .count()
    )


def collect_service_port_capacity_totals(snapshot: DataSnapshot) -> dict[str, int]:
    ports = NetworkPort.objects.filter(data_snapshot=snapshot)
    return {
        "pon_total": ports.filter(metadata__service_port_role="gpon_pon").count(),
        "pon_active": ports.filter(
            metadata__service_port_role="gpon_pon",
            inventory_status=NetworkPortStatus.ACTIVE,
        ).count(),
        "dsl_total": ports.filter(metadata__service_port_role="xdsl").count(),
        "dsl_active": ports.filter(
            metadata__service_port_role="xdsl",
            inventory_status=NetworkPortStatus.ACTIVE,
        ).count(),
        "dedicated_fiber_total": ports.filter(
            metadata__service_port_role="dedicated_fiber"
        ).count(),
        "reserved_backup_capacity": ports.filter(
            metadata__service_port_role="dedicated_fiber",
            metadata__reserved_backup_capacity=True,
        ).count(),
    }


def collect_reserved_port_line_count(snapshot: DataSnapshot) -> int:
    return LineConnection.objects.filter(
        data_snapshot=snapshot,
        port__inventory_status=NetworkPortStatus.RESERVED,
    ).count()


def collect_non_gpon_ports_over_capacity(snapshot: DataSnapshot, service_port_role: str) -> int:
    return (
        NetworkPort.objects.filter(
            data_snapshot=snapshot,
            metadata__service_port_role=service_port_role,
        )
        .annotate(line_count=Count("line_connections"))
        .filter(line_count__gt=1)
        .count()
    )


def collect_non_outage_incident_outages(snapshot: DataSnapshot) -> int:
    return Incident.objects.filter(
        data_snapshot=snapshot,
        service_impact_class__in=[
            ServiceImpactClass.DEGRADATION,
            ServiceImpactClass.PROTECTION_LOSS,
        ],
        outages__isnull=False,
    ).count()


def collect_noise_incident_count(snapshot: DataSnapshot) -> int:
    return Incident.objects.filter(
        data_snapshot=snapshot,
        metadata__scenario_code="SCN-NOISE-001",
    ).count()


def collect_duplicate_final_compensation(snapshot: DataSnapshot) -> int:
    duplicates = (
        CompensationHistory.objects.filter(
            data_snapshot=snapshot,
            incident__isnull=False,
            compensation_conflict_group__gt="",
            decision_status__in=["approved", "rejected"],
        )
        .values("subscription_id", "incident_id", "compensation_conflict_group")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    return duplicates.count()


def collect_cross_snapshot_fk_errors(snapshot: DataSnapshot) -> int:
    return sum(
        [
            NetworkLink.objects.filter(data_snapshot=snapshot)
            .exclude(source_device__data_snapshot=snapshot, target_device__data_snapshot=snapshot)
            .count(),
            NetworkPort.objects.filter(data_snapshot=snapshot)
            .exclude(device__data_snapshot=snapshot)
            .count(),
            LineConnection.objects.filter(data_snapshot=snapshot)
            .exclude(port__data_snapshot=snapshot, access_segment__data_snapshot=snapshot)
            .count(),
            Subscription.objects.filter(data_snapshot=snapshot)
            .exclude(
                customer__data_snapshot=snapshot,
                service_package__data_snapshot=snapshot,
            )
            .count(),
            SubscriptionConnection.objects.filter(data_snapshot=snapshot)
            .exclude(subscription__data_snapshot=snapshot, line_connection__data_snapshot=snapshot)
            .count(),
            Alarm.objects.filter(data_snapshot=snapshot)
            .exclude(alarm_type__data_snapshot=snapshot)
            .count(),
            Outage.objects.filter(data_snapshot=snapshot)
            .exclude(source_device__data_snapshot=snapshot, incident__data_snapshot=snapshot)
            .count(),
        ]
    )


def collect_path_diversity(snapshot: DataSnapshot) -> dict[str, int]:
    service = PathDiversityService()
    counts: Counter[str] = Counter()
    for backup in (
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            connection_role=SubscriptionConnectionRole.BACKUP,
        )
        .select_related("subscription", "line_connection")
        .order_by("subscription__subscription_number")
    ):
        primary = SubscriptionConnection.objects.get(
            data_snapshot=snapshot,
            subscription=backup.subscription,
            connection_role=SubscriptionConnectionRole.PRIMARY,
        )
        result = service.evaluate(
            primary_line=primary.line_connection,
            backup_line=backup.line_connection,
            snapshot=snapshot,
        )
        counts[result.classification] += 1
    return {
        key: counts.get(key, 0)
        for key in commercial_config.BACKUP_DISTRIBUTION["actual_path_diversity"]
    }


def collect_path_diversity_service_errors(snapshot: DataSnapshot) -> int:
    service = PathDiversityService()
    errors = 0
    backup_connections = (
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            connection_role=SubscriptionConnectionRole.BACKUP,
        )
        .select_related("subscription", "line_connection")
        .order_by("subscription__subscription_number")
    )
    for backup in backup_connections:
        primary = SubscriptionConnection.objects.get(
            data_snapshot=snapshot,
            subscription=backup.subscription,
            connection_role=SubscriptionConnectionRole.PRIMARY,
        )
        try:
            service.evaluate(
                primary_line=primary.line_connection,
                backup_line=backup.line_connection,
                snapshot=snapshot,
            )
        except Exception:
            errors += 1
    return errors


def normalize_counter(values) -> dict[str, int]:
    return dict(Counter(values))


def check(name: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "passed": expected == actual,
    }


def check_at_least(name: str, minimum: int, actual: int) -> dict[str, Any]:
    return {
        "name": name,
        "expected": {"minimum": minimum},
        "actual": actual,
        "passed": actual >= minimum,
    }
