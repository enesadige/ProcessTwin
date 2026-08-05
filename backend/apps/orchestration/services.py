from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import ProcessTwinError
from apps.datasets.models import DataSnapshot
from apps.orchestration.models import TERMINAL_QUERY_RUN_STATUSES, QueryRun, QueryRunStatus
from apps.orchestration.structured_query import StructuredQuery

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
        "tool_name",
        "argument_summary",
        "status",
        "result_summary",
        "error_code",
        "correlation_id",
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
    r"(?:\s*(?:id|no|number|numarası))?\s*[:=#-]?\s*[A-Za-z0-9._-]+",
    re.IGNORECASE,
)
_EMAIL_ADDRESS_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE_NUMBER_RE = re.compile(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b")
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
    text = _PHONE_NUMBER_RE.sub("[REDACTED_PHONE]", text)
    return text or "[REDACTED]"


def sanitize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if (
                normalized_key.startswith("raw_")
                or any(part in normalized_key for part in SENSITIVE_KEY_PARTS)
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
                    defaults={"data_snapshot": data_snapshot, **defaults},
                )
        except IntegrityError:
            query_run = QueryRun.objects.get(idempotency_key=idempotency_key)
            created = False
        if query_run.data_snapshot_id != data_snapshot.id:
            raise QueryRunIdempotencyConflictError()
        return query_run, created

    def transition(self, query_run: QueryRun, *, target_status: QueryRunStatus | str) -> QueryRun:
        target = QueryRunStatus(target_status)
        current = QueryRunStatus(query_run.status)
        if target not in STATUS_TRANSITIONS[current]:
            raise QueryRunTransitionError(current=current.value, target=target.value)
        query_run.status = target
        if target == QueryRunStatus.EXECUTING:
            query_run.started_at = timezone.now()
        query_run.full_clean()
        query_run.save()
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

    def complete(self, query_run: QueryRun, *, final_result: Mapping[str, Any]) -> QueryRun:
        if not isinstance(final_result, Mapping):
            raise QueryRunError(
                message="final_result must be an object.", code="invalid_query_run_result"
            )
        query_run.final_result = sanitize_json(dict(final_result))
        query_run.completed_at = timezone.now()
        return self.transition(query_run, target_status=QueryRunStatus.COMPLETED)

    def fail(self, query_run: QueryRun, *, error_code: str, error_summary: str) -> QueryRun:
        normalized_code = (error_code or "").strip().lower()
        if not _ERROR_CODE_RE.fullmatch(normalized_code):
            raise QueryRunError(
                message="error_code is invalid.", code="invalid_query_run_error_code"
            )
        query_run.error_code = normalized_code
        query_run.error_summary = sanitize_text(error_summary)
        query_run.completed_at = timezone.now()
        return self.transition(query_run, target_status=QueryRunStatus.FAILED)

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
