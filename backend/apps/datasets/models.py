from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
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


class GroundTruthEligibility(models.TextChoices):
    ELIGIBLE = "eligible", "Eligible"
    INELIGIBLE = "ineligible", "Ineligible"
    MANUAL_REVIEW = "manual_review", "Manual review"


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


class GroundTruthCase(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="ground_truth_cases",
    )
    case_code = models.CharField(max_length=120)
    outage_code = models.CharField(max_length=100)
    expected_source_device_code = models.CharField(max_length=80)
    expected_incident_code = models.CharField(max_length=100)
    expected_alarm_type_codes = models.JSONField(default=list)
    expected_duration_minutes = models.PositiveIntegerField()
    expected_rule_code = models.CharField(max_length=80)
    expected_rule_version = models.PositiveIntegerField()
    affected_subscription_codes = models.JSONField(default=list)
    affected_subscription_hash = models.CharField(max_length=64)
    affected_subscription_count = models.PositiveIntegerField()
    affected_customer_codes = models.JSONField(default=list)
    affected_customer_hash = models.CharField(max_length=64)
    affected_customer_count = models.PositiveIntegerField()
    unaffected_subscription_count = models.PositiveIntegerField()
    unaffected_customer_count = models.PositiveIntegerField()
    affected_segment_counts = models.JSONField(default=dict)
    affected_priority_counts = models.JSONField(default=dict)
    expected_eligibility = models.CharField(
        max_length=24,
        choices=GroundTruthEligibility.choices,
    )
    expected_reason_code = models.CharField(max_length=80)
    expected_total_refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TRY")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "datasets_ground_truth_case"
        ordering = ["data_snapshot", "outage_code"]
        verbose_name = "Ground truth kaydı"
        verbose_name_plural = "Ground truth kayıtları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "case_code"],
                name="unique_ground_truth_case_code_per_snapshot",
            ),
            models.UniqueConstraint(
                fields=["data_snapshot", "outage_code"],
                name="unique_ground_truth_case_outage_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    affected_subscription_count__gte=models.F("affected_customer_count")
                ),
                name="ground_truth_subscriptions_not_less_than_customers",
            ),
            models.CheckConstraint(
                condition=models.Q(expected_total_refund_amount__gte=Decimal("0.00")),
                name="ground_truth_refund_amount_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.case_code} - {self.outage_code}"

    def clean(self):
        errors: dict[str, str] = {}
        if len(self.currency) != 3:
            errors["currency"] = "Currency must be a three-letter ISO code."
        if len(self.affected_subscription_codes) != self.affected_subscription_count:
            errors["affected_subscription_count"] = (
                "Affected subscription count must match affected subscription code list."
            )
        if len(self.affected_customer_codes) != self.affected_customer_count:
            errors["affected_customer_count"] = (
                "Affected customer count must match affected customer code list."
            )
        if sorted(self.affected_subscription_codes) != self.affected_subscription_codes:
            errors["affected_subscription_codes"] = "Affected subscription codes must be sorted."
        if sorted(self.affected_customer_codes) != self.affected_customer_codes:
            errors["affected_customer_codes"] = "Affected customer codes must be sorted."
        if len(set(self.affected_subscription_codes)) != len(self.affected_subscription_codes):
            errors["affected_subscription_codes"] = "Affected subscription codes must be unique."
        if len(set(self.affected_customer_codes)) != len(self.affected_customer_codes):
            errors["affected_customer_codes"] = "Affected customer codes must be unique."
        if errors:
            raise ValidationError(errors)
