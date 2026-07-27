import pytest
from django.db import IntegrityError

from apps.core.choices import ResultStatus
from apps.datasets.models import (
    DatasetKind,
    DatasetSnapshotStatus,
    DatasetVersion,
    DataSnapshot,
)


@pytest.mark.django_db
def test_dataset_version_generates_stable_slug():
    dataset = DatasetVersion.objects.create(
        name="Maltepe MVP",
        kind=DatasetKind.SYNTHETIC,
        generator_version="gen-0.1.0",
        seed="maltepe-seed-001",
        config={"district": "Maltepe", "device": "BNG"},
    )

    assert dataset.slug == "maltepe-mvp-gen-010-maltepe-seed-001"
    assert str(dataset) == "Maltepe MVP (gen-0.1.0)"


@pytest.mark.django_db
def test_data_snapshot_defaults_to_draft_and_insufficient_data():
    dataset = DatasetVersion.objects.create(
        name="Maltepe MVP",
        generator_version="gen-0.1.0",
        seed="maltepe-seed-001",
    )

    snapshot = DataSnapshot.objects.create(
        dataset_version=dataset,
        name="Initial snapshot",
        row_counts={"outages": 1, "customers": 10},
    )

    assert snapshot.status == DatasetSnapshotStatus.DRAFT
    assert snapshot.validation_status == ResultStatus.INSUFFICIENT_DATA
    assert snapshot.snapshot_key == "maltepe-mvp-gen-010-maltepe-seed-001-initial-snapshot"


@pytest.mark.django_db
def test_only_one_snapshot_can_be_active():
    dataset = DatasetVersion.objects.create(
        name="Maltepe MVP",
        generator_version="gen-0.1.0",
        seed="maltepe-seed-001",
    )
    DataSnapshot.objects.create(dataset_version=dataset, name="Active one", is_active=True)

    with pytest.raises(IntegrityError):
        DataSnapshot.objects.create(dataset_version=dataset, name="Active two", is_active=True)
