import hashlib
import json
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils.dateparse import parse_datetime

from apps.customers.models import Customer, Subscription, SubscriptionConnection
from apps.datasets.models import DataSnapshot, GroundTruthCase, GroundTruthEligibility
from apps.network.models import NetworkDevice, NetworkDeviceType
from apps.operations.models import Outage
from data_generator.configs import maltepe_mvp_v1 as seed_config

FULL_OUTAGE_TYPE = "full_outage"
RULE_CODE = seed_config.REFUND_RULE_PLAN["code"]


def seed_ground_truth(*, snapshot: DataSnapshot) -> dict[str, int]:
    cases_created = 0
    for scenario in build_ground_truth_scenarios():
        create_ground_truth_case(snapshot=snapshot, scenario=scenario)
        cases_created += 1
    return {"ground_truth_cases": cases_created}


def build_ground_truth_scenarios() -> list[dict]:
    return [seed_config.OUTAGE_PLAN["main"], *seed_config.OUTAGE_PLAN["secondary"]]


def create_ground_truth_case(*, snapshot: DataSnapshot, scenario: dict) -> GroundTruthCase:
    outage = Outage.objects.select_related("incident", "source_device").get(
        data_snapshot=snapshot,
        outage_code=scenario["outage_code"],
    )
    affected_connections = get_affected_subscription_connections(
        snapshot=snapshot,
        source_device=outage.source_device,
        started_at=outage.started_at,
        ended_at=outage.ended_at,
    )
    affected_subscriptions = [connection.subscription for connection in affected_connections]
    affected_customers = sorted(
        {subscription.customer for subscription in affected_subscriptions},
        key=lambda customer: customer.customer_number,
    )
    affected_subscription_codes = sorted(
        subscription.subscription_number for subscription in affected_subscriptions
    )
    affected_customer_codes = [customer.customer_number for customer in affected_customers]
    expected_rule_version = select_expected_rule_version_number(outage.started_at)
    expected_eligibility, expected_reason_code = determine_expected_eligibility(
        duration_minutes=scenario["duration_minutes"],
        expected_rule_version=expected_rule_version,
    )
    expected_total_refund_amount = calculate_total_refund_amount(
        subscriptions=affected_subscriptions,
        expected_eligibility=expected_eligibility,
    )

    return save_clean(
        GroundTruthCase(
            data_snapshot=snapshot,
            case_code=f"GT-{scenario['outage_code']}",
            outage_code=scenario["outage_code"],
            expected_source_device_code=scenario["source_device"],
            expected_incident_code=scenario["incident_number"],
            expected_alarm_type_codes=get_expected_alarm_type_codes(scenario),
            expected_duration_minutes=scenario["duration_minutes"],
            expected_rule_code=RULE_CODE,
            expected_rule_version=expected_rule_version,
            affected_subscription_codes=affected_subscription_codes,
            affected_subscription_hash=hash_codes(affected_subscription_codes),
            affected_subscription_count=len(affected_subscription_codes),
            affected_customer_codes=affected_customer_codes,
            affected_customer_hash=hash_codes(affected_customer_codes),
            affected_customer_count=len(affected_customer_codes),
            unaffected_subscription_count=Subscription.objects.filter(
                data_snapshot=snapshot
            ).count()
            - len(affected_subscription_codes),
            unaffected_customer_count=Customer.objects.filter(data_snapshot=snapshot).count()
            - len(affected_customer_codes),
            affected_segment_counts=normalize_counter(
                Counter(customer.segment for customer in affected_customers)
            ),
            affected_priority_counts=normalize_counter(
                Counter(customer.priority_level for customer in affected_customers)
            ),
            expected_eligibility=expected_eligibility,
            expected_reason_code=expected_reason_code,
            expected_total_refund_amount=expected_total_refund_amount,
            currency=seed_config.REFUND_RULE_PLAN["refund_formula"]["currency"],
            metadata={
                "seed_role": "ground_truth_case",
                "oracle_source": "seed_config_and_business_codes",
                "does_not_use_production_customer_impact_service": True,
                "does_not_use_production_compensation_service": True,
                "outage_type": FULL_OUTAGE_TYPE,
                "subscription_refund_amounts": build_subscription_refund_amounts(
                    affected_subscriptions,
                    expected_eligibility,
                ),
            },
        )
    )


def get_affected_subscription_connections(
    *,
    snapshot: DataSnapshot,
    source_device: NetworkDevice,
    started_at,
    ended_at,
) -> list[SubscriptionConnection]:
    connections = (
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            is_active=True,
            valid_from__lt=ended_at,
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=started_at))
        .select_related(
            "subscription",
            "subscription__customer",
            "line_connection__port__device",
        )
        .order_by("subscription__subscription_number")
    )
    return [
        connection
        for connection in connections
        if connection_matches_source_device(connection, source_device)
    ]


def connection_matches_source_device(
    connection: SubscriptionConnection,
    source_device: NetworkDevice,
) -> bool:
    line_device = connection.line_connection.port.device
    if source_device.device_type == NetworkDeviceType.BNG:
        return line_device.metadata.get("parent_bng") == source_device.code
    return line_device.code == source_device.code


def select_expected_rule_version_number(moment) -> int:
    matching_versions = []
    for version_config in seed_config.REFUND_RULE_PLAN["versions"]:
        valid_from = parse_required_datetime(version_config["valid_from"])
        valid_to = parse_optional_datetime(version_config["valid_to"])
        if valid_from <= moment and (valid_to is None or moment < valid_to):
            matching_versions.append(version_config)
    if len(matching_versions) != 1:
        raise ValueError("Ground truth rule version selection must resolve to exactly one version.")
    return matching_versions[0]["version"]


def determine_expected_eligibility(
    *,
    duration_minutes: int,
    expected_rule_version: int,
) -> tuple[str, str]:
    version_config = next(
        version
        for version in seed_config.REFUND_RULE_PLAN["versions"]
        if version["version"] == expected_rule_version
    )
    if duration_minutes >= version_config["minimum_impact_minutes"]:
        return GroundTruthEligibility.ELIGIBLE, "duration_threshold_met"
    return GroundTruthEligibility.INELIGIBLE, "duration_below_threshold"


def calculate_total_refund_amount(
    *,
    subscriptions: list[Subscription],
    expected_eligibility: str,
) -> Decimal:
    if expected_eligibility != GroundTruthEligibility.ELIGIBLE:
        return Decimal("0.00")
    return sum(
        (calculate_subscription_refund_amount(subscription) for subscription in subscriptions),
        Decimal("0.00"),
    )


def calculate_subscription_refund_amount(subscription: Subscription) -> Decimal:
    percentage = Decimal(seed_config.REFUND_RULE_PLAN["refund_formula"]["percentage"])
    return (subscription.monthly_price * percentage).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def build_subscription_refund_amounts(
    subscriptions: list[Subscription],
    expected_eligibility: str,
) -> list[dict[str, str]]:
    return [
        {
            "subscription_code": subscription.subscription_number,
            "expected_refund_amount": str(
                calculate_subscription_refund_amount(subscription)
                if expected_eligibility == GroundTruthEligibility.ELIGIBLE
                else Decimal("0.00")
            ),
            "currency": seed_config.REFUND_RULE_PLAN["refund_formula"]["currency"],
        }
        for subscription in sorted(subscriptions, key=lambda item: item.subscription_number)
    ]


def get_expected_alarm_type_codes(scenario: dict) -> list[str]:
    alarm_codes = [scenario["alarm_type"]]
    if supporting_alarm_type := scenario.get("supporting_alarm_type"):
        alarm_codes.append(supporting_alarm_type)
    return sorted(alarm_codes)


def hash_codes(codes: list[str]) -> str:
    encoded = json.dumps(codes, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def normalize_counter(counter: Counter) -> dict[str, int]:
    return dict(sorted(counter.items()))


def parse_required_datetime(value: str):
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid datetime value: {value}")
    return parsed


def parse_optional_datetime(value: str | None):
    if value is None:
        return None
    return parse_required_datetime(value)


def save_clean(instance):
    instance.full_clean()
    instance.save()
    return instance
