import pytest
from django.test import override_settings

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.rag.corpus_utils import content_hash
from apps.rag.models import DocumentChunk, SourceDocument
from apps.rag.providers.base import PROMPT_VERSION
from apps.rag.providers.mock import MockEmbeddingProvider
from apps.rag.services.search import SearchRequest, search


@pytest.mark.django_db
@override_settings(RAG_EMBEDDING_PROVIDER="mock")
def test_hybrid_search_exposes_section_scores_and_ranking_version():
    dataset = DatasetVersion.objects.create(
        name="Hybrid dataset", generator_version="test", seed="hybrid"
    )
    snapshot = DataSnapshot.objects.create(
        dataset_version=dataset, name="Hybrid snapshot", snapshot_key="hybrid-snapshot"
    )
    content = "# Metro SLA\n\nPaket kaybı SLA ihlali."
    document = SourceDocument.objects.create(
        data_snapshot=snapshot,
        document_code="ME-PACKET-LOSS-BREACH",
        title="Metro SLA",
        document_type="sla",
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
        heading="Metro SLA",
        text="Paket kaybı SLA ihlali.",
        content_hash=content_hash("Paket kaybı SLA ihlali."),
    )
    chunk.embedding = MockEmbeddingProvider().embed(chunk.text)
    chunk.embedding_provider = "mock"
    chunk.embedding_model = "mock-embedding-768"
    chunk.embedding_version = "asymmetric-retrieval-v1"
    chunk.embedding_dimensions = 768
    chunk.metadata = {"prompt_version": PROMPT_VERSION}
    chunk.save()

    result = search(
        SearchRequest(
            query="paket kaybı SLA",
            snapshot_identifier=snapshot.snapshot_key,
            search_mode="hybrid",
        )
    )

    assert result["effective_mode"] == "hybrid"
    assert result["ranking_version"] == "hybrid-section-v2"
    assert result["results"][0]["hybrid_score"] is not None
    assert result["results"][0]["semantic_rank"] == 1
    assert result["results"][0]["full_text_rank"] == 1
