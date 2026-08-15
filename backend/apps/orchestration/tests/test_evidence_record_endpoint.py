from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.models import (
    EvidenceCalculation,
    EvidenceRAGReference,
    EvidenceRecord,
    EvidenceRuleReference,
    EvidenceToolCall,
    QueryRunStatus,
)
from apps.orchestration.services import QueryRunService
from apps.rag.models import DocumentChunk, DocumentStatus, DocumentType, SourceDocument, SourceKind
from apps.rules.models import Rule, RuleType, RuleVersion

ENDPOINT = "/api/orchestration/evidence-records/detail/"
LIST_ENDPOINT = "/api/orchestration/evidence-records/"


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _query_run(snapshot, suffix: str):
    return QueryRunService().create_or_get(
        data_snapshot=snapshot,
        idempotency_key=f"evidence-record-endpoint-{suffix}",
        original_query="Evidence detayını göster.",
    )[0]


def _record(snapshot, suffix: str, *, finalized: bool) -> EvidenceRecord:
    record = EvidenceRecord.objects.create(
        data_snapshot=snapshot,
        query_run=_query_run(snapshot, suffix),
        snapshot_context={"snapshot_key": snapshot.snapshot_key, "token": "must-not-expose"},
        warnings=["safe_warning"],
    )
    if finalized:
        record.finalize()
    return record


def _complete_record(snapshot) -> EvidenceRecord:
    record = _record(snapshot, "complete", finalized=False)
    rule = Rule.objects.create(
        data_snapshot=snapshot,
        code="EVIDENCE-ENDPOINT",
        name="Evidence endpoint rule",
        rule_type=RuleType.COMPENSATION,
    )
    version = RuleVersion.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        version=1,
        valid_from=timezone.now() - timedelta(days=1),
    )
    document = SourceDocument.objects.create(
        data_snapshot=snapshot,
        document_code="EVIDENCE-ENDPOINT-DOC",
        title="Evidence endpoint document",
        document_type=DocumentType.RULE_POLICY,
        source_kind=SourceKind.SYNTHETIC,
        version=1,
        content="Evidence document",
        content_hash=_hash("evidence-endpoint-document"),
        status=DocumentStatus.ACTIVE,
    )
    chunk = DocumentChunk.objects.create(
        source_document=document,
        sequence=1,
        heading="Kapsam",
        text="Evidence section",
        content_hash=_hash("evidence-endpoint-chunk"),
    )
    EvidenceToolCall.objects.create(
        evidence_record=record,
        sequence=1,
        server_name="compensation",
        tool_name="evaluate_outage",
        status="succeeded",
        request_summary={"attempt_count": 2, "raw_payload": "not-exposed"},
        response_summary={"safe_result_summary": "Evaluation complete.", "token": "hidden"},
        duration_ms=18,
    )
    EvidenceCalculation.objects.create(
        evidence_record=record,
        sequence=1,
        calculation_code="compensation_summary",
        inputs={"considered": 2},
        outputs={"eligible": 1, "total_amount": "72.06"},
    )
    EvidenceRuleReference.objects.create(
        evidence_record=record,
        rule_version=version,
        reference_role="selected",
    )
    EvidenceRAGReference.objects.create(
        evidence_record=record,
        source_document=document,
        document_chunk=chunk,
        section_path=["Kapsam"],
        retrieval_score=0.91,
    )
    record.query_run.status = QueryRunStatus.COMPLETED
    record.query_run.completed_at = timezone.now()
    record.query_run.final_result = {"summary": "safe"}
    record.query_run.save()
    record.finalize()
    return record


def _client() -> Client:
    user = get_user_model().objects.create_user(
        username="evidence-record-reader",
        password="correct-pass-123",
        role="analyst",
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_evidence_record_endpoint_returns_finalized_snapshot_local_safe_detail():
    snapshot = create_snapshot("evidence-record-endpoint-source")
    record = _complete_record(snapshot)

    response = _client().get(
        ENDPOINT,
        {"snapshot_identifier": snapshot.snapshot_key, "evidence_code": record.evidence_code},
    )

    assert response.status_code == 200
    payload = response.json()["data"]["evidence_record"]
    assert payload["evidence_code"] == record.evidence_code
    assert payload["finalized"] is True
    assert payload["snapshot"]["key"] == snapshot.snapshot_key
    assert payload["tool_timeline"] == [
        {
            "sequence": 1,
            "server": "compensation",
            "tool_name": "evaluate_outage",
            "status": "succeeded",
            "attempt_count": 2,
            "duration_ms": 18,
            "result_summary": "Evaluation complete.",
            "error_code": None,
        }
    ]
    assert payload["calculations"][0]["outputs"]["total_amount"] == "72.06"
    assert payload["rule_references"] == [
        {
            "rule_code": "EVIDENCE-ENDPOINT",
            "version": 1,
            "reference_role": "selected",
            "metadata": {},
        }
    ]
    assert payload["rag_references"][0]["document_code"] == "EVIDENCE-ENDPOINT-DOC"
    assert payload["rag_references"][0]["chunk_heading"] == "Kapsam"
    assert payload["rag_references"][0]["retrieval_score"] == 0.91
    serialized = str(payload)
    assert "raw_payload" not in serialized
    assert "must-not-expose" not in serialized
    assert "token" not in serialized


@pytest.mark.django_db
def test_evidence_record_endpoint_rejects_draft_missing_and_cross_snapshot_records():
    snapshot = create_snapshot("evidence-record-endpoint-source")
    other_snapshot = create_snapshot("evidence-record-endpoint-other")
    draft = _record(snapshot, "draft", finalized=False)
    finalized = _complete_record(snapshot)
    client = _client()

    draft_response = client.get(
        ENDPOINT,
        {"snapshot_identifier": snapshot.snapshot_key, "evidence_code": draft.evidence_code},
    )
    mismatch_response = client.get(
        ENDPOINT,
        {
            "snapshot_identifier": other_snapshot.snapshot_key,
            "evidence_code": finalized.evidence_code,
        },
    )
    missing_response = client.get(
        ENDPOINT,
        {"snapshot_identifier": snapshot.snapshot_key, "evidence_code": "EV-MISSING"},
    )

    assert draft_response.status_code == 404
    assert mismatch_response.status_code == 404
    assert missing_response.status_code == 404
    assert all(
        response.json()["error"]["code"] == "not_found"
        for response in (draft_response, mismatch_response, missing_response)
    )


@pytest.mark.django_db
def test_evidence_record_list_returns_only_finalized_terminal_records_with_snapshot_provenance():
    snapshot = create_snapshot("evidence-record-list-source")
    listed = _complete_record(snapshot)
    draft = _record(snapshot, "list-draft", finalized=False)
    pending = _record(snapshot, "list-pending", finalized=True)

    response = _client().get(LIST_ENDPOINT)

    assert response.status_code == 200
    records = response.json()["data"]["evidence_records"]
    item = next(record for record in records if record["evidence_code"] == listed.evidence_code)
    assert item == {
        "evidence_code": listed.evidence_code,
        "snapshot": {"id": snapshot.id, "key": snapshot.snapshot_key},
        "query_run": {
            "code": listed.query_run.query_run_code,
            "terminal_status": QueryRunStatus.COMPLETED,
        },
        "finalized_at": listed.finalized_at.isoformat(),
    }
    evidence_codes = {record["evidence_code"] for record in records}
    assert draft.evidence_code not in evidence_codes
    assert pending.evidence_code not in evidence_codes
