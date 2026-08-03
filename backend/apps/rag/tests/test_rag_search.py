from datetime import datetime

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.rag.corpus_utils import content_hash
from apps.rag.models import DocumentChunk, SourceDocument
from apps.rag.providers.base import PROMPT_VERSION
from apps.rag.providers.mock import MockEmbeddingProvider
from apps.rag.services.search import (
    CHARACTER_FRAGMENT_FACTOR,
    H1_BOILERPLATE_FACTOR,
    SearchRequest,
    hybrid_section_score,
    rerank_semantic_results,
    search,
    section_information_factor,
)


def search_fixture():
    dataset = DatasetVersion.objects.create(
        name="Search dataset", generator_version="test", seed="search"
    )
    snapshot = DataSnapshot.objects.create(
        dataset_version=dataset, name="Search snapshot", snapshot_key="search-snapshot"
    )
    docs = []
    for code, title, text in (
        ("REFUND-001-V1-SOURCE", "REFUND-001 v1", "minimum 180 dakika"),
        ("SYN-FAILOVER-MAINTENANCE-2026", "Failover", "başarısız yedek hat geçişi"),
    ):
        content = f"# {title}\n\n{text}\n"
        document = SourceDocument.objects.create(
            data_snapshot=snapshot if code.startswith("REFUND") else None,
            document_code=code,
            title=title,
            document_type="procedure",
            source_kind="synthetic",
            version=1,
            language="tr",
            content=content,
            content_hash=content_hash(content),
            status="active",
        )
        chunk = DocumentChunk.objects.create(
            source_document=document,
            sequence=0,
            heading=title,
            text=text,
            content_hash=content_hash(text),
        )
        chunk.embedding = MockEmbeddingProvider().embed(text)
        chunk.embedding_provider = "mock"
        chunk.embedding_model = "mock-embedding-768"
        chunk.embedding_version = "asymmetric-retrieval-v1"
        chunk.embedding_dimensions = 768
        chunk.metadata = {"prompt_version": PROMPT_VERSION}
        chunk.save(
            update_fields=[
                "embedding",
                "embedding_provider",
                "embedding_model",
                "embedding_version",
                "embedding_dimensions",
                "metadata",
                "updated_at",
            ]
        )
        docs.append(document)
    return snapshot, docs


@pytest.mark.django_db
def test_full_text_includes_snapshot_and_global_documents():
    snapshot, _ = search_fixture()
    result = search(
        SearchRequest(
            query="REFUND-001",
            snapshot_identifier=snapshot.snapshot_key,
            search_mode="full_text",
        )
    )

    assert result["result_count"] == 1
    assert result["results"][0]["document_code"] == "REFUND-001-V1-SOURCE"
    assert result["results"][0]["exact_code_match"] is True


@pytest.mark.django_db
@override_settings(RAG_EMBEDDING_PROVIDER="mock")
def test_semantic_search_returns_scores_without_vectors_in_payload():
    snapshot, _ = search_fixture()
    result = search(
        SearchRequest(
            query="başarısız yedek hat geçişi",
            snapshot_identifier=snapshot.snapshot_key,
            search_mode="semantic",
        )
    )

    assert result["results"]
    assert result["results"][0]["semantic_score"] is not None
    assert "embedding" not in result["results"][0]


@pytest.mark.django_db
def test_full_text_supports_corpus_vocabulary_aliases():
    snapshot, _ = search_fixture()
    result = search(
        SearchRequest(
            query="başarısız yedek hat geçişi",
            snapshot_identifier=snapshot.snapshot_key,
            search_mode="full_text",
        )
    )

    assert result["results"][0]["document_code"] == "SYN-FAILOVER-MAINTENANCE-2026"


def test_search_request_rejects_short_or_naive_queries():
    with pytest.raises(ValidationError):
        search(SearchRequest(query="x", snapshot_identifier="snapshot"))
    with pytest.raises(ValidationError):
        search(
            SearchRequest(
                query="valid",
                snapshot_identifier="snapshot",
                evaluation_time=datetime(2026, 1, 1),
            )
        )


def _ranking_item(*, pk, sequence, text, score, metadata=None, exact=False):
    document = SourceDocument(document_code="DOC", version=1)
    chunk = DocumentChunk(
        pk=pk,
        source_document=document,
        sequence=sequence,
        heading="Section",
        text=text,
        metadata=metadata or {},
    )
    return {"chunk": chunk, "score": score, "exact_code_match": exact}


def test_low_information_factors_are_general_and_exact_codes_are_exempt():
    h1 = _ranking_item(pk=1, sequence=0, text="# Başlık\n\n> Sentetik uyarı", score=0.7)
    fragment = _ranking_item(
        pk=2,
        sequence=3,
        text="Bölünmüş içerik",
        score=0.7,
        metadata={"split_reason": "character_limit", "overlap_applied": True},
    )
    exact = {**h1, "exact_code_match": True}

    assert section_information_factor(h1) == H1_BOILERPLATE_FACTOR
    assert section_information_factor(fragment) == CHARACTER_FRAGMENT_FACTOR
    assert section_information_factor(exact) == 1.0


def test_semantic_section_rerank_preserves_raw_score_and_uses_stable_tie_break():
    fragment = _ranking_item(
        pk=2,
        sequence=2,
        text="Fragment",
        score=0.651,
        metadata={"split_reason": "character_limit"},
    )
    section = _ranking_item(pk=1, sequence=1, text="Tam bölüm", score=0.636)

    ranked = rerank_semantic_results([fragment, section])

    assert [item["chunk"].pk for item in ranked] == [1, 2]
    assert ranked[0]["score"] == 0.636
    assert [item["rank"] for item in ranked] == [1, 2]


def test_hybrid_section_score_keeps_semantic_primary_and_full_text_bounded():
    semantic = {"ranking_score": 0.61, "rank": 1}
    full_text = {"rank": 1}

    assert hybrid_section_score(semantic, None, exact=False) == 0.61
    assert hybrid_section_score(semantic, full_text, exact=False) == pytest.approx(0.62)
    assert hybrid_section_score(semantic, full_text, exact=True) == pytest.approx(1.62)
