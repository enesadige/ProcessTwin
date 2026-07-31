from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from data_generator.exporters.synthetic_review_pack import (
    ExportOptions,
    ReviewPackWriter,
    resolve_snapshot,
    serialize_value,
)
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.datasets.models import DatasetVersion, DataSnapshot


@pytest.mark.django_db
def test_resolve_snapshot_requires_explicit_selector():
    with pytest.raises(ValueError, match="snapshot-key veya --dataset-slug"):
        resolve_snapshot(snapshot_key=None, dataset_slug=None)


@pytest.mark.django_db
def test_resolve_snapshot_rejects_mismatched_dataset_slug():
    dataset = DatasetVersion.objects.create(
        name="Synthetic A",
        slug="synthetic-a",
        generator_version="v1",
        seed="seed-a",
    )
    snapshot = DataSnapshot.objects.create(
        dataset_version=dataset,
        name="Snapshot A",
        snapshot_key="snapshot-a",
    )

    with pytest.raises(ValueError, match="aynı dataset"):
        resolve_snapshot(snapshot_key=snapshot.snapshot_key, dataset_slug="other-dataset")


@pytest.mark.django_db
def test_export_command_passes_options_to_exporter(monkeypatch, tmp_path):
    captured = {}

    class StubResult:
        dataset_slug = "multi-city-realism-v1"
        snapshot_key = "snapshot-key"
        output_dir = tmp_path
        zip_path = None
        zip_size_bytes = 0
        csv_count = 3
        total_csv_rows = 10
        xlsx_created = False
        db_counts_unchanged = True
        inconsistencies = []

    def fake_export(options):
        captured["options"] = options
        return StubResult()

    monkeypatch.setattr(
        "apps.datasets.management.commands.export_synthetic_review_pack.export_synthetic_review_pack",
        fake_export,
    )

    call_command(
        "export_synthetic_review_pack",
        "--dataset-slug",
        "multi-city-realism-v1",
        "--include-full-data",
        "--include-maltepe-regression",
        "--sample-size",
        "7",
        "--output-dir",
        str(tmp_path),
        "--zip",
        "--overwrite",
    )

    options = captured["options"]
    assert isinstance(options, ExportOptions)
    assert options.dataset_slug == "multi-city-realism-v1"
    assert options.snapshot_key is None
    assert options.sample_size == 7
    assert options.include_full_data is True
    assert options.include_maltepe_regression is True
    assert options.make_zip is True
    assert options.overwrite is True


def test_serialize_value_handles_review_pack_formats():
    assert serialize_value(None) == ""
    assert serialize_value(True) == "true"
    assert serialize_value(Decimal("39.90")) == "39.90"
    assert serialize_value(datetime(2026, 8, 1, 0, 0, tzinfo=UTC)) == ("2026-08-01T00:00:00+00:00")
    assert serialize_value({"b": 2, "a": 1}) == '{"a": 1, "b": 2}'


@pytest.mark.django_db
def test_write_csv_rejects_duplicate_headers(tmp_path):
    dataset = DatasetVersion.objects.create(
        name="Synthetic",
        slug="synthetic",
        generator_version="v1",
        seed="seed",
    )
    snapshot = DataSnapshot.objects.create(
        dataset_version=dataset,
        name="Snapshot",
        snapshot_key="snapshot",
    )
    writer = ReviewPackWriter(
        output_dir=tmp_path,
        snapshot=snapshot,
        maltepe_snapshot=None,
        sample_size=5,
        include_full_data=False,
        source_git_commit="test",
        progress=lambda message: None,
    )

    with pytest.raises(ValueError, match="Duplicate headers"):
        writer.write_csv(
            "bad.csv",
            ["a", "a"],
            [{"a": 1}],
            "test",
            "test",
            "snapshot",
        )


@pytest.mark.django_db
def test_secret_scan_detects_high_risk_values(tmp_path):
    dataset = DatasetVersion.objects.create(
        name="Synthetic",
        slug="synthetic",
        generator_version="v1",
        seed="seed",
    )
    snapshot = DataSnapshot.objects.create(
        dataset_version=dataset,
        name="Snapshot",
        snapshot_key="snapshot",
    )
    (tmp_path / "leak.csv").write_text(
        "name,value\nSECRET_KEY=unsafe,email@example.com\n",
        encoding="utf-8",
    )
    writer = ReviewPackWriter(
        output_dir=Path(tmp_path),
        snapshot=snapshot,
        maltepe_snapshot=None,
        sample_size=5,
        include_full_data=False,
        source_git_commit="test",
        progress=lambda message: None,
    )

    findings = writer.scan_for_secrets()

    assert any("possible secret pattern" in item for item in findings)
    assert any("possible email/PII pattern" in item for item in findings)


@pytest.mark.django_db
def test_command_surfaces_export_errors(monkeypatch, tmp_path):
    def fake_export(options):
        raise ValueError("forced selector error")

    monkeypatch.setattr(
        "apps.datasets.management.commands.export_synthetic_review_pack.export_synthetic_review_pack",
        fake_export,
    )

    with pytest.raises(CommandError, match="forced selector error"):
        call_command(
            "export_synthetic_review_pack",
            "--output-dir",
            str(tmp_path),
        )
