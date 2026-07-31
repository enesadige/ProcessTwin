from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from apps.compensation.models import DecisionEvidence
from apps.network.internal_serializers import iso_or_none, json_safe, snapshot_summary
from apps.rules.models import Rule, RuleSet, RuleVersion
from apps.rules.services.schema import validate_action_config, validate_condition_tree


def safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json_safe(payload)


def rule_set_summary(rule_set: RuleSet | None) -> dict[str, Any] | None:
    if rule_set is None:
        return None
    return {
        "code": rule_set.code,
        "version": rule_set.version,
        "name": rule_set.name,
        "effective_from": iso_or_none(rule_set.effective_from),
        "effective_to": iso_or_none(rule_set.effective_to),
        "active": rule_set.active,
        "change_reason": rule_set.change_reason,
    }


def rule_summary(rule: Rule) -> dict[str, Any]:
    return {
        "code": rule.code,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "family": rule.family,
        "conflict_group": rule.conflict_group,
        "status": rule.status,
        "description": rule.description,
        "rule_set": rule_set_summary(rule.rule_set),
    }


def version_summary(version: RuleVersion | None) -> dict[str, Any] | None:
    if version is None:
        return None
    return {
        "rule_code": version.rule.code,
        "version": version.version,
        "status": version.status,
        "priority": version.priority,
        "action_type": version.action_type,
        "price_basis": version.price_basis,
        "stackable": version.stackable,
        "active": version.active,
        "valid_from": iso_or_none(version.valid_from),
        "valid_to": iso_or_none(version.valid_to),
        "change_note": version.change_note,
        "rule_set": rule_set_summary(version.rule.rule_set),
    }


def version_detail(
    version: RuleVersion,
    *,
    include_raw_config: bool,
    include_schema_summary: bool,
) -> dict[str, Any]:
    payload = {
        **version_summary(version),
        "condition_summary": condition_human_summary(version.condition_tree),
        "action_summary": action_human_summary(version),
    }
    if include_schema_summary:
        payload["schema_summary"] = schema_summary(version)
    if include_raw_config:
        payload["condition_tree"] = version.condition_tree
        payload["action_config"] = version.action_config
    return payload


def schema_summary(version: RuleVersion) -> dict[str, Any]:
    condition_result = validate_condition_tree(version.condition_tree)
    action_result = validate_action_config(version.action_type, version.action_config)
    return {
        "condition_tree_valid": condition_result.valid,
        "action_config_valid": action_result.valid,
        "required_condition_fields": condition_result.required_fields,
        "errors": condition_result.errors + action_result.errors,
    }


def condition_human_summary(condition_tree: dict[str, Any]) -> dict[str, Any]:
    fields: list[str] = []
    operators: list[str] = []
    condition_count = 0

    def walk(node: Any) -> None:
        nonlocal condition_count
        if not isinstance(node, dict):
            return
        if "conditions" in node:
            for child in node.get("conditions") or []:
                walk(child)
            return
        if "all" in node or "any" in node:
            for child in node.get("all") or node.get("any") or []:
                walk(child)
            return
        field = node.get("field")
        operator = node.get("operator", node.get("op"))
        if field:
            fields.append(str(field))
        if operator:
            operators.append(str(operator))
        condition_count += 1

    walk(condition_tree)
    return {
        "condition_count": condition_count,
        "fields": sorted(set(fields)),
        "operators": sorted(set(operators)),
        "summary": "; ".join(
            f"{field} uses {count} condition(s)"
            for field, count in sorted(Counter(fields).items())
        ),
    }


def action_human_summary(version: RuleVersion) -> dict[str, Any]:
    action = version.action_config or {}
    summary = {
        "action_type": version.action_type,
        "price_basis": version.price_basis,
        "stackable": version.stackable,
        "keys": sorted(action.keys()),
    }
    if "tiers" in action:
        summary["tiers"] = [
            {
                "min_seconds": tier.get("min_seconds"),
                "rate": tier.get("rate"),
            }
            for tier in action.get("tiers", [])
        ]
    if "exceedance_tiers" in action:
        summary["exceedance_tiers"] = [
            {
                "min_ratio_exclusive": tier.get("min_ratio_exclusive"),
                "rate": tier.get("rate"),
            }
            for tier in action.get("exceedance_tiers", [])
        ]
    for key in (
        "incident_cap_percent",
        "monthly_cumulative_cap_percent",
        "minimum_positive_amount",
        "modifier_rate",
        "max_modifier_rate",
        "reason_code",
    ):
        if key in action:
            summary[key] = action[key]
    return summary


def decision_evidence_summary(record: DecisionEvidence) -> dict[str, Any]:
    evaluation = record.compensation_evaluation if record.compensation_evaluation_id else None
    return {
        "evidence_hash": record.evidence_hash,
        "decision": record.decision,
        "rule_set": rule_set_summary(record.rule_set),
        "selected_rule_version": version_summary(record.selected_rule_version),
        "price_basis": record.price_basis,
        "selected_price": decimal_or_none(record.selected_price),
        "unrounded_amount": decimal_or_none(record.unrounded_amount),
        "final_amount": str(record.final_amount),
        "currency": record.currency,
        "matched_conditions": record.matched_conditions,
        "failed_conditions": record.failed_conditions,
        "excluded_rules": record.excluded_rules,
        "candidate_base_rules": record.candidate_base_rules,
        "applied_modifiers": record.applied_modifiers,
        "manual_review_reasons": record.manual_review_reasons,
        "created_at": iso_or_none(record.created_at),
        "finalized": record.finalized,
        "compensation_evaluation": (
            {
                "evaluation_code": evaluation.evaluation_code,
                "result_type": evaluation.result_type,
                "status": evaluation.status,
                "outage_code": evaluation.outage.outage_code,
                "subscription_number": evaluation.subscription.subscription_number,
                "customer_number": evaluation.customer.customer_number,
            }
            if evaluation
            else None
        ),
    }


def decimal_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def snapshot_payload(snapshot) -> dict[str, Any]:
    return snapshot_summary(snapshot)
