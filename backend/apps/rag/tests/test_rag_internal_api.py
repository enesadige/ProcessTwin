import json

import pytest

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.rag.corpus_utils import content_hash
from apps.rag.models import SourceDocument


@pytest.mark.django_db
def test_rag_search_requires_authentication(client, settings):
    response = client.post(
        "/api/internal/v1/rag/search/",
        data=json.dumps({"query": "test", "snapshot_identifier": "missing"}),
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_rag_search_preserves_correlation_id_and_returns_metadata(client, settings, monkeypatch):
    settings.INTERNAL_API_SERVICE_TOKEN = "rag-test-token"
    dataset = DatasetVersion.objects.create(
        name="API dataset", generator_version="test", seed="api"
    )
    snapshot = DataSnapshot.objects.create(
        dataset_version=dataset, name="API snapshot", snapshot_key="api-snapshot"
    )
    content = "# Arama\n\nSentetik metin."
    SourceDocument.objects.create(
        data_snapshot=snapshot,
        document_code="API-DOC",
        title="Arama",
        document_type="procedure",
        source_kind="synthetic",
        version=1,
        language="tr",
        content=content,
        content_hash=content_hash(content),
        status="active",
    )
    monkeypatch.setattr(
        "apps.rag.internal_views.search",
        lambda request: {
            "query": request.query,
            "warnings": [],
            "results": [],
        },
    )
    response = client.post(
        "/api/internal/v1/rag/search/",
        data=json.dumps({"query": "test", "snapshot_identifier": snapshot.snapshot_key}),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer rag-test-token",
        HTTP_X_CORRELATION_ID="rag-correlation-1",
    )

    assert response.status_code == 200
    assert response["X-Correlation-ID"] == "rag-correlation-1"
    assert response.json()["metadata"]["correlation_id"] == "rag-correlation-1"
