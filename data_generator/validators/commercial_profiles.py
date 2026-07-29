from decimal import Decimal
from typing import Any

from data_generator.configs import realistic_commercial_profile_v1 as config


def validate_realistic_commercial_profile_config() -> dict[str, Any]:
    checks = [
        build_check(
            "customer_scale",
            {"customers": 14400, "subscriptions": 16200},
            {
                "customers": config.DATASET_SCALE["customers"],
                "subscriptions": config.DATASET_SCALE["subscriptions"],
            },
        ),
        build_check(
            "segment_totals",
            config.DATASET_SCALE["segments"],
            sum_district_mapping("segments"),
        ),
        build_check(
            "priority_totals",
            config.DATASET_SCALE["priority_levels"],
            sum_district_mapping("priority"),
        ),
        build_check(
            "subscription_status_totals",
            config.DATASET_SCALE["subscription_statuses"],
            sum_district_mapping("subscription_statuses"),
        ),
        build_check(
            "subscription_count_totals",
            {"single": 12830, "double": 1340, "triple": 230},
            sum_district_mapping("subscription_counts"),
        ),
        build_check(
            "package_count",
            27,
            len(config.PACKAGE_CATALOG),
        ),
        build_check(
            "package_subscription_total",
            16200,
            sum(item["subscription_count"] for item in config.PACKAGE_CATALOG),
        ),
        build_check(
            "service_type_package_counts",
            {"broadband": 22, "metro_ethernet": 5},
            count_by(config.PACKAGE_CATALOG, "service_type"),
        ),
        build_check(
            "sla_profile_count",
            5,
            len(config.SLA_PROFILES),
        ),
        build_check(
            "campaign_count",
            10,
            len(config.CAMPAIGNS),
        ),
        build_check(
            "backup_distribution",
            {
                "backup_records": 208,
                "unused_backup_port_capacity": 53,
                "reserved_backup_port_capacity": 261,
            },
            {
                "backup_records": sum(config.BACKUP_DISTRIBUTION["by_district"].values()),
                "unused_backup_port_capacity": config.BACKUP_DISTRIBUTION[
                    "unused_backup_port_capacity"
                ],
                "reserved_backup_port_capacity": config.BACKUP_DISTRIBUTION[
                    "reserved_backup_port_capacity"
                ],
            },
        ),
        build_check(
            "backup_segment_distribution",
            208,
            sum(config.BACKUP_DISTRIBUTION["by_segment"].values()),
        ),
        build_check(
            "backup_path_diversity_distribution",
            208,
            sum(config.BACKUP_DISTRIBUTION["actual_path_diversity"].values()),
        ),
        build_check(
            "payment_record_count",
            59600,
            sum(config.PAYMENT_HISTORY["statuses"].values()),
        ),
        build_check(
            "campaign_enrollment_count",
            4050,
            sum(config.CAMPAIGN_ENROLLMENT_TARGETS["statuses"].values()),
        ),
        build_check(
            "compensation_history_decision_count",
            1100,
            sum(config.COMPENSATION_HISTORY_TARGETS["decision_statuses"].values()),
        ),
        build_check(
            "compensation_history_settlement_count",
            620,
            sum(config.COMPENSATION_HISTORY_TARGETS["approved_settlement_statuses"].values()),
        ),
        build_check(
            "price_version_target",
            72,
            config.PRICE_VERSION_TARGETS["service_package_price_versions"],
        ),
        build_check(
            "metro_ethernet_package_rules",
            True,
            all(
                item["service_type"] != "metro_ethernet"
                or (
                    item["technology"] == "fiber"
                    and item["symmetric"] is True
                    and item["backup_eligible"] is True
                    and "individual" not in item["allowed_segments"]
                )
                for item in config.PACKAGE_CATALOG
            ),
        ),
        build_check(
            "package_price_values_are_positive",
            True,
            all(Decimal(item["list_price"]) >= Decimal("0.00") for item in config.PACKAGE_CATALOG),
        ),
    ]
    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }


def sum_district_mapping(key: str) -> dict[str, int]:
    totals: dict[str, int] = {}
    for district_config in config.DISTRICT_COMMERCIAL_DISTRIBUTION.values():
        for item_key, value in district_config[key].items():
            totals[item_key] = totals.get(item_key, 0) + value
    return totals


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    totals: dict[str, int] = {}
    for row in rows:
        totals[row[key]] = totals.get(row[key], 0) + 1
    return totals


def build_check(name: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "passed": expected == actual,
    }
