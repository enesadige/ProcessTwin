from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from django.db import transaction
from django.db.models import Q

from apps.orchestration.models import (  # isort: split
    EvidenceCalculation,
    EvidenceRAGReference,
    EvidenceRecord,
    EvidenceRuleReference,
    EvidenceToolCall,
    QueryRun,
    QueryRunStatus,
)

from apps.orchestration.services import sanitize_json, sanitize_text
from apps.rag.models import DocumentChunk, SourceDocument
from apps.rules.models import RuleVersion

_RULE_VERSION_RE = re.compile(r"^(?P<code>.+):v(?P<version>\d+)$")
_TERMINAL_STATUSES = frozenset({QueryRunStatus.COMPLETED, QueryRunStatus.FAILED})


class DecisionEvidenceService:
    """Persist immutable, sanitized orchestration provenance for a QueryRun.

    This service intentionally consumes only data already persisted on the
    QueryRun. It does not execute tools, resolve rules, or perform retrieval.
    Compensation ``DecisionEvidence`` remains an independent authoritative
    record; its already-persisted reference can appear only as safe context.
    """

    def start(self, query_run: QueryRun) -> EvidenceRecord:
        """Create or reuse the draft record when a run enters execution."""
        with transaction.atomic():
            record, _ = EvidenceRecord.objects.select_for_update().get_or_create(
                query_run=query_run,
                defaults={
                    "data_snapshot": query_run.data_snapshot,
                    "snapshot_context": self._snapshot_context(query_run),
                },
            )
            return record

    def finalize(self, query_run: QueryRun) -> EvidenceRecord:
        """Write only persisted, safe evidence and make the record immutable."""
        if QueryRunStatus(query_run.status) not in _TERMINAL_STATUSES:
            raise ValueError("Evidence can only be finalized for terminal QueryRuns.")

        with transaction.atomic():
            query_run = QueryRun.objects.select_for_update().get(pk=query_run.pk)
            record, _ = EvidenceRecord.objects.select_for_update().get_or_create(
                query_run=query_run,
                defaults={
                    "data_snapshot": query_run.data_snapshot,
                    "snapshot_context": self._snapshot_context(query_run),
                },
            )
            if record.finalized:
                return record

            warnings: list[str] = []
            self._record_tools(record, query_run)
            self._record_rule_references(record, query_run, warnings)
            self._record_calculations(record, query_run)
            self._record_rag_references(record, query_run, warnings)

            record.snapshot_context = self._snapshot_context(query_run)
            record.warnings = self._warnings(query_run, warnings)
            record.save(update_fields=["snapshot_context", "warnings", "updated_at"])
            record.finalize()
            return record

    @staticmethod
    def _snapshot_context(query_run: QueryRun) -> dict[str, Any]:
        return sanitize_json(
            {
                "snapshot_id": query_run.data_snapshot_id,
                "snapshot_key": query_run.data_snapshot.snapshot_key,
                "query_run_code": query_run.query_run_code,
                "terminal_status": query_run.status,
                "structured_query_parser": query_run.structured_query_parser,
                "structured_query_parser_version": query_run.structured_query_parser_version,
                "resolved_llm_provider": query_run.resolved_llm_provider,
                "resolved_llm_model": query_run.resolved_llm_model,
                "resolved_embedding_provider": query_run.resolved_embedding_provider,
                "resolved_embedding_model": query_run.resolved_embedding_model,
                "result_fingerprint": (
                    query_run.final_result.get("result_fingerprint")
                    if isinstance(query_run.final_result, Mapping)
                    else None
                ),
                "error_code": query_run.error_code or None,
            }
        )

    @staticmethod
    def _safe_mapping(value: object) -> dict[str, Any]:
        return sanitize_json(dict(value)) if isinstance(value, Mapping) else {}

    def _record_tools(self, record: EvidenceRecord, query_run: QueryRun) -> None:
        for sequence, raw_record in enumerate(query_run.executed_tools, start=1):
            if not isinstance(raw_record, Mapping):
                continue
            request_summary = {
                key: raw_record[key]
                for key in ("call_id", "correlation_id", "result_fingerprint", "attempt_count")
                if raw_record.get(key) not in (None, "")
            }
            response_summary = {
                key: raw_record[key]
                for key in ("safe_result_summary", "result_summary", "error_code")
                if raw_record.get(key) not in (None, "")
            }
            EvidenceToolCall.objects.get_or_create(
                evidence_record=record,
                sequence=sequence,
                defaults={
                    "server_name": str(raw_record.get("server") or "unknown"),
                    "tool_name": str(raw_record.get("tool_name") or "unknown"),
                    "status": str(raw_record.get("status") or "unknown"),
                    "request_summary": self._safe_mapping(request_summary),
                    "response_summary": self._safe_mapping(response_summary),
                    "duration_ms": self._positive_int(raw_record.get("duration_ms")),
                },
            )

    def _record_rule_references(
        self, record: EvidenceRecord, query_run: QueryRun, warnings: list[str]
    ) -> None:
        final_result = query_run.final_result if isinstance(query_run.final_result, Mapping) else {}
        explicit_versions: list[str] = []
        for summary_key in ("rule_summary", "compensation_summary"):
            summary = final_result.get(summary_key)
            if not isinstance(summary, Mapping):
                continue
            versions = summary.get("rule_versions")
            if isinstance(versions, Mapping):
                explicit_versions.extend(str(value) for value in versions if value)
            elif isinstance(versions, Sequence) and not isinstance(versions, (str, bytes)):
                explicit_versions.extend(str(value) for value in versions if value)

        for reference in dict.fromkeys(explicit_versions):
            match = _RULE_VERSION_RE.fullmatch(reference)
            if not match:
                warnings.append("rule_version_reference_unresolved")
                continue
            rule_version = RuleVersion.objects.filter(
                data_snapshot_id=record.data_snapshot_id,
                rule__code=match.group("code"),
                version=int(match.group("version")),
            ).first()
            if rule_version is None:
                warnings.append("rule_version_reference_unresolved")
                continue
            EvidenceRuleReference.objects.get_or_create(
                evidence_record=record,
                rule_version=rule_version,
                reference_role="selected",
            )

    def _record_calculations(self, record: EvidenceRecord, query_run: QueryRun) -> None:
        final_result = query_run.final_result if isinstance(query_run.final_result, Mapping) else {}
        calculation_summaries = (
            ("analytics_summary", final_result.get("analytics_summary")),
            ("analytics_summaries", final_result.get("analytics_summaries")),
            ("impact_summary", final_result.get("impact_summary")),
            ("compensation_summary", final_result.get("compensation_summary")),
        )
        sequence = 1
        for code, value in calculation_summaries:
            values = value if code == "analytics_summaries" and isinstance(value, list) else [value]
            for summary in values:
                if not isinstance(summary, Mapping):
                    continue
                inputs, outputs = self._calculation_summary(code, summary)
                EvidenceCalculation.objects.get_or_create(
                    evidence_record=record,
                    sequence=sequence,
                    defaults={
                        "calculation_code": code,
                        "inputs": self._safe_mapping(inputs),
                        "outputs": self._safe_mapping(outputs),
                    },
                )
                sequence += 1

    @staticmethod
    def _calculation_summary(
        code: str, summary: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if code.startswith("analytics"):
            return (
                {key: summary.get(key) for key in ("metric", "aggregation", "group_by", "filters")},
                {
                    key: summary.get(key)
                    for key in ("rows", "included_event_count", "excluded_unknown_count")
                },
            )
        if code == "impact_summary":
            return ({}, dict(summary))
        return (
            {key: summary.get(key) for key in ("scope", "status", "considered")},
            {
                key: summary.get(key)
                for key in ("eligible", "ineligible_pending", "total_amount", "currency")
            },
        )

    def _record_rag_references(
        self, record: EvidenceRecord, query_run: QueryRun, warnings: list[str]
    ) -> None:
        final_result = query_run.final_result if isinstance(query_run.final_result, Mapping) else {}
        sources = final_result.get("retrieval_sources")
        if not isinstance(sources, list):
            return
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            code = source.get("source_code")
            version = source.get("version")
            if not isinstance(code, str) or not isinstance(version, int):
                warnings.append("rag_reference_unresolved")
                continue
            documents = list(
                SourceDocument.objects.filter(
                    Q(data_snapshot_id=record.data_snapshot_id) | Q(data_snapshot__isnull=True),
                    document_code=code,
                    version=version,
                )[:2]
            )
            if len(documents) != 1:
                warnings.append("rag_reference_unresolved")
                continue
            document = documents[0]
            section = source.get("section")
            chunks = list(
                DocumentChunk.objects.filter(source_document=document, heading=section)[:2]
            ) if isinstance(section, str) and section else []
            chunk = chunks[0] if len(chunks) == 1 else None
            section_path = source.get("section_path")
            if isinstance(section_path, list):
                normalized_path = section_path
            elif isinstance(section_path, str) and section_path:
                normalized_path = [section_path]
            elif isinstance(section, str) and section:
                normalized_path = [section]
            else:
                normalized_path = []
            EvidenceRAGReference.objects.get_or_create(
                evidence_record=record,
                source_document=document,
                document_chunk=chunk,
                defaults={
                    "section_path": sanitize_json(normalized_path),
                    "retrieval_score": self._score(source.get("score")),
                },
            )

    @staticmethod
    def _positive_int(value: object) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    @staticmethod
    def _score(value: object) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None

    @staticmethod
    def _warnings(query_run: QueryRun, additional: list[str]) -> list[str]:
        values: list[str] = []
        final_result = query_run.final_result if isinstance(query_run.final_result, Mapping) else {}
        for source in (final_result.get("warnings"), query_run.response_audit.get("warnings")):
            if isinstance(source, list):
                values.extend(item for item in source if isinstance(item, str))
        if query_run.error_code:
            values.append(f"query_run_error:{query_run.error_code}")
        values.extend(additional)
        return list(dict.fromkeys(sanitize_text(item) for item in values))
