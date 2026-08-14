from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.models import (
    EvidenceCalculation,
    EvidenceRAGReference,
    EvidenceRecord,
    EvidenceRuleReference,
    EvidenceToolCall,
)
from apps.orchestration.services import QueryRunService
from apps.rag.models import DocumentChunk, DocumentStatus, DocumentType, SourceDocument, SourceKind
from apps.rules.models import Rule, RuleType, RuleVersion


def content_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def create_query_run(snapshot, *, suffix: str):
    run, _ = QueryRunService().create_or_get(
        data_snapshot=snapshot,
        idempotency_key=f"evidence-model-{suffix}",
        original_query="Kanıt kaydını incele.",
    )
    return run


def create_rule_version(snapshot, *, suffix: str) -> RuleVersion:
    rule = Rule.objects.create(
        data_snapshot=snapshot,
        code=f"EVIDENCE-{suffix}",
        name="Evidence rule",
        rule_type=RuleType.COMPENSATION,
    )
    return RuleVersion.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        version=1,
        valid_from=timezone.now() - timedelta(days=1),
    )


def create_document(snapshot, *, suffix: str) -> tuple[SourceDocument, DocumentChunk]:
    document = SourceDocument.objects.create(
        data_snapshot=snapshot,
        document_code=f"DOC-EVIDENCE-{suffix}",
        title="Evidence document",
        document_type=DocumentType.RULE_POLICY,
        source_kind=SourceKind.SYNTHETIC,
        version=1,
        content="Kural kanıtı.",
        content_hash=content_hash(f"document-{suffix}"),
        status=DocumentStatus.ACTIVE,
    )
    chunk = DocumentChunk.objects.create(
        source_document=document,
        sequence=1,
        heading="Kapsam",
        text="Kural kanıtı.",
        content_hash=content_hash(f"chunk-{suffix}"),
    )
    return document, chunk


@pytest.mark.django_db
def test_evidence_record_keeps_query_run_and_all_child_provenance_snapshot_local():
    snapshot = create_snapshot("evidence-model-record")
    query_run = create_query_run(snapshot, suffix="record")
    rule_version = create_rule_version(snapshot, suffix="record")
    document, chunk = create_document(snapshot, suffix="record")

    record = EvidenceRecord.objects.create(
        data_snapshot=snapshot,
        query_run=query_run,
        snapshot_context={"snapshot_key": snapshot.snapshot_key},
        warnings=["retrieval_partial"],
    )
    tool_call = EvidenceToolCall.objects.create(
        evidence_record=record,
        sequence=1,
        server_name="rules",
        tool_name="get_rule_version",
        status="succeeded",
        request_summary={"rule_version_id": rule_version.id},
        response_summary={"rule_code": rule_version.rule.code},
        duration_ms=12,
    )
    rule_reference = EvidenceRuleReference.objects.create(
        evidence_record=record,
        rule_version=rule_version,
        reference_role="selected",
    )
    calculation = EvidenceCalculation.objects.create(
        evidence_record=record,
        sequence=1,
        calculation_code="compensation_amount",
        inputs={"outage_minutes": 120},
        outputs={"amount": "72.06"},
    )
    rag_reference = EvidenceRAGReference.objects.create(
        evidence_record=record,
        source_document=document,
        document_chunk=chunk,
        section_path=["Kapsam"],
        retrieval_score=0.91,
    )

    assert record.query_run_id == query_run.id
    assert record.data_snapshot_id == snapshot.id
    assert tool_call.evidence_record_id == record.id
    assert rule_reference.rule_version_id == rule_version.id
    assert calculation.outputs == {"amount": "72.06"}
    assert rag_reference.document_chunk_id == chunk.id


@pytest.mark.django_db
def test_evidence_record_rejects_cross_snapshot_query_rule_and_rag_references():
    snapshot = create_snapshot("evidence-model-first")
    other_snapshot = create_snapshot("evidence-model-second")
    other_query_run = create_query_run(other_snapshot, suffix="other")

    with pytest.raises(ValidationError, match="QueryRun must belong"):
        EvidenceRecord.objects.create(data_snapshot=snapshot, query_run=other_query_run)

    record = EvidenceRecord.objects.create(
        data_snapshot=snapshot,
        query_run=create_query_run(snapshot, suffix="first"),
    )

    with pytest.raises(ValidationError, match="RuleVersion must belong"):
        EvidenceRuleReference.objects.create(
            evidence_record=record,
            rule_version=create_rule_version(other_snapshot, suffix="other"),
        )

    other_document, _ = create_document(other_snapshot, suffix="other")
    with pytest.raises(ValidationError, match="Source document must be global or match"):
        EvidenceRAGReference.objects.create(
            evidence_record=record,
            source_document=other_document,
        )


@pytest.mark.django_db
def test_finalized_evidence_and_children_cannot_be_changed_or_extended():
    snapshot = create_snapshot("evidence-model-finalized")
    record = EvidenceRecord.objects.create(
        data_snapshot=snapshot,
        query_run=create_query_run(snapshot, suffix="finalized"),
    )
    tool_call = EvidenceToolCall.objects.create(
        evidence_record=record,
        sequence=1,
        server_name="network",
        tool_name="get_outage",
        status="succeeded",
    )

    record.finalize()
    assert record.finalized is True
    assert record.finalized_at is not None

    record.warnings = ["late-warning"]
    with pytest.raises(ValidationError, match="immutable"):
        record.save()

    tool_call.tool_name = "get_other_outage"
    with pytest.raises(ValidationError, match="Finalized evidence records"):
        tool_call.save()

    with pytest.raises(ValidationError, match="Finalized evidence records"):
        EvidenceCalculation.objects.create(
            evidence_record=record,
            sequence=1,
            calculation_code="late_calculation",
        )
