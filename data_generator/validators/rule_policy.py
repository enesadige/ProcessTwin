from dataclasses import dataclass

from apps.rules.models import RuleActionType, RuleFamily, RulePriceBasis
from apps.rules.services.schema import validate_action_config, validate_condition_tree
from data_generator.configs import synthetic_compensation_policy_v1 as policy_config


@dataclass(frozen=True)
class RulePolicyConfigCheck:
    name: str
    expected: object
    actual: object
    passed: bool


def validate_synthetic_compensation_policy_config() -> list[RulePolicyConfigCheck]:
    checks: list[RulePolicyConfigCheck] = []
    rules = policy_config.RULES
    checks.append(
        RulePolicyConfigCheck(
            name="rule_count",
            expected=policy_config.CATALOG_TARGETS["rule_count"],
            actual=len(rules),
            passed=len(rules) == policy_config.CATALOG_TARGETS["rule_count"],
        )
    )
    rule_codes = [rule["code"] for rule in rules]
    checks.append(
        RulePolicyConfigCheck(
            name="unique_rule_codes",
            expected=len(rule_codes),
            actual=len(set(rule_codes)),
            passed=len(rule_codes) == len(set(rule_codes)),
        )
    )
    checks.append(
        RulePolicyConfigCheck(
            name="rule_set_code",
            expected="SYN-COMP-2026",
            actual=policy_config.RULE_SET["code"],
            passed=policy_config.RULE_SET["code"] == "SYN-COMP-2026",
        )
    )
    checks.extend(_validate_each_rule(rules))
    checks.append(
        RulePolicyConfigCheck(
            name="ground_truth_candidate_count",
            expected=policy_config.CATALOG_TARGETS["ground_truth_candidate_count"],
            actual=len(policy_config.GROUND_TRUTH_CANDIDATES),
            passed=len(policy_config.GROUND_TRUTH_CANDIDATES)
            == policy_config.CATALOG_TARGETS["ground_truth_candidate_count"],
        )
    )
    return checks


def _validate_each_rule(rules: list[dict]) -> list[RulePolicyConfigCheck]:
    checks: list[RulePolicyConfigCheck] = []
    family_values = {choice.value for choice in RuleFamily}
    action_values = {choice.value for choice in RuleActionType}
    price_basis_values = {choice.value for choice in RulePriceBasis}
    for rule in rules:
        code = rule["code"]
        condition_result = validate_condition_tree(rule["condition_tree"])
        action_result = validate_action_config(rule["action_type"], rule["action_config"])
        checks.append(
            RulePolicyConfigCheck(
                name=f"{code}.condition_schema",
                expected=[],
                actual=condition_result.errors,
                passed=condition_result.valid,
            )
        )
        checks.append(
            RulePolicyConfigCheck(
                name=f"{code}.action_schema",
                expected=[],
                actual=action_result.errors,
                passed=action_result.valid,
            )
        )
        checks.append(
            RulePolicyConfigCheck(
                name=f"{code}.family",
                expected="known family",
                actual=rule["family"],
                passed=rule["family"] in family_values,
            )
        )
        checks.append(
            RulePolicyConfigCheck(
                name=f"{code}.action_type",
                expected="known action_type",
                actual=rule["action_type"],
                passed=rule["action_type"] in action_values,
            )
        )
        checks.append(
            RulePolicyConfigCheck(
                name=f"{code}.price_basis",
                expected="known price_basis",
                actual=rule["price_basis"],
                passed=rule["price_basis"] in price_basis_values,
            )
        )
    return checks
