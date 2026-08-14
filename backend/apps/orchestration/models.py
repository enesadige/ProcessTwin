from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

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


def generate_evidence_record_code() -> str:
    return f"EV-{uuid4().hex.upper()}"


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
    response_audit = models.JSONField(default=dict, blank=True)
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
                    "response_audit",
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
                    "response_audit": self.response_audit,
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


class EvidenceRecord(TimeStampedModel):
    """Immutable provenance container for one completed analysis run.

    This is deliberately separate from ``compensation.DecisionEvidence``. The
    latter remains the authoritative compensation decision record; this model
    records the wider orchestration provenance around a QueryRun.
    """

    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.PROTECT,
        related_name="evidence_records",
    )
    query_run = models.OneToOneField(
        QueryRun,
        on_delete=models.PROTECT,
        related_name="evidence_record",
    )
    evidence_code = models.CharField(max_length=48, default=generate_evidence_record_code)
    snapshot_context = models.JSONField(default=dict, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    finalized = models.BooleanField(default=False)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "orchestration_evidence_record"
        ordering = ["-created_at", "evidence_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "evidence_code"],
                name="evidence_record_snapshot_code_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(finalized=False, finalized_at__isnull=True)
                    | models.Q(finalized=True, finalized_at__isnull=False)
                ),
                name="evidence_record_finalization_timestamp",
            ),
        ]
        indexes = [
            models.Index(
                fields=["data_snapshot", "finalized", "created_at"],
                name="evidence_record_snap_final_idx",
            )
        ]

    def __str__(self) -> str:
        return self.evidence_code

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.query_run_id and self.data_snapshot_id:
            if self.query_run.data_snapshot_id != self.data_snapshot_id:
                errors["query_run"] = "QueryRun must belong to the same data snapshot."
        if self.finalized and self.finalized_at is None:
            errors["finalized_at"] = "Finalized evidence requires finalized_at."
        if not self.finalized and self.finalized_at is not None:
            errors["finalized_at"] = "Only finalized evidence can have finalized_at."
        if self.pk:
            existing = EvidenceRecord.objects.filter(pk=self.pk).values("finalized").first()
            if existing and existing["finalized"]:
                errors["finalized"] = "Finalized evidence records are immutable."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def finalize(self) -> None:
        if self.finalized:
            return
        self.finalized = True
        self.finalized_at = timezone.now()
        self.save(update_fields=["finalized", "finalized_at", "updated_at"])

    def delete(self, *args, **kwargs):
        if self.finalized:
            raise ValidationError("Finalized evidence records cannot be deleted.")
        return super().delete(*args, **kwargs)


class EvidenceChildModel(TimeStampedModel):
    """Common immutability contract for evidence entries."""

    evidence_record = models.ForeignKey(
        EvidenceRecord,
        on_delete=models.CASCADE,
        related_name="%(class)s_records",
    )

    class Meta:
        abstract = True

    def _validate_evidence_record(self, errors: dict[str, str]) -> None:
        if self.evidence_record_id and self.evidence_record.finalized:
            errors["evidence_record"] = "Finalized evidence records cannot be changed."

    def clean(self) -> None:
        errors: dict[str, str] = {}
        self._validate_evidence_record(errors)
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.evidence_record_id and self.evidence_record.finalized:
            raise ValidationError("Finalized evidence entries cannot be deleted.")
        return super().delete(*args, **kwargs)


class EvidenceToolCall(EvidenceChildModel):
    sequence = models.PositiveIntegerField()
    server_name = models.CharField(max_length=80)
    tool_name = models.CharField(max_length=160)
    status = models.CharField(max_length=32)
    request_summary = models.JSONField(default=dict, blank=True)
    response_summary = models.JSONField(default=dict, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "orchestration_evidence_tool_call"
        ordering = ["evidence_record", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["evidence_record", "sequence"],
                name="evidence_tool_call_sequence_uniq",
            ),
        ]


class EvidenceRuleReference(EvidenceChildModel):
    rule_version = models.ForeignKey(
        "rules.RuleVersion",
        on_delete=models.PROTECT,
        related_name="evidence_rule_references",
    )
    reference_role = models.CharField(max_length=32, default="selected")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "orchestration_evidence_rule_reference"
        ordering = ["evidence_record", "rule_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["evidence_record", "rule_version", "reference_role"],
                name="evidence_rule_reference_uniq",
            ),
        ]

    def clean(self) -> None:
        errors: dict[str, str] = {}
        self._validate_evidence_record(errors)
        if self.rule_version_id and self.evidence_record_id:
            if self.rule_version.data_snapshot_id != self.evidence_record.data_snapshot_id:
                errors["rule_version"] = "RuleVersion must belong to the evidence snapshot."
        if errors:
            raise ValidationError(errors)


class EvidenceCalculation(EvidenceChildModel):
    sequence = models.PositiveIntegerField()
    calculation_code = models.CharField(max_length=120)
    inputs = models.JSONField(default=dict, blank=True)
    outputs = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "orchestration_evidence_calculation"
        ordering = ["evidence_record", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["evidence_record", "sequence"],
                name="evidence_calculation_sequence_uniq",
            ),
        ]


class EvidenceRAGReference(EvidenceChildModel):
    source_document = models.ForeignKey(
        "rag.SourceDocument",
        on_delete=models.PROTECT,
        related_name="evidence_rag_references",
    )
    document_chunk = models.ForeignKey(
        "rag.DocumentChunk",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidence_rag_references",
    )
    section_path = models.JSONField(default=list, blank=True)
    retrieval_score = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "orchestration_evidence_rag_reference"
        ordering = ["evidence_record", "source_document", "document_chunk"]
        constraints = [
            models.UniqueConstraint(
                fields=["evidence_record", "source_document", "document_chunk"],
                name="evidence_rag_reference_uniq",
            ),
        ]

    def clean(self) -> None:
        errors: dict[str, str] = {}
        self._validate_evidence_record(errors)
        if self.source_document_id and self.evidence_record_id:
            document_snapshot_id = self.source_document.data_snapshot_id
            if document_snapshot_id not in (None, self.evidence_record.data_snapshot_id):
                errors["source_document"] = (
                    "Source document must be global or match evidence snapshot."
                )
        if self.document_chunk_id and self.source_document_id:
            if self.document_chunk.source_document_id != self.source_document_id:
                errors["document_chunk"] = (
                    "Document chunk must belong to the selected source document."
                )
        if errors:
            raise ValidationError(errors)
