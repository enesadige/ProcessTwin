from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.rag.models import (
    EMBEDDING_DIMENSIONS,
    DocumentChunk,
    DocumentStatus,
    DocumentType,
    IndexRun,
    IndexRunStatus,
    SourceDocument,
    SourceKind,
)

pytestmark = pytest.mark.django_db


def digest() -> str:
    return "a" * 64


def make_snapshot(slug="rag-test"):
    dataset = DatasetVersion.objects.create(
        name="RAG test dataset",
        slug=slug,
        generator_version="test-v1",
        seed="rag-test-seed",
    )
    return DataSnapshot.objects.create(dataset_version=dataset, name="RAG test snapshot")


def make_document(snapshot=None, code="DOC-001", version=1):
    document = SourceDocument(
        data_snapshot=snapshot,
        document_code=code,
        title="Sentetik kural dokümanı",
        document_type=DocumentType.RULE_POLICY,
        source_kind=SourceKind.SYNTHETIC,
        version=version,
        content="İçerik",
        content_hash=digest(),
        status=DocumentStatus.DRAFT,
    )
    document.full_clean()
    document.save()
    return document


def test_source_document_supports_global_and_snapshot_scopes():
    assert make_document() is not None
    assert make_document(make_snapshot(), code="DOC-002") is not None


def test_source_document_scope_and_version_uniqueness():
    snapshot = make_snapshot()
    make_document(snapshot, code="DOC-003")
    with pytest.raises(ValidationError):
        duplicate = SourceDocument(
            data_snapshot=snapshot,
            document_code="DOC-003",
            title="Duplicate",
            document_type=DocumentType.PROCEDURE,
            source_kind=SourceKind.SYNTHETIC,
            version=1,
            content="İçerik",
            content_hash=digest(),
        )
        duplicate.full_clean()
    make_document(snapshot, code="DOC-003", version=2)
    make_document(make_snapshot("rag-test-2"), code="DOC-003")


def test_global_document_duplicate_is_rejected():
    make_document(code="DOC-GLOBAL")
    with pytest.raises(ValidationError):
        duplicate = SourceDocument(
            document_code="DOC-GLOBAL",
            title="Duplicate",
            document_type=DocumentType.RULE_POLICY,
            source_kind=SourceKind.SYNTHETIC,
            version=1,
            content="İçerik",
            content_hash=digest(),
        )
        duplicate.full_clean()


def test_source_document_rejects_invalid_range_and_hash():
    document = SourceDocument(
        document_code="DOC-INVALID",
        title="Invalid",
        document_type=DocumentType.OTHER,
        source_kind=SourceKind.MANUAL,
        version=1,
        content="İçerik",
        content_hash="invalid",
        valid_from=timezone.now(),
        valid_to=timezone.now() - timedelta(minutes=1),
    )
    with pytest.raises(ValidationError) as error:
        document.full_clean()
    assert "content_hash" in error.value.message_dict
    assert "valid_to" in error.value.message_dict


def test_document_chunk_validates_ranges_and_metadata():
    document = make_document(code="DOC-CHUNK")
    chunk = DocumentChunk(
        source_document=document,
        sequence=0,
        section_path=["Bölüm 1", "Kapsam"],
        text="Parça",
        content_hash=digest(),
        rule_code="REFUND-001",
        rule_version=2,
    )
    chunk.full_clean()
    chunk.save()
    assert chunk.section_path == ["Bölüm 1", "Kapsam"]
    assert chunk.rule_code == "REFUND-001"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"char_start": 0},
        {"char_start": 4, "char_end": 2},
        {"token_start": 0},
        {"token_start": 4, "token_end": 2},
    ],
)
def test_document_chunk_rejects_incomplete_or_reversed_ranges(kwargs):
    chunk = DocumentChunk(
        source_document=make_document(code="DOC-RANGE"),
        sequence=0,
        text="Parça",
        content_hash=digest(),
        **kwargs,
    )
    with pytest.raises(ValidationError):
        chunk.full_clean()


def test_document_chunk_sequence_is_unique_and_embedding_is_optional():
    document = make_document(code="DOC-SEQUENCE")
    first = DocumentChunk(
        source_document=document,
        sequence=0,
        text="Parça",
        content_hash=digest(),
    )
    first.full_clean()
    first.save()
    duplicate = DocumentChunk(
        source_document=document,
        sequence=0,
        text="Tekrar",
        content_hash=digest(),
    )
    with pytest.raises(ValidationError):
        duplicate.full_clean()
    assert first.embedding is None


def test_document_chunk_accepts_768_dimensions_and_rejects_other_dimensions():
    document = make_document(code="DOC-EMBEDDING")
    valid = DocumentChunk(
        source_document=document,
        sequence=0,
        text="Parça",
        content_hash=digest(),
        embedding=[0.0] * EMBEDDING_DIMENSIONS,
        embedding_dimensions=EMBEDDING_DIMENSIONS,
    )
    valid.full_clean()
    invalid = DocumentChunk(
        source_document=document,
        sequence=1,
        text="Parça",
        content_hash=digest(),
        embedding=[0.0] * 3,
    )
    with pytest.raises(ValidationError):
        invalid.full_clean()


def test_index_run_status_and_time_invariants():
    now = timezone.make_aware(datetime(2026, 1, 1))
    running = IndexRun(status=IndexRunStatus.RUNNING)
    with pytest.raises(ValidationError):
        running.full_clean()
    succeeded = IndexRun(status=IndexRunStatus.SUCCEEDED, started_at=now)
    with pytest.raises(ValidationError):
        succeeded.full_clean()
    reversed_times = IndexRun(
        status=IndexRunStatus.PENDING,
        started_at=now,
        completed_at=now - timedelta(seconds=1),
    )
    with pytest.raises(ValidationError):
        reversed_times.full_clean()


def test_index_run_metadata_and_snapshot_are_optional():
    run = IndexRun(
        data_snapshot=make_snapshot("rag-index-test"),
        status=IndexRunStatus.PENDING,
        metadata={"synthetic": True},
        embedding_provider="not-generated",
    )
    run.full_clean()
    run.save()
    assert run.data_snapshot_id is not None
    assert run.metadata["synthetic"] is True
