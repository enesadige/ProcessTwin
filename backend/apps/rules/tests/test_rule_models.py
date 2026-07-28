from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.rules.models import (
    Rule,
    RuleChangeSet,
    RuleChangeSetStatus,
    RuleStatus,
    RuleTestCase,
    RuleType,
    RuleVersion,
    RuleVersionStatus,
)
from apps.rules.services.version_selection import select_rule_version_for_moment


def create_snapshot(seed: str = "rule-seed-001") -> DataSnapshot:
    dataset = DatasetVersion.objects.create(
        name=f"Rule Dataset {seed}",
        generator_version="gen-0.1.0",
        seed=seed,
    )
    return DataSnapshot.objects.create(dataset_version=dataset, name="Initial snapshot")


def create_refund_rule(snapshot: DataSnapshot) -> Rule:
    return Rule.objects.create(
        data_snapshot=snapshot,
        code="REFUND-001",
        name="Outage refund eligibility placeholder",
        rule_type=RuleType.COMPENSATION,
        status=RuleStatus.ACTIVE,
        description="Placeholder rule shell; business thresholds will be finalized later.",
    )


@pytest.mark.django_db
def test_rule_and_versions_can_store_placeholder_condition_and_action_config():
    snapshot = create_snapshot()
    rule = create_refund_rule(snapshot)
    change_set = RuleChangeSet.objects.create(
        data_snapshot=snapshot,
        change_set_code="CS-RULE-001",
        title="Initial placeholder refund rule",
        status=RuleChangeSetStatus.APPROVED,
        reason="Model smoke only; not a finalized business policy.",
    )
    now = timezone.now()

    version = RuleVersion.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        version=1,
        status=RuleVersionStatus.ACTIVE,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=30),
        condition_tree={"all": [{"field": "outage_duration_minutes", "op": ">=", "value": 120}]},
        action_config={"type": "refund_evaluation", "amount_strategy": "service_defined"},
        change_set=change_set,
    )

    assert str(rule) == "REFUND-001 - Outage refund eligibility placeholder"
    assert str(version) == "REFUND-001 v1"
    assert version.is_valid_at(now)
    assert not version.is_valid_at(now + timedelta(days=60))
    assert version.action_config["amount_strategy"] == "service_defined"


@pytest.mark.django_db
def test_rule_version_rejects_overlapping_validity_ranges():
    snapshot = create_snapshot()
    rule = create_refund_rule(snapshot)
    now = timezone.now()
    RuleVersion.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        version=1,
        status=RuleVersionStatus.ACTIVE,
        valid_from=now,
        valid_to=now + timedelta(days=30),
    )
    overlapping = RuleVersion(
        data_snapshot=snapshot,
        rule=rule,
        version=2,
        status=RuleVersionStatus.DRAFT,
        valid_from=now + timedelta(days=10),
        valid_to=now + timedelta(days=40),
    )

    with pytest.raises(ValidationError):
        overlapping.full_clean()


@pytest.mark.django_db
def test_rule_version_allows_adjacent_validity_ranges():
    snapshot = create_snapshot()
    rule = create_refund_rule(snapshot)
    now = timezone.now()
    first_end = now + timedelta(days=30)
    RuleVersion.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        version=1,
        status=RuleVersionStatus.ACTIVE,
        valid_from=now,
        valid_to=first_end,
    )
    adjacent = RuleVersion(
        data_snapshot=snapshot,
        rule=rule,
        version=2,
        status=RuleVersionStatus.DRAFT,
        valid_from=first_end,
        valid_to=first_end + timedelta(days=30),
    )

    adjacent.full_clean()


@pytest.mark.django_db
def test_rule_version_rejects_cross_snapshot_rule_or_change_set():
    first_snapshot = create_snapshot("first-seed")
    second_snapshot = create_snapshot("second-seed")
    first_rule = create_refund_rule(first_snapshot)
    second_change_set = RuleChangeSet.objects.create(
        data_snapshot=second_snapshot,
        change_set_code="CS-RULE-001",
        title="Second snapshot change set",
    )

    version = RuleVersion(
        data_snapshot=second_snapshot,
        rule=first_rule,
        version=1,
        valid_from=timezone.now(),
        change_set=second_change_set,
    )

    with pytest.raises(ValidationError):
        version.full_clean()


@pytest.mark.django_db
def test_rule_test_case_must_match_rule_and_version_snapshot():
    first_snapshot = create_snapshot("first-seed")
    second_snapshot = create_snapshot("second-seed")
    first_rule = create_refund_rule(first_snapshot)
    second_rule = create_refund_rule(second_snapshot)
    first_version = RuleVersion.objects.create(
        data_snapshot=first_snapshot,
        rule=first_rule,
        version=1,
        valid_from=timezone.now(),
    )
    test_case = RuleTestCase(
        data_snapshot=second_snapshot,
        rule=second_rule,
        rule_version=first_version,
        name="Mismatched rule version",
        input_payload={"outage_duration_minutes": 180},
        expected_output={"eligible": True},
    )

    with pytest.raises(ValidationError):
        test_case.full_clean()


@pytest.mark.django_db
def test_rule_identifiers_are_unique_per_snapshot():
    snapshot = create_snapshot()
    rule = create_refund_rule(snapshot)
    RuleTestCase.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        name="basic placeholder scenario",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Rule.objects.create(
                data_snapshot=snapshot,
                code="REFUND-001",
                name="Duplicate",
                rule_type=RuleType.COMPENSATION,
            )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            RuleTestCase.objects.create(
                data_snapshot=snapshot,
                rule=rule,
                name="basic placeholder scenario",
            )


@pytest.mark.django_db
def test_rule_version_selection_returns_single_active_version_for_moment():
    snapshot = create_snapshot()
    rule = create_refund_rule(snapshot)
    moment = timezone.now()
    version = RuleVersion.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        version=1,
        status=RuleVersionStatus.ACTIVE,
        valid_from=moment - timedelta(days=1),
        valid_to=moment + timedelta(days=1),
    )

    selection = select_rule_version_for_moment(
        snapshot=snapshot,
        rule_code="REFUND-001",
        moment=moment,
    )

    assert selection.status == "selected"
    assert selection.selected_version == version
    assert selection.reason == "single_active_version_for_moment"


@pytest.mark.django_db
def test_rule_version_selection_returns_manual_review_when_no_version_matches():
    snapshot = create_snapshot()
    create_refund_rule(snapshot)
    moment = timezone.now()

    selection = select_rule_version_for_moment(
        snapshot=snapshot,
        rule_code="REFUND-001",
        moment=moment,
    )

    assert selection.status == "manual_review"
    assert selection.selected_version is None
    assert selection.reason == "no_active_version_for_moment"


@pytest.mark.django_db
def test_rule_version_selection_returns_manual_review_for_multiple_matches():
    snapshot = create_snapshot()
    rule = create_refund_rule(snapshot)
    moment = timezone.now()
    RuleVersion.objects.bulk_create(
        [
            RuleVersion(
                data_snapshot=snapshot,
                rule=rule,
                version=1,
                status=RuleVersionStatus.ACTIVE,
                valid_from=moment - timedelta(days=2),
                valid_to=moment + timedelta(days=2),
            ),
            RuleVersion(
                data_snapshot=snapshot,
                rule=rule,
                version=2,
                status=RuleVersionStatus.ACTIVE,
                valid_from=moment - timedelta(days=1),
                valid_to=moment + timedelta(days=1),
            ),
        ]
    )

    selection = select_rule_version_for_moment(
        snapshot=snapshot,
        rule_code="REFUND-001",
        moment=moment,
    )

    assert selection.status == "manual_review"
    assert selection.selected_version is None
    assert selection.reason == "multiple_active_versions_for_moment"
