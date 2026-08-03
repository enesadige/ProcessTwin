import re

from django.core.exceptions import ValidationError
from django.db import models
from pgvector.django import VectorField

from apps.core.models import TimeStampedModel
from apps.datasets.models import DataSnapshot

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
EMBEDDING_DIMENSIONS = 768


class DocumentType(models.TextChoices):
    RULE_POLICY = "rule_policy", "Rule policy"
    PROCEDURE = "procedure", "Procedure"
    SLA = "sla", "SLA"
    CAMPAIGN = "campaign", "Campaign"
    TECHNICAL_GUIDE = "technical_guide", "Technical guide"
    OPERATIONAL_RUNBOOK = "operational_runbook", "Operational runbook"
    OTHER = "other", "Other"


class SourceKind(models.TextChoices):
    SYNTHETIC = "synthetic", "Synthetic"
    INTERNAL = "internal", "Internal"
    IMPORTED = "imported", "Imported"
    MANUAL = "manual", "Manual"


class DocumentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class IndexRunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class EmbeddingProviderName(models.TextChoices):
    MOCK = "mock", "Mock"
    GEMINI = "gemini", "Gemini"
    OLLAMA = "ollama", "Ollama"


def validate_sha256(value: str) -> None:
    if not SHA256_RE.fullmatch(value or ""):
        raise ValidationError("Value must be a 64-character SHA-256 hexadecimal digest.")


class SourceDocument(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_documents",
    )
    document_code = models.CharField(max_length=120)
    title = models.CharField(max_length=240)
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    source_kind = models.CharField(max_length=24, choices=SourceKind.choices)
    version = models.PositiveIntegerField()
    language = models.CharField(max_length=16, default="tr")
    content = models.TextField()
    content_hash = models.CharField(max_length=64, validators=[validate_sha256])
    is_synthetic = models.BooleanField(default=True)
    status = models.CharField(
        max_length=16,
        choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT,
    )
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rag_source_document"
        ordering = ["document_code", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "document_code", "version"],
                condition=models.Q(data_snapshot__isnull=False),
                name="rag_doc_snapshot_code_version_uniq",
            ),
            models.UniqueConstraint(
                fields=["document_code", "version"],
                condition=models.Q(data_snapshot__isnull=True),
                name="rag_doc_global_code_version_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_from__isnull=True)
                | models.Q(valid_to__gte=models.F("valid_from")),
                name="rag_doc_valid_range",
            ),
        ]
        indexes = [
            models.Index(fields=["document_code"], name="rag_doc_code_idx"),
            models.Index(fields=["content_hash"], name="rag_doc_hash_idx"),
            models.Index(fields=["status"], name="rag_doc_status_idx"),
            models.Index(fields=["data_snapshot", "document_code"], name="rag_doc_snap_code_idx"),
            models.Index(fields=["valid_from", "valid_to"], name="rag_doc_valid_idx"),
        ]

    def clean(self):
        errors = {}
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            errors["valid_to"] = "valid_to cannot be earlier than valid_from."
        if self.data_snapshot_id is not None:
            duplicate = SourceDocument.objects.filter(
                data_snapshot_id=self.data_snapshot_id,
                document_code=self.document_code,
                version=self.version,
            ).exclude(pk=self.pk)
        else:
            duplicate = SourceDocument.objects.filter(
                data_snapshot__isnull=True,
                document_code=self.document_code,
                version=self.version,
            ).exclude(pk=self.pk)
        if duplicate.exists():
            errors["document_code"] = "document_code and version must be unique in this scope."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        scope = self.data_snapshot.snapshot_key if self.data_snapshot_id else "global"
        return f"{self.document_code} v{self.version} ({scope})"


class DocumentChunk(TimeStampedModel):
    source_document = models.ForeignKey(
        SourceDocument,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    sequence = models.PositiveIntegerField()
    heading = models.CharField(max_length=240, blank=True)
    section_path = models.JSONField(default=list, blank=True)
    text = models.TextField()
    content_hash = models.CharField(max_length=64, validators=[validate_sha256])
    char_start = models.PositiveIntegerField(null=True, blank=True)
    char_end = models.PositiveIntegerField(null=True, blank=True)
    token_start = models.PositiveIntegerField(null=True, blank=True)
    token_end = models.PositiveIntegerField(null=True, blank=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    rule_code = models.CharField(max_length=80, null=True, blank=True)
    rule_version = models.PositiveIntegerField(null=True, blank=True)
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True)
    embedding_provider = models.CharField(max_length=80, null=True, blank=True)
    embedding_model = models.CharField(max_length=160, null=True, blank=True)
    embedding_version = models.CharField(max_length=80, null=True, blank=True)
    embedding_dimensions = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rag_document_chunk"
        ordering = ["source_document", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_document", "sequence"],
                name="rag_chunk_document_sequence_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(char_start__isnull=True, char_end__isnull=True)
                | models.Q(char_start__isnull=False, char_end__isnull=False),
                name="rag_chunk_char_bounds_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(token_start__isnull=True, token_end__isnull=True)
                | models.Q(token_start__isnull=False, token_end__isnull=False),
                name="rag_chunk_token_bounds_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_from__isnull=True)
                | models.Q(valid_to__gte=models.F("valid_from")),
                name="rag_chunk_valid_range",
            ),
        ]
        indexes = [
            models.Index(fields=["source_document", "sequence"], name="rag_chunk_doc_seq_idx"),
            models.Index(fields=["content_hash"], name="rag_chunk_hash_idx"),
            models.Index(fields=["rule_code"], name="rag_chunk_rule_idx"),
            models.Index(fields=["rule_code", "rule_version"], name="rag_chunk_rule_ver_idx"),
            models.Index(fields=["valid_from", "valid_to"], name="rag_chunk_valid_idx"),
        ]

    def clean(self):
        errors = {}
        duplicate = DocumentChunk.objects.filter(
            source_document_id=self.source_document_id,
            sequence=self.sequence,
        ).exclude(pk=self.pk)
        if self.source_document_id and duplicate.exists():
            errors["sequence"] = "sequence must be unique within source_document."
        if (self.char_start is None) != (self.char_end is None):
            errors["char_start"] = "char_start and char_end must be provided together."
        elif self.char_start is not None and self.char_end < self.char_start:
            errors["char_end"] = "char_end cannot be earlier than char_start."
        if (self.token_start is None) != (self.token_end is None):
            errors["token_start"] = "token_start and token_end must be provided together."
        elif self.token_start is not None and self.token_end < self.token_start:
            errors["token_end"] = "token_end cannot be earlier than token_start."
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            errors["valid_to"] = "valid_to cannot be earlier than valid_from."
        if self.embedding is not None:
            try:
                embedding_length = len(self.embedding)
            except TypeError:
                errors["embedding"] = "embedding must be a sized vector."
            else:
                if embedding_length != EMBEDDING_DIMENSIONS:
                    errors["embedding"] = (
                        f"embedding must contain {EMBEDDING_DIMENSIONS} dimensions."
                    )
                if self.embedding_dimensions not in (None, EMBEDDING_DIMENSIONS):
                    errors["embedding_dimensions"] = (
                        "embedding_dimensions must be "
                        f"{EMBEDDING_DIMENSIONS} when embedding is set."
                    )
        if self.embedding_dimensions is not None and self.embedding_dimensions <= 0:
            errors["embedding_dimensions"] = "embedding_dimensions must be positive."
        if errors:
            raise ValidationError(errors)

    def full_clean(
        self,
        exclude=None,
        validate_unique=True,
        validate_constraints=False,
    ):
        """Avoid Django constraint expression evaluation on pgvector numpy values.

        Database constraints remain active. The corresponding cross-field and
        uniqueness checks are performed in ``clean`` above.
        """
        return super().full_clean(
            exclude=exclude,
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def __str__(self) -> str:
        return f"{self.source_document.document_code}#{self.sequence}"


class DocumentChunkEmbedding(TimeStampedModel):
    document_chunk = models.ForeignKey(
        DocumentChunk,
        on_delete=models.CASCADE,
        related_name="embedding_records",
    )
    provider = models.CharField(max_length=80, choices=EmbeddingProviderName.choices)
    model = models.CharField(max_length=160)
    dimensions = models.PositiveIntegerField(default=EMBEDDING_DIMENSIONS)
    embedding_version = models.CharField(max_length=80)
    prompt_version = models.CharField(max_length=120)
    content_hash = models.CharField(max_length=64, validators=[validate_sha256])
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)

    class Meta:
        db_table = "rag_document_chunk_embedding"
        ordering = ["document_chunk", "provider", "model", "embedding_version"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "document_chunk",
                    "provider",
                    "model",
                    "dimensions",
                    "embedding_version",
                    "prompt_version",
                    "content_hash",
                ],
                name="rag_chunk_embedding_identity_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(dimensions=EMBEDDING_DIMENSIONS),
                name="rag_chunk_embedding_dimensions_768",
            ),
        ]
        indexes = [
            models.Index(
                fields=["provider", "model", "embedding_version", "prompt_version"],
                name="rag_emb_descriptor_idx",
            ),
            models.Index(
                fields=["document_chunk", "provider", "model"],
                name="rag_emb_chunk_provider_idx",
            ),
            models.Index(fields=["content_hash"], name="rag_emb_content_hash_idx"),
        ]

    def clean(self):
        errors = {}
        for field_name in ("model", "embedding_version", "prompt_version"):
            if not (getattr(self, field_name, "") or "").strip():
                errors[field_name] = f"{field_name} cannot be blank."
        if self.dimensions != EMBEDDING_DIMENSIONS:
            errors["dimensions"] = f"dimensions must be {EMBEDDING_DIMENSIONS}."
        try:
            embedding_length = len(self.embedding)
        except TypeError:
            errors["embedding"] = "embedding must be a sized vector."
        else:
            if embedding_length != EMBEDDING_DIMENSIONS:
                errors["embedding"] = (
                    f"embedding must contain {EMBEDDING_DIMENSIONS} dimensions."
                )
        if errors:
            raise ValidationError(errors)

    def full_clean(
        self,
        exclude=None,
        validate_unique=True,
        validate_constraints=False,
    ):
        return super().full_clean(
            exclude=exclude,
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def __str__(self) -> str:
        return (
            f"{self.document_chunk} {self.provider}/{self.model} "
            f"({self.embedding_version})"
        )


class IndexRun(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rag_index_runs",
    )
    status = models.CharField(
        max_length=16,
        choices=IndexRunStatus.choices,
        default=IndexRunStatus.PENDING,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    source_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    embedding_count = models.PositiveIntegerField(default=0)
    embedding_provider = models.CharField(max_length=80, null=True, blank=True)
    embedding_model = models.CharField(max_length=160, null=True, blank=True)
    embedding_dimensions = models.PositiveIntegerField(null=True, blank=True)
    source_digest = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        validators=[validate_sha256],
    )
    error_summary = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rag_index_run"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="rag_index_status_idx"),
            models.Index(fields=["data_snapshot", "status"], name="rag_index_snap_status_idx"),
            models.Index(fields=["created_at"], name="rag_index_created_idx"),
        ]

    def clean(self):
        errors = {}
        if self.started_at and self.completed_at and self.completed_at < self.started_at:
            errors["completed_at"] = "completed_at cannot be earlier than started_at."
        if self.status == IndexRunStatus.RUNNING and self.started_at is None:
            errors["started_at"] = "running index runs require started_at."
        if self.status == IndexRunStatus.SUCCEEDED and self.completed_at is None:
            errors["completed_at"] = "succeeded index runs require completed_at."
        if self.embedding_dimensions is not None and self.embedding_dimensions <= 0:
            errors["embedding_dimensions"] = "embedding_dimensions must be positive."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"IndexRun {self.pk or 'new'} ({self.status})"
