from __future__ import annotations

from collections import Counter
from typing import Any

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
from apps.datasets.models import DataSnapshot
from apps.geography.models import City, District
from apps.network.models import LineConnection, NetworkDevice, NetworkLink, NetworkPort
from apps.network.services.path_diversity import PathDiversityService
from apps.operations.models import (
    Alarm,
    AlarmType,
    Incident,
    MaintenanceWindow,
    OperationalEvent,
    Outage,
    QualityMeasurement,
)
from apps.rules.models import Rule, RuleSet, RuleVersion
from data_generator.configs import multi_city_realism_v1 as config
from data_generator.configs import realistic_commercial_profile_v1 as commercial_config


def validate_multicity_realism_snapshot(snapshot: DataSnapshot) -> dict[str, Any]:
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
        check("alarm_types", 30, row_counts["alarm_types"]),
        check("alarms", 2100, row_counts["alarms"]),
        check("incidents", 210, row_counts["incidents"]),
        check("outages", 78, row_counts["outages"]),
        check("maintenance_windows", 30, row_counts["maintenance_windows"]),
        check("operational_events", 900, row_counts["operational_events"]),
        check("quality_measurements", 12000, row_counts["quality_measurements"]),
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
        check(
            "alarm_statuses",
            config.TIMELINE_TARGETS["alarm_statuses"],
            collect_alarm_statuses(snapshot),
        ),
        check("alarm_type_coverage", 30, collect_used_alarm_type_count(snapshot)),
        check("scenario_coverage", 22, collect_scenario_coverage(snapshot)),
        check("active_snapshot_is_maltepe", True, collect_active_snapshot_is_maltepe(snapshot)),
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


def collect_active_snapshot_is_maltepe(snapshot: DataSnapshot) -> bool:
    active = DataSnapshot.objects.filter(is_active=True).select_related("dataset_version").first()
    return bool(active and active.dataset_version.slug.startswith("maltepe-mvp"))


def collect_path_diversity(snapshot: DataSnapshot) -> dict[str, int]:
    counts = Counter(
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            connection_role=SubscriptionConnectionRole.BACKUP,
        ).values_list("metadata__target_diversity", flat=True)
    )
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
