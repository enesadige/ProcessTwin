from types import SimpleNamespace

from apps.rag.corpus_utils import content_hash
from apps.rag.services.chunking import build_chunk_specs


def source_document(content, *, metadata=None, code="DOC-CHUNK", version=1):
    return SimpleNamespace(
        content=content,
        content_hash=content_hash(content),
        document_code=code,
        version=version,
        metadata=metadata or {},
        data_snapshot_id=None,
        data_snapshot=None,
    )


def test_heading_sections_preserve_hierarchy_and_exact_offsets():
    content = "# Ana\n\nGiris.\n\n## Alt\n\nREFUND-001 uygulanir.\n"
    specs = build_chunk_specs(
        source_document(
            content,
            metadata={"rule_refs": ["REFUND-001"]},
            code="REFUND-001-V2-SOURCE",
            version=2,
        )
    )

    assert [spec.sequence for spec in specs] == list(range(len(specs)))
    assert specs[0].section_path == ["Ana"]
    assert specs[1].section_path == ["Ana", "Alt"]
    assert specs[1].rule_code == "REFUND-001"
    assert specs[1].rule_version == 2
    for spec in specs:
        assert content[spec.char_start : spec.char_end] == spec.text
        assert spec.content_hash == content_hash(spec.text)
        assert spec.metadata["chunking_version"] == "heading-char-v1"


def test_multiple_references_are_metadata_only_and_unlisted_codes_are_ignored():
    content = "# Kurallar\n\nBB-FULL-OUTAGE-TIERED ve BB-PARTIAL-OUTAGE-PRORATED birlikte.\n"
    document = source_document(
        content,
        metadata={"rule_refs": ["BB-FULL-OUTAGE-TIERED", "BB-PARTIAL-OUTAGE-PRORATED"]},
    )

    spec = build_chunk_specs(document)[0]
    assert spec.rule_code is None
    assert spec.rule_version is None
    assert spec.metadata["rule_refs"] == [
        "BB-FULL-OUTAGE-TIERED",
        "BB-PARTIAL-OUTAGE-PRORATED",
    ]


def test_long_plain_text_uses_deterministic_character_overlap():
    content = "# Uzun bölüm\n\n" + ("uzun metin " * 400)
    specs = build_chunk_specs(source_document(content))

    assert len(specs) > 1
    assert all(len(spec.text) <= 1800 for spec in specs)
    overlap_specs = [spec for spec in specs if spec.metadata["overlap_applied"]]
    assert overlap_specs
    assert overlap_specs[0].char_start < specs[1].char_end
    assert all(spec.text.strip() for spec in specs)


def test_alarm_and_ground_truth_references_are_narrowed_per_chunk():
    content = (
        "# Olay\n\nBNG_UNREACHABLE alarmı için GT-MCR-NET-BNG-WIDE-001 vakası.\n\n"
        "## Genel\n\nGenel açıklama.\n"
    )
    document = source_document(
        content,
        metadata={
            "alarm_refs": ["BNG_UNREACHABLE", "OPTICAL_SIGNAL_LOSS"],
            "ground_truth_refs": ["GT-MCR-NET-BNG-WIDE-001", "GT-MCR-NET-POWER-ZONE-001"],
        },
    )

    specs = build_chunk_specs(document)
    assert specs[0].metadata["alarm_refs"] == ["BNG_UNREACHABLE"]
    assert specs[0].metadata["ground_truth_refs"] == ["GT-MCR-NET-BNG-WIDE-001"]
    assert specs[-1].metadata["alarm_refs"] == []
    assert specs[-1].metadata["ground_truth_refs"] == []
