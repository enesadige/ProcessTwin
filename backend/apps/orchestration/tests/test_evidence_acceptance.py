from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.evidence_service import DecisionEvidenceService
from apps.orchestration.models import (
    EvidenceCalculation,
    EvidenceRAGReference,
    EvidenceRuleReference,
    EvidenceToolCall,
    QueryRunStatus,
)
from apps.orchestration.services import QueryRunService
from apps.rag.models import DocumentChunk, DocumentStatus, DocumentType, SourceDocument, SourceKind
from apps.rules.models import Rule, RuleType, RuleVersion

ENDPOINT = "/api/orchestration/evidence-records/detail/"


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _client() -> Client:
    user = get_user_model().objects.create_user(
        username="evidence-acceptance-reader",
        password="correct-pass-123",
        role="analyst",
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_completed_query_run_materializes_snapshot_local_evidence_through_public_detail_api():
    snapshot = create_snapshot("evidence-acceptance")
    rule = Rule.objects.create(
        data_snapshot=snapshot,
        code="EVIDENCE-ACCEPTANCE-RULE",
        name="Evidence acceptance rule",
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
        document_code="EVIDENCE-ACCEPTANCE-DOC",
        title="Evidence acceptance document",
        document_type=DocumentType.RULE_POLICY,
        source_kind=SourceKind.SYNTHETIC,
        version=1,
        content="Snapshot-local evidence source.",
        content_hash=_hash("evidence-acceptance-document"),
        status=DocumentStatus.ACTIVE,
    )
    DocumentChunk.objects.create(
        source_document=document,
        sequence=1,
        heading="Kapsam",
        text="Evidence acceptance section.",
        content_hash=_hash("evidence-acceptance-chunk"),
    )

    service = QueryRunService()
    query_run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="evidence-acceptance-completed-query-run",
        original_query="Doğrulanmış telafi kanıtını göster.",
    )
    planned = service.save_plan(
        query_run,
        structured_query={"intent": "compensation"},
        planned_tools=[
            {"server": "network", "tool_name": "get_outage"},
            {"server": "compensation", "tool_name": "evaluate_outage"},
        ],
    )
    executing = service.transition(planned, target_status=QueryRunStatus.EXECUTING)
    draft = executing.evidence_record
    assert draft.finalized is False

    for record in (
        {
            "call_id": "acceptance-network",
            "server": "network",
            "tool_name": "get_outage",
            "status": "succeeded",
            "attempt_count": 1,
            "duration_ms": 11,
            "safe_result_summary": "Outage resolved.",
            "raw_payload": {"authorization": "must-not-persist"},
        },
        {
            "call_id": "acceptance-compensation",
            "server": "compensation",
            "tool_name": "evaluate_outage",
            "status": "succeeded",
            "attempt_count": 2,
            "duration_ms": 19,
            "safe_result_summary": "Compensation evaluated.",
            "raw_payload": {"token": "must-not-persist"},
        },
    ):
        executing = service.append_execution_record(executing, record=record)

    completed = service.complete(
        executing,
        final_result={
            "warnings": ["retrieval_partial"],
            "analytics_summary": {
                "metric": "affected_customers",
                "aggregation": "sum",
                "rows": [{"label": "Ankara", "value": 12}],
                "included_event_count": 1,
                "excluded_unknown_count": 0,
            },
            "compensation_summary": {
                "status": "calculated",
                "considered": 2,
                "eligible": 1,
                "total_amount": "72.06",
                "currency": "TRY",
                "rule_versions": {f"{rule.code}:v{version.version}": 1},
            },
            "retrieval_sources": [
                {
                    "source_code": document.document_code,
                    "version": document.version,
                    "section": "Kapsam",
                    "section_path": "Kapsam",
                    "score": 0.91,
                }
            ],
        },
    )
    record = completed.evidence_record
    assert record.id == draft.id
    assert record.finalized is True
    assert record.data_snapshot_id == snapshot.id
    assert EvidenceToolCall.objects.filter(evidence_record=record).count() == 2
    assert EvidenceCalculation.objects.filter(evidence_record=record).count() == 2
    assert EvidenceRuleReference.objects.filter(
        evidence_record=record, rule_version=version, reference_role="selected"
    ).count() == 1
    assert EvidenceRAGReference.objects.filter(
        evidence_record=record, source_document=document
    ).count() == 1

    response = _client().get(
        ENDPOINT,
        {"snapshot_identifier": snapshot.snapshot_key, "evidence_code": record.evidence_code},
    )

    assert response.status_code == 200
    payload = response.json()["data"]["evidence_record"]
    assert payload["query_run"]["code"] == completed.query_run_code
    assert payload["query_run"]["terminal_status"] == QueryRunStatus.COMPLETED
    assert payload["snapshot"]["key"] == snapshot.snapshot_key
    assert [tool["tool_name"] for tool in payload["tool_timeline"]] == [
        "get_outage",
        "evaluate_outage",
    ]
    assert [tool["attempt_count"] for tool in payload["tool_timeline"]] == [1, 2]
    assert [tool["duration_ms"] for tool in payload["tool_timeline"]] == [11, 19]
    assert payload["calculations"][0]["calculation_code"] == "analytics_summary"
    assert payload["calculations"][1]["calculation_code"] == "compensation_summary"
    assert payload["rule_references"] == [
        {
            "rule_code": rule.code,
            "version": 1,
            "reference_role": "selected",
            "metadata": {},
        }
    ]
    assert payload["rag_references"][0]["document_code"] == document.document_code
    assert payload["rag_references"][0]["document_version"] == document.version
    assert payload["rag_references"][0]["chunk_heading"] == "Kapsam"
    assert payload["rag_references"][0]["retrieval_score"] == 0.91
    assert payload["warnings"] == ["retrieval_partial"]
    assert "authorization" not in str(payload)
    assert "must-not-persist" not in str(payload)

    DecisionEvidenceService().finalize(completed)
    assert EvidenceToolCall.objects.filter(evidence_record=record).count() == 2
    assert EvidenceCalculation.objects.filter(evidence_record=record).count() == 2
