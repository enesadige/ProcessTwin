import pytest
from data_generator.configs import synthetic_compensation_policy_v1 as policy_config
from data_generator.seeders.rule_policy import seed_synthetic_compensation_policy
from data_generator.validators.rule_policy import validate_synthetic_compensation_policy_config
from django.utils import timezone

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.rules.models import Rule, RuleSet, RuleVersion
from apps.rules.services.evaluation import RuleEvaluationService, select_primary_base_rule
from apps.rules.services.schema import validate_action_config, validate_condition_tree


def test_synthetic_compensation_policy_config_has_exact_catalog_targets():
    checks = validate_synthetic_compensation_policy_config()

    assert all(check.passed for check in checks), [
        (check.name, check.expected, check.actual) for check in checks if not check.passed
    ]
    assert policy_config.CATALOG_TARGETS["rule_count"] == 25
    assert [rule["code"] for rule in policy_config.RULES] == [
        "ELIG-SUBSCRIPTION-VALID",
        "ELIG-CUSTOMER-IMPACT-CONFIRMED",
        "EXCL-PENDING-CANCELLED",
        "EXCL-SUSPENSION-POLICY",
        "EXCL-PLANNED-MAINTENANCE-NORMAL",
        "EXCL-PROTECTION-LOSS-ONLY",
        "EXCL-DUPLICATE-COMPENSATION",
        "BB-FULL-OUTAGE-TIERED",
        "BB-PARTIAL-OUTAGE-PRORATED",
        "BB-DEGRADATION-QUALITY",
        "ME-SHORT-FAILOVER-INTERRUPTION",
        "ME-AVAILABILITY-BREACH",
        "ME-LATENCY-BREACH",
        "ME-JITTER-BREACH",
        "ME-PACKET-LOSS-BREACH",
        "ME-FAILED-FAILOVER",
        "ME-DEGRADED-FAILOVER",
        "MOD-GRADED-RESTORATION",
        "MOD-RECURRING-INCIDENT",
        "MOD-MAINTENANCE-OVERRUN",
        "MOD-RESTORATION-TARGET-BREACH",
        "SLA-PATH-DIVERSITY-BREACH",
        "SLA-BACKUP-MISSING",
        "MR-UNKNOWN-MISSING-EVIDENCE",
        "CAP-FLOOR-CONFLICT",
    ]


def test_unknown_condition_field_is_schema_error_not_executable_logic():
    result = validate_condition_tree(
        {"field": "metadata.free_text_rule", "operator": "eq", "value": True}
    )

    assert result.valid is False
    assert "unsupported" in result.errors[0]


def test_unknown_condition_operator_is_schema_error():
    result = validate_condition_tree(
        {"field": "impact_class", "operator": "starts_with", "value": "full"}
    )

    assert result.valid is False
    assert "unsupported" in result.errors[0]


def test_unknown_action_type_is_schema_error():
    result = validate_action_config("python_eval", {})

    assert result.valid is False
    assert result.errors == ["Unsupported action_type: python_eval"]


@pytest.mark.django_db
def test_policy_catalog_seeder_creates_ruleset_rules_and_versions_without_refund_rule():
    snapshot = create_snapshot()

    rule_set = seed_synthetic_compensation_policy(snapshot)

    assert rule_set.code == "SYN-COMP-2026"
    assert RuleSet.objects.filter(data_snapshot=snapshot).count() == 1
    assert Rule.objects.filter(data_snapshot=snapshot).count() == 25
    assert RuleVersion.objects.filter(data_snapshot=snapshot).count() == 25
    assert not Rule.objects.filter(data_snapshot=snapshot, code="REFUND-001").exists()
    assert (
        Rule.objects.get(data_snapshot=snapshot, code="BB-FULL-OUTAGE-TIERED").rule_set == rule_set
    )


@pytest.mark.django_db
def test_policy_evaluation_selects_single_primary_base_rule_deterministically():
    snapshot = create_snapshot()
    seed_synthetic_compensation_policy(snapshot)

    result = RuleEvaluationService().evaluate_rule_set(
        snapshot=snapshot,
        rule_set_code="SYN-COMP-2026",
        event_datetime=dt(2026, 7, 20, 12, 0),
        context={
            "service_type": "broadband",
            "impact_class": "full_outage",
            "outage_duration_seconds": 4 * 60 * 60,
            "subscription_active_during_outage": True,
            "connection_active_during_outage": True,
            "customer_impacted": True,
            "price_available": True,
            "root_cause_known": True,
        },
    )

    assert result.evaluation_status == "matched"
    assert result.selected_base_rule.rule_code == "BB-FULL-OUTAGE-TIERED"
    assert all(item["rule_code"] != "BB-PARTIAL-OUTAGE-PRORATED" for item in result.excluded_rules)


def test_primary_base_conflict_prefers_priority_then_specificity_then_code():
    candidates = [
        candidate("RULE-B", priority=10, specific_count=2),
        candidate("RULE-A", priority=10, specific_count=2),
        candidate("RULE-C", priority=20, specific_count=10),
    ]

    assert select_primary_base_rule(candidates).rule_code == "RULE-A"


def candidate(rule_code: str, *, priority: int, specific_count: int):
    from apps.rules.services.evaluation import PolicyRuleCandidate

    return PolicyRuleCandidate(
        rule_code=rule_code,
        rule_version=1,
        priority=priority,
        specific_condition_count=specific_count,
        action_type="tiered_percentage",
        price_basis="contracted_monthly_price",
        stackable=False,
        conflict_group="test",
        evaluation_status="matched",
        matched=True,
        matched_conditions=[{}] * specific_count,
        unmatched_conditions=[],
        action_config={},
    )


def create_snapshot() -> DataSnapshot:
    dataset = DatasetVersion.objects.create(
        name="Synthetic policy dataset",
        generator_version="policy-v1",
        seed="policy-test",
    )
    return DataSnapshot.objects.create(dataset_version=dataset, name="Policy snapshot")


def dt(year: int, month: int, day: int, hour: int, minute: int):
    return timezone.datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=timezone.get_current_timezone(),
    )
