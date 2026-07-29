from data_generator.configs import realistic_commercial_profile_v1 as config
from data_generator.validators.commercial_profiles import (
    validate_realistic_commercial_profile_config,
)


def test_realistic_commercial_profile_config_totals_are_consistent():
    result = validate_realistic_commercial_profile_config()

    assert result["passed"] is True
    assert {check["name"] for check in result["checks"]} >= {
        "customer_scale",
        "segment_totals",
        "priority_totals",
        "subscription_status_totals",
        "package_count",
        "backup_distribution",
        "payment_record_count",
        "campaign_enrollment_count",
        "compensation_history_decision_count",
    }


def test_realistic_commercial_profile_has_exact_package_sla_and_campaign_counts():
    assert len(config.PACKAGE_CATALOG) == 27
    assert len(config.SLA_PROFILES) == 5
    assert len(config.CAMPAIGNS) == 10
    assert sum(item["subscription_count"] for item in config.PACKAGE_CATALOG) == 16200
    assert sum(config.BACKUP_DISTRIBUTION["by_district"].values()) == 208
    assert config.BACKUP_DISTRIBUTION["unused_backup_port_capacity"] == 53


def test_metro_ethernet_packages_are_fiber_non_individual_and_backup_eligible():
    metro_packages = [
        package for package in config.PACKAGE_CATALOG if package["service_type"] == "metro_ethernet"
    ]

    assert len(metro_packages) == 5
    assert all(package["technology"] == "fiber" for package in metro_packages)
    assert all(package["symmetric"] is True for package in metro_packages)
    assert all(package["backup_eligible"] is True for package in metro_packages)
    assert all("individual" not in package["allowed_segments"] for package in metro_packages)


def test_sla_required_backup_profiles_have_diversity_targets():
    required_profiles = [
        profile for profile in config.SLA_PROFILES if profile["backup_requirement"] == "required"
    ]

    assert {profile["code"] for profile in required_profiles} == {
        "mission_critical",
        "public_critical",
    }
    assert all(
        profile["required_path_diversity"] == "fully_diverse" for profile in required_profiles
    )
