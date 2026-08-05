import json
from collections import Counter
from decimal import Decimal

import pytest
from data_generator.configs import multicity_ground_truth_v1 as config
from data_generator.seeders.multicity_ground_truth import find_incident, find_outage
from data_generator.validators.multicity_ground_truth import check, validate_case

from apps.datasets.management.commands.validate_multicity_ground_truth import format_failed_checks
from apps.datasets.models import (
    DatasetVersion,
    DataSnapshot,
    GroundTruthCase,
    GroundTruthEligibility,
)


def test_multicity_ground_truth_config_schema_and_category_coverage():
    required_keys = {
        "case_code",
        "category",
        "scenario_code",
        "expected_selected_rule",
        "expected_decision",
        "expected_exact_amount",
    }
    codes = [case["case_code"] for case in config.GROUND_TRUTH_CASES]
    categories = {case["category"] for case in config.GROUND_TRUTH_CASES}

    assert len(config.GROUND_TRUTH_CASES) == config.EXPECTED_CASE_COUNT == 30
    assert len(codes) == len(set(codes))
    assert config.REQUIRED_CATEGORIES <= categories
    assert all(required_keys <= set(case) for case in config.GROUND_TRUTH_CASES)
    assert sum(config.PATH_DIVERSITY_EXPECTED.values()) == 208


def test_multicity_ground_truth_category_distribution_is_intentional():
    counts = Counter(case["category"] for case in config.GROUND_TRUTH_CASES)

    assert counts["network_operation"] == 8
    assert counts["rule_compensation"] == 11
    assert counts["path_diversity"] == 4
    assert counts["manual_review"] == 3
    assert counts["maintenance"] == 2
    assert counts["duplicate"] == 1
    assert counts["noise"] == 1


def test_multicity_ground_truth_critical_expected_values():
    cases = {case["case_code"]: case for case in config.GROUND_TRUTH_CASES}

    assert cases["GT-MCR-NET-BNG-WIDE-001"]["expected_affected_subscription_count"] == 572
    assert cases["GT-MCR-NET-BNG-WIDE-001"]["expected_affected_customer_count"] == 495
    assert cases["GT-MCR-RULE-FAILOVER-45S-001"]["expected_exact_amount"] == "35.00"
    assert cases["GT-MCR-RULE-MONTHLY-CAP-001"]["expected_modifier_or_cap"] == (
        "billing_period_cumulative_cap"
    )
    assert cases["GT-MCR-RULE-NOISE-NO-INCIDENT-001"]["expected_selected_rule"] == "NONE"
    assert cases["GT-MCR-RULE-NOISE-NO-INCIDENT-001"]["expected_outage_exists"] is False


@pytest.mark.django_db
def test_multicity_ground_truth_validator_skips_noise_case_rule_lookup(monkeypatch):
    dataset = DatasetVersion.objects.create(
        name="Multi-city Realism",
        slug=config.DATASET_SLUG,
        generator_version="test",
        seed="test",
    )
    snapshot = DataSnapshot.objects.create(dataset_version=dataset, name="snapshot")
    case_config = next(
        case
        for case in config.GROUND_TRUTH_CASES
        if case["case_code"] == "GT-MCR-RULE-NOISE-NO-INCIDENT-001"
    )
    GroundTruthCase.objects.create(
        data_snapshot=snapshot,
        case_code=case_config["case_code"],
        outage_code=f"NO-OUTAGE-{case_config['case_code']}",
        expected_source_device_code="",
        expected_incident_code="",
        expected_alarm_type_codes=[],
        expected_duration_minutes=0,
        expected_rule_code="NONE",
        expected_rule_version=config.RULE_SET_VERSION,
        affected_subscription_codes=[],
        affected_subscription_hash="0" * 64,
        affected_subscription_count=0,
        affected_customer_codes=[],
        affected_customer_hash="0" * 64,
        affected_customer_count=0,
        unaffected_subscription_count=0,
        unaffected_customer_count=0,
        affected_segment_counts={},
        affected_priority_counts={},
        expected_eligibility=GroundTruthEligibility.INELIGIBLE,
        expected_reason_code="noise_alarm_suppressed_no_incident",
        expected_total_refund_amount=Decimal("0.00"),
        currency=config.CURRENCY,
        metadata={"scenario_code": "SCN-NOISE-001"},
    )

    def fail_if_called(**kwargs):
        raise AssertionError("Rule lookup must not run for expected_selected_rule=NONE")

    monkeypatch.setattr(
        "data_generator.validators.multicity_ground_truth.validate_rule_amount",
        fail_if_called,
    )

    checks = validate_case(snapshot=snapshot, case_config=case_config)

    assert all(item["passed"] for item in checks)


def test_multicity_ground_truth_failure_report_is_machine_readable():
    report = {
        "case_count": 1,
        "failed": [check("forced_failure", "expected", "actual")],
    }

    parsed = json.loads(format_failed_checks(report, as_json=True))

    assert parsed["passed"] is False
    assert parsed["case_count"] == 1
    assert parsed["failed_count"] == 1
    assert parsed["failed"][0]["name"] == "forced_failure"


@pytest.mark.django_db
def test_ground_truth_lookup_tolerates_missing_legacy_reference_in_causal_snapshot():
    dataset = DatasetVersion.objects.create(
        name="Causal multi-city",
        slug="causal-multi-city-ground-truth-test",
        generator_version="test",
        seed="test",
    )
    snapshot = DataSnapshot.objects.create(dataset_version=dataset, name="snapshot")

    assert find_outage(snapshot=snapshot, case_config={"outage_code": "OUT-MCR-0021"}) is None
    assert (
        find_incident(
            snapshot=snapshot,
            case_config={"incident_number": "INC-MCR-0140"},
            outage=None,
        )
        is None
    )
