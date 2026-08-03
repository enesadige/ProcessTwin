import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.rag.corpus_utils import content_hash
from apps.rag.models import (
    DocumentChunk,
    DocumentStatus,
    DocumentType,
    IndexRun,
    SourceDocument,
    SourceKind,
)
from apps.rag.services.indexing import run_index

pytestmark = pytest.mark.django_db


def make_document(code="DOC-INDEX", content="# Başlık\n\nMetin.\n"):
    return SourceDocument.objects.create(
        document_code=code,
        title=code,
        document_type=DocumentType.PROCEDURE,
        source_kind=SourceKind.SYNTHETIC,
        version=1,
        language="tr",
        content=content,
        content_hash=content_hash(content),
        status=DocumentStatus.ACTIVE,
        metadata={"corpus_key": "test-corpus"},
    )


def test_index_command_creates_chunks_and_second_run_is_unchanged():
    document = make_document()

    call_command("index_rag_documents", document_code=[document.document_code])
    first_count = DocumentChunk.objects.filter(source_document=document).count()
    first_run = IndexRun.objects.latest("id")

    call_command("index_rag_documents", document_code=[document.document_code])
    second_run = IndexRun.objects.latest("id")

    assert first_count > 0
    assert second_run.metadata["unchanged_count"] == 1
    assert second_run.chunk_count == first_run.chunk_count == first_count
    assert DocumentChunk.objects.filter(source_document=document).count() == first_count


def test_validate_only_does_not_create_index_run_or_chunks():
    document = make_document()

    call_command("index_rag_documents", document_code=[document.document_code], validate_only=True)

    assert IndexRun.objects.count() == 0
    assert DocumentChunk.objects.filter(source_document=document).count() == 0


def test_unknown_document_and_conflicting_options_are_rejected():
    with pytest.raises(CommandError, match="Unknown document code"):
        call_command("index_rag_documents", document_code=["MISSING-DOCUMENT"])
    with pytest.raises(CommandError, match="cannot be used together"):
        call_command("index_rag_documents", reset=True, validate_only=True)


def test_failed_index_keeps_previous_chunks_and_records_safe_failure():
    document = make_document()
    call_command("index_rag_documents", document_code=[document.document_code])
    original_count = DocumentChunk.objects.filter(source_document=document).count()

    changed_content = "# Changed\n\n" + ("x" * 1900)
    SourceDocument.objects.filter(pk=document.pk).update(content=changed_content)
    document.refresh_from_db()

    with pytest.raises(ValidationError):
        run_index([document])

    assert DocumentChunk.objects.filter(source_document=document).count() == original_count
    failed = IndexRun.objects.latest("id")
    assert failed.status == "failed"
    assert "traceback" not in failed.error_summary.lower()
