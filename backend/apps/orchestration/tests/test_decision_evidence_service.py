from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest
from django.utils import timezone

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.evidence_service import DecisionEvidenceService
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


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _run(snapshot, suffix: str):
    return QueryRunService().create_or_get(
        data_snapshot=snapshot,
        idempotency_key=f"decision-evidence-service-{suffix}",
        original_query="Doğrulanmış kanıtı göster.",
    )[0]


def _rule_version(snapshot) -> RuleVersion:
    rule = Rule.objects.create(
        data_snapshot=snapshot,
        code="COMPENSATION-TEST",
        name="Compensation test",
        rule_type=RuleType.COMPENSATION,
    )
    return RuleVersion.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        version=1,
        valid_from=timezone.now() - timedelta(days=1),
    )


def _document(snapshot):
    document = SourceDocument.objects.create(
        data_snapshot=snapshot,
        document_code="DOC-TEST",
        title="Evidence document",
        document_type=DocumentType.RULE_POLICY,
        source_kind=SourceKind.SYNTHETIC,
        version=1,
        content="Doğrulanmış belge.",
        content_hash=_hash("document"),
        status=DocumentStatus.ACTIVE,
    )
    DocumentChunk.objects.create(
        source_document=document,
        sequence=1,
        heading="Kapsam",
        text="Doğrulanmış bölüm.",
        content_hash=_hash("chunk"),
    )
    return document


def _executing(run):
    service = QueryRunService()
    planned = service.save_plan(
        run,
        structured_query={"intent": "compensation"},
        planned_tools=[{"server": "compensation", "tool_name": "evaluate_outage"}],
    )
    return service.transition(planned, target_status=QueryRunStatus.EXECUTING)


@pytest.mark.django_db
def test_completed_run_persists_only_existing_safe_provenance_and_finalizes():
    snapshot = create_snapshot("decision-evidence-service-success")
    version = _rule_version(snapshot)
    _document(snapshot)
    executing = _executing(_run(snapshot, "success"))
    service = QueryRunService()
    service.append_execution_record(
        executing,
        record={
            "call_id": "call-1",
            "server": "compensation",
            "tool_name": "evaluate_outage",
            "status": "succeeded",
            "attempt_count": 1,
            "duration_ms": 12,
            "safe_result_summary": "Evaluation completed.",
            "raw_payload": {"token": "must-not-persist"},
        },
    )
    completed = service.complete(
        executing,
        final_result={
            "warnings": ["retrieval_partial"],
            "rule_summary": {"rule_versions": [f"{version.rule.code}:v{version.version}"]},
            "compensation_summary": {
                "status": "calculated",
                "considered": 2,
                "eligible": 1,
                "total_amount": "72.06",
                "currency": "TRY",
                "rule_versions": {f"{version.rule.code}:v{version.version}": 1},
                "evidence_references": ["compensation-evidence-hash"],
            },
            "retrieval_sources": [
                {
                    "source_code": "DOC-TEST",
                    "version": 1,
                    "section": "Kapsam",
                    "section_path": "Kapsam",
                    "score": 0.91,
                }
            ],
        },
    )

    record = completed.evidence_record
    assert record.finalized is True
    assert record.data_snapshot_id == snapshot.id
    assert record.snapshot_context["query_run_code"] == completed.query_run_code
    assert EvidenceToolCall.objects.filter(evidence_record=record).count() == 1
    tool = EvidenceToolCall.objects.get(evidence_record=record)
    assert tool.response_summary == {"safe_result_summary": "Evaluation completed."}
    assert "token" not in str(tool.request_summary)
    assert (
        EvidenceRuleReference.objects.filter(
            evidence_record=record, rule_version=version
        ).count()
        == 1
    )
    assert EvidenceCalculation.objects.filter(evidence_record=record).count() == 1
    rag = EvidenceRAGReference.objects.get(evidence_record=record)
    assert rag.source_document.document_code == "DOC-TEST"
    assert rag.document_chunk.heading == "Kapsam"
    assert rag.retrieval_score == 0.91


@pytest.mark.django_db
def test_failed_and_answerability_runs_do_not_fabricate_children_or_duplicate_records():
    snapshot = create_snapshot("decision-evidence-service-terminal")
    service = QueryRunService()

    failed = service.fail(
        _run(snapshot, "failed"),
        error_code="tool_failed",
        error_summary="Bearer secret failed.",
    )
    failed_record = failed.evidence_record
    assert failed_record.finalized is True
    assert EvidenceToolCall.objects.filter(evidence_record=failed_record).count() == 0
    assert EvidenceRuleReference.objects.filter(evidence_record=failed_record).count() == 0
    assert EvidenceRAGReference.objects.filter(evidence_record=failed_record).count() == 0

    clarification = _executing(_run(snapshot, "clarification"))
    completed = service.complete(
        clarification,
        final_result={
            "schema_version": "answerability-result.v1",
            "answerability": {"status": "clarification"},
        },
    )
    record = completed.evidence_record
    DecisionEvidenceService().finalize(completed)
    assert EvidenceRecord.objects.filter(query_run=completed).count() == 1
    assert EvidenceToolCall.objects.filter(evidence_record=record).count() == 0
    assert EvidenceCalculation.objects.filter(evidence_record=record).count() == 0


@pytest.mark.django_db
def test_retry_creates_a_separate_evidence_record_while_replay_reuses_finalized_one():
    snapshot = create_snapshot("decision-evidence-service-retry")
    service = QueryRunService()
    original = service.complete(
        _executing(_run(snapshot, "original")), final_result={"summary": "safe"}
    )
    original_record_id = original.evidence_record.id

    DecisionEvidenceService().finalize(original)
    assert EvidenceRecord.objects.filter(query_run=original).count() == 1
    assert original.evidence_record.id == original_record_id

    retry, _ = service.create_retry(original, idempotency_key="decision-evidence-service-retry-new")
    retry = service.complete(_executing(retry), final_result={"summary": "safe retry"})
    assert retry.retry_of_id == original.id
    assert retry.evidence_record.id != original_record_id
