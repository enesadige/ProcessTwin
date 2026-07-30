import pytest
from data_generator.configs import multi_city_realism_v1 as config
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.choices import ResultStatus
from apps.datasets.models import DatasetVersion, DataSnapshot


@pytest.mark.django_db
def test_seed_multicity_realism_creates_passive_snapshot_without_large_fixture(monkeypatch):
    def fake_seed(*, snapshot, batch_size):
        return {
            "customers": 14400,
            "subscriptions": 16200,
            "alarms": 2100,
            "quality_measurements": 12000,
        }

    def fake_validate(snapshot, **kwargs):
        return {
            "passed": True,
            "row_counts": {"subscriptions": 16200},
            "checks": [{"name": "fake", "expected": 1, "actual": 1, "passed": True}],
        }

    monkeypatch.setattr(
        "apps.datasets.management.commands.seed_multicity_realism.seed_multicity_realism_dataset",
        fake_seed,
    )
    monkeypatch.setattr(
        "apps.datasets.management.commands.seed_multicity_realism.validate_multicity_realism_snapshot",
        fake_validate,
    )

    call_command("seed_multicity_realism")

    dataset = DatasetVersion.objects.get(slug=config.DATASET_SLUG)
    snapshot = dataset.snapshots.get()
    assert dataset.generator_version == config.GENERATOR_VERSION
    assert dataset.seed == config.DATASET_SEED
    assert dataset.config["reference_datetime"] == config.DEFAULT_REFERENCE_DATETIME
    assert snapshot.name == config.SNAPSHOT_NAME
    assert snapshot.is_active is False
    assert snapshot.validation_status == ResultStatus.EXACT
    assert snapshot.validation_result["seed_stage"] == "039.5.6_multi_city_realism"


@pytest.mark.django_db
def test_seed_multicity_realism_second_run_validates_without_duplicates(monkeypatch):
    calls = {"seed": 0}

    def fake_seed(*, snapshot, batch_size):
        calls["seed"] += 1
        return {
            "customers": 14400,
            "subscriptions": 16200,
            "alarms": 2100,
            "quality_measurements": 12000,
        }

    def fake_validate(snapshot, **kwargs):
        return {
            "passed": True,
            "row_counts": {"subscriptions": 16200},
            "checks": [{"name": "fake", "expected": 1, "actual": 1, "passed": True}],
        }

    monkeypatch.setattr(
        "apps.datasets.management.commands.seed_multicity_realism.seed_multicity_realism_dataset",
        fake_seed,
    )
    monkeypatch.setattr(
        "apps.datasets.management.commands.seed_multicity_realism.validate_multicity_realism_snapshot",
        fake_validate,
    )

    call_command("seed_multicity_realism")
    call_command("seed_multicity_realism")

    assert calls["seed"] == 1
    assert DatasetVersion.objects.filter(slug=config.DATASET_SLUG).count() == 1
    assert DataSnapshot.objects.filter(dataset_version__slug=config.DATASET_SLUG).count() == 1


@pytest.mark.django_db
def test_seed_multicity_realism_rolls_back_on_validation_failure(monkeypatch):
    def fake_seed(*, snapshot, batch_size):
        return {"customers": 0, "subscriptions": 0, "alarms": 0, "quality_measurements": 0}

    def fake_validate(snapshot, **kwargs):
        return {
            "passed": False,
            "row_counts": {},
            "checks": [{"name": "forced", "expected": 1, "actual": 0, "passed": False}],
        }

    monkeypatch.setattr(
        "apps.datasets.management.commands.seed_multicity_realism.seed_multicity_realism_dataset",
        fake_seed,
    )
    monkeypatch.setattr(
        "apps.datasets.management.commands.seed_multicity_realism.validate_multicity_realism_snapshot",
        fake_validate,
    )

    with pytest.raises(CommandError, match="forced"):
        call_command("seed_multicity_realism")

    assert not DatasetVersion.objects.filter(slug=config.DATASET_SLUG).exists()


@pytest.mark.django_db
def test_seed_multicity_realism_validate_only_requires_existing_dataset():
    with pytest.raises(CommandError, match="does not exist"):
        call_command("seed_multicity_realism", "--validate-only")


def test_multicity_realism_config_totals_are_consistent():
    assert (
        sum(
            len(names)
            for city_config in config.CITY_PROFILES.values()
            for names in city_config["districts"].values()
        )
        == 59
    )
    assert sum(item["gpon"] for item in config.DISTRICT_TECHNOLOGY_DISTRIBUTION.values()) == 7577
    assert sum(item["fiber"] for item in config.DISTRICT_TECHNOLOGY_DISTRIBUTION.values()) == 2042
    assert sum(item["vdsl"] for item in config.DISTRICT_TECHNOLOGY_DISTRIBUTION.values()) == 5894
    assert sum(item["adsl"] for item in config.DISTRICT_TECHNOLOGY_DISTRIBUTION.values()) == 687
    assert sum(item["metro"] for item in config.DISTRICT_TECHNOLOGY_DISTRIBUTION.values()) == 520
    assert (
        sum(config.DEVICE_DISTRIBUTION[district]["olt"] for district in config.DEVICE_DISTRIBUTION)
        == 32
    )
    assert (
        sum(
            config.DEVICE_DISTRIBUTION[district]["dslam"] for district in config.DEVICE_DISTRIBUTION
        )
        == 95
    )
    assert (
        sum(
            config.DEVICE_DISTRIBUTION[district]["standard_access"]
            for district in config.DEVICE_DISTRIBUTION
        )
        == 51
    )
    assert (
        sum(
            config.DEVICE_DISTRIBUTION[district]["corporate_fiber_aggregation"]
            for district in config.DEVICE_DISTRIBUTION
        )
        == 33
    )
