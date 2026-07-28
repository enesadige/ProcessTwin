from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from apps.datasets.models import DataSnapshot
from apps.operations.models import Outage
from apps.rules.models import RuleVersion
from apps.rules.services.version_selection import select_rule_version_for_moment

SUPPORTED_OPERATORS = frozenset({"eq", "not_eq", "gte", "gt", "lte", "lt", "in", "not_in"})
OPERATOR_ALIASES = {
    "==": "eq",
    "!=": "not_eq",
    ">=": "gte",
    ">": "gt",
    "<=": "lte",
    "<": "lt",
}
FIELD_ALIASES = {
    "impact_duration_minutes": "outage_duration_seconds",
    "subscription_connection_overlaps_outage": "connection_active_during_outage",
}
SECONDS_FIELD_ALIASES = frozenset({"impact_duration_minutes"})


class RuleEvaluationServiceError(Exception):
    """Base error for deterministic rule evaluation failures."""


class RuleEvaluationInputError(RuleEvaluationServiceError):
    """Raised when snapshot, rule, or event inputs are invalid."""


@dataclass(frozen=True)
class RuleConditionResult:
    field: str | None
    operator: str | None
    expected: Any
    actual: Any
    matched: bool
    path: str


@dataclass(frozen=True)
class RuleEvaluationResult:
    rule_code: str
    rule_version: int | None
    event_datetime: str
    evaluation_status: str
    matched: bool
    matched_conditions: list[dict[str, Any]]
    unmatched_conditions: list[dict[str, Any]]
    missing_fields: list[str]
    unsupported_operators: list[str]
    selected_rule_version: dict[str, Any] | None
    action_config: dict[str, Any]
    errors: list[str]


class RuleEvaluationService:
    def evaluate(
        self,
        *,
        snapshot: DataSnapshot,
        rule_code: str,
        event_datetime,
        context: dict[str, Any],
    ) -> RuleEvaluationResult:
        self._validate_inputs(
            snapshot=snapshot,
            rule_code=rule_code,
            event_datetime=event_datetime,
            context=context,
        )
        selection = select_rule_version_for_moment(
            snapshot=snapshot,
            rule_code=rule_code,
            moment=event_datetime,
        )
        if selection.status != "selected" or selection.selected_version is None:
            return self._manual_review_result(
                rule_code=rule_code,
                event_datetime=event_datetime,
                selected_rule_version=None,
                action_config={},
                errors=[selection.reason],
            )

        version = selection.selected_version
        condition_result = self._evaluate_node(
            node=version.condition_tree,
            context=context,
            path="condition_tree",
        )
        matched_conditions = [
            self._condition_result_to_dict(item)
            for item in condition_result["conditions"]
            if item.matched
        ]
        unmatched_conditions = [
            self._condition_result_to_dict(item)
            for item in condition_result["conditions"]
            if not item.matched
        ]
        missing_fields = sorted(set(condition_result["missing_fields"]))
        unsupported_operators = sorted(set(condition_result["unsupported_operators"]))
        errors = list(condition_result["errors"])
        if missing_fields or unsupported_operators or errors:
            return self._manual_review_result(
                rule_code=rule_code,
                event_datetime=event_datetime,
                selected_rule_version=version,
                action_config=version.action_config,
                matched_conditions=matched_conditions,
                unmatched_conditions=unmatched_conditions,
                missing_fields=missing_fields,
                unsupported_operators=unsupported_operators,
                errors=errors,
            )

        matched = bool(condition_result["matched"])
        return RuleEvaluationResult(
            rule_code=rule_code,
            rule_version=version.version,
            event_datetime=event_datetime.isoformat(),
            evaluation_status="matched" if matched else "unmatched",
            matched=matched,
            matched_conditions=matched_conditions,
            unmatched_conditions=unmatched_conditions,
            missing_fields=[],
            unsupported_operators=[],
            selected_rule_version=self._version_to_dict(version),
            action_config=version.action_config,
            errors=[],
        )

    def evaluate_for_outage(
        self,
        *,
        snapshot: DataSnapshot,
        rule_code: str,
        outage: Outage,
        context: dict[str, Any],
    ) -> RuleEvaluationResult:
        if outage is None:
            raise RuleEvaluationInputError("An Outage must be provided.")
        if not outage.pk:
            raise RuleEvaluationInputError("Outage must be a persisted Outage.")
        if outage.data_snapshot_id != snapshot.id:
            raise RuleEvaluationInputError(
                f"Outage {outage.outage_code} does not belong to snapshot "
                f"{snapshot.snapshot_key}."
            )
        return self.evaluate(
            snapshot=snapshot,
            rule_code=rule_code,
            event_datetime=outage.started_at,
            context=context,
        )

    def _validate_inputs(
        self,
        *,
        snapshot: DataSnapshot,
        rule_code: str,
        event_datetime,
        context: dict[str, Any],
    ) -> None:
        if snapshot is None:
            raise RuleEvaluationInputError("A DataSnapshot must be provided explicitly.")
        if not snapshot.pk:
            raise RuleEvaluationInputError("Snapshot must be a persisted DataSnapshot.")
        if not rule_code:
            raise RuleEvaluationInputError("rule_code must be provided.")
        if event_datetime is None:
            raise RuleEvaluationInputError("event_datetime must be provided.")
        if timezone.is_naive(event_datetime):
            raise RuleEvaluationInputError("event_datetime must be timezone-aware.")
        if context is None or not isinstance(context, dict):
            raise RuleEvaluationInputError("context must be a dictionary.")

    def _evaluate_node(self, *, node: dict[str, Any], context: dict[str, Any], path: str):
        if not isinstance(node, dict):
            return self._empty_node_result(errors=[f"{path} must be an object."])

        if "operator" in node and "conditions" in node:
            operator = node["operator"]
            children = node["conditions"]
        elif "all" in node:
            operator = "all"
            children = node["all"]
        elif "any" in node:
            operator = "any"
            children = node["any"]
        else:
            return self._evaluate_condition(node=node, context=context, path=path)

        if operator not in {"all", "any"}:
            return self._empty_node_result(errors=[f"{path} has unsupported group {operator}."])
        if not isinstance(children, list):
            return self._empty_node_result(errors=[f"{path}.conditions must be a list."])

        child_results = [
            self._evaluate_node(
                node=child,
                context=context,
                path=f"{path}.{operator}[{index}]",
            )
            for index, child in enumerate(children)
        ]
        matched_values = [result["matched"] for result in child_results]
        return {
            "matched": all(matched_values) if operator == "all" else any(matched_values),
            "conditions": [
                condition for result in child_results for condition in result["conditions"]
            ],
            "missing_fields": [
                field for result in child_results for field in result["missing_fields"]
            ],
            "unsupported_operators": [
                op for result in child_results for op in result["unsupported_operators"]
            ],
            "errors": [error for result in child_results for error in result["errors"]],
        }

    def _evaluate_condition(
        self,
        *,
        node: dict[str, Any],
        context: dict[str, Any],
        path: str,
    ):
        field = node.get("field")
        raw_operator = node.get("operator", node.get("op"))
        normalized_operator = normalize_operator(raw_operator)
        raw_expected = node.get("value")
        context_field = FIELD_ALIASES.get(field, field)
        expected = normalize_expected_value(field=field, value=raw_expected)

        if not field:
            return self._empty_node_result(errors=[f"{path} is missing field."])
        if normalized_operator not in SUPPORTED_OPERATORS:
            return {
                "matched": False,
                "conditions": [],
                "missing_fields": [],
                "unsupported_operators": [str(raw_operator)],
                "errors": [],
            }
        if context_field not in context:
            return {
                "matched": False,
                "conditions": [],
                "missing_fields": [context_field],
                "unsupported_operators": [],
                "errors": [],
            }

        actual = context[context_field]
        matched = apply_operator(
            operator=normalized_operator,
            actual=actual,
            expected=expected,
        )
        return {
            "matched": matched,
            "conditions": [
                RuleConditionResult(
                    field=context_field,
                    operator=normalized_operator,
                    expected=expected,
                    actual=actual,
                    matched=matched,
                    path=path,
                )
            ],
            "missing_fields": [],
            "unsupported_operators": [],
            "errors": [],
        }

    def _manual_review_result(
        self,
        *,
        rule_code: str,
        event_datetime,
        selected_rule_version: RuleVersion | None,
        action_config: dict[str, Any],
        matched_conditions: list[dict[str, Any]] | None = None,
        unmatched_conditions: list[dict[str, Any]] | None = None,
        missing_fields: list[str] | None = None,
        unsupported_operators: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> RuleEvaluationResult:
        return RuleEvaluationResult(
            rule_code=rule_code,
            rule_version=selected_rule_version.version if selected_rule_version else None,
            event_datetime=event_datetime.isoformat(),
            evaluation_status="manual_review",
            matched=False,
            matched_conditions=matched_conditions or [],
            unmatched_conditions=unmatched_conditions or [],
            missing_fields=missing_fields or [],
            unsupported_operators=unsupported_operators or [],
            selected_rule_version=(
                self._version_to_dict(selected_rule_version) if selected_rule_version else None
            ),
            action_config=action_config,
            errors=errors or [],
        )

    def _empty_node_result(self, *, errors: list[str] | None = None):
        return {
            "matched": False,
            "conditions": [],
            "missing_fields": [],
            "unsupported_operators": [],
            "errors": errors or [],
        }

    def _condition_result_to_dict(self, result: RuleConditionResult) -> dict[str, Any]:
        return {
            "field": result.field,
            "operator": result.operator,
            "expected": result.expected,
            "actual": result.actual,
            "matched": result.matched,
            "path": result.path,
        }

    def _version_to_dict(self, version: RuleVersion) -> dict[str, Any]:
        return {
            "rule_code": version.rule.code,
            "version": version.version,
            "status": version.status,
            "valid_from": version.valid_from.isoformat(),
            "valid_to": version.valid_to.isoformat() if version.valid_to else None,
        }


def normalize_operator(raw_operator: Any) -> str | None:
    if raw_operator is None:
        return None
    operator = str(raw_operator)
    return OPERATOR_ALIASES.get(operator, operator)


def normalize_expected_value(*, field: str | None, value: Any) -> Any:
    if field in SECONDS_FIELD_ALIASES and isinstance(value, int | float):
        return int(value * 60)
    return value


def apply_operator(*, operator: str, actual: Any, expected: Any) -> bool:
    if operator == "eq":
        return actual == expected
    if operator == "not_eq":
        return actual != expected
    if operator == "gte":
        return actual >= expected
    if operator == "gt":
        return actual > expected
    if operator == "lte":
        return actual <= expected
    if operator == "lt":
        return actual < expected
    if operator == "in":
        return actual in expected
    if operator == "not_in":
        return actual not in expected
    raise ValueError(f"Unsupported operator: {operator}")
