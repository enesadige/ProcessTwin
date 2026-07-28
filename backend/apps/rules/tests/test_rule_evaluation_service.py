import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.operations.models import Outage
from apps.rules.models import Rule, RuleVersion, RuleVersionStatus
from apps.rules.services.evaluation import RuleEvaluationInputError, RuleEvaluationService


@pytest.mark.django_db
def test_rule_evaluation_selects_v2_for_main_bng_outage_and_matches_duration_seconds():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")

    result = RuleEvaluationService().evaluate_for_outage(
        snapshot=snapshot,
        rule_code="REFUND-001",
        outage=outage,
        context=eligible_context(duration_seconds=12000),
    )

    assert result.rule_code == "REFUND-001"
    assert result.rule_version == 2
    assert result.evaluation_status == "matched"
    assert result.matched is True
    assert result.selected_rule_version["version"] == 2
    assert result.action_config["minimum_impact_minutes"] == 120
    assert duration_condition(result)["expected"] == 7200
    assert duration_condition(result)["actual"] == 12000


@pytest.mark.django_db
def test_rule_evaluation_selects_v1_for_v1_date_and_matches_200_minutes():
    snapshot = seed_snapshot()

    result = evaluate_at(
        snapshot=snapshot,
        event_datetime=dt(2026, 7, 10, 12, 0),
        duration_seconds=12000,
    )

    assert result.rule_version == 1
    assert result.evaluation_status == "matched"
    assert result.action_config["minimum_impact_minutes"] == 180
    assert duration_condition(result)["expected"] == 10800


@pytest.mark.django_db
def test_rule_evaluation_v1_rejects_179_minutes_but_matches_exact_180_minutes():
    snapshot = seed_snapshot()
    event_datetime = dt(2026, 7, 10, 12, 0)

    below = evaluate_at(
        snapshot=snapshot,
        event_datetime=event_datetime,
        duration_seconds=179 * 60,
    )
    exact = evaluate_at(
        snapshot=snapshot,
        event_datetime=event_datetime,
        duration_seconds=180 * 60,
    )

    assert below.rule_version == 1
    assert below.evaluation_status == "unmatched"
    assert below.matched is False
    assert duration_condition(below)["expected"] == 10800
    assert duration_condition(below)["actual"] == 10740
    assert exact.evaluation_status == "matched"
    assert exact.matched is True
    assert duration_condition(exact)["actual"] == 10800


@pytest.mark.django_db
def test_rule_evaluation_v2_rejects_119_minutes_but_matches_exact_120_minutes():
    snapshot = seed_snapshot()
    event_datetime = dt(2026, 7, 20, 12, 0)

    below = evaluate_at(
        snapshot=snapshot,
        event_datetime=event_datetime,
        duration_seconds=119 * 60,
    )
    exact = evaluate_at(
        snapshot=snapshot,
        event_datetime=event_datetime,
        duration_seconds=120 * 60,
    )

    assert below.rule_version == 2
    assert below.evaluation_status == "unmatched"
    assert below.matched is False
    assert duration_condition(below)["expected"] == 7200
    assert duration_condition(below)["actual"] == 7140
    assert exact.evaluation_status == "matched"
    assert exact.matched is True
    assert duration_condition(exact)["actual"] == 7200


@pytest.mark.django_db
def test_rule_evaluation_unmatches_non_full_outage_context():
    snapshot = seed_snapshot()

    result = RuleEvaluationService().evaluate(
        snapshot=snapshot,
        rule_code="REFUND-001",
        event_datetime=dt(2026, 7, 20, 12, 0),
        context=eligible_context(duration_seconds=12000) | {"outage_type": "degradation"},
    )

    assert result.evaluation_status == "unmatched"
    assert result.matched is False
    assert field_condition(result, "outage_type")["matched"] is False


@pytest.mark.django_db
def test_rule_evaluation_unmatches_inactive_subscription_or_connection():
    snapshot = seed_snapshot()
    service = RuleEvaluationService()
    event_datetime = dt(2026, 7, 20, 12, 0)

    inactive_subscription = service.evaluate(
        snapshot=snapshot,
        rule_code="REFUND-001",
        event_datetime=event_datetime,
        context=eligible_context(duration_seconds=12000)
        | {"subscription_active_during_outage": False},
    )
    inactive_connection = service.evaluate(
        snapshot=snapshot,
        rule_code="REFUND-001",
        event_datetime=event_datetime,
        context=eligible_context(duration_seconds=12000)
        | {"connection_active_during_outage": False},
    )

    assert inactive_subscription.evaluation_status == "unmatched"
    subscription_condition = field_condition(
        inactive_subscription,
        "subscription_active_during_outage",
    )
    assert subscription_condition["matched"] is False
    assert inactive_connection.evaluation_status == "unmatched"
    connection_condition = field_condition(
        inactive_connection,
        "connection_active_during_outage",
    )
    assert connection_condition["matched"] is False


@pytest.mark.django_db
def test_rule_evaluation_returns_manual_review_for_missing_required_context_fields():
    snapshot = seed_snapshot()

    missing_duration = RuleEvaluationService().evaluate(
        snapshot=snapshot,
        rule_code="REFUND-001",
        event_datetime=dt(2026, 7, 20, 12, 0),
        context={
            "outage_type": "full_outage",
            "subscription_active_during_outage": True,
            "connection_active_during_outage": True,
        },
    )
    missing_subscription = RuleEvaluationService().evaluate(
        snapshot=snapshot,
        rule_code="REFUND-001",
        event_datetime=dt(2026, 7, 20, 12, 0),
        context={
            "outage_type": "full_outage",
            "outage_duration_seconds": 12000,
            "connection_active_during_outage": True,
        },
    )
    missing_connection = RuleEvaluationService().evaluate(
        snapshot=snapshot,
        rule_code="REFUND-001",
        event_datetime=dt(2026, 7, 20, 12, 0),
        context={
            "outage_type": "full_outage",
            "outage_duration_seconds": 12000,
            "subscription_active_during_outage": True,
        },
    )

    assert missing_duration.evaluation_status == "manual_review"
    assert missing_duration.missing_fields == ["outage_duration_seconds"]
    assert missing_subscription.evaluation_status == "manual_review"
    assert missing_subscription.missing_fields == ["subscription_active_during_outage"]
    assert missing_connection.evaluation_status == "manual_review"
    assert missing_connection.missing_fields == ["connection_active_during_outage"]


@pytest.mark.django_db
def test_rule_evaluation_returns_manual_review_for_unknown_operator():
    snapshot = seed_snapshot()
    version = get_rule_version(snapshot=snapshot, version_number=2)
    version.condition_tree = {
        "operator": "all",
        "conditions": [
            {"field": "outage_type", "op": "starts_with", "value": "full"},
        ],
    }
    version.save(update_fields=["condition_tree"])

    result = RuleEvaluationService().evaluate(
        snapshot=snapshot,
        rule_code="REFUND-001",
        event_datetime=dt(2026, 7, 20, 12, 0),
        context=eligible_context(duration_seconds=12000),
    )

    assert result.evaluation_status == "manual_review"
    assert result.unsupported_operators == ["starts_with"]


@pytest.mark.django_db
def test_rule_evaluation_returns_manual_review_when_no_rule_version_matches():
    snapshot = seed_snapshot()

    result = RuleEvaluationService().evaluate(
        snapshot=snapshot,
        rule_code="REFUND-001",
        event_datetime=dt(2025, 12, 31, 12, 0),
        context=eligible_context(duration_seconds=12000),
    )

    assert result.evaluation_status == "manual_review"
    assert result.rule_version is None
    assert result.errors == ["no_active_version_for_moment"]
    assert result.selected_rule_version is None


@pytest.mark.django_db
def test_rule_evaluation_returns_manual_review_when_multiple_rule_versions_match():
    snapshot = seed_snapshot()
    rule = Rule.objects.get(data_snapshot=snapshot, code="REFUND-001")
    existing = get_rule_version(snapshot=snapshot, version_number=2)
    RuleVersion.objects.bulk_create(
        [
            RuleVersion(
                data_snapshot=snapshot,
                rule=rule,
                version=99,
                status=RuleVersionStatus.ACTIVE,
                valid_from=existing.valid_from,
                valid_to=existing.valid_to,
                condition_tree=existing.condition_tree,
                action_config=existing.action_config,
            )
        ]
    )

    result = RuleEvaluationService().evaluate(
        snapshot=snapshot,
        rule_code="REFUND-001",
        event_datetime=dt(2026, 7, 20, 12, 0),
        context=eligible_context(duration_seconds=12000),
    )

    assert result.evaluation_status == "manual_review"
    assert result.rule_version is None
    assert result.errors == ["multiple_active_versions_for_moment"]


@pytest.mark.django_db
def test_rule_evaluation_rejects_naive_event_datetime():
    snapshot = seed_snapshot()

    with pytest.raises(RuleEvaluationInputError, match="timezone-aware"):
        RuleEvaluationService().evaluate(
            snapshot=snapshot,
            rule_code="REFUND-001",
            event_datetime=timezone.datetime(2026, 7, 20, 12, 0),
            context=eligible_context(duration_seconds=12000),
        )


def seed_snapshot() -> DataSnapshot:
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def get_outage(snapshot: DataSnapshot, outage_code: str) -> Outage:
    return Outage.objects.get(data_snapshot=snapshot, outage_code=outage_code)


def get_rule_version(*, snapshot: DataSnapshot, version_number: int) -> RuleVersion:
    return RuleVersion.objects.get(
        data_snapshot=snapshot,
        rule__code="REFUND-001",
        version=version_number,
    )


def evaluate_at(*, snapshot: DataSnapshot, event_datetime, duration_seconds: int):
    return RuleEvaluationService().evaluate(
        snapshot=snapshot,
        rule_code="REFUND-001",
        event_datetime=event_datetime,
        context=eligible_context(duration_seconds=duration_seconds),
    )


def eligible_context(*, duration_seconds: int) -> dict:
    return {
        "outage_type": "full_outage",
        "outage_duration_seconds": duration_seconds,
        "subscription_active_during_outage": True,
        "connection_active_during_outage": True,
    }


def dt(year: int, month: int, day: int, hour: int, minute: int):
    return timezone.datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=timezone.get_current_timezone(),
    )


def duration_condition(result):
    return field_condition(result, "outage_duration_seconds")


def field_condition(result, field_name: str):
    conditions = result.matched_conditions + result.unmatched_conditions
    return next(condition for condition in conditions if condition["field"] == field_name)
