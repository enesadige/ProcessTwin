from pathlib import Path

import pytest

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.rag.corpus_manifest import (
    CORPUS_KEY,
    DOCUMENTS,
    GROUND_TRUTH_CASES,
    MULTICITY_ALARMS,
    MULTICITY_RULES,
    PROJECT_ROOT,
    SYNTHETIC_NOTICE,
)
from apps.rag.corpus_utils import content_hash, normalize_markdown
from apps.rag.management.commands.seed_rag_corpus import (
    resolve_ground_truth_snapshot,
    snapshot_for_descriptor,
)


def test_manifest_has_versioned_thirteen_document_causal_corpus():
    assert len(DOCUMENTS) == 13
    identities = {
        (item["document_code"], item["version"], item["snapshot_identifier"])
        for item in DOCUMENTS
    }
    assert len(identities) == 13
    assert sum(item["scope_type"] == "global" for item in DOCUMENTS) == 3
    assert sum(item["scope_type"] == "multi_city" for item in DOCUMENTS) == 8
    assert sum(item["scope_type"] == "maltepe" for item in DOCUMENTS) == 2
    expected_versions = {
        ("SYN-CAUSAL-ANALYSIS-2026", 1),
        ("SYN-ALARM-CATALOG-2026", 2),
        ("SYN-COMP-2026-ELIGIBILITY", 2),
    }
    assert expected_versions <= {
        (item["document_code"], item["version"]) for item in DOCUMENTS
    }


def test_manifest_files_are_canonical_synthetic_turkish_sources():
    for descriptor in DOCUMENTS:
        path = PROJECT_ROOT / descriptor["file_path"]
        assert path.is_file()
        assert path.parts[-2] in {"rules", "procedures", "alarm_catalog", "compensation"}
        content = path.read_text(encoding="utf-8")
        assert SYNTHETIC_NOTICE in content
        assert descriptor["language"] == "tr"
        assert descriptor["source_kind"] == "synthetic"


def test_manifest_coverage_catalogs_are_non_empty_and_unique():
    assert len(set(MULTICITY_RULES)) == 25
    assert len(set(MULTICITY_ALARMS)) == 32
    assert len(set(GROUND_TRUTH_CASES)) == 30
    assert all(code for code in MULTICITY_RULES + MULTICITY_ALARMS + GROUND_TRUTH_CASES)
    assert CORPUS_KEY == "processtwin-rag-corpus-v1"


def test_markdown_normalization_is_lf_nfc_and_single_final_newline():
    normalized = normalize_markdown("# Başlık\r\nmetin  \r\n\r\n")
    assert normalized == "# Başlık\nmetin\n"
    assert normalized.endswith("\n")
    assert not normalized.endswith("\n\n")
    assert content_hash(normalized) == content_hash(normalized.replace("\n", "\r\n"))


def test_document_paths_are_relative_to_project():
    for descriptor in DOCUMENTS:
        assert not Path(descriptor["file_path"]).is_absolute()


def test_causal_sources_are_public_safe_and_exclude_raw_sample_data():
    causal_documents = [
        item for item in DOCUMENTS if item["version"] == 2 or "CAUSAL" in item["document_code"]
    ]
    forbidden = ("outageAlarms_anonymized", "password=", "authorization:", "api_key=", "sk-")
    for descriptor in causal_documents:
        content = (PROJECT_ROOT / descriptor["file_path"]).read_text(encoding="utf-8")
        assert all(value.casefold() not in content.casefold() for value in forbidden)


def test_multicity_corpus_descriptors_use_the_explicit_versioned_snapshot():
    descriptor = next(item for item in DOCUMENTS if item["scope_type"] == "multi_city")
    selected_snapshot = object()

    assert (
        snapshot_for_descriptor(descriptor, {"multicity": selected_snapshot})
        is selected_snapshot
    )


@pytest.mark.django_db
def test_repair_snapshot_uses_declared_source_for_ground_truth_references():
    source_dataset = DatasetVersion.objects.create(
        name="RAG source",
        generator_version="test-v1",
        seed="source",
    )
    source = DataSnapshot.objects.create(dataset_version=source_dataset, name="Source")
    repair_dataset = DatasetVersion.objects.create(
        name="RAG repair",
        generator_version="test-v2",
        seed="repair",
        config={"source_snapshot_id": source.pk},
    )
    repair = DataSnapshot.objects.create(dataset_version=repair_dataset, name="Repair")

    assert resolve_ground_truth_snapshot(repair) == source


@pytest.mark.django_db
def test_snapshot_without_declared_source_keeps_its_own_ground_truth_scope():
    dataset = DatasetVersion.objects.create(
        name="RAG standalone",
        generator_version="test-v1",
        seed="standalone",
    )
    snapshot = DataSnapshot.objects.create(dataset_version=dataset, name="Standalone")

    assert resolve_ground_truth_snapshot(snapshot) == snapshot
