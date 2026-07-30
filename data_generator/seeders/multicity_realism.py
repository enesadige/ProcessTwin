from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import cycle
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.compensation.models import (
    CompensationEvaluation,
    CompensationEvaluationStatus,
    CompensationResultType,
    DecisionEvidence,
    DecisionEvidenceDecision,
)
from apps.customers.models import (
    Campaign,
    CampaignAllowedSegment,
    CampaignAllowedServiceType,
    CampaignAllowedTechnology,
    CampaignEnrollment,
    CompensationDecisionStatus,
    CompensationHistory,
    CompensationSettlementStatus,
    Customer,
    CustomerSegment,
    CustomerStatus,
    PaymentRecord,
    PaymentStatus,
    ServicePackage,
    ServicePackageAllowedSegment,
    ServicePackagePriceVersion,
    ServiceType,
    SLAProfile,
    Subscription,
    SubscriptionConnection,
    SubscriptionConnectionRole,
    SubscriptionStatus,
    SuspensionReason,
)
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.geography.models import AreaProfileType, City, District, Neighborhood
from apps.network.models import (
    AccessSegment,
    AccessTechnology,
    DeviceFailureDomainMembership,
    FailureDomain,
    FailureDomainType,
    LineConnection,
    LineConnectionFailureDomainMembership,
    LineConnectionStatus,
    NetworkDevice,
    NetworkDeviceAccessRole,
    NetworkDeviceType,
    NetworkLink,
    NetworkLinkFailureDomainMembership,
    NetworkLinkStatus,
    NetworkPort,
    NetworkPortStatus,
    NetworkPortType,
)
from apps.operations.models import (
    Alarm,
    AlarmStatus,
    AlarmType,
    AlarmTypeAllowedSourceKind,
    AlarmTypeSupportedDeviceType,
    FailoverResult,
    Incident,
    IncidentAlarm,
    IncidentAlarmRole,
    IncidentStatus,
    IncidentType,
    MaintenanceWindow,
    MaintenanceWindowDevice,
    MaintenanceWindowNetworkLink,
    MaintenanceWindowStatus,
    OperationalEvent,
    OperationalEventType,
    Outage,
    OutageStatus,
    OutageType,
    QualityMeasurement,
    QualityMetricType,
    RootCauseCategory,
    ServiceImpactClass,
    Severity,
)
from apps.rules.models import Rule, RuleSet, RuleStatus, RuleType, RuleVersion, RuleVersionStatus
from data_generator.configs import multi_city_realism_v1 as config
from data_generator.configs import realistic_alarm_catalog_v1 as alarm_config
from data_generator.configs import realistic_commercial_profile_v1 as commercial_config
from data_generator.configs import synthetic_compensation_policy_v1 as policy_config

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
REFERENCE_DATETIME = parse_datetime(config.DEFAULT_REFERENCE_DATETIME)
VALID_FROM = parse_datetime("2026-03-01T00:00:00+03:00")
CANCELLED_AT = parse_datetime("2026-07-20T00:00:00+03:00")


@dataclass(frozen=True)
class SeedContext:
    snapshot: DataSnapshot
    reference_datetime: datetime
    cities: dict[str, City]
    districts: dict[str, District]
    neighborhoods: dict[str, list[Neighborhood]]
    devices: dict[str, NetworkDevice]
    links: dict[str, NetworkLink]
    ports_by_role: dict[str, list[NetworkPort]]
    access_segments: dict[str, AccessSegment]
    failure_domains: dict[str, FailureDomain]
    service_packages: dict[str, ServicePackage]
    sla_profiles: dict[str, SLAProfile]
    campaigns: dict[str, Campaign]
    customers_by_district: dict[str, list[Customer]]
    subscriptions: list[Subscription]
    primary_connections: list[SubscriptionConnection]
    backup_connections: list[SubscriptionConnection]
    alarm_types: dict[str, AlarmType]
    incidents: list[Incident]
    outages: list[Outage]
    rule_set: RuleSet
    rule_versions: list[RuleVersion]


def parse_reference_datetime(value: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError("reference datetime must be ISO 8601")
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, ISTANBUL_TZ)
    return parsed.astimezone(ISTANBUL_TZ)


def seed_multicity_realism_dataset(*, snapshot: DataSnapshot, batch_size: int = 2000) -> dict:
    parse_reference_datetime(snapshot.dataset_version.config["reference_datetime"])
    cities, districts, neighborhoods = seed_geography()
    sla_profiles = seed_sla_profiles(snapshot)
    service_packages = seed_service_packages(snapshot, sla_profiles)
    campaigns = seed_campaigns(snapshot)
    rule_set, rule_versions = seed_rule_catalog(snapshot)
    (
        devices,
        links,
        ports_by_role,
        access_segments,
        failure_domains,
        link_by_pair,
    ) = seed_network(snapshot, cities, districts, neighborhoods, batch_size=batch_size)
    customers_by_district = seed_customers(snapshot, cities, districts, neighborhoods, batch_size)
    subscriptions, primary_connections, backup_connections = seed_subscriptions_and_lines(
        snapshot=snapshot,
        districts=districts,
        customers_by_district=customers_by_district,
        service_packages=service_packages,
        ports_by_role=ports_by_role,
        access_segments=access_segments,
        failure_domains=failure_domains,
        link_by_pair=link_by_pair,
        batch_size=batch_size,
    )
    alarm_types = seed_alarm_types(snapshot)
    incidents, outages = seed_timeline(
        snapshot=snapshot,
        devices=devices,
        links=links,
        ports_by_role=ports_by_role,
        failure_domains=failure_domains,
        primary_connections=primary_connections,
        backup_connections=backup_connections,
        alarm_types=alarm_types,
        batch_size=batch_size,
    )
    seed_payments(snapshot, subscriptions, batch_size)
    seed_campaign_enrollments(snapshot, subscriptions, campaigns, batch_size)
    seed_compensation_history_and_evidence(
        snapshot=snapshot,
        subscriptions=subscriptions,
        incidents=incidents,
        outages=outages,
        rule_set=rule_set,
        rule_versions=rule_versions,
        batch_size=batch_size,
    )
    return collect_seed_counts(snapshot)


def seed_geography() -> tuple[dict[str, City], dict[str, District], dict[str, list[Neighborhood]]]:
    cities: dict[str, City] = {}
    districts: dict[str, District] = {}
    neighborhoods: dict[str, list[Neighborhood]] = {}
    for city_name, city_config in config.CITY_PROFILES.items():
        city, _ = City.objects.get_or_create(
            name=city_name,
            defaults={
                "plate_code": city_config["plate_code"],
                "metadata": {"synthetic_profile": "multi_city_realism_v1"},
            },
        )
        cities[city_name] = city
        for district_name, neighborhood_names in city_config["districts"].items():
            district, _ = District.objects.get_or_create(
                city=city,
                name=district_name,
                defaults={
                    "profile_type": AreaProfileType.MIXED,
                    "metadata": {"synthetic_profile": "multi_city_realism_v1"},
                },
            )
            districts[district_name] = district
            items: list[Neighborhood] = []
            for name in neighborhood_names:
                neighborhood, _ = Neighborhood.objects.get_or_create(
                    district=district,
                    name=name,
                    defaults={
                        "profile_type": AreaProfileType.MIXED,
                        "metadata": {"synthetic_profile": "multi_city_realism_v1"},
                    },
                )
                items.append(neighborhood)
            neighborhoods[district_name] = items
    return cities, districts, neighborhoods


def seed_sla_profiles(snapshot: DataSnapshot) -> dict[str, SLAProfile]:
    rows = [
        SLAProfile(
            data_snapshot=snapshot,
            code=item["code"],
            name=item["name"],
            availability_target_percent=Decimal(item["availability_target_percent"]),
            support_window=item["support_window"],
            response_target_minutes=item["response_target_minutes"],
            restoration_target_minutes=item["restoration_target_minutes"],
            latency_threshold_ms=item["latency_threshold_ms"],
            jitter_threshold_ms=item["jitter_threshold_ms"],
            packet_loss_threshold_percent=Decimal(item["packet_loss_threshold_percent"]),
            backup_requirement=item["backup_requirement"],
            required_path_diversity=item["required_path_diversity"],
            monitoring_level=item["monitoring_level"],
            is_contractual=item["is_contractual"],
            active=item["active"],
            metadata={"synthetic": True},
        )
        for item in commercial_config.SLA_PROFILES
    ]
    SLAProfile.objects.bulk_create(rows)
    return {profile.code: profile for profile in SLAProfile.objects.filter(data_snapshot=snapshot)}


def seed_service_packages(
    snapshot: DataSnapshot,
    sla_profiles: dict[str, SLAProfile],
) -> dict[str, ServicePackage]:
    valid_from = parse_datetime("2026-01-01T00:00:00+03:00")
    package_rows = []
    allowed_rows = []
    price_rows = []
    for item in commercial_config.PACKAGE_CATALOG:
        package_rows.append(
            ServicePackage(
                data_snapshot=snapshot,
                package_code=item["code"],
                name=item["code"].replace("-", " "),
                technology=item["technology"],
                service_type=item["service_type"],
                status=item["status"],
                default_sla_profile=sla_profiles[item["default_sla"]],
                download_mbps=item["download_mbps"],
                upload_mbps=item["upload_mbps"],
                symmetric=item["symmetric"],
                monthly_price=Decimal(item["list_price"]),
                commitment_months=item["commitment_months"],
                backup_eligible=item["backup_eligible"],
                valid_from=valid_from,
                metadata={
                    "synthetic": True,
                    "target_subscription_count": item["subscription_count"],
                },
            )
        )
    ServicePackage.objects.bulk_create(package_rows)
    packages = {
        package.package_code: package
        for package in ServicePackage.objects.filter(data_snapshot=snapshot).select_related(
            "default_sla_profile"
        )
    }
    for package_index, item in enumerate(commercial_config.PACKAGE_CATALOG, start=1):
        package = packages[item["code"]]
        for segment in item["allowed_segments"]:
            allowed_rows.append(
                ServicePackageAllowedSegment(
                    data_snapshot=snapshot,
                    service_package=package,
                    segment=segment,
                )
            )
        base_price = Decimal(item["list_price"])
        prices = [
            (1, Decimal("0.92"), "2026-01-01T00:00:00+03:00", "2026-04-01T00:00:00+03:00", False),
            (2, Decimal("0.96"), "2026-04-01T00:00:00+03:00", "2026-07-01T00:00:00+03:00", False),
            (3, Decimal("1.00"), "2026-07-01T00:00:00+03:00", None, True),
        ]
        if package_index > 18:
            prices = prices[-2:]
        for version, factor, start, end, active in prices:
            amount = (base_price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            price_rows.append(
                ServicePackagePriceVersion(
                    data_snapshot=snapshot,
                    service_package=package,
                    amount=amount if not active else base_price,
                    currency="TRY",
                    valid_from=parse_datetime(start),
                    valid_to=parse_datetime(end) if end else None,
                    version_number=version,
                    active=active,
                    metadata={"synthetic": True},
                )
            )
    ServicePackageAllowedSegment.objects.bulk_create(allowed_rows)
    ServicePackagePriceVersion.objects.bulk_create(price_rows)
    return packages


def seed_campaigns(snapshot: DataSnapshot) -> dict[str, Campaign]:
    valid_from = parse_datetime("2026-04-01T00:00:00+03:00")
    valid_to = parse_datetime("2026-12-31T23:59:59+03:00")
    rows = [
        Campaign(
            data_snapshot=snapshot,
            code=item["code"],
            name=item["code"].replace("_", " ").title(),
            discount_type=item["discount_type"],
            discount_value=Decimal(item["discount_value"]),
            duration_months=item["duration_months"],
            valid_from=valid_from,
            valid_to=valid_to,
            stackable=item["stackable"],
            status=item["status"],
            metadata={"synthetic": True},
        )
        for item in commercial_config.CAMPAIGNS
    ]
    Campaign.objects.bulk_create(rows)
    campaigns = {
        campaign.code: campaign for campaign in Campaign.objects.filter(data_snapshot=snapshot)
    }
    segment_rows = []
    service_type_rows = []
    technology_rows = []
    for item in commercial_config.CAMPAIGNS:
        campaign = campaigns[item["code"]]
        segment_rows.extend(
            CampaignAllowedSegment(data_snapshot=snapshot, campaign=campaign, segment=segment)
            for segment in item["allowed_segments"]
        )
        service_type_rows.extend(
            CampaignAllowedServiceType(
                data_snapshot=snapshot,
                campaign=campaign,
                service_type=service_type,
            )
            for service_type in item["allowed_service_types"]
        )
        technology_rows.extend(
            CampaignAllowedTechnology(
                data_snapshot=snapshot,
                campaign=campaign,
                technology=technology,
            )
            for technology in item["allowed_technologies"]
            if technology != "gpon"
        )
    CampaignAllowedSegment.objects.bulk_create(segment_rows)
    CampaignAllowedServiceType.objects.bulk_create(service_type_rows)
    CampaignAllowedTechnology.objects.bulk_create(technology_rows)
    return campaigns


def seed_rule_catalog(snapshot: DataSnapshot) -> tuple[RuleSet, list[RuleVersion]]:
    rule_set_cfg = policy_config.RULE_SET
    rule_set = RuleSet.objects.create(
        data_snapshot=snapshot,
        code=rule_set_cfg["code"],
        version=rule_set_cfg["version"],
        name=rule_set_cfg["name"],
        effective_from=parse_datetime(rule_set_cfg["effective_from"]),
        effective_to=None,
        active=True,
        change_reason=rule_set_cfg["change_reason"],
        metadata={"synthetic_policy_only": True},
    )
    rule_rows = [
        Rule(
            data_snapshot=snapshot,
            rule_set=rule_set,
            code=item["code"],
            name=item["name"],
            rule_type=RuleType.COMPENSATION,
            family=item["family"],
            conflict_group=item["conflict_group"],
            status=RuleStatus.ACTIVE,
            description="Synthetic rule for multi-city realism dataset.",
            metadata={"synthetic_policy_only": True},
        )
        for item in policy_config.RULES
    ]
    Rule.objects.bulk_create(rule_rows)
    rules = {rule.code: rule for rule in Rule.objects.filter(data_snapshot=snapshot)}
    version_rows = [
        RuleVersion(
            data_snapshot=snapshot,
            rule=rules[item["code"]],
            version=rule_set.version,
            status=RuleVersionStatus.ACTIVE,
            priority=item["priority"],
            action_type=item["action_type"],
            price_basis=item["price_basis"],
            stackable=item["stackable"],
            active=True,
            valid_from=rule_set.effective_from,
            valid_to=rule_set.effective_to,
            condition_tree=item["condition_tree"],
            action_config=item["action_config"],
            change_note="Initial synthetic policy v1.",
            metadata={"synthetic_policy_only": True},
        )
        for item in policy_config.RULES
    ]
    RuleVersion.objects.bulk_create(version_rows)
    return rule_set, list(RuleVersion.objects.filter(data_snapshot=snapshot).select_related("rule"))


def seed_network(
    snapshot: DataSnapshot,
    cities: dict[str, City],
    districts: dict[str, District],
    neighborhoods: dict[str, list[Neighborhood]],
    *,
    batch_size: int,
) -> tuple[
    dict[str, NetworkDevice],
    dict[str, NetworkLink],
    dict[str, list[NetworkPort]],
    dict[str, AccessSegment],
    dict[str, FailureDomain],
    dict[tuple[int, int], NetworkLink],
]:
    device_rows: list[NetworkDevice] = []
    for city_name, city_config in config.CITY_PROFILES.items():
        city = cities[city_name]
        city_code = city_name[:3].upper()
        for index in range(1, 3):
            device_rows.append(
                NetworkDevice(
                    data_snapshot=snapshot,
                    code=f"BNG-{city_code}-{index:03d}",
                    name=f"{city_name} synthetic BNG {index}",
                    device_type=NetworkDeviceType.BNG,
                    city=city,
                    metadata={"synthetic": True},
                )
            )
        for index in range(1, 5):
            device_rows.append(
                NetworkDevice(
                    data_snapshot=snapshot,
                    code=f"AGG-{city_code}-{index:03d}",
                    name=f"{city_name} synthetic metro aggregation {index}",
                    device_type=NetworkDeviceType.METRO_AGGREGATION,
                    city=city,
                    metadata={"synthetic": True},
                )
            )
        for district_name in city_config["districts"]:
            district = districts[district_name]
            neighborhood_cycle = cycle(neighborhoods[district_name])
            counts = config.DEVICE_DISTRIBUTION[district_name]
            device_rows.extend(
                build_access_devices(
                    snapshot,
                    city,
                    district,
                    neighborhood_cycle,
                    district_name,
                    "OLT",
                    NetworkDeviceType.OLT,
                    counts["olt"],
                )
            )
            device_rows.extend(
                build_access_devices(
                    snapshot,
                    city,
                    district,
                    neighborhood_cycle,
                    district_name,
                    "DSLAM",
                    NetworkDeviceType.DSLAM,
                    counts["dslam"],
                )
            )
            device_rows.extend(
                build_access_devices(
                    snapshot,
                    city,
                    district,
                    neighborhood_cycle,
                    district_name,
                    "AN",
                    NetworkDeviceType.ACCESS_NODE,
                    counts["standard_access"],
                    access_role=NetworkDeviceAccessRole.STANDARD_ACCESS,
                )
            )
            device_rows.extend(
                build_access_devices(
                    snapshot,
                    city,
                    district,
                    neighborhood_cycle,
                    district_name,
                    "CAN",
                    NetworkDeviceType.ACCESS_NODE,
                    counts["corporate_fiber_aggregation"],
                    access_role=NetworkDeviceAccessRole.CORPORATE_FIBER_AGGREGATION,
                )
            )
    NetworkDevice.objects.bulk_create(device_rows, batch_size=batch_size)
    devices = {
        device.code: device for device in NetworkDevice.objects.filter(data_snapshot=snapshot)
    }

    link_rows: list[NetworkLink] = []
    for city_name, city_config in config.CITY_PROFILES.items():
        city_code = city_name[:3].upper()
        bngs = [devices[f"BNG-{city_code}-{index:03d}"] for index in range(1, 3)]
        aggs = [devices[f"AGG-{city_code}-{index:03d}"] for index in range(1, 5)]
        for index, agg in enumerate(aggs):
            bng = bngs[0 if index < 2 else 1]
            link_rows.append(
                NetworkLink(
                    data_snapshot=snapshot,
                    link_code=f"LNK-{bng.code}-{agg.code}",
                    source_device=bng,
                    target_device=agg,
                    status=NetworkLinkStatus.ACTIVE,
                    capacity_mbps=100000,
                    metadata={"synthetic": True, "link_layer": "bng_to_aggregation"},
                )
            )
        for district_name in city_config["districts"]:
            district_devices = [
                device
                for device in devices.values()
                if device.district_id == districts[district_name].id
            ]
            for offset, device in enumerate(sorted(district_devices, key=lambda item: item.code)):
                agg = aggs[offset % len(aggs)]
                link_rows.append(
                    NetworkLink(
                        data_snapshot=snapshot,
                        link_code=f"LNK-{agg.code}-{device.code}",
                        source_device=agg,
                        target_device=device,
                        status=NetworkLinkStatus.ACTIVE,
                        capacity_mbps=40000,
                        metadata={
                            "synthetic": True,
                            "link_layer": "aggregation_to_access",
                        },
                    )
                )
    extra_targets = [
        device
        for device in sorted(devices.values(), key=lambda item: item.code)
        if device.device_type == NetworkDeviceType.ACCESS_NODE
        and device.access_role == NetworkDeviceAccessRole.STANDARD_ACCESS
    ][:18]
    for index, target in enumerate(extra_targets, start=1):
        city_code = target.city.name[:3].upper()
        source = devices[f"AGG-{city_code}-{((index + 1) % 4) + 1:03d}"]
        link_rows.append(
            NetworkLink(
                data_snapshot=snapshot,
                link_code=f"LNK-ALT-{index:03d}-{source.code}-{target.code}",
                source_device=source,
                target_device=target,
                status=NetworkLinkStatus.ACTIVE,
                capacity_mbps=20000,
                metadata={"synthetic": True, "link_layer": "alternate_access"},
            )
        )
    NetworkLink.objects.bulk_create(link_rows, batch_size=batch_size)
    links = {link.link_code: link for link in NetworkLink.objects.filter(data_snapshot=snapshot)}
    link_by_pair = {(link.source_device_id, link.target_device_id): link for link in links.values()}

    failure_domains = seed_failure_domains(snapshot)
    seed_device_and_link_domains(snapshot, devices, links, failure_domains, batch_size)
    ports_by_role = seed_ports(snapshot, devices, batch_size)
    access_segments = seed_access_segments(snapshot, devices, batch_size)
    return devices, links, ports_by_role, access_segments, failure_domains, link_by_pair


def build_access_devices(
    snapshot,
    city,
    district,
    neighborhood_cycle,
    district_name: str,
    prefix: str,
    device_type: str,
    count: int,
    *,
    access_role: str | None = None,
) -> list[NetworkDevice]:
    district_code = district_name[:3].upper()
    rows = []
    for index in range(1, count + 1):
        rows.append(
            NetworkDevice(
                data_snapshot=snapshot,
                code=f"{prefix}-{district_code}-{index:03d}",
                name=f"{district_name} synthetic {prefix} {index}",
                device_type=device_type,
                access_role=access_role,
                city=city,
                district=district,
                neighborhood=next(neighborhood_cycle),
                metadata={"synthetic": True, "district_profile": district_name},
            )
        )
    return rows


def seed_failure_domains(snapshot: DataSnapshot) -> dict[str, FailureDomain]:
    rows: list[FailureDomain] = []
    for index in range(1, 1000):
        rows.append(
            FailureDomain(
                data_snapshot=snapshot,
                code=f"FD-SITE-{index:03d}",
                name=f"Synthetic site {index:03d}",
                domain_type=FailureDomainType.SITE,
                description="Synthetic site risk domain.",
            )
        )
        rows.append(
            FailureDomain(
                data_snapshot=snapshot,
                code=f"FD-PWR-{index:03d}",
                name=f"Synthetic power zone {index:03d}",
                domain_type=FailureDomainType.POWER_ZONE,
                description="Synthetic power risk domain.",
            )
        )
        rows.append(
            FailureDomain(
                data_snapshot=snapshot,
                code=f"FD-FBR-{index:03d}",
                name=f"Synthetic fiber route {index:03d}",
                domain_type=FailureDomainType.FIBER_ROUTE,
                description="Synthetic fiber route risk domain.",
            )
        )
    FailureDomain.objects.bulk_create(rows)
    return {item.code: item for item in FailureDomain.objects.filter(data_snapshot=snapshot)}


def seed_device_and_link_domains(snapshot, devices, links, failure_domains, batch_size):
    return


def seed_ports(
    snapshot, devices: dict[str, NetworkDevice], batch_size: int
) -> dict[str, list[NetworkPort]]:
    rows: list[NetworkPort] = []
    active_pon_remaining = config.NETWORK_TARGETS["active_pon_ports"]
    active_dsl_remaining = config.NETWORK_TARGETS["active_dsl_ports"]
    dedicated_used_capacity = (
        2042 + commercial_config.BACKUP_DISTRIBUTION["reserved_backup_port_capacity"]
    )
    dedicated_used_remaining = dedicated_used_capacity
    for device in sorted(devices.values(), key=lambda item: item.code):
        if device.device_type == NetworkDeviceType.OLT:
            for index in range(1, 17):
                active = active_pon_remaining > 0
                active_pon_remaining -= 1 if active else 0
                rows.append(
                    NetworkPort(
                        data_snapshot=snapshot,
                        device=device,
                        port_code=f"PON-{index:02d}",
                        port_type=NetworkPortType.ACCESS,
                        inventory_status=NetworkPortStatus.ACTIVE
                        if active
                        else NetworkPortStatus.RESERVED,
                        capacity_mbps=2500,
                        metadata={"service_port_role": "gpon_pon", "synthetic": True},
                    )
                )
        elif device.device_type == NetworkDeviceType.DSLAM:
            for index in range(1, 97):
                active = active_dsl_remaining > 0
                active_dsl_remaining -= 1 if active else 0
                rows.append(
                    NetworkPort(
                        data_snapshot=snapshot,
                        device=device,
                        port_code=f"DSL-{index:03d}",
                        port_type=NetworkPortType.CUSTOMER,
                        inventory_status=NetworkPortStatus.ACTIVE
                        if active
                        else NetworkPortStatus.RESERVED,
                        capacity_mbps=100,
                        metadata={"service_port_role": "xdsl", "synthetic": True},
                    )
                )
        elif device.device_type == NetworkDeviceType.ACCESS_NODE:
            for index in range(1, 49):
                planned = dedicated_used_remaining > 0
                dedicated_used_remaining -= 1 if planned else 0
                rows.append(
                    NetworkPort(
                        data_snapshot=snapshot,
                        device=device,
                        port_code=f"ETH-{index:03d}",
                        port_type=NetworkPortType.CUSTOMER,
                        inventory_status=NetworkPortStatus.ACTIVE
                        if planned
                        else NetworkPortStatus.RESERVED,
                        capacity_mbps=10000,
                        metadata={
                            "service_port_role": "dedicated_fiber",
                            "reserved_backup_capacity": index > 40,
                            "synthetic": True,
                        },
                    )
                )
    NetworkPort.objects.bulk_create(rows, batch_size=batch_size)
    by_role: dict[str, list[NetworkPort]] = defaultdict(list)
    ports = NetworkPort.objects.filter(data_snapshot=snapshot).select_related("device")
    for port in ports:
        role = port.metadata.get("service_port_role", "other")
        by_role[role].append(port)
    for role in by_role:
        by_role[role].sort(key=lambda item: (item.device.code, item.port_code))
    return by_role


def seed_access_segments(snapshot, devices, batch_size) -> dict[str, AccessSegment]:
    rows = []
    for device in sorted(devices.values(), key=lambda item: item.code):
        if device.device_type == NetworkDeviceType.OLT:
            technologies = [AccessTechnology.GPON]
        elif device.device_type == NetworkDeviceType.DSLAM:
            technologies = [AccessTechnology.VDSL, AccessTechnology.ADSL]
        elif device.device_type == NetworkDeviceType.ACCESS_NODE:
            technologies = [AccessTechnology.FIBER]
        else:
            continue
        for technology in technologies:
            rows.append(
                AccessSegment(
                    data_snapshot=snapshot,
                    segment_code=f"SEG-{device.code}-{technology}",
                    name=f"{device.code} {technology} synthetic segment",
                    technology=technology,
                    serving_device=device,
                    city=device.city,
                    district=device.district,
                    neighborhood=device.neighborhood,
                    metadata={"synthetic": True},
                )
            )
    AccessSegment.objects.bulk_create(rows, batch_size=batch_size)
    return {
        segment.segment_code: segment
        for segment in AccessSegment.objects.filter(data_snapshot=snapshot).select_related(
            "serving_device"
        )
    }


def seed_customers(
    snapshot, cities, districts, neighborhoods, batch_size
) -> dict[str, list[Customer]]:
    rows: list[Customer] = []
    for (
        district_name,
        district_config,
    ) in commercial_config.DISTRICT_COMMERCIAL_DISTRIBUTION.items():
        district = districts[district_name]
        city = district.city
        neighborhood_cycle = cycle(neighborhoods[district_name])
        segments = expand_counts(district_config["segments"])
        priorities = expand_counts(district_config["priority"])
        for index, segment in enumerate(segments, start=1):
            priority = priorities[index - 1]
            rows.append(
                Customer(
                    data_snapshot=snapshot,
                    customer_number=f"CUST-MCR-{district_name[:3].upper()}-{index:05d}",
                    display_name=f"Synthetic {district_name} customer {index:05d}",
                    segment=segment,
                    status=CustomerStatus.ACTIVE,
                    priority_level=priority,
                    city=city,
                    district=district,
                    neighborhood=next(neighborhood_cycle),
                    metadata={"synthetic": True, "dataset": config.DATASET_SLUG},
                )
            )
    Customer.objects.bulk_create(rows, batch_size=batch_size)
    customers_by_district: dict[str, list[Customer]] = {}
    for district_name in commercial_config.DISTRICT_COMMERCIAL_DISTRIBUTION:
        customers_by_district[district_name] = list(
            Customer.objects.filter(
                data_snapshot=snapshot, district=districts[district_name]
            ).order_by("customer_number")
        )
    return customers_by_district


def seed_subscriptions_and_lines(
    *,
    snapshot,
    districts,
    customers_by_district,
    service_packages,
    ports_by_role,
    access_segments,
    failure_domains,
    link_by_pair,
    batch_size,
) -> tuple[list[Subscription], list[SubscriptionConnection], list[SubscriptionConnection]]:
    subscription_rows: list[Subscription] = []
    line_rows: list[LineConnection] = []
    subscription_plans: list[dict] = []
    package_pools = build_package_pools(service_packages)
    for district_name, customers in customers_by_district.items():
        district_config = commercial_config.DISTRICT_COMMERCIAL_DISTRIBUTION[district_name]
        slots = build_customer_slots(customers, district_config["subscription_counts"])
        status_values = expand_counts(district_config["subscription_statuses"])
        tech_values = build_district_access_profile(district_name)
        plan_items = assign_subscription_plans(
            district_name=district_name,
            slots=slots,
            statuses=status_values,
            access_profiles=tech_values,
            package_pools=package_pools,
        )
        subscription_plans.extend(plan_items)
    for global_index, plan in enumerate(subscription_plans, start=1):
        package = plan["package"]
        status = plan["status"]
        valid_to = CANCELLED_AT if status == SubscriptionStatus.CANCELLED else None
        is_active = status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.SUSPENDED}
        suspension_reason = ""
        if status == SubscriptionStatus.SUSPENDED:
            reasons = [
                SuspensionReason.CUSTOMER_REQUEST,
                SuspensionReason.PAYMENT_RELATED,
                SuspensionReason.ADMINISTRATIVE,
                SuspensionReason.PROVIDER_FAULT,
                SuspensionReason.UNKNOWN,
            ]
            suspension_reason = reasons[global_index % len(reasons)]
        subscription_rows.append(
            Subscription(
                data_snapshot=snapshot,
                subscription_number=f"SUB-MCR-{global_index:05d}",
                customer=plan["customer"],
                service_package=package,
                sla_profile=package.default_sla_profile,
                status=status,
                suspension_reason=suspension_reason,
                valid_from=VALID_FROM,
                valid_to=valid_to,
                is_active=is_active,
                monthly_price=package.monthly_price,
                metadata={
                    "synthetic": True,
                    "district": plan["district_name"],
                    "access_technology": plan["access_technology"],
                    "service_type": package.service_type,
                },
            )
        )
    Subscription.objects.bulk_create(subscription_rows, batch_size=batch_size)
    subscriptions = list(
        Subscription.objects.filter(data_snapshot=snapshot)
        .select_related("customer", "service_package", "sla_profile")
        .order_by("subscription_number")
    )
    for plan, subscription in zip(subscription_plans, subscriptions, strict=True):
        plan["subscription"] = subscription

    port_queues = {
        "gpon": deque(
            [p for p in ports_by_role["gpon_pon"] if p.inventory_status == NetworkPortStatus.ACTIVE]
        ),
        "vdsl": deque(
            [p for p in ports_by_role["xdsl"] if p.inventory_status == NetworkPortStatus.ACTIVE]
        ),
        "adsl": deque(
            [p for p in ports_by_role["xdsl"] if p.inventory_status == NetworkPortStatus.ACTIVE]
        ),
        "fiber_standard": deque(
            p
            for p in ports_by_role["dedicated_fiber"]
            if p.device.access_role == NetworkDeviceAccessRole.STANDARD_ACCESS
        ),
        "fiber_corporate": deque(
            p
            for p in ports_by_role["dedicated_fiber"]
            if p.device.access_role == NetworkDeviceAccessRole.CORPORATE_FIBER_AGGREGATION
        ),
    }
    used_dsl_port_ids: set[int] = set()
    used_fiber_port_ids: set[int] = set()
    primary_plans = [
        plan for plan in subscription_plans if plan["status"] != SubscriptionStatus.PENDING
    ]
    for line_index, plan in enumerate(primary_plans, start=1):
        port = pop_port_for_plan(plan, port_queues, used_dsl_port_ids, used_fiber_port_ids)
        plan["primary_port"] = port
        segment = access_segments[f"SEG-{port.device.code}-{plan['line_technology']}"]
        line_rows.append(
            LineConnection(
                data_snapshot=snapshot,
                line_code=f"LINE-MCR-P-{line_index:05d}",
                port=port,
                access_segment=segment,
                technology=plan["line_technology"],
                status=LineConnectionStatus.TERMINATED
                if plan["status"] == SubscriptionStatus.CANCELLED
                else LineConnectionStatus.ACTIVE,
                valid_from=VALID_FROM,
                valid_to=CANCELLED_AT if plan["status"] == SubscriptionStatus.CANCELLED else None,
                is_active=plan["status"] != SubscriptionStatus.CANCELLED,
                metadata={"synthetic": True, "connection_role": "primary"},
            )
        )
        plan["primary_line_code"] = line_rows[-1].line_code
    backup_plans = select_backup_plans(subscription_plans)
    for backup_index, plan in enumerate(backup_plans, start=1):
        port = pop_backup_port_for_plan(plan, port_queues, used_fiber_port_ids, backup_index)
        plan["backup_port"] = port
        segment = access_segments[f"SEG-{port.device.code}-{AccessTechnology.FIBER}"]
        line_rows.append(
            LineConnection(
                data_snapshot=snapshot,
                line_code=f"LINE-MCR-B-{backup_index:05d}",
                port=port,
                access_segment=segment,
                technology=AccessTechnology.FIBER,
                status=LineConnectionStatus.ACTIVE,
                valid_from=VALID_FROM,
                valid_to=None,
                is_active=True,
                metadata={
                    "synthetic": True,
                    "connection_role": "backup",
                    "target_diversity": plan["backup_diversity"],
                },
            )
        )
        plan["backup_line_code"] = line_rows[-1].line_code
    LineConnection.objects.bulk_create(line_rows, batch_size=batch_size)
    lines = {
        line.line_code: line
        for line in LineConnection.objects.filter(data_snapshot=snapshot).select_related(
            "port__device",
            "access_segment",
        )
    }
    seed_line_failure_domains(
        snapshot=snapshot,
        lines=lines,
        primary_plans=primary_plans,
        backup_plans=backup_plans,
        failure_domains=failure_domains,
        batch_size=batch_size,
    )
    connection_rows = []
    for plan in primary_plans:
        subscription = plan["subscription"]
        connection_rows.append(
            SubscriptionConnection(
                data_snapshot=snapshot,
                subscription=subscription,
                line_connection=lines[plan["primary_line_code"]],
                valid_from=VALID_FROM,
                valid_to=CANCELLED_AT
                if subscription.status == SubscriptionStatus.CANCELLED
                else None,
                is_active=subscription.status != SubscriptionStatus.CANCELLED,
                connection_role=SubscriptionConnectionRole.PRIMARY,
                port_identifier=lines[plan["primary_line_code"]].port.port_code,
                metadata={"synthetic": True},
            )
        )
    for plan in backup_plans:
        subscription = plan["subscription"]
        connection_rows.append(
            SubscriptionConnection(
                data_snapshot=snapshot,
                subscription=subscription,
                line_connection=lines[plan["backup_line_code"]],
                valid_from=VALID_FROM,
                valid_to=None,
                is_active=True,
                connection_role=SubscriptionConnectionRole.BACKUP,
                port_identifier=lines[plan["backup_line_code"]].port.port_code,
                metadata={
                    "synthetic": True,
                    "target_diversity": plan["backup_diversity"],
                },
            )
        )
    SubscriptionConnection.objects.bulk_create(connection_rows, batch_size=batch_size)
    primary_connections = list(
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            connection_role=SubscriptionConnectionRole.PRIMARY,
        ).select_related("subscription", "line_connection__port__device")
    )
    backup_connections = list(
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            connection_role=SubscriptionConnectionRole.BACKUP,
        ).select_related("subscription", "line_connection__port__device")
    )
    return subscriptions, primary_connections, backup_connections


def expand_counts(counts: dict[str, int]) -> list[str]:
    values: list[str] = []
    for key, count in counts.items():
        values.extend([key] * count)
    return values


def build_customer_slots(
    customers: list[Customer], subscription_counts: dict[str, int]
) -> list[Customer]:
    slots: list[Customer] = []
    index = 0
    for count_key, multiplicity in (("single", 1), ("double", 2), ("triple", 3)):
        for customer in customers[index : index + subscription_counts[count_key]]:
            slots.extend([customer] * multiplicity)
        index += subscription_counts[count_key]
    return slots


def build_district_access_profile(district_name: str) -> list[dict[str, str]]:
    tech = config.DISTRICT_TECHNOLOGY_DISTRIBUTION[district_name]
    rows = []
    rows.extend(
        {"access_technology": "fiber", "service_type": ServiceType.METRO_ETHERNET}
        for _ in range(tech["metro"])
    )
    rows.extend(
        {"access_technology": "fiber", "service_type": ServiceType.BROADBAND}
        for _ in range(tech["fiber"] - tech["metro"])
    )
    rows.extend(
        {"access_technology": "gpon", "service_type": ServiceType.BROADBAND}
        for _ in range(tech["gpon"])
    )
    rows.extend(
        {"access_technology": "vdsl", "service_type": ServiceType.BROADBAND}
        for _ in range(tech["vdsl"])
    )
    rows.extend(
        {"access_technology": "adsl", "service_type": ServiceType.BROADBAND}
        for _ in range(tech["adsl"])
    )
    return rows


def build_package_pools(
    service_packages: dict[str, ServicePackage],
) -> dict[tuple[str, str, str], deque[ServicePackage]]:
    pools: dict[tuple[str, str, str], deque[ServicePackage]] = defaultdict(deque)
    for package in service_packages.values():
        segments = list(package.allowed_segments.values_list("segment", flat=True))
        for segment in segments:
            tech_keys = (
                ["gpon", "fiber"]
                if package.technology == AccessTechnology.FIBER
                else [package.technology]
            )
            for tech_key in tech_keys:
                pools[(segment, tech_key, package.service_type)].append(package)
    return pools


def assign_subscription_plans(
    *,
    district_name: str,
    slots: list[Customer],
    statuses: list[str],
    access_profiles: list[dict[str, str]],
    package_pools: dict[tuple[str, str, str], deque[ServicePackage]],
) -> list[dict]:
    segment_rank = {
        CustomerSegment.ENTERPRISE: 0,
        CustomerSegment.PUBLIC: 1,
        CustomerSegment.SME: 2,
        CustomerSegment.INDIVIDUAL: 3,
    }
    sorted_slots = sorted(
        slots, key=lambda customer: (segment_rank[customer.segment], customer.customer_number)
    )
    profiles = deque(access_profiles)
    plans: list[dict] = []
    for index, customer in enumerate(sorted_slots):
        profile = select_profile_for_customer(customer, profiles)
        package = rotate_package(
            package_pools[(customer.segment, profile["access_technology"], profile["service_type"])]
        )
        plans.append(
            {
                "district_name": district_name,
                "customer": customer,
                "status": statuses[index],
                "package": package,
                "access_technology": profile["access_technology"],
                "line_technology": profile["access_technology"],
            }
        )
    return sorted(plans, key=lambda item: item["customer"].customer_number)


def select_profile_for_customer(
    customer: Customer, profiles: deque[dict[str, str]]
) -> dict[str, str]:
    fallback = None
    for _ in range(len(profiles)):
        profile = profiles.popleft()
        allowed = True
        if (
            profile["service_type"] == ServiceType.METRO_ETHERNET
            and customer.segment == CustomerSegment.INDIVIDUAL
        ):
            allowed = False
        if (
            profile["access_technology"] == AccessTechnology.ADSL
            and customer.segment != CustomerSegment.INDIVIDUAL
        ):
            allowed = False
        if (
            profile["access_technology"] == AccessTechnology.VDSL
            and customer.segment == CustomerSegment.ENTERPRISE
        ):
            allowed = False
        if allowed:
            return profile
        fallback = profile
        profiles.append(profile)
    if fallback is None:
        raise ValueError("No access profile available")
    return fallback


def rotate_package(pool: deque[ServicePackage]) -> ServicePackage:
    if not pool:
        raise ValueError("No compatible service package available")
    package = pool.popleft()
    pool.append(package)
    return package


def pop_port_for_plan(plan, port_queues, used_dsl_port_ids, used_fiber_port_ids) -> NetworkPort:
    tech = plan["access_technology"]
    if tech == AccessTechnology.GPON:
        port = port_queues["gpon"][0]
        port_queues["gpon"].rotate(-1)
        return port
    if tech in {AccessTechnology.VDSL, AccessTechnology.ADSL}:
        queue = port_queues[tech]
        while queue:
            port = queue.popleft()
            if port.id not in used_dsl_port_ids:
                used_dsl_port_ids.add(port.id)
                return port
        raise ValueError("No DSL port left")
    queue_name = (
        "fiber_corporate"
        if plan["package"].service_type == ServiceType.METRO_ETHERNET
        else "fiber_standard"
    )
    queue = port_queues[queue_name]
    while queue:
        port = queue.popleft()
        if port.id not in used_fiber_port_ids:
            used_fiber_port_ids.add(port.id)
            return port
    raise ValueError("No fiber port left")


def select_backup_plans(subscription_plans: list[dict]) -> list[dict]:
    targets = commercial_config.BACKUP_DISTRIBUTION["by_district"]
    diversity_values = expand_counts(commercial_config.BACKUP_DISTRIBUTION["actual_path_diversity"])
    diversity_iter = iter(diversity_values)
    selected = []
    for district_name, count in targets.items():
        candidates = [
            plan
            for plan in subscription_plans
            if plan["district_name"] == district_name
            and plan["status"] in {SubscriptionStatus.ACTIVE, SubscriptionStatus.SUSPENDED}
            and plan["package"].service_type == ServiceType.METRO_ETHERNET
        ]
        for plan in candidates[:count]:
            plan["backup_diversity"] = next(diversity_iter)
            selected.append(plan)
    return selected


def pop_backup_port_for_plan(plan, port_queues, used_fiber_port_ids, backup_index) -> NetworkPort:
    queue = port_queues["fiber_corporate"]
    primary_device_id = plan["primary_port"].device_id
    primary_signature = collect_device_path_signature(plan["primary_port"].device)

    def port_matches_target(port: NetworkPort) -> bool:
        if port.id in used_fiber_port_ids:
            return False
        if port.device_id == primary_device_id:
            return plan["backup_diversity"] == "partially_diverse"
        signature = collect_device_path_signature(port.device)
        shares_aggregation = bool(
            primary_signature["aggregation_ids"] & signature["aggregation_ids"]
        )
        shares_bng = bool(primary_signature["bng_ids"] & signature["bng_ids"])
        if plan["backup_diversity"] == "partially_diverse":
            return shares_aggregation or shares_bng
        return not shares_aggregation and not shares_bng

    for port in list(queue):
        if port_matches_target(port):
            queue.remove(port)
            used_fiber_port_ids.add(port.id)
            return port

    # Keep generation deterministic if a district exhausts the ideal backup pool.
    # The validator catches any resulting path-diversity drift.
    if plan["backup_diversity"] == "partially_diverse":
        for port in list(queue):
            if port.id not in used_fiber_port_ids and port.device_id == primary_device_id:
                queue.remove(port)
                used_fiber_port_ids.add(port.id)
                return port
    while queue:
        port = queue.popleft()
        if port.id in used_fiber_port_ids:
            continue
        if (
            plan["backup_diversity"] in {"fully_diverse", "unknown", "shared_risk"}
            and port.device_id == primary_device_id
        ):
            continue
        used_fiber_port_ids.add(port.id)
        return port
    raise ValueError("No backup fiber port left")


def collect_device_path_signature(device) -> dict[str, set[int]]:
    links_by_id: dict[int, NetworkLink] = {}
    visited_device_ids: set[int] = set()
    visiting_device_ids: set[int] = set()

    def walk(current) -> None:
        if current.id in visiting_device_ids or current.id in visited_device_ids:
            return
        visiting_device_ids.add(current.id)
        incoming_links = NetworkLink.objects.filter(
            data_snapshot=device.data_snapshot,
            target_device=current,
        ).select_related("source_device")
        for link in incoming_links:
            links_by_id[link.id] = link
            walk(link.source_device)
        visiting_device_ids.remove(current.id)
        visited_device_ids.add(current.id)

    walk(device)
    upstream_devices = {link.source_device for link in links_by_id.values()}
    return {
        "aggregation_ids": {
            upstream.id
            for upstream in upstream_devices
            if upstream.device_type == NetworkDeviceType.METRO_AGGREGATION
        },
        "bng_ids": {
            upstream.id
            for upstream in upstream_devices
            if upstream.device_type == NetworkDeviceType.BNG
        },
    }


def seed_line_failure_domains(
    *,
    snapshot,
    lines,
    primary_plans,
    backup_plans,
    failure_domains,
    batch_size,
):
    rows = []
    domain_counter = 1
    backup_subscription_ids = {plan["subscription"].id for plan in backup_plans}
    for plan in primary_plans:
        if plan["subscription"].id not in backup_subscription_ids:
            continue
        line = lines[plan["primary_line_code"]]
        for prefix in ("SITE", "PWR", "FBR"):
            rows.append(
                LineConnectionFailureDomainMembership(
                    data_snapshot=snapshot,
                    line_connection=line,
                    failure_domain=failure_domains[f"FD-{prefix}-{domain_counter:03d}"],
                )
            )
        plan["domain_counter"] = domain_counter
        domain_counter += 1
    for plan in backup_plans:
        line = lines[plan["backup_line_code"]]
        primary_counter = plan["domain_counter"]
        if plan["backup_diversity"] == "shared_risk":
            counters = [primary_counter, primary_counter, primary_counter]
        elif plan["backup_diversity"] == "unknown":
            counters = [primary_counter + 400, None, primary_counter + 402]
        else:
            counters = [
                primary_counter + 400,
                primary_counter + 401,
                primary_counter + 402,
            ]
        for prefix, counter in zip(("SITE", "PWR", "FBR"), counters, strict=True):
            if counter is None:
                continue
            rows.append(
                LineConnectionFailureDomainMembership(
                    data_snapshot=snapshot,
                    line_connection=line,
                    failure_domain=failure_domains[f"FD-{prefix}-{counter:03d}"],
                )
            )
    LineConnectionFailureDomainMembership.objects.bulk_create(rows, batch_size=batch_size)


def seed_alarm_types(snapshot: DataSnapshot) -> dict[str, AlarmType]:
    rows = [
        AlarmType(
            data_snapshot=snapshot,
            code=item["code"],
            name=item["name"],
            severity=item["severity"],
            category=item["category"],
            probable_cause_family=item["probable_cause_family"],
            service_impact_class=item["service_impact_class"],
            auto_clear_policy=item["auto_clear_policy"],
            deduplication_window_seconds=item["deduplication_window_seconds"],
            correlation_family=item["correlation_family"],
            default_incident_type=item["default_incident_type"],
            is_root_candidate=item["is_root_candidate"],
            metadata={"synthetic": True, "impact_class": item["impact_class"]},
        )
        for item in alarm_config.ALARM_CATALOG
    ]
    AlarmType.objects.bulk_create(rows)
    alarm_types = {item.code: item for item in AlarmType.objects.filter(data_snapshot=snapshot)}
    source_rows = []
    device_rows = []
    for item in alarm_config.ALARM_CATALOG:
        alarm_type = alarm_types[item["code"]]
        source_rows.extend(
            AlarmTypeAllowedSourceKind(
                data_snapshot=snapshot,
                alarm_type=alarm_type,
                source_kind=source_kind,
            )
            for source_kind in item["allowed_source_kinds"]
        )
        device_rows.extend(
            AlarmTypeSupportedDeviceType(
                data_snapshot=snapshot,
                alarm_type=alarm_type,
                device_type=device_type,
            )
            for device_type in item["supported_device_types"]
        )
    AlarmTypeAllowedSourceKind.objects.bulk_create(source_rows)
    AlarmTypeSupportedDeviceType.objects.bulk_create(device_rows)
    return alarm_types


def seed_timeline(
    *,
    snapshot,
    devices,
    links,
    ports_by_role,
    failure_domains,
    primary_connections,
    backup_connections,
    alarm_types,
    batch_size,
) -> tuple[list[Incident], list[Outage]]:
    start = REFERENCE_DATETIME - timedelta(days=60)
    device_pool = list(devices.values())
    link_pool = list(links.values())
    port_pool = (
        ports_by_role["gpon_pon"]
        + ports_by_role["xdsl"][:300]
        + ports_by_role["dedicated_fiber"][:300]
    )
    line_pool = list(
        LineConnection.objects.filter(data_snapshot=snapshot).select_related("port__device")[:600]
    )
    failure_domain_pool = list(failure_domains.values())
    sub_conn_pool = primary_connections[:600] + backup_connections
    incident_scenarios = [
        scenario
        for scenario in alarm_config.SCENARIO_TEMPLATES
        if scenario.get("creates_incident", True)
    ]
    scenario_cycle = cycle(incident_scenarios)

    incident_rows = []
    impact_plan = (
        [ServiceImpactClass.FULL_OUTAGE] * 34
        + [ServiceImpactClass.PARTIAL_OUTAGE] * 34
        + [ServiceImpactClass.SHORT_INTERRUPTION] * 10
        + [ServiceImpactClass.DEGRADATION] * 60
        + [ServiceImpactClass.PROTECTION_LOSS] * 22
        + [ServiceImpactClass.NO_DIRECT_CUSTOMER_IMPACT] * 20
        + [ServiceImpactClass.UNKNOWN] * 30
    )
    for index in range(1, config.TIMELINE_TARGETS["incidents"] + 1):
        scenario = next(scenario_cycle)
        impact = impact_plan[index - 1]
        incident_type = scenario.get("incident_type", IncidentType.UNKNOWN)
        if impact == ServiceImpactClass.DEGRADATION:
            incident_type = IncidentType.SERVICE_DEGRADATION
        elif impact == ServiceImpactClass.PROTECTION_LOSS:
            incident_type = IncidentType.PROTECTION_EVENT
        elif index > 180:
            incident_type = IncidentType.PLANNED_MAINTENANCE
        elif impact in {
            ServiceImpactClass.FULL_OUTAGE,
            ServiceImpactClass.PARTIAL_OUTAGE,
            ServiceImpactClass.SHORT_INTERRUPTION,
        }:
            incident_type = IncidentType.NETWORK_OUTAGE
        started_at = start + timedelta(hours=index * 6)
        duration = timedelta(minutes=45 + (index % 180))
        primary_device = device_pool[index % len(device_pool)]
        incident_rows.append(
            Incident(
                data_snapshot=snapshot,
                incident_number=f"INC-MCR-{index:04d}",
                title=f"Synthetic multi-city incident {index:04d}",
                status=IncidentStatus.RESOLVED,
                severity=Severity.MAJOR
                if impact != ServiceImpactClass.FULL_OUTAGE
                else Severity.CRITICAL,
                incident_type=incident_type,
                service_impact_class=impact,
                correlation_method="deterministic_catalog_v1",
                failover_result=scenario.get("failover_result", FailoverResult.UNKNOWN),
                transition_duration_seconds=45
                if scenario["code"] == "SCN-FAILOVER-SHORT-001"
                else None,
                primary_device=primary_device,
                root_cause_category=RootCauseCategory.UNKNOWN,
                root_cause_summary=scenario["expected_root_cause"],
                detected_at=started_at,
                started_at=started_at,
                resolved_at=started_at + duration,
                restored_at=started_at + duration,
                closed_at=started_at + duration + timedelta(minutes=15),
                metadata={
                    "synthetic": True,
                    "scenario_code": scenario["code"],
                    "ground_truth_candidate": scenario.get("ground_truth_candidate", False),
                },
            )
        )
    Incident.objects.bulk_create(incident_rows, batch_size=batch_size)
    incidents = list(Incident.objects.filter(data_snapshot=snapshot).order_by("incident_number"))

    outage_rows = []
    outage_incidents = [
        incident
        for incident in incidents
        if incident.service_impact_class
        in {
            ServiceImpactClass.FULL_OUTAGE,
            ServiceImpactClass.PARTIAL_OUTAGE,
            ServiceImpactClass.SHORT_INTERRUPTION,
        }
    ][: config.TIMELINE_TARGETS["outages"]]
    for index, incident in enumerate(outage_incidents, start=1):
        outage_rows.append(
            Outage(
                data_snapshot=snapshot,
                outage_code=f"OUT-MCR-{index:04d}",
                incident=incident,
                source_device=incident.primary_device,
                outage_type=OutageType.DEVICE,
                impact_type=incident.service_impact_class,
                status=OutageStatus.RESOLVED,
                root_cause_category=RootCauseCategory.UNKNOWN,
                root_cause_summary=incident.root_cause_summary,
                detected_at=incident.detected_at,
                started_at=incident.started_at,
                ended_at=incident.resolved_at,
                resolved_at=incident.resolved_at,
                restored_at=incident.restored_at,
                transition_duration_seconds=incident.transition_duration_seconds,
                impact_scope={"synthetic": True},
                metadata={"scenario_code": incident.metadata["scenario_code"]},
            )
        )
    Outage.objects.bulk_create(outage_rows, batch_size=batch_size)
    outages = list(Outage.objects.filter(data_snapshot=snapshot).select_related("incident"))

    maintenance_rows = []
    for index in range(1, config.TIMELINE_TARGETS["maintenance_windows"] + 1):
        incident = incidents[180 + index - 1]
        maintenance_rows.append(
            MaintenanceWindow(
                data_snapshot=snapshot,
                reference_code=f"MW-MCR-{index:03d}",
                status=MaintenanceWindowStatus.OVERRUN
                if index % 5 == 0
                else MaintenanceWindowStatus.COMPLETED,
                planned_start_at=incident.started_at - timedelta(minutes=15),
                planned_end_at=incident.started_at + timedelta(minutes=30),
                actual_start_at=incident.started_at - timedelta(minutes=15),
                actual_end_at=incident.resolved_at,
                expected_impact_class=ServiceImpactClass.SHORT_INTERRUPTION,
                actual_impact_class=incident.service_impact_class,
                overrun_minutes=max(
                    0,
                    int(
                        (
                            incident.resolved_at - (incident.started_at + timedelta(minutes=30))
                        ).total_seconds()
                        // 60
                    ),
                ),
                description="Synthetic planned maintenance window.",
                linked_incident=incident if index % 5 == 0 else None,
            )
        )
    MaintenanceWindow.objects.bulk_create(maintenance_rows, batch_size=batch_size)
    maintenance_windows = list(MaintenanceWindow.objects.filter(data_snapshot=snapshot))
    MaintenanceWindowDevice.objects.bulk_create(
        [
            MaintenanceWindowDevice(
                data_snapshot=snapshot,
                maintenance_window=window,
                device=device_pool[index % len(device_pool)],
            )
            for index, window in enumerate(maintenance_windows)
        ],
        batch_size=batch_size,
    )
    MaintenanceWindowNetworkLink.objects.bulk_create(
        [
            MaintenanceWindowNetworkLink(
                data_snapshot=snapshot,
                maintenance_window=window,
                network_link=link_pool[index % len(link_pool)],
            )
            for index, window in enumerate(maintenance_windows)
        ],
        batch_size=batch_size,
    )

    alarm_rows = []
    status_values = expand_counts(config.TIMELINE_TARGETS["alarm_statuses"])
    alarm_type_values = list(alarm_types.values())
    acknowledged_budget = config.TIMELINE_TARGETS["acknowledged_open_alarms"]
    for index in range(1, config.TIMELINE_TARGETS["alarms"] + 1):
        alarm_type = alarm_type_values[(index - 1) % len(alarm_type_values)]
        status = status_values[index - 1]
        detected_at = start + timedelta(minutes=index * 37)
        source_kwargs = choose_alarm_source(
            alarm_type=alarm_type,
            index=index,
            device_pool=device_pool,
            link_pool=link_pool,
            port_pool=port_pool,
            line_pool=line_pool,
            failure_domain_pool=failure_domain_pool,
            sub_conn_pool=sub_conn_pool,
        )
        acknowledged_at = None
        if status == AlarmStatus.OPEN and acknowledged_budget > 0:
            acknowledged_at = detected_at + timedelta(minutes=5)
            acknowledged_budget -= 1
        alarm_rows.append(
            Alarm(
                data_snapshot=snapshot,
                alarm_id=f"ALM-MCR-{index:05d}",
                alarm_type=alarm_type,
                severity=alarm_type.severity,
                status=status,
                detected_at=detected_at,
                received_at=detected_at + timedelta(seconds=5),
                acknowledged_at=acknowledged_at,
                cleared_at=detected_at + timedelta(minutes=20)
                if status == AlarmStatus.CLEARED
                else None,
                last_seen_at=detected_at + timedelta(minutes=index % 20),
                occurrence_count=1 + (index % 4),
                deduplication_key=f"DEDUP-MCR-{index:05d}",
                suppression_reason="noise_suppression" if status == AlarmStatus.SUPPRESSED else "",
                recurrence_group_key=f"REC-MCR-{index % 75:03d}" if index % 11 == 0 else "",
                raw_payload={"synthetic": True},
                metadata={"scenario_code": alarm_config.SCENARIO_TEMPLATES[index % 22]["code"]},
                **source_kwargs,
            )
        )
    Alarm.objects.bulk_create(alarm_rows, batch_size=batch_size)
    alarms = list(Alarm.objects.filter(data_snapshot=snapshot).order_by("alarm_id"))
    incident_alarm_rows = []
    eligible_alarms = [alarm for alarm in alarms if alarm.status != AlarmStatus.SUPPRESSED]
    for index, incident in enumerate(incidents):
        for alarm in eligible_alarms[index * 2 : index * 2 + 2]:
            incident_alarm_rows.append(
                IncidentAlarm(
                    data_snapshot=snapshot,
                    incident=incident,
                    alarm=alarm,
                    role=IncidentAlarmRole.PRIMARY
                    if len(incident_alarm_rows) % 2 == 0
                    else IncidentAlarmRole.SUPPORTING,
                    metadata={"synthetic": True},
                )
            )
    IncidentAlarm.objects.bulk_create(incident_alarm_rows, batch_size=batch_size)

    event_rows = []
    for index in range(1, config.TIMELINE_TARGETS["operational_events"] + 1):
        incident = incidents[index % len(incidents)]
        event_rows.append(
            OperationalEvent(
                data_snapshot=snapshot,
                event_code=f"EVT-MCR-{index:05d}",
                event_type=[
                    OperationalEventType.NOTE,
                    OperationalEventType.MANUAL_INTERVENTION,
                    OperationalEventType.AUTO_RECOVERY,
                    OperationalEventType.MAINTENANCE,
                ][index % 4],
                occurred_at=incident.started_at + timedelta(minutes=index % 60),
                device=incident.primary_device,
                incident=incident,
                source="synthetic_generator",
                summary=f"Synthetic operational event {index:05d}",
                metadata={"synthetic": True},
            )
        )
    OperationalEvent.objects.bulk_create(event_rows, batch_size=batch_size)
    seed_quality_measurements(
        snapshot=snapshot,
        device_pool=device_pool,
        link_pool=link_pool,
        line_pool=line_pool,
        sub_conn_pool=sub_conn_pool,
        start=start,
        batch_size=batch_size,
    )
    return incidents, outages


def choose_alarm_source(
    *,
    alarm_type,
    index,
    device_pool,
    link_pool,
    port_pool,
    line_pool,
    failure_domain_pool,
    sub_conn_pool,
) -> dict:
    source_kinds = list(alarm_type.allowed_source_kinds.values_list("source_kind", flat=True))
    source_kind = source_kinds[0]
    if source_kind == "device":
        supported = list(alarm_type.supported_device_types.values_list("device_type", flat=True))
        devices = [
            device for device in device_pool if not supported or device.device_type in supported
        ]
        return {"device": devices[index % len(devices)]}
    if source_kind == "network_link":
        return {"network_link": link_pool[index % len(link_pool)]}
    if source_kind == "network_port":
        return {"network_port": port_pool[index % len(port_pool)]}
    if source_kind == "line_connection":
        return {"line_connection": line_pool[index % len(line_pool)]}
    if source_kind == "failure_domain":
        return {"failure_domain": failure_domain_pool[index % len(failure_domain_pool)]}
    return {"subscription_connection": sub_conn_pool[index % len(sub_conn_pool)]}


def seed_quality_measurements(
    *,
    snapshot,
    device_pool,
    link_pool,
    line_pool,
    sub_conn_pool,
    start,
    batch_size,
):
    metric_cycle = cycle(
        [
            (QualityMetricType.LATENCY_MS, "ms", Decimal("24.5000")),
            (QualityMetricType.JITTER_MS, "ms", Decimal("6.0000")),
            (QualityMetricType.PACKET_LOSS_PERCENT, "percent", Decimal("0.2500")),
            (QualityMetricType.AVAILABILITY_PERCENT, "percent", Decimal("99.9000")),
            (QualityMetricType.BANDWIDTH_UTILIZATION_PERCENT, "percent", Decimal("72.0000")),
        ]
    )
    rows = []
    for index in range(1, config.TIMELINE_TARGETS["quality_measurements"] + 1):
        metric_type, unit, base_value = next(metric_cycle)
        measured_at = start + timedelta(minutes=index)
        source_kind = index % 4
        kwargs = {}
        if source_kind == 0:
            kwargs["device"] = device_pool[index % len(device_pool)]
        elif source_kind == 1:
            kwargs["network_link"] = link_pool[index % len(link_pool)]
        elif source_kind == 2:
            kwargs["line_connection"] = line_pool[index % len(line_pool)]
        else:
            kwargs["subscription_connection"] = sub_conn_pool[index % len(sub_conn_pool)]
        rows.append(
            QualityMeasurement(
                data_snapshot=snapshot,
                metric_type=metric_type,
                measured_at=measured_at,
                value=base_value + Decimal(index % 17),
                unit=unit,
                metadata={"synthetic": True},
                **kwargs,
            )
        )
    QualityMeasurement.objects.bulk_create(rows, batch_size=batch_size)


def seed_payments(snapshot, subscriptions: list[Subscription], batch_size: int) -> None:
    periods = [
        ("2026-04", date(2026, 4, 1), date(2026, 5, 1), date(2026, 4, 15)),
        ("2026-05", date(2026, 5, 1), date(2026, 6, 1), date(2026, 5, 15)),
        ("2026-06", date(2026, 6, 1), date(2026, 7, 1), date(2026, 6, 15)),
        ("2026-07", date(2026, 7, 1), date(2026, 8, 1), date(2026, 7, 15)),
    ]
    eligible_subscriptions = [
        subscription
        for subscription in subscriptions
        if subscription.status != SubscriptionStatus.PENDING
    ][:14900]
    status_values = expand_counts(commercial_config.PAYMENT_HISTORY["statuses"])
    rows = []
    index = 0
    for subscription in eligible_subscriptions:
        for period, start_date, end_date, due_date in periods:
            status = status_values[index]
            recurring = subscription.monthly_price
            one_time = Decimal("0.00")
            discount = Decimal("0.00") if index % 5 else Decimal("25.00")
            billed = max(Decimal("0.00"), recurring + one_time - discount)
            paid = billed
            paid_at = timezone.make_aware(
                datetime.combine(due_date, datetime.min.time()), ISTANBUL_TZ
            )
            if status == PaymentStatus.PAID_LATE:
                paid_at += timedelta(days=7)
            elif status == PaymentStatus.OVERDUE:
                paid = Decimal("0.00")
                paid_at = None
            elif status == PaymentStatus.PARTIAL:
                paid = (billed / Decimal("2")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                paid_at += timedelta(days=3)
            elif status == PaymentStatus.FAILED:
                paid = Decimal("0.00")
                paid_at = None
            elif status == PaymentStatus.REVERSED:
                paid = Decimal("0.00")
                paid_at = None
            elif status == PaymentStatus.VOIDED:
                recurring = one_time = discount = billed = paid = Decimal("0.00")
                paid_at = None
            outstanding = billed - paid
            rows.append(
                PaymentRecord(
                    data_snapshot=snapshot,
                    subscription=subscription,
                    period=period,
                    amount=billed,
                    billing_period_start=start_date,
                    billing_period_end=end_date,
                    due_date=due_date,
                    recurring_amount=recurring,
                    one_time_amount=one_time,
                    discount_amount=discount,
                    billed_amount=billed,
                    paid_amount=paid,
                    outstanding_amount=outstanding,
                    currency="TRY",
                    status=status,
                    paid_at=paid_at,
                    metadata={"synthetic": True},
                )
            )
            index += 1
    PaymentRecord.objects.bulk_create(rows, batch_size=batch_size)


def seed_campaign_enrollments(snapshot, subscriptions, campaigns, batch_size):
    status_values = expand_counts(commercial_config.CAMPAIGN_ENROLLMENT_TARGETS["statuses"])
    campaign_items = list(campaigns.values())
    rows = []
    eligible_subscriptions = [
        subscription
        for subscription in subscriptions
        if subscription.status != SubscriptionStatus.PENDING
    ]
    for index, status in enumerate(status_values, start=1):
        subscription = eligible_subscriptions[index % len(eligible_subscriptions)]
        campaign = find_compatible_campaign(subscription, campaign_items, index)
        valid_from = parse_datetime("2026-04-01T00:00:00+03:00") + timedelta(days=index % 60)
        valid_to = valid_from + timedelta(days=30 * max(campaign.duration_months, 1))
        rows.append(
            CampaignEnrollment(
                data_snapshot=snapshot,
                subscription=subscription,
                campaign=campaign,
                campaign_code=campaign.code,
                name=campaign.name,
                status=status,
                valid_from=valid_from,
                valid_to=valid_to,
                metadata={"synthetic": True},
            )
        )
    CampaignEnrollment.objects.bulk_create(rows, batch_size=batch_size)


def find_compatible_campaign(subscription, campaigns, index):
    for offset in range(len(campaigns)):
        campaign = campaigns[(index + offset) % len(campaigns)]
        segments = set(campaign.segments.values_list("segment", flat=True))
        service_types = set(campaign.service_types.values_list("service_type", flat=True))
        technologies = set(campaign.technologies.values_list("technology", flat=True))
        if segments and subscription.customer.segment not in segments:
            continue
        if service_types and subscription.service_package.service_type not in service_types:
            continue
        if technologies and subscription.service_package.technology not in technologies:
            continue
        return campaign
    return campaigns[index % len(campaigns)]


def seed_compensation_history_and_evidence(
    *,
    snapshot,
    subscriptions,
    incidents,
    outages,
    rule_set,
    rule_versions,
    batch_size,
) -> None:
    rule_version_cycle = cycle(rule_versions)
    eligible_subscriptions = [
        subscription
        for subscription in subscriptions
        if subscription.status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.SUSPENDED}
    ]
    decision_values = expand_counts(
        commercial_config.COMPENSATION_HISTORY_TARGETS["decision_statuses"]
    )
    settlement_values = expand_counts(
        commercial_config.COMPENSATION_HISTORY_TARGETS["approved_settlement_statuses"]
    )
    settlement_iter = iter(settlement_values)
    history_rows = []
    evaluation_rows = []
    outage_cycle = cycle(outages)
    for index, decision_status in enumerate(decision_values, start=1):
        subscription = eligible_subscriptions[index % len(eligible_subscriptions)]
        incident = incidents[index % len(incidents)]
        outage = (
            next(outage_cycle)
            if incident.service_impact_class != ServiceImpactClass.DEGRADATION
            else None
        )
        rule_version = next(rule_version_cycle)
        if decision_status == CompensationDecisionStatus.APPROVED:
            settlement_status = next(settlement_iter)
            amount = (subscription.monthly_price * Decimal("0.04")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        else:
            settlement_status = CompensationSettlementStatus.NOT_APPLICABLE
            amount = Decimal("0.00")
        decided_at = incident.resolved_at + timedelta(hours=2)
        settled_at = (
            decided_at + timedelta(days=2)
            if settlement_status
            in {
                CompensationSettlementStatus.CREDITED,
                CompensationSettlementStatus.PAID,
            }
            else None
        )
        conflict_group = rule_version.rule.conflict_group or "synthetic"
        history_rows.append(
            CompensationHistory(
                data_snapshot=snapshot,
                subscription=subscription,
                customer=subscription.customer,
                incident=incident,
                outage=outage,
                rule_version=rule_version,
                compensation_conflict_group=f"{conflict_group}-{index:04d}",
                reference_code=f"COMP-HIST-MCR-{index:05d}",
                amount=amount,
                decision_status=decision_status,
                settlement_status=settlement_status,
                currency="TRY",
                reason="Synthetic historical compensation record.",
                decided_at=decided_at,
                settled_at=settled_at,
                idempotency_key=f"mcr-hist-{index:05d}",
                metadata={"synthetic": True},
            )
        )
        if outage is not None and index <= 320:
            result_type = (
                CompensationResultType.ELIGIBLE
                if decision_status == CompensationDecisionStatus.APPROVED
                else CompensationResultType.MANUAL_REVIEW
                if decision_status == CompensationDecisionStatus.MANUAL_REVIEW
                else CompensationResultType.NOT_ELIGIBLE
            )
            evaluation_rows.append(
                CompensationEvaluation(
                    data_snapshot=snapshot,
                    evaluation_code=f"EVAL-MCR-{index:05d}",
                    outage=outage,
                    customer=subscription.customer,
                    subscription=subscription,
                    rule_version=rule_version,
                    result_type=result_type,
                    status=CompensationEvaluationStatus.CALCULATED,
                    proposed_amount=amount,
                    currency="TRY",
                    explanation="Synthetic historical evaluation support record.",
                    calculation_trace={"synthetic": True},
                    metadata={"synthetic": True},
                )
            )
    CompensationHistory.objects.bulk_create(history_rows, batch_size=batch_size)
    CompensationEvaluation.objects.bulk_create(evaluation_rows, batch_size=batch_size)
    evaluations = list(
        CompensationEvaluation.objects.filter(data_snapshot=snapshot).select_related("rule_version")
    )
    evidence_rows = []
    for evaluation in evaluations:
        payload = {
            "evaluation_code": evaluation.evaluation_code,
            "rule": evaluation.rule_version.rule.code,
            "amount": str(evaluation.proposed_amount),
            "decision": evaluation.result_type,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        decision = {
            CompensationResultType.ELIGIBLE: DecisionEvidenceDecision.ELIGIBLE,
            CompensationResultType.NOT_ELIGIBLE: DecisionEvidenceDecision.INELIGIBLE,
            CompensationResultType.MANUAL_REVIEW: DecisionEvidenceDecision.MANUAL_REVIEW,
        }.get(evaluation.result_type, DecisionEvidenceDecision.MANUAL_REVIEW)
        evidence_rows.append(
            DecisionEvidence(
                data_snapshot=snapshot,
                compensation_evaluation=evaluation,
                rule_set=rule_set,
                selected_rule_version=evaluation.rule_version,
                price_basis=evaluation.rule_version.price_basis,
                selected_price=evaluation.subscription.monthly_price,
                unrounded_amount=evaluation.proposed_amount,
                final_amount=evaluation.proposed_amount,
                currency="TRY",
                decision=decision,
                evidence_schema_version=1,
                evidence_hash=digest,
                matched_conditions=[{"code": "synthetic_seed"}],
                failed_conditions=[],
                excluded_rules=[],
                candidate_base_rules=[evaluation.rule_version.rule.code],
                applied_modifiers=[],
                formula_inputs={"synthetic": True},
                cap_floor_trace=[],
                manual_review_reasons=[]
                if decision != DecisionEvidenceDecision.MANUAL_REVIEW
                else ["synthetic_manual_review"],
                context_snapshot=payload,
                finalized=True,
            )
        )
    DecisionEvidence.objects.bulk_create(evidence_rows, batch_size=batch_size)


def collect_seed_counts(snapshot: DataSnapshot) -> dict[str, int]:
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
        "failure_domains": FailureDomain.objects.filter(data_snapshot=snapshot).count(),
        "service_packages": ServicePackage.objects.filter(data_snapshot=snapshot).count(),
        "sla_profiles": SLAProfile.objects.filter(data_snapshot=snapshot).count(),
        "campaigns": Campaign.objects.filter(data_snapshot=snapshot).count(),
        "service_package_price_versions": ServicePackagePriceVersion.objects.filter(
            data_snapshot=snapshot
        ).count(),
        "payment_records": PaymentRecord.objects.filter(data_snapshot=snapshot).count(),
        "campaign_enrollments": CampaignEnrollment.objects.filter(data_snapshot=snapshot).count(),
        "compensation_history": CompensationHistory.objects.filter(data_snapshot=snapshot).count(),
        "compensation_evaluations": CompensationEvaluation.objects.filter(
            data_snapshot=snapshot
        ).count(),
        "decision_evidence": DecisionEvidence.objects.filter(data_snapshot=snapshot).count(),
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


def delete_multicity_realism_dataset_tree(dataset: DatasetVersion) -> None:
    snapshots = list(dataset.snapshots.all())
    for snapshot in snapshots:
        DecisionEvidence.objects.filter(data_snapshot=snapshot).delete()
        CompensationEvaluation.objects.filter(data_snapshot=snapshot).delete()
        CompensationHistory.objects.filter(data_snapshot=snapshot).delete()
        MaintenanceWindowDevice.objects.filter(data_snapshot=snapshot).delete()
        MaintenanceWindowNetworkLink.objects.filter(data_snapshot=snapshot).delete()
        MaintenanceWindow.objects.filter(data_snapshot=snapshot).delete()
        QualityMeasurement.objects.filter(data_snapshot=snapshot).delete()
        Outage.objects.filter(data_snapshot=snapshot).delete()
        OperationalEvent.objects.filter(data_snapshot=snapshot).delete()
        IncidentAlarm.objects.filter(data_snapshot=snapshot).delete()
        Alarm.objects.filter(data_snapshot=snapshot).delete()
        Incident.objects.filter(data_snapshot=snapshot).delete()
        AlarmTypeSupportedDeviceType.objects.filter(data_snapshot=snapshot).delete()
        AlarmTypeAllowedSourceKind.objects.filter(data_snapshot=snapshot).delete()
        AlarmType.objects.filter(data_snapshot=snapshot).delete()
        RuleVersion.objects.filter(data_snapshot=snapshot).delete()
        Rule.objects.filter(data_snapshot=snapshot).delete()
        RuleSet.objects.filter(data_snapshot=snapshot).delete()
        CampaignEnrollment.objects.filter(data_snapshot=snapshot).delete()
        CampaignAllowedSegment.objects.filter(data_snapshot=snapshot).delete()
        CampaignAllowedServiceType.objects.filter(data_snapshot=snapshot).delete()
        CampaignAllowedTechnology.objects.filter(data_snapshot=snapshot).delete()
        Campaign.objects.filter(data_snapshot=snapshot).delete()
        PaymentRecord.objects.filter(data_snapshot=snapshot).delete()
        SubscriptionConnection.objects.filter(data_snapshot=snapshot).delete()
        Subscription.objects.filter(data_snapshot=snapshot).delete()
        ServicePackageAllowedSegment.objects.filter(data_snapshot=snapshot).delete()
        ServicePackagePriceVersion.objects.filter(data_snapshot=snapshot).delete()
        ServicePackage.objects.filter(data_snapshot=snapshot).delete()
        SLAProfile.objects.filter(data_snapshot=snapshot).delete()
        Customer.objects.filter(data_snapshot=snapshot).delete()
        DeviceFailureDomainMembership.objects.filter(data_snapshot=snapshot).delete()
        NetworkLinkFailureDomainMembership.objects.filter(data_snapshot=snapshot).delete()
        LineConnectionFailureDomainMembership.objects.filter(data_snapshot=snapshot).delete()
        FailureDomain.objects.filter(data_snapshot=snapshot).delete()
        LineConnection.objects.filter(data_snapshot=snapshot).delete()
        NetworkLink.objects.filter(data_snapshot=snapshot).delete()
        NetworkPort.objects.filter(data_snapshot=snapshot).delete()
        AccessSegment.objects.filter(data_snapshot=snapshot).delete()
        NetworkDevice.objects.filter(data_snapshot=snapshot).delete()
        snapshot.delete()
    dataset.delete()
