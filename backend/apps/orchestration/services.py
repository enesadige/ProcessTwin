from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from pydantic import ValidationError

from apps.core.exceptions import ProcessTwinError
from apps.datasets.models import DataSnapshot
from apps.orchestration.models import TERMINAL_QUERY_RUN_STATUSES, QueryRun, QueryRunStatus
from apps.orchestration.structured_query import StructuredQuery
from apps.orchestration.tool_plan import ToolPlan

SENSITIVE_KEY_PARTS = frozenset(
    {
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "ip",
        "mac",
        "subscriber_id",
        "subscriber_number",
        "customer_id",
        "customer_number",
        "subscription_number",
        "session_identifier",
        "raw_payload",
        "payload",
    }
)
SAFE_TOOL_FIELDS = frozenset(
    {
        "call_id",
        "server",
        "tool_name",
        "argument_summary",
        "status",
        "result_summary",
        "safe_result_summary",
        "result_fingerprint",
        "error_code",
        "error_summary",
        "correlation_id",
        "attempt_count",
        "duration_ms",
        "started_at",
        "completed_at",
    }
)
STATUS_TRANSITIONS = {
    QueryRunStatus.PENDING: frozenset({QueryRunStatus.PLANNED, QueryRunStatus.FAILED}),
    QueryRunStatus.PLANNED: frozenset({QueryRunStatus.EXECUTING, QueryRunStatus.FAILED}),
    QueryRunStatus.EXECUTING: frozenset({QueryRunStatus.COMPLETED, QueryRunStatus.FAILED}),
    QueryRunStatus.COMPLETED: frozenset(),
    QueryRunStatus.FAILED: frozenset(),
}

_IP_ADDRESS_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC_ADDRESS_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
_BEARER_RE = re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:api[_ -]?key|token|secret|password|authorization)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_IDENTIFIER_LABEL_RE = re.compile(
    r"\b(?:customer|müşteri|subscriber|abonelik|subscription)"
    r"(?:\s+(?:id|no|number|numarası)\s*[:=#-]?\s*[A-Za-z0-9._-]+"
    r"|\s+[0-9][A-Za-z0-9._-]*|\s*[:=#-]\s*[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
_EMAIL_ADDRESS_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE_NUMBER_RE = re.compile(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b")
_DECIMAL_NUMBER_RE = re.compile(r"^\d+[.,]\d{1,2}$")
_ISO_TIME_BUCKET_RE = re.compile(r"^\d{4}-(?:\d{2}|\d{2}-\d{2}|W\d{2})$")
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class QueryRunError(ProcessTwinError):
    pass


class QueryRunTransitionError(QueryRunError):
    def __init__(self, *, current: str, target: str):
        super().__init__(
            message="QueryRun status transition is not allowed.",
            code="invalid_query_run_transition",
            details={"current_status": current, "target_status": target},
        )


class QueryRunIdempotencyConflictError(QueryRunError):
    def __init__(self):
        super().__init__(
            message="Idempotency key is already associated with another snapshot.",
            code="query_run_idempotency_snapshot_conflict",
        )


def sanitize_text(value: str | None) -> str:
    text = (value or "").strip()
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _SECRET_ASSIGNMENT_RE.sub("[REDACTED]", text)
    text = _IDENTIFIER_LABEL_RE.sub("[REDACTED_IDENTIFIER]", text)
    text = _IP_ADDRESS_RE.sub("[REDACTED_IP]", text)
    text = _MAC_ADDRESS_RE.sub("[REDACTED_MAC]", text)
    text = _EMAIL_ADDRESS_RE.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_NUMBER_RE.sub(
        lambda match: (
            match.group(0)
            if _DECIMAL_NUMBER_RE.fullmatch(match.group(0))
            or _ISO_TIME_BUCKET_RE.fullmatch(match.group(0))
            else "[REDACTED_PHONE]"
        ),
        text,
    )
    return text or "[REDACTED]"


def sanitize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            key_parts = set(re.split(r"[^a-z0-9]+", normalized_key))
            if (
                normalized_key.startswith("raw_")
                or normalized_key in SENSITIVE_KEY_PARTS
                or any(part in key_parts for part in SENSITIVE_KEY_PARTS)
            ):
                continue
            sanitized[str(key)] = sanitize_json(item)
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_json(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def sanitize_tool_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    sanitized_records: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise QueryRunError(
                message="Tool records must be objects.", code="invalid_query_run_tool_record"
            )
        sanitized_records.append(
            {
                str(key): sanitize_json(value)
                for key, value in record.items()
                if str(key) in SAFE_TOOL_FIELDS
            }
        )
    return sanitized_records


class QueryRunService:
    """Deterministic persistence boundary; orchestration remains out of scope."""

    def create_or_get(
        self,
        *,
        data_snapshot: DataSnapshot,
        idempotency_key: str,
        original_query: str,
        request_id: str | None = None,
        owner=None,
    ) -> tuple[QueryRun, bool]:
        if not idempotency_key.strip():
            raise QueryRunError(
                message="idempotency_key is required.", code="invalid_query_run_idempotency_key"
            )
        defaults: dict[str, Any] = {"original_query": sanitize_text(original_query)}
        if request_id:
            defaults["request_id"] = request_id
        try:
            with transaction.atomic():
                query_run, created = QueryRun.objects.get_or_create(
                    idempotency_key=idempotency_key,
                    defaults={"data_snapshot": data_snapshot, "owner": owner, **defaults},
                )
        except IntegrityError:
            query_run = QueryRun.objects.get(idempotency_key=idempotency_key)
            created = False
        if query_run.data_snapshot_id != data_snapshot.id:
            raise QueryRunIdempotencyConflictError()
        if owner is not None and query_run.owner_id not in {None, owner.pk}:
            raise QueryRunIdempotencyConflictError()
        return query_run, created

    def transition(self, query_run: QueryRun, *, target_status: QueryRunStatus | str) -> QueryRun:
        target = QueryRunStatus(target_status)
        current = QueryRunStatus(query_run.status)
        if target not in STATUS_TRANSITIONS[current]:
            raise QueryRunTransitionError(current=current.value, target=target.value)
        now = timezone.now()
        fields = {"status": target, "updated_at": now}
        if target == QueryRunStatus.EXECUTING:
            fields["started_at"] = now
        if target == QueryRunStatus.PLANNED:
            fields.update(
                structured_query=query_run.structured_query,
                planned_tools=query_run.planned_tools,
                model_version=query_run.model_version,
                prompt_version=query_run.prompt_version,
            )
        updated = QueryRun.objects.filter(pk=query_run.pk, status=current).update(**fields)
        if updated != 1:
            raise QueryRunTransitionError(current=current.value, target=target.value)
        query_run.refresh_from_db()
        if target == QueryRunStatus.EXECUTING:
            from apps.orchestration.evidence_service import DecisionEvidenceService

            DecisionEvidenceService().start(query_run)
        return query_run

    def save_plan(
        self,
        query_run: QueryRun,
        *,
        structured_query: Mapping[str, Any],
        planned_tools: Sequence[Mapping[str, Any]],
        model_version: str | None = None,
        prompt_version: str | None = None,
    ) -> QueryRun:
        if QueryRunStatus(query_run.status) != QueryRunStatus.PENDING:
            raise QueryRunTransitionError(current=query_run.status, target=QueryRunStatus.PLANNED)
        query_run.structured_query = sanitize_json(dict(structured_query))
        query_run.planned_tools = sanitize_tool_records(planned_tools)
        query_run.model_version = (model_version or "").strip()
        query_run.prompt_version = (prompt_version or "").strip()
        return self.transition(query_run, target_status=QueryRunStatus.PLANNED)

    def save_structured_query(
        self,
        query_run: QueryRun,
        *,
        structured_query: StructuredQuery | Mapping[str, Any],
    ) -> QueryRun:
        """Persist an already validated structured query without creating a tool plan."""
        query = (
            structured_query
            if isinstance(structured_query, StructuredQuery)
            else StructuredQuery.model_validate(structured_query)
        )
        if query.snapshot_identifier != query_run.data_snapshot.snapshot_key:
            raise QueryRunError(
                message="Structured query snapshot does not match QueryRun.",
                code="structured_query_snapshot_mismatch",
            )
        normalized = query.to_audit_dict()
        current_status = QueryRunStatus(query_run.status)
        if current_status == QueryRunStatus.PLANNED and query_run.structured_query == normalized:
            return query_run
        if current_status != QueryRunStatus.PENDING:
            raise QueryRunTransitionError(
                current=current_status.value, target=QueryRunStatus.PLANNED.value
            )
        query_run.structured_query = normalized
        return self.transition(query_run, target_status=QueryRunStatus.PLANNED)

    def replace_structured_query_before_plan(
        self,
        query_run: QueryRun,
        *,
        structured_query: StructuredQuery | Mapping[str, Any],
        parser_version: str,
    ) -> QueryRun:
        """Persist optional semantic dimensions after the safe deterministic plan state."""
        query = (
            structured_query
            if isinstance(structured_query, StructuredQuery)
            else StructuredQuery.model_validate(structured_query)
        )
        if query.snapshot_identifier != query_run.data_snapshot.snapshot_key:
            raise QueryRunError(
                message="Structured query snapshot does not match QueryRun.",
                code="structured_query_snapshot_mismatch",
            )
        if QueryRunStatus(query_run.status) != QueryRunStatus.PLANNED or query_run.planned_tools:
            raise QueryRunTransitionError(
                current=query_run.status, target=QueryRunStatus.PLANNED.value
            )
        query_run.structured_query = query.to_audit_dict()
        query_run.structured_query_parser_version = parser_version
        query_run.full_clean()
        query_run.save(
            update_fields=[
                "structured_query",
                "structured_query_parser_version",
                "updated_at",
            ]
        )
        return query_run

    def save_provider_provenance(
        self,
        query_run: QueryRun,
        *,
        requested_llm_provider: str | None,
        resolved_llm_provider: str,
        resolved_llm_model: str | None,
        requested_embedding_provider: str | None,
        resolved_embedding_provider: str,
        resolved_embedding_model: str,
        embedding_prompt_version: str,
        structured_query_parser: str,
        structured_query_parser_version: str,
    ) -> QueryRun:
        """Persist resolved allowlisted provider choices before planning begins."""
        if QueryRunStatus(query_run.status) != QueryRunStatus.PENDING:
            return query_run
        query_run.requested_llm_provider = requested_llm_provider or ""
        query_run.resolved_llm_provider = resolved_llm_provider
        query_run.resolved_llm_model = resolved_llm_model or ""
        query_run.requested_embedding_provider = requested_embedding_provider or ""
        query_run.resolved_embedding_provider = resolved_embedding_provider
        query_run.resolved_embedding_model = resolved_embedding_model
        query_run.embedding_prompt_version = embedding_prompt_version
        query_run.structured_query_parser = structured_query_parser
        query_run.structured_query_parser_version = structured_query_parser_version
        query_run.full_clean()
        query_run.save(
            update_fields=[
                "requested_llm_provider",
                "resolved_llm_provider",
                "resolved_llm_model",
                "requested_embedding_provider",
                "resolved_embedding_provider",
                "resolved_embedding_model",
                "embedding_prompt_version",
                "structured_query_parser",
                "structured_query_parser_version",
                "updated_at",
            ]
        )
        return query_run

    def save_tool_plan(
        self,
        query_run: QueryRun,
        *,
        tool_plan: ToolPlan | Mapping[str, Any],
    ) -> QueryRun:
        """Persist a validated plan without moving the run into execution."""
        plan = tool_plan if isinstance(tool_plan, ToolPlan) else ToolPlan.model_validate(tool_plan)
        if plan.snapshot_identifier != query_run.data_snapshot.snapshot_key:
            raise QueryRunError(
                message="Tool plan snapshot does not match QueryRun.",
                code="tool_plan_snapshot_mismatch",
            )
        current_status = QueryRunStatus(query_run.status)
        if current_status != QueryRunStatus.PLANNED:
            raise QueryRunTransitionError(
                current=current_status.value, target=QueryRunStatus.PLANNED.value
            )
        try:
            persisted_context = StructuredQuery.model_validate(query_run.structured_query)
        except ValidationError as exc:
            raise QueryRunError(
                message="QueryRun structured query is invalid.",
                code="query_run_structured_query_invalid",
            ) from exc
        if plan.structured_query_context.to_audit_dict() != persisted_context.to_audit_dict():
            raise QueryRunError(
                message="Tool plan context does not match QueryRun.",
                code="tool_plan_structured_query_mismatch",
            )
        normalized = plan.to_planned_tools()
        if query_run.planned_tools == normalized:
            return query_run
        if query_run.planned_tools:
            raise QueryRunError(
                message="QueryRun tool plan is already recorded.",
                code="query_run_tool_plan_immutable",
            )
        query_run.planned_tools = normalized
        query_run.full_clean()
        query_run.save(update_fields=["planned_tools", "updated_at"])
        return query_run

    def save_execution_summary(
        self,
        query_run: QueryRun,
        *,
        executed_tools: Sequence[Mapping[str, Any]],
    ) -> QueryRun:
        if QueryRunStatus(query_run.status) != QueryRunStatus.EXECUTING:
            raise QueryRunTransitionError(current=query_run.status, target=QueryRunStatus.EXECUTING)
        query_run.executed_tools = sanitize_tool_records(executed_tools)
        query_run.full_clean()
        query_run.save()
        return query_run

    def append_execution_record(
        self,
        query_run: QueryRun,
        *,
        record: Mapping[str, Any],
    ) -> QueryRun:
        """Append one safe call audit record without losing a concurrent update."""
        sanitized_records = sanitize_tool_records([record])
        sanitized_record = sanitized_records[0]
        call_id = sanitized_record.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise QueryRunError(
                message="Tool execution record requires call_id.",
                code="invalid_query_run_tool_record",
            )
        with transaction.atomic():
            locked_run = QueryRun.objects.select_for_update().get(pk=query_run.pk)
            if QueryRunStatus(locked_run.status) != QueryRunStatus.EXECUTING:
                raise QueryRunTransitionError(
                    current=locked_run.status, target=QueryRunStatus.EXECUTING
                )
            existing_call_ids = {
                item.get("call_id")
                for item in locked_run.executed_tools
                if isinstance(item, Mapping)
            }
            if call_id in existing_call_ids:
                return locked_run
            locked_run.executed_tools = [*locked_run.executed_tools, sanitized_record]
            locked_run.full_clean()
            locked_run.save(update_fields=["executed_tools", "updated_at"])
            return locked_run

    def complete(self, query_run: QueryRun, *, final_result: Mapping[str, Any]) -> QueryRun:
        if not isinstance(final_result, Mapping):
            raise QueryRunError(
                message="final_result must be an object.", code="invalid_query_run_result"
            )
        completed_at = timezone.now()
        updated = QueryRun.objects.filter(pk=query_run.pk, status=QueryRunStatus.EXECUTING).update(
            status=QueryRunStatus.COMPLETED,
            final_result=sanitize_json(dict(final_result)),
            completed_at=completed_at,
            updated_at=completed_at,
        )
        if updated != 1:
            raise QueryRunTransitionError(current=query_run.status, target=QueryRunStatus.COMPLETED)
        query_run.refresh_from_db()
        from apps.orchestration.evidence_service import DecisionEvidenceService

        DecisionEvidenceService().finalize(query_run)
        return query_run

    def save_response_audit(
        self, query_run: QueryRun, *, audit: Mapping[str, Any]
    ) -> QueryRun:
        """Persist bounded response diagnostics without mutating terminal facts."""
        if QueryRunStatus(query_run.status) not in TERMINAL_QUERY_RUN_STATUSES:
            raise QueryRunTransitionError(
                current=query_run.status, target="response_audit"
            )
        normalized = sanitize_json(dict(audit))
        QueryRun.objects.filter(pk=query_run.pk).update(
            response_audit=normalized, updated_at=timezone.now()
        )
        query_run.response_audit = normalized
        return query_run

    def fail(self, query_run: QueryRun, *, error_code: str, error_summary: str) -> QueryRun:
        normalized_code = (error_code or "").strip().lower()
        if not _ERROR_CODE_RE.fullmatch(normalized_code):
            raise QueryRunError(
                message="error_code is invalid.", code="invalid_query_run_error_code"
            )
        completed_at = timezone.now()
        updated = QueryRun.objects.filter(
            pk=query_run.pk,
            status__in=(
                QueryRunStatus.PENDING,
                QueryRunStatus.PLANNED,
                QueryRunStatus.EXECUTING,
            ),
        ).update(
            status=QueryRunStatus.FAILED,
            error_code=normalized_code,
            error_summary=sanitize_text(error_summary),
            completed_at=completed_at,
            updated_at=completed_at,
        )
        if updated != 1:
            raise QueryRunTransitionError(current=query_run.status, target=QueryRunStatus.FAILED)
        query_run.refresh_from_db()
        from apps.orchestration.evidence_service import DecisionEvidenceService

        DecisionEvidenceService().finalize(query_run)
        return query_run

    def create_retry(
        self,
        query_run: QueryRun,
        *,
        idempotency_key: str,
        request_id: str | None = None,
    ) -> tuple[QueryRun, bool]:
        if QueryRunStatus(query_run.status) not in TERMINAL_QUERY_RUN_STATUSES:
            raise QueryRunError(
                message="Only terminal QueryRun records can be retried.",
                code="query_run_retry_requires_terminal_status",
            )
        retry, created = self.create_or_get(
            data_snapshot=query_run.data_snapshot,
            idempotency_key=idempotency_key,
            original_query=query_run.original_query,
            request_id=request_id,
        )
        if created:
            retry.retry_of = query_run
            retry.full_clean()
            retry.save(update_fields=["retry_of", "updated_at"])
        elif retry.retry_of_id != query_run.id:
            raise QueryRunError(
                message="Idempotency key is already associated with another retry.",
                code="query_run_retry_idempotency_conflict",
            )
        return retry, created
