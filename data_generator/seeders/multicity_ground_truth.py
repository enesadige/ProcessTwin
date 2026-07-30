from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal
from typing import Any

from django.db.models import Q

from apps.customers.models import Customer, Subscription, SubscriptionConnection
from apps.datasets.models import DataSnapshot, GroundTruthCase, GroundTruthEligibility
from apps.network.models import (
    LineConnection,
    LineConnectionStatus,
    NetworkLink,
    NetworkPort,
    NetworkPortStatus,
)
from apps.operations.models import Incident, Outage
from data_generator.configs import multicity_ground_truth_v1 as config


def seed_multicity_ground_truth(snapshot: DataSnapshot) -> dict[str, int]:
    GroundTruthCase.objects.filter(
        data_snapshot=snapshot,
        metadata__seed_role="multicity_ground_truth_v1",
    ).delete()
    cases = [
        build_ground_truth_case(snapshot=snapshot, case_config=item)
        for item in config.GROUND_TRUTH_CASES
    ]
    GroundTruthCase.objects.bulk_create(cases)
    return {"ground_truth_cases": len(cases)}


def build_ground_truth_case(
    *, snapshot: DataSnapshot, case_config: dict[str, Any]
) -> GroundTruthCase:
    outage = find_outage(snapshot=snapshot, case_config=case_config)
    incident = find_incident(snapshot=snapshot, case_config=case_config, outage=outage)
    affected_subscriptions = (
        collect_oracle_affected_subscriptions(snapshot=snapshot, outage=outage)
        if outage is not None
        else []
    )
    affected_customers = sorted(
        {subscription.customer for subscription in affected_subscriptions},
        key=lambda customer: customer.customer_number,
    )
    subscription_codes = sorted(
        subscription.subscription_number for subscription in affected_subscriptions
    )
    customer_codes = [customer.customer_number for customer in affected_customers]
    duration_minutes = 0
    if outage is not None and outage.ended_at:
        duration_minutes = int((outage.ended_at - outage.started_at).total_seconds() // 60)

    expected_decision = case_config["expected_decision"]
    eligibility = {
        "eligible": GroundTruthEligibility.ELIGIBLE,
        "ineligible": GroundTruthEligibility.INELIGIBLE,
        "manual_review": GroundTruthEligibility.MANUAL_REVIEW,
        "evidence_only": GroundTruthEligibility.INELIGIBLE,
    }[expected_decision]
    expected_amount = Decimal(case_config["expected_exact_amount"])

    return GroundTruthCase(
        data_snapshot=snapshot,
        case_code=case_config["case_code"],
        outage_code=case_config.get("outage_code") or f"NO-OUTAGE-{case_config['case_code']}",
        expected_source_device_code=get_expected_source_device_code(outage, incident),
        expected_incident_code=case_config.get("incident_number", ""),
        expected_alarm_type_codes=get_expected_alarm_type_codes(case_config),
        expected_duration_minutes=duration_minutes,
        expected_rule_code=case_config["expected_selected_rule"],
        expected_rule_version=config.RULE_SET_VERSION,
        affected_subscription_codes=subscription_codes,
        affected_subscription_hash=hash_codes(subscription_codes),
        affected_subscription_count=len(subscription_codes),
        affected_customer_codes=customer_codes,
        affected_customer_hash=hash_codes(customer_codes),
        affected_customer_count=len(customer_codes),
        unaffected_subscription_count=Subscription.objects.filter(data_snapshot=snapshot).count()
        - len(subscription_codes),
        unaffected_customer_count=Customer.objects.filter(data_snapshot=snapshot).count()
        - len(customer_codes),
        affected_segment_counts=normalize_counter(
            Counter(customer.segment for customer in affected_customers)
        ),
        affected_priority_counts=normalize_counter(
            Counter(customer.priority_level for customer in affected_customers)
        ),
        expected_eligibility=eligibility,
        expected_reason_code=case_config.get("expected_manual_review_reason")
        or case_config.get("expected_modifier_or_cap")
        or expected_decision,
        expected_total_refund_amount=expected_amount,
        currency=config.CURRENCY,
        metadata={
            "seed_role": "multicity_ground_truth_v1",
            "ground_truth_version": config.GROUND_TRUTH_VERSION,
            "oracle_source": "static_config_and_direct_topology_query",
            "does_not_use_production_customer_impact_service": True,
            "does_not_use_production_compensation_service": True,
            **case_config,
        },
    )


def find_outage(*, snapshot: DataSnapshot, case_config: dict[str, Any]) -> Outage | None:
    outage_code = case_config.get("outage_code")
    if not outage_code:
        return None
    return Outage.objects.select_related("incident", "source_device").get(
        data_snapshot=snapshot,
        outage_code=outage_code,
    )


def find_incident(
    *,
    snapshot: DataSnapshot,
    case_config: dict[str, Any],
    outage: Outage | None,
) -> Incident | None:
    if outage is not None:
        return outage.incident
    incident_number = case_config.get("incident_number")
    if not incident_number:
        return None
    return Incident.objects.select_related("primary_device").get(
        data_snapshot=snapshot,
        incident_number=incident_number,
    )


def collect_oracle_affected_subscriptions(
    *,
    snapshot: DataSnapshot,
    outage: Outage,
) -> list[Subscription]:
    device_ids = collect_descendant_device_ids(
        snapshot=snapshot, source_device_id=outage.source_device_id
    )
    port_ids = list(
        NetworkPort.objects.filter(
            data_snapshot=snapshot,
            device_id__in=device_ids,
            inventory_status=NetworkPortStatus.ACTIVE,
        ).values_list("id", flat=True)
    )
    line_ids = list(
        LineConnection.objects.filter(
            data_snapshot=snapshot,
            is_active=True,
            status=LineConnectionStatus.ACTIVE,
            port_id__in=port_ids,
        )
        .filter(valid_from__lt=outage.ended_at)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=outage.started_at))
        .values_list("id", flat=True)
    )
    subscription_ids = list(
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            is_active=True,
            connection_role="primary",
            line_connection_id__in=line_ids,
            subscription__data_snapshot=snapshot,
            subscription__is_active=True,
            subscription__status="active",
            subscription__customer__data_snapshot=snapshot,
        )
        .filter(valid_from__lt=outage.ended_at)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=outage.started_at))
        .filter(subscription__valid_from__lt=outage.ended_at)
        .filter(
            Q(subscription__valid_to__isnull=True) | Q(subscription__valid_to__gt=outage.started_at)
        )
        .values_list("subscription_id", flat=True)
    )
    backup_protected_ids = set(
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            is_active=True,
            connection_role="backup",
            subscription_id__in=subscription_ids,
            line_connection__data_snapshot=snapshot,
            line_connection__is_active=True,
            line_connection__status=LineConnectionStatus.ACTIVE,
            line_connection__port__data_snapshot=snapshot,
            line_connection__port__inventory_status=NetworkPortStatus.ACTIVE,
        )
        .exclude(line_connection__port__device_id__in=device_ids)
        .filter(valid_from__lt=outage.ended_at)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=outage.started_at))
        .filter(line_connection__valid_from__lt=outage.ended_at)
        .filter(
            Q(line_connection__valid_to__isnull=True)
            | Q(line_connection__valid_to__gt=outage.started_at)
        )
        .values_list("subscription_id", flat=True)
    )
    impacted_subscription_ids = [
        subscription_id
        for subscription_id in subscription_ids
        if subscription_id not in backup_protected_ids
    ]
    return list(
        Subscription.objects.filter(id__in=impacted_subscription_ids)
        .select_related("customer", "service_package")
        .order_by("subscription_number")
    )


def collect_descendant_device_ids(*, snapshot: DataSnapshot, source_device_id: int) -> set[int]:
    descendants = {source_device_id}
    frontier = [source_device_id]
    while frontier:
        children = list(
            NetworkLink.objects.filter(
                data_snapshot=snapshot,
                source_device_id__in=frontier,
            ).values_list("target_device_id", flat=True)
        )
        frontier = [device_id for device_id in children if device_id not in descendants]
        descendants.update(frontier)
    return descendants


def get_expected_source_device_code(outage: Outage | None, incident: Incident | None) -> str:
    if outage is not None and outage.source_device_id:
        return outage.source_device.code
    if incident is not None and incident.primary_device_id:
        return incident.primary_device.code
    return ""


def get_expected_alarm_type_codes(case_config: dict[str, Any]) -> list[str]:
    scenario_code = case_config.get("scenario_code", "")
    if not scenario_code.startswith("SCN-"):
        return []
    from data_generator.configs.realistic_alarm_catalog_v1 import SCENARIO_TEMPLATES

    for scenario in SCENARIO_TEMPLATES:
        if scenario["code"] == scenario_code:
            return sorted(scenario.get("alarm_codes", []))
    return []


def hash_codes(codes: list[str]) -> str:
    encoded = json.dumps(codes, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def normalize_counter(counter: Counter) -> dict[str, int]:
    return dict(sorted(counter.items()))
