from django.utils.dateparse import parse_datetime

from apps.datasets.models import DataSnapshot
from apps.rules.models import Rule, RuleStatus, RuleType, RuleVersion, RuleVersionStatus
from data_generator.configs import maltepe_mvp_v1 as seed_config


def seed_rules(*, snapshot: DataSnapshot) -> dict[str, int]:
    rule = create_refund_rule(snapshot)
    versions_created = 0
    for version_config in seed_config.REFUND_RULE_PLAN["versions"]:
        create_refund_rule_version(
            snapshot=snapshot,
            rule=rule,
            version_config=version_config,
        )
        versions_created += 1
    return {
        "rules": 1,
        "rule_versions": versions_created,
    }


def create_refund_rule(snapshot: DataSnapshot) -> Rule:
    rule_config = seed_config.REFUND_RULE_PLAN
    return save_clean(
        Rule(
            data_snapshot=snapshot,
            code=rule_config["code"],
            name=rule_config["name"],
            rule_type=RuleType(rule_config["rule_type"]),
            status=RuleStatus(rule_config["status"]),
            description=rule_config["description"],
            metadata={
                "seed_role": "refund_rule",
                "synthetic_demo_policy": True,
                "payment_campaign_history_deferred": True,
            },
        )
    )


def create_refund_rule_version(
    *,
    snapshot: DataSnapshot,
    rule: Rule,
    version_config: dict,
) -> RuleVersion:
    minimum_impact_minutes = version_config["minimum_impact_minutes"]
    return save_clean(
        RuleVersion(
            data_snapshot=snapshot,
            rule=rule,
            version=version_config["version"],
            status=RuleVersionStatus(version_config["status"]),
            valid_from=parse_required_datetime(version_config["valid_from"]),
            valid_to=parse_optional_datetime(version_config["valid_to"]),
            condition_tree=build_condition_tree(minimum_impact_minutes),
            action_config=build_action_config(minimum_impact_minutes),
            metadata={
                "seed_role": "refund_rule_version",
                "synthetic_demo_policy": True,
                "segment_specific_behavior": False,
                "vip_specific_behavior": False,
                "payment_campaign_history_deferred": True,
            },
        )
    )


def build_condition_tree(minimum_impact_minutes: int) -> dict:
    return {
        "operator": "all",
        "conditions": [
            {
                "field": "outage_type",
                "op": "==",
                "value": "full_outage",
            },
            {
                "field": "subscription_active_during_outage",
                "op": "==",
                "value": True,
            },
            {
                "field": "subscription_connection_overlaps_outage",
                "op": "==",
                "value": True,
            },
            {
                "field": "impact_duration_minutes",
                "op": ">=",
                "value": minimum_impact_minutes,
            },
        ],
        "missing_required_data_result": "manual_review",
    }


def build_action_config(minimum_impact_minutes: int) -> dict:
    return {
        "action": "calculate_refund_candidate",
        "result_on_missing_required_data": "manual_review",
        "minimum_impact_minutes": minimum_impact_minutes,
        "refund_formula": seed_config.REFUND_RULE_PLAN["refund_formula"],
        "segment_overrides": {},
        "priority_overrides": {},
        "excluded_deferred_inputs": seed_config.REFUND_RULE_PLAN["deferred_inputs"],
    }


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
