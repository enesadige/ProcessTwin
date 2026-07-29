from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.rules.models import RuleActionType, RulePriceBasis

SUPPORTED_CONDITION_OPERATORS = frozenset(
    {"eq", "not_eq", "gte", "gt", "lte", "lt", "in", "not_in"}
)
SUPPORTED_GROUP_OPERATORS = frozenset({"all", "any"})
ALLOWED_CONDITION_FIELDS = frozenset(
    {
        "affected_capacity_ratio",
        "affected_duration_seconds",
        "backup_required_missing",
        "billing_period_seconds",
        "billing_period_cumulative_amount",
        "connection_active_during_outage",
        "customer_impacted",
        "duplicate_final_compensation_exists",
        "exceedance_ratio",
        "failover_result",
        "impact_class",
        "incident_cap_percent",
        "incident_type",
        "maintenance_overrun_minutes",
        "minimum_duration_seconds",
        "outage_duration_seconds",
        "outage_type",
        "observed_path_diversity",
        "payment_status",
        "planned_maintenance_notified",
        "price_available",
        "probable_cause_family",
        "protection_loss_only",
        "quality_severity",
        "recurring_incident_count",
        "required_path_diversity",
        "restoration_target_breached",
        "root_cause_known",
        "service_type",
        "sla_contractual",
        "subscription_active_during_outage",
        "subscription_connection_overlaps_outage",
        "subscription_status",
        "suspension_reason",
        "transition_duration_seconds",
    }
)


class RuleSchemaValidationError(ValueError):
    """Raised when deterministic rule config violates the supported schema."""


@dataclass(frozen=True)
class RuleSchemaValidationResult:
    valid: bool
    errors: list[str]
    required_fields: list[str]


def validate_condition_tree(condition_tree: dict[str, Any]) -> RuleSchemaValidationResult:
    errors: list[str] = []
    required_fields: set[str] = set()
    _validate_condition_node(
        condition_tree, errors=errors, required_fields=required_fields, path="condition_tree"
    )
    return RuleSchemaValidationResult(
        valid=not errors,
        errors=errors,
        required_fields=sorted(required_fields),
    )


def validate_action_config(
    action_type: str, action_config: dict[str, Any]
) -> RuleSchemaValidationResult:
    errors: list[str] = []
    if not isinstance(action_config, dict):
        return RuleSchemaValidationResult(
            valid=False,
            errors=["action_config must be an object."],
            required_fields=[],
        )

    supported_action_types = {choice.value for choice in RuleActionType}
    if action_type not in supported_action_types:
        errors.append(f"Unsupported action_type: {action_type}")

    if action_type == RuleActionType.TIERED_PERCENTAGE:
        _validate_tiers(action_config, errors)
        _validate_percent(action_config, "incident_cap_percent", errors, required=False)
    elif action_type == RuleActionType.PRORATED:
        _validate_decimal_field(action_config, "minimum_duration_seconds", errors, required=True)
        _validate_percent(action_config, "incident_cap_percent", errors, required=True)
    elif action_type == RuleActionType.SLA_MATRIX:
        _validate_sla_matrix(action_config, errors)
        _validate_percent(action_config, "incident_cap_percent", errors, required=True)
    elif action_type == RuleActionType.MULTIPLIER:
        _validate_percent(action_config, "modifier_rate", errors, required=True)
    elif action_type == RuleActionType.CAP_FLOOR:
        _validate_decimal_field(action_config, "minimum_positive_amount", errors, required=True)
        _validate_percent(action_config, "monthly_cumulative_cap_percent", errors, required=True)
    elif action_type == RuleActionType.LEGACY_MONTHLY_PRICE_PERCENTAGE:
        formula = action_config.get("refund_formula")
        if not isinstance(formula, dict):
            errors.append("legacy action requires refund_formula object.")
        elif formula.get("type") != "monthly_price_percentage":
            errors.append("legacy refund_formula.type must be monthly_price_percentage.")

    price_basis = action_config.get("price_basis")
    if price_basis is not None and price_basis not in {choice.value for choice in RulePriceBasis}:
        errors.append(f"Unsupported price_basis: {price_basis}")

    return RuleSchemaValidationResult(valid=not errors, errors=errors, required_fields=[])


def assert_valid_rule_schema(
    *,
    condition_tree: dict[str, Any],
    action_type: str,
    action_config: dict[str, Any],
) -> None:
    condition_result = validate_condition_tree(condition_tree)
    action_result = validate_action_config(action_type, action_config)
    errors = condition_result.errors + action_result.errors
    if errors:
        raise RuleSchemaValidationError("; ".join(errors))


def _validate_condition_node(
    node: Any,
    *,
    errors: list[str],
    required_fields: set[str],
    path: str,
) -> None:
    if not isinstance(node, dict):
        errors.append(f"{path} must be an object.")
        return
    if "operator" in node and "conditions" in node:
        group_operator = node["operator"]
        children = node["conditions"]
        if group_operator not in SUPPORTED_GROUP_OPERATORS:
            errors.append(f"{path}.operator unsupported group: {group_operator}")
            return
        if not isinstance(children, list):
            errors.append(f"{path}.conditions must be a list.")
            return
        for index, child in enumerate(children):
            _validate_condition_node(
                child,
                errors=errors,
                required_fields=required_fields,
                path=f"{path}.conditions[{index}]",
            )
        return
    if "all" in node or "any" in node:
        group_operator = "all" if "all" in node else "any"
        children = node[group_operator]
        if not isinstance(children, list):
            errors.append(f"{path}.{group_operator} must be a list.")
            return
        for index, child in enumerate(children):
            _validate_condition_node(
                child,
                errors=errors,
                required_fields=required_fields,
                path=f"{path}.{group_operator}[{index}]",
            )
        return

    field = node.get("field")
    operator = node.get("operator", node.get("op"))
    if field not in ALLOWED_CONDITION_FIELDS:
        errors.append(f"{path}.field unsupported: {field}")
    else:
        required_fields.add(field)
    if operator not in SUPPORTED_CONDITION_OPERATORS:
        errors.append(f"{path}.operator unsupported: {operator}")
    if "value" not in node:
        errors.append(f"{path}.value is required.")


def _validate_tiers(action_config: dict[str, Any], errors: list[str]) -> None:
    tiers = action_config.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        errors.append("tiered action requires non-empty tiers list.")
        return
    for index, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            errors.append(f"tiers[{index}] must be an object.")
            continue
        _validate_decimal_field(
            tier, "min_seconds", errors, required=True, prefix=f"tiers[{index}]."
        )
        _validate_percent(tier, "rate", errors, required=True, prefix=f"tiers[{index}].")


def _validate_sla_matrix(action_config: dict[str, Any], errors: list[str]) -> None:
    tiers = action_config.get("exceedance_tiers")
    if not isinstance(tiers, list) or not tiers:
        errors.append("sla_matrix action requires non-empty exceedance_tiers list.")
        return
    for index, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            errors.append(f"exceedance_tiers[{index}] must be an object.")
            continue
        _validate_decimal_field(
            tier,
            "min_ratio_exclusive",
            errors,
            required=True,
            prefix=f"exceedance_tiers[{index}].",
        )
        _validate_percent(tier, "rate", errors, required=True, prefix=f"exceedance_tiers[{index}].")


def _validate_percent(
    payload: dict[str, Any],
    field_name: str,
    errors: list[str],
    *,
    required: bool,
    prefix: str = "",
) -> None:
    if field_name not in payload:
        if required:
            errors.append(f"{prefix}{field_name} is required.")
        return
    value = _parse_decimal(payload[field_name])
    if value is None or value < Decimal("0") or value > Decimal("1"):
        errors.append(f"{prefix}{field_name} must be a decimal ratio between 0 and 1.")


def _validate_decimal_field(
    payload: dict[str, Any],
    field_name: str,
    errors: list[str],
    *,
    required: bool,
    prefix: str = "",
) -> None:
    if field_name not in payload:
        if required:
            errors.append(f"{prefix}{field_name} is required.")
        return
    if _parse_decimal(payload[field_name]) is None:
        errors.append(f"{prefix}{field_name} must be decimal-compatible.")


def _parse_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
