from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.datasets.models import DataSnapshot


def generate_query_run_code() -> str:
    return f"QR-{uuid4().hex.upper()}"


def generate_request_id() -> str:
    return str(uuid4())


class QueryRunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PLANNED = "planned", "Planned"
    EXECUTING = "executing", "Executing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


TERMINAL_QUERY_RUN_STATUSES = frozenset({QueryRunStatus.COMPLETED, QueryRunStatus.FAILED})


class QueryRun(TimeStampedModel):
    """Privacy-safe audit record for a future query orchestration execution."""

    query_run_code = models.CharField(max_length=48, unique=True, default=generate_query_run_code)
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.PROTECT,
        related_name="query_runs",
    )
    request_id = models.CharField(max_length=128, db_index=True, default=generate_request_id)
    idempotency_key = models.CharField(max_length=160, unique=True, db_index=True)
    retry_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retries",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orchestration_runs",
    )
    original_query = models.TextField()
    structured_query = models.JSONField(default=dict, blank=True)
    planned_tools = models.JSONField(default=list, blank=True)
    executed_tools = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16,
        choices=QueryRunStatus.choices,
        default=QueryRunStatus.PENDING,
    )
    final_result = models.JSONField(null=True, blank=True)
    model_version = models.CharField(max_length=160, blank=True)
    prompt_version = models.CharField(max_length=160, blank=True)
    requested_llm_provider = models.CharField(max_length=32, blank=True)
    resolved_llm_provider = models.CharField(max_length=32, blank=True)
    resolved_llm_model = models.CharField(max_length=160, blank=True)
    requested_embedding_provider = models.CharField(max_length=32, blank=True)
    resolved_embedding_provider = models.CharField(max_length=32, blank=True)
    resolved_embedding_model = models.CharField(max_length=160, blank=True)
    embedding_prompt_version = models.CharField(max_length=160, blank=True)
    structured_query_parser = models.CharField(max_length=64, blank=True)
    structured_query_parser_version = models.CharField(max_length=160, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_summary = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "orchestration_query_run"
        ordering = ["-created_at", "query_run_code"]
        verbose_name = "Sorgu çalıştırması"
        verbose_name_plural = "Sorgu çalıştırmaları"
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=QueryRunStatus.COMPLETED)
                    | (models.Q(completed_at__isnull=False) & models.Q(final_result__isnull=False))
                ),
                name="query_run_completed_requires_result",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=QueryRunStatus.FAILED)
                    | (models.Q(completed_at__isnull=False) & ~models.Q(error_code=""))
                ),
                name="query_run_failed_requires_error",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status__in=TERMINAL_QUERY_RUN_STATUSES)
                    | models.Q(completed_at__isnull=True)
                ),
                name="query_run_nonterminal_not_completed",
            ),
        ]
        indexes = [
            models.Index(
                fields=["data_snapshot", "status", "created_at"],
                name="query_run_snapshot_status_idx",
            ),
            models.Index(fields=["request_id"], name="query_run_request_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.query_run_code} ({self.status})"

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if not isinstance(self.structured_query, dict):
            errors["structured_query"] = "structured_query must be an object."
        if not isinstance(self.planned_tools, list):
            errors["planned_tools"] = "planned_tools must be a list."
        if not isinstance(self.executed_tools, list):
            errors["executed_tools"] = "executed_tools must be a list."
        if self.status == QueryRunStatus.COMPLETED:
            if self.completed_at is None:
                errors["completed_at"] = "Completed runs require completed_at."
            if self.final_result is None:
                errors["final_result"] = "Completed runs require final_result."
        elif self.status == QueryRunStatus.FAILED:
            if self.completed_at is None:
                errors["completed_at"] = "Failed runs require completed_at."
            if not self.error_code:
                errors["error_code"] = "Failed runs require error_code."
        elif self.completed_at is not None:
            errors["completed_at"] = "Only terminal runs can have completed_at."
        if self.pk:
            persisted = (
                QueryRun.objects.filter(pk=self.pk)
                .values(
                    "status",
                    "data_snapshot_id",
                    "idempotency_key",
                    "retry_of_id",
                    "owner_id",
                    "original_query",
                    "structured_query",
                    "planned_tools",
                    "executed_tools",
                    "final_result",
                    "model_version",
                    "prompt_version",
                    "requested_llm_provider",
                    "resolved_llm_provider",
                    "resolved_llm_model",
                    "requested_embedding_provider",
                    "resolved_embedding_provider",
                    "resolved_embedding_model",
                    "embedding_prompt_version",
                    "structured_query_parser",
                    "structured_query_parser_version",
                    "error_code",
                    "error_summary",
                    "started_at",
                    "completed_at",
                    "request_id",
                    "query_run_code",
                )
                .first()
            )
            if persisted and persisted["status"] in TERMINAL_QUERY_RUN_STATUSES:
                current = {
                    "status": self.status,
                    "data_snapshot_id": self.data_snapshot_id,
                    "idempotency_key": self.idempotency_key,
                    "retry_of_id": self.retry_of_id,
                    "owner_id": self.owner_id,
                    "original_query": self.original_query,
                    "structured_query": self.structured_query,
                    "planned_tools": self.planned_tools,
                    "executed_tools": self.executed_tools,
                    "final_result": self.final_result,
                    "model_version": self.model_version,
                    "prompt_version": self.prompt_version,
                    "requested_llm_provider": self.requested_llm_provider,
                    "resolved_llm_provider": self.resolved_llm_provider,
                    "resolved_llm_model": self.resolved_llm_model,
                    "requested_embedding_provider": self.requested_embedding_provider,
                    "resolved_embedding_provider": self.resolved_embedding_provider,
                    "resolved_embedding_model": self.resolved_embedding_model,
                    "embedding_prompt_version": self.embedding_prompt_version,
                    "structured_query_parser": self.structured_query_parser,
                    "structured_query_parser_version": self.structured_query_parser_version,
                    "error_code": self.error_code,
                    "error_summary": self.error_summary,
                    "started_at": self.started_at,
                    "completed_at": self.completed_at,
                    "request_id": self.request_id,
                    "query_run_code": self.query_run_code,
                }
                if current != persisted:
                    errors["status"] = "Terminal QueryRun records are immutable."
        if errors:
            raise ValidationError(errors)
