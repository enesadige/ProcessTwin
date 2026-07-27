import pytest
from data_generator.configs import maltepe_mvp_v1 as seed_config
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.choices import ResultStatus
from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetSnapshotStatus, DatasetVersion, DataSnapshot
from apps.geography.models import City, District, Neighborhood


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_passive_dataset_snapshot_and_geography():
    call_command("seed_maltepe_mvp")

    dataset = DatasetVersion.objects.get(slug=get_target_dataset_slug())
    snapshot = dataset.snapshots.get()
    city = City.objects.get(name="İstanbul")
    district = District.objects.get(city=city, name="Maltepe")
    neighborhoods = list(
        Neighborhood.objects.filter(district=district)
        .order_by("name")
        .values_list("name", flat=True)
    )

    assert dataset.kind == "synthetic"
    assert dataset.generator_version == seed_config.GENERATOR_VERSION
    assert dataset.seed == seed_config.DATASET_SEED
    assert dataset.config["reference_datetime"] == seed_config.DEFAULT_REFERENCE_DATETIME
    assert dataset.config["customer_plan"]["vip_customers"] == 20
    assert snapshot.name == seed_config.SNAPSHOT_NAME
    assert snapshot.status == DatasetSnapshotStatus.VALIDATED
    assert snapshot.validation_status == ResultStatus.EXACT
    assert snapshot.is_active is False
    assert snapshot.activated_at is None
    assert snapshot.row_counts["neighborhoods"] == 5
    assert neighborhoods == sorted(seed_config.NEIGHBORHOODS)


@pytest.mark.django_db
def test_seed_maltepe_mvp_rejects_duplicate_without_reset():
    call_command("seed_maltepe_mvp")

    with pytest.raises(CommandError, match="already exists"):
        call_command("seed_maltepe_mvp")

    assert DatasetVersion.objects.filter(slug=get_target_dataset_slug()).count() == 1


@pytest.mark.django_db
def test_seed_maltepe_mvp_reset_recreates_only_target_dataset_and_keeps_geography():
    call_command("seed_maltepe_mvp")
    city_id = City.objects.get(name="İstanbul").id
    other_dataset = DatasetVersion.objects.create(
        name="Other Dataset",
        generator_version="other-v1",
        seed="other-seed",
    )

    call_command("seed_maltepe_mvp", "--reset")

    assert DatasetVersion.objects.filter(slug=get_target_dataset_slug()).count() == 1
    assert DatasetVersion.objects.filter(id=other_dataset.id).exists()
    assert City.objects.get(name="İstanbul").id == city_id
    assert City.objects.filter(name="İstanbul").count() == 1


@pytest.mark.django_db
def test_seed_maltepe_mvp_can_create_passive_snapshot_when_another_snapshot_is_active():
    other_dataset = DatasetVersion.objects.create(
        name="Other Active Dataset",
        generator_version="other-active-v1",
        seed="other-active-seed",
    )
    DataSnapshot.objects.create(
        dataset_version=other_dataset,
        name="Other active snapshot",
        is_active=True,
    )

    call_command("seed_maltepe_mvp")

    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    assert snapshot.is_active is False
    assert DataSnapshot.objects.filter(is_active=True).get().dataset_version == other_dataset


@pytest.mark.django_db
def test_seed_maltepe_mvp_activate_creates_active_snapshot_when_none_exists():
    call_command("seed_maltepe_mvp", "--activate")

    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    assert snapshot.is_active is True
    assert snapshot.activated_at is not None


@pytest.mark.django_db
def test_seed_maltepe_mvp_activate_rejects_existing_active_snapshot():
    other_dataset = DatasetVersion.objects.create(
        name="Other Active Dataset",
        generator_version="other-active-v1",
        seed="other-active-seed",
    )
    DataSnapshot.objects.create(
        dataset_version=other_dataset,
        name="Other active snapshot",
        is_active=True,
    )

    with pytest.raises(CommandError, match="Another active data snapshot"):
        call_command("seed_maltepe_mvp", "--activate")

    assert not DatasetVersion.objects.filter(slug=get_target_dataset_slug()).exists()


@pytest.mark.django_db
def test_seed_maltepe_mvp_stores_custom_reference_datetime_as_istanbul_iso_string():
    call_command("seed_maltepe_mvp", "--reference-datetime", "2026-09-01T00:00:00+03:00")

    dataset = DatasetVersion.objects.get(slug=get_target_dataset_slug())
    assert dataset.config["reference_datetime"] == "2026-09-01T00:00:00+03:00"
