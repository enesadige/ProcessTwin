from pathlib import Path

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


def test_manifest_has_exactly_ten_documents_and_unique_codes():
    assert len(DOCUMENTS) == 10
    codes = [item["document_code"] for item in DOCUMENTS]
    assert len(codes) == len(set(codes))
    assert sum(item["scope_type"] == "global" for item in DOCUMENTS) == 2
    assert sum(item["scope_type"] == "multi_city" for item in DOCUMENTS) == 6
    assert sum(item["scope_type"] == "maltepe" for item in DOCUMENTS) == 2


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
    assert len(set(MULTICITY_ALARMS)) == 30
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
