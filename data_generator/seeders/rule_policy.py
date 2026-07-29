from django.utils.dateparse import parse_datetime

from apps.rules.models import Rule, RuleSet, RuleStatus, RuleType, RuleVersion, RuleVersionStatus
from data_generator.configs import synthetic_compensation_policy_v1 as policy_config


def seed_synthetic_compensation_policy(snapshot) -> RuleSet:
    rule_set_config = policy_config.RULE_SET
    rule_set, _ = RuleSet.objects.update_or_create(
        data_snapshot=snapshot,
        code=rule_set_config["code"],
        version=rule_set_config["version"],
        defaults={
            "name": rule_set_config["name"],
            "effective_from": parse_required_datetime(rule_set_config["effective_from"]),
            "effective_to": parse_optional_datetime(rule_set_config["effective_to"]),
            "active": rule_set_config["active"],
            "change_reason": rule_set_config["change_reason"],
            "metadata": {"synthetic_policy_only": True},
        },
    )
    for rule_config in policy_config.RULES:
        rule, _ = Rule.objects.update_or_create(
            data_snapshot=snapshot,
            code=rule_config["code"],
            defaults={
                "rule_set": rule_set,
                "name": rule_config["name"],
                "rule_type": RuleType.COMPENSATION,
                "family": rule_config["family"],
                "conflict_group": rule_config["conflict_group"],
                "status": RuleStatus.ACTIVE,
                "description": "Synthetic rule for realistic simulation dataset.",
                "metadata": {"synthetic_policy_only": True},
            },
        )
        RuleVersion.objects.update_or_create(
            data_snapshot=snapshot,
            rule=rule,
            version=rule_set.version,
            defaults={
                "status": RuleVersionStatus.ACTIVE,
                "priority": rule_config["priority"],
                "action_type": rule_config["action_type"],
                "price_basis": rule_config["price_basis"],
                "stackable": rule_config["stackable"],
                "active": True,
                "valid_from": rule_set.effective_from,
                "valid_to": rule_set.effective_to,
                "condition_tree": rule_config["condition_tree"],
                "action_config": rule_config["action_config"],
                "change_note": "Initial synthetic policy v1.",
                "metadata": {"synthetic_policy_only": True},
            },
        )
    return rule_set


def parse_required_datetime(value: str):
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid datetime value: {value}")
    return parsed


def parse_optional_datetime(value: str | None):
    if value is None:
        return None
    return parse_required_datetime(value)
