from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.datasets.models import DataSnapshot


class RuleType(models.TextChoices):
    COMPENSATION = "compensation", "Compensation"
    ELIGIBILITY = "eligibility", "Eligibility"
    ROOT_CAUSE = "root_cause", "Root cause"
    ROUTING = "routing", "Routing"
    VALIDATION = "validation", "Validation"


class RuleStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    DEPRECATED = "deprecated", "Deprecated"
    ARCHIVED = "archived", "Archived"


class RuleVersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    RETIRED = "retired", "Retired"


class RuleChangeSetStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    IN_REVIEW = "in_review", "In review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    APPLIED = "applied", "Applied"


class RuleTestCaseStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class Rule(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="rules",
    )
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    rule_type = models.CharField(max_length=32, choices=RuleType.choices)
    status = models.CharField(max_length=24, choices=RuleStatus.choices, default=RuleStatus.DRAFT)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rules_rule"
        ordering = ["data_snapshot", "code"]
        verbose_name = "Kural"
        verbose_name_plural = "Kurallar"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "code"],
                name="unique_rule_code_per_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class RuleChangeSet(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="rule_change_sets",
    )
    change_set_code = models.CharField(max_length=80)
    title = models.CharField(max_length=160)
    status = models.CharField(
        max_length=24,
        choices=RuleChangeSetStatus.choices,
        default=RuleChangeSetStatus.DRAFT,
    )
    reason = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_rule_change_sets",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_rule_change_sets",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rules_change_set"
        ordering = ["data_snapshot", "-created_at", "change_set_code"]
        verbose_name = "Kural değişiklik seti"
        verbose_name_plural = "Kural değişiklik setleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "change_set_code"],
                name="unique_rule_change_set_code_per_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.change_set_code} - {self.title}"


class RuleVersion(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="rule_versions",
    )
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=24,
        choices=RuleVersionStatus.choices,
        default=RuleVersionStatus.DRAFT,
    )
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    condition_tree = models.JSONField(default=dict, blank=True)
    action_config = models.JSONField(default=dict, blank=True)
    change_set = models.ForeignKey(
        RuleChangeSet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rule_versions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_rule_versions",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rules_rule_version"
        ordering = ["rule__code", "-version"]
        verbose_name = "Kural versiyonu"
        verbose_name_plural = "Kural versiyonları"
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "version"],
                name="unique_rule_version_number",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="rule_version_valid_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rule.code} v{self.version}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.valid_to and self.valid_to <= self.valid_from:
            errors["valid_to"] = "valid_to must be later than valid_from."
        if (
            self.rule_id
            and self.data_snapshot_id
            and self.rule.data_snapshot_id != self.data_snapshot_id
        ):
            errors["rule"] = "Rule must belong to the same data snapshot."
        if (
            self.change_set_id
            and self.data_snapshot_id
            and self.change_set.data_snapshot_id != self.data_snapshot_id
        ):
            errors["change_set"] = "Change set must belong to the same data snapshot."
        if self.rule_id and self._overlaps_existing_version():
            errors["valid_from"] = "Rule version validity overlaps with an existing version."
        if errors:
            raise ValidationError(errors)

    def _overlaps_existing_version(self) -> bool:
        versions = RuleVersion.objects.filter(rule_id=self.rule_id).exclude(pk=self.pk)
        for version in versions:
            existing_end = version.valid_to
            current_end = self.valid_to
            starts_before_existing_end = existing_end is None or self.valid_from < existing_end
            existing_starts_before_current_end = (
                current_end is None or version.valid_from < current_end
            )
            if starts_before_existing_end and existing_starts_before_current_end:
                return True
        return False

    def is_valid_at(self, moment) -> bool:
        if self.status != RuleVersionStatus.ACTIVE:
            return False
        if moment < self.valid_from:
            return False
        return self.valid_to is None or moment < self.valid_to


class RuleTestCase(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="rule_test_cases",
    )
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name="test_cases")
    rule_version = models.ForeignKey(
        RuleVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_cases",
    )
    name = models.CharField(max_length=160)
    status = models.CharField(
        max_length=24,
        choices=RuleTestCaseStatus.choices,
        default=RuleTestCaseStatus.DRAFT,
    )
    input_payload = models.JSONField(default=dict, blank=True)
    expected_output = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rules_test_case"
        ordering = ["rule__code", "name"]
        verbose_name = "Kural test senaryosu"
        verbose_name_plural = "Kural test senaryoları"
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "name"],
                name="unique_rule_test_case_name",
            )
        ]

    def __str__(self) -> str:
        return f"{self.rule.code} - {self.name}"

    def clean(self):
        errors: dict[str, str] = {}
        if (
            self.rule_id
            and self.data_snapshot_id
            and self.rule.data_snapshot_id != self.data_snapshot_id
        ):
            errors["rule"] = "Rule must belong to the same data snapshot."
        if (
            self.rule_version_id
            and self.data_snapshot_id
            and self.rule_version.data_snapshot_id != self.data_snapshot_id
        ):
            errors["rule_version"] = "Rule version must belong to the same data snapshot."
        if self.rule_version_id and self.rule_id and self.rule_version.rule_id != self.rule_id:
            errors["rule_version"] = "Rule version must belong to the selected rule."
        if errors:
            raise ValidationError(errors)
