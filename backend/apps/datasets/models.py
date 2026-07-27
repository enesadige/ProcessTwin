from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.text import slugify

from apps.core.choices import ResultStatus
from apps.core.models import TimeStampedModel


class DatasetKind(models.TextChoices):
    SYNTHETIC = "synthetic", "Synthetic"
    IMPORTED = "imported", "Imported"
    MIXED = "mixed", "Mixed"


class DatasetSnapshotStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    VALIDATED = "validated", "Validated"
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class DatasetVersion(TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    kind = models.CharField(
        max_length=24,
        choices=DatasetKind.choices,
        default=DatasetKind.SYNTHETIC,
    )
    generator_version = models.CharField(max_length=80)
    seed = models.CharField(max_length=120)
    config = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_dataset_versions",
    )

    class Meta:
        db_table = "datasets_version"
        ordering = ["-created_at", "name"]
        verbose_name = "Veri seti versiyonu"
        verbose_name_plural = "Veri seti versiyonları"

    def __str__(self) -> str:
        return f"{self.name} ({self.generator_version})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.name}-{self.generator_version}-{self.seed}")
        super().save(*args, **kwargs)


class DataSnapshot(TimeStampedModel):
    dataset_version = models.ForeignKey(
        DatasetVersion,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    name = models.CharField(max_length=120)
    snapshot_key = models.SlugField(max_length=160, unique=True, blank=True)
    status = models.CharField(
        max_length=24,
        choices=DatasetSnapshotStatus.choices,
        default=DatasetSnapshotStatus.DRAFT,
    )
    is_active = models.BooleanField(default=False)
    row_counts = models.JSONField(default=dict, blank=True)
    validation_status = models.CharField(
        max_length=24,
        choices=ResultStatus.choices,
        default=ResultStatus.INSUFFICIENT_DATA,
    )
    validation_result = models.JSONField(default=dict, blank=True)
    source_started_at = models.DateTimeField(null=True, blank=True)
    source_finished_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "datasets_snapshot"
        ordering = ["-created_at", "name"]
        verbose_name = "Veri snapshot'ı"
        verbose_name_plural = "Veri snapshot'ları"
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=Q(is_active=True),
                name="one_active_data_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.dataset_version.slug}"

    def save(self, *args, **kwargs):
        if not self.snapshot_key:
            self.snapshot_key = slugify(f"{self.dataset_version.slug}-{self.name}")
        super().save(*args, **kwargs)
