from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from apps.compensation.services.calculation import CompensationService
from apps.customers.models import SubscriptionConnection, SubscriptionConnectionRole
from apps.customers.services.impact import CustomerImpactService
from apps.datasets.models import DataSnapshot, GroundTruthCase
from apps.network.services.path_diversity import PathDiversityService
from apps.operations.models import Incident, Outage
from apps.operations.services.root_cause import RootCauseService
from apps.rules.models import RuleVersion
from data_generator.configs import multicity_ground_truth_v1 as config


def validate_multicity_ground_truth(
    snapshot: DataSnapshot,
    *,
    case_code: str | None = None,
) -> dict[str, Any]:
    selected_cases = [
        item
        for item in config.GROUND_TRUTH_CASES
        if case_code is None or item["case_code"] == case_code
    ]
    checks = [
        check("config_case_count", config.EXPECTED_CASE_COUNT, len(config.GROUND_TRUTH_CASES)),
        check("case_codes_unique", True, case_codes_are_unique()),
        check(
            "required_category_coverage", sorted(config.REQUIRED_CATEGORIES), collect_categories()
        ),
        check(
            "db_ground_truth_case_count",
            len(config.GROUND_TRUTH_CASES) if case_code is None else 1,
            GroundTruthCase.objects.filter(
                data_snapshot=snapshot,
                case_code__in=[item["case_code"] for item in selected_cases],
            ).count(),
        ),
        check(
            "path_diversity_distribution",
            config.PATH_DIVERSITY_EXPECTED,
            collect_path_diversity(snapshot),
        ),
        check("noise_alarm_no_incident", 0, collect_noise_incident_count(snapshot)),
    ]
    for case_config in selected_cases:
        checks.extend(validate_case(snapshot=snapshot, case_config=case_config))
    return {
        "passed": all(item["passed"] for item in checks),
        "case_count": len(selected_cases),
        "checks": checks,
        "failed": [item for item in checks if not item["passed"]],
    }


def validate_case(*, snapshot: DataSnapshot, case_config: dict[str, Any]) -> list[dict[str, Any]]:
    case = GroundTruthCase.objects.get(
        data_snapshot=snapshot,
        case_code=case_config["case_code"],
    )
    checks = [
        check(
            f"{case.case_code}.expected_rule",
            case_config["expected_selected_rule"],
            case.expected_rule_code,
        ),
        check(
            f"{case.case_code}.expected_amount",
            Decimal(case_config["expected_exact_amount"]),
            case.expected_total_refund_amount,
        ),
        check(
            f"{case.case_code}.metadata_scenario",
            case_config["scenario_code"],
            case.metadata.get("scenario_code"),
        ),
    ]
    incident = get_incident(snapshot=snapshot, case_config=case_config)
    outage = get_outage(snapshot=snapshot, case_config=case_config)
    expected_outage_exists = case_config.get("expected_outage_exists")
    if expected_outage_exists is not None:
        checks.append(
            check(
                f"{case.case_code}.outage_exists",
                expected_outage_exists,
                outage is not None,
            )
        )
    if incident is not None:
        checks.extend(
            [
                check(
                    f"{case.case_code}.incident_type",
                    case_config.get("expected_incident_type", incident.incident_type),
                    incident.incident_type,
                ),
                check(
                    f"{case.case_code}.impact_class",
                    case_config.get("expected_impact_class", incident.service_impact_class),
                    incident.service_impact_class,
                ),
            ]
        )
    if "impact" in case_config.get("service_checks", []):
        checks.extend(validate_impact(snapshot=snapshot, case_config=case_config, outage=outage))
    if "root_cause" in case_config.get("service_checks", []):
        checks.extend(
            validate_root_cause(snapshot=snapshot, case_config=case_config, outage=outage)
        )
    if (
        case_config.get("expected_selected_rule")
        and case_config["expected_selected_rule"] != "NONE"
    ):
        checks.extend(validate_rule_amount(snapshot=snapshot, case_config=case_config))
    if precondition := case_config.get("subscription_precondition"):
        checks.append(validate_subscription_precondition(case_config, precondition))
    if expected_path := case_config.get("expected_path_diversity"):
        checks.append(validate_path_diversity_sample(snapshot, case_config, expected_path))
    return checks


def validate_impact(
    *,
    snapshot: DataSnapshot,
    case_config: dict[str, Any],
    outage: Outage | None,
) -> list[dict[str, Any]]:
    if outage is None:
        return [check(f"{case_config['case_code']}.impact_outage_present", True, False)]
    result = CustomerImpactService().calculate_impact(outage=outage, snapshot=snapshot)
    return [
        check(
            f"{case_config['case_code']}.affected_subscription_count",
            case_config["expected_affected_subscription_count"],
            result.affected_subscription_count,
        ),
        check(
            f"{case_config['case_code']}.affected_customer_count",
            case_config["expected_affected_customer_count"],
            result.affected_customer_count,
        ),
    ]


def validate_root_cause(
    *,
    snapshot: DataSnapshot,
    case_config: dict[str, Any],
    outage: Outage | None,
) -> list[dict[str, Any]]:
    if outage is None:
        return [check(f"{case_config['case_code']}.root_outage_present", True, False)]
    result = RootCauseService().analyze(outage=outage, snapshot=snapshot)[0]
    return [
        check(
            f"{case_config['case_code']}.root_cause",
            case_config["expected_root_cause"],
            result.candidate_device_code,
        ),
        check(
            f"{case_config['case_code']}.root_classification",
            case_config["expected_root_classification"],
            result.classification,
        ),
    ]


def validate_rule_amount(
    *,
    snapshot: DataSnapshot,
    case_config: dict[str, Any],
) -> list[dict[str, Any]]:
    rule_code = case_config.get("amount_rule", case_config["expected_selected_rule"])
    version = (
        RuleVersion.objects.filter(
            data_snapshot=snapshot,
            rule__code=rule_code,
            version=config.RULE_SET_VERSION,
        )
        .select_related("rule")
        .first()
    )
    if version is None:
        return [check(f"{case_config['case_code']}.rule_version_exists", True, False)]
    action_context = case_config.get("action_context")
    if action_context is None:
        return []
    result = CompensationService().calculate_policy_amount(
        action_type=version.action_type,
        action_config=version.action_config,
        price_basis_amount=case_config.get("price_basis_amount"),
        context=action_context,
    )
    return [
        check(
            f"{case_config['case_code']}.decision",
            normalize_expected_decision(case_config["expected_decision"]),
            result.status,
        ),
        check(
            f"{case_config['case_code']}.amount",
            Decimal(case_config["expected_exact_amount"]),
            result.final_amount,
        ),
    ]


def validate_subscription_precondition(
    case_config: dict[str, Any],
    precondition: dict[str, str],
) -> dict[str, Any]:
    class StubSubscription:
        status = precondition["status"]
        suspension_reason = precondition["suspension_reason"]

    actual = CompensationService().evaluate_subscription_policy_preconditions(
        subscription=StubSubscription(),
    )
    expected_status = normalize_expected_decision(case_config["expected_decision"])
    return check(
        f"{case_config['case_code']}.subscription_precondition",
        expected_status,
        actual["status"],
    )


def validate_path_diversity_sample(
    snapshot: DataSnapshot,
    case_config: dict[str, Any],
    expected_path: str,
) -> dict[str, Any]:
    backup = (
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            connection_role=SubscriptionConnectionRole.BACKUP,
        )
        .select_related("subscription", "line_connection")
        .order_by("subscription__subscription_number")
    )
    for backup_connection in backup:
        primary = SubscriptionConnection.objects.get(
            data_snapshot=snapshot,
            subscription=backup_connection.subscription,
            connection_role=SubscriptionConnectionRole.PRIMARY,
        )
        result = PathDiversityService().evaluate(
            primary_line=primary.line_connection,
            backup_line=backup_connection.line_connection,
            snapshot=snapshot,
        )
        if result.classification == expected_path:
            return check(
                f"{case_config['case_code']}.path_diversity_sample",
                expected_path,
                result.classification,
            )
    return check(f"{case_config['case_code']}.path_diversity_sample", expected_path, "missing")


def collect_path_diversity(snapshot: DataSnapshot) -> dict[str, int]:
    service = PathDiversityService()
    counts: Counter[str] = Counter()
    for backup in (
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            connection_role=SubscriptionConnectionRole.BACKUP,
        )
        .select_related("subscription", "line_connection")
        .order_by("subscription__subscription_number")
    ):
        primary = SubscriptionConnection.objects.get(
            data_snapshot=snapshot,
            subscription=backup.subscription,
            connection_role=SubscriptionConnectionRole.PRIMARY,
        )
        result = service.evaluate(
            primary_line=primary.line_connection,
            backup_line=backup.line_connection,
            snapshot=snapshot,
        )
        counts[result.classification] += 1
    return {key: counts.get(key, 0) for key in config.PATH_DIVERSITY_EXPECTED}


def collect_noise_incident_count(snapshot: DataSnapshot) -> int:
    return Incident.objects.filter(
        data_snapshot=snapshot,
        metadata__scenario_code="SCN-NOISE-001",
    ).count()


def get_incident(*, snapshot: DataSnapshot, case_config: dict[str, Any]) -> Incident | None:
    incident_number = case_config.get("incident_number")
    if not incident_number:
        return None
    return Incident.objects.filter(
        data_snapshot=snapshot,
        incident_number=incident_number,
    ).first()


def get_outage(*, snapshot: DataSnapshot, case_config: dict[str, Any]) -> Outage | None:
    outage_code = case_config.get("outage_code")
    if not outage_code:
        return None
    return Outage.objects.filter(data_snapshot=snapshot, outage_code=outage_code).first()


def case_codes_are_unique() -> bool:
    codes = [item["case_code"] for item in config.GROUND_TRUTH_CASES]
    return len(codes) == len(set(codes))


def collect_categories() -> list[str]:
    return sorted({item["category"] for item in config.GROUND_TRUTH_CASES})


def normalize_expected_decision(decision: str) -> str:
    if decision == "evidence_only":
        return "evidence_only"
    return decision


def check(name: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "passed": expected == actual,
    }
