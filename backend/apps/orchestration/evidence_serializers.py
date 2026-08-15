from __future__ import annotations

from typing import Any

from apps.orchestration.models import EvidenceRecord
from apps.orchestration.services import sanitize_json


def evidence_record_list_item(record: EvidenceRecord) -> dict[str, Any]:
    """Return the small, safe summary used by the general evidence index."""
    return {
        "evidence_code": record.evidence_code,
        "snapshot": {
            "id": record.data_snapshot_id,
            "key": record.data_snapshot.snapshot_key,
        },
        "query_run": {
            "code": record.query_run.query_run_code,
            "terminal_status": record.query_run.status,
        },
        "finalized_at": record.finalized_at.isoformat() if record.finalized_at else None,
    }


def evidence_record_detail(record: EvidenceRecord) -> dict[str, Any]:
    """Return the safe, persisted evidence detail for a finalized record."""
    return {
        "evidence_code": record.evidence_code,
        "finalized": record.finalized,
        "finalized_at": record.finalized_at.isoformat() if record.finalized_at else None,
        "snapshot": {
            "id": record.data_snapshot_id,
            "key": record.data_snapshot.snapshot_key,
        },
        "query_run": {
            "code": record.query_run.query_run_code,
            "terminal_status": record.query_run.status,
            "started_at": (
                record.query_run.started_at.isoformat() if record.query_run.started_at else None
            ),
            "completed_at": (
                record.query_run.completed_at.isoformat()
                if record.query_run.completed_at
                else None
            ),
        },
        "provenance": sanitize_json(record.snapshot_context),
        "warnings": sanitize_json(record.warnings),
        "tool_timeline": [
            {
                "sequence": tool.sequence,
                "server": tool.server_name,
                "tool_name": tool.tool_name,
                "status": tool.status,
                "attempt_count": tool.request_summary.get("attempt_count"),
                "duration_ms": tool.duration_ms,
                "result_summary": (
                    tool.response_summary.get("safe_result_summary")
                    or tool.response_summary.get("result_summary")
                ),
                "error_code": tool.response_summary.get("error_code"),
            }
            for tool in record.evidencetoolcall_records.all()
        ],
        "calculations": [
            {
                "sequence": calculation.sequence,
                "calculation_code": calculation.calculation_code,
                "inputs": sanitize_json(calculation.inputs),
                "outputs": sanitize_json(calculation.outputs),
            }
            for calculation in record.evidencecalculation_records.all()
        ],
        "rule_references": [
            {
                "rule_code": reference.rule_version.rule.code,
                "version": reference.rule_version.version,
                "reference_role": reference.reference_role,
                "metadata": sanitize_json(reference.metadata),
            }
            for reference in record.evidencerulereference_records.all()
        ],
        "rag_references": [
            {
                "document_code": reference.source_document.document_code,
                "document_version": reference.source_document.version,
                "chunk_heading": (
                    reference.document_chunk.heading if reference.document_chunk else None
                ),
                "section_path": sanitize_json(reference.section_path),
                "retrieval_score": reference.retrieval_score,
            }
            for reference in record.evidenceragreference_records.all()
        ],
    }
