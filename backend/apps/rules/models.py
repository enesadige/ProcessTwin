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


class RuleFamily(models.TextChoices):
    LEGACY = "legacy", "Legacy"
    ELIGIBILITY = "eligibility", "Eligibility"
    EXCLUSION = "exclusion", "Exclusion"
    BROADBAND = "broadband", "Broadband"
    METRO_SLA = "metro_sla", "Metro/SLA"
    FAILOVER = "failover", "Failover"
    MODIFIER = "modifier", "Modifier"
    SLA_EVIDENCE = "sla_evidence", "SLA evidence"
    MANUAL_REVIEW = "manual_review", "Manual review"
    FINAL_POLICY = "final_policy", "Final policy"


class RuleActionType(models.TextChoices):
    LEGACY_MONTHLY_PRICE_PERCENTAGE = (
        "legacy_monthly_price_percentage",
        "Legacy monthly price percentage",
    )
    PASS = "pass", "Pass"
    INELIGIBLE = "ineligible", "Ineligible"
    MANUAL_REVIEW = "manual_review", "Manual review"
    TIERED_PERCENTAGE = "tiered_percentage", "Tiered percentage"
    PRORATED = "prorated", "Prorated"
    SLA_MATRIX = "sla_matrix", "SLA matrix"
    MULTIPLIER = "multiplier", "Multiplier"
    CAP_FLOOR = "cap_floor", "Cap/floor"
    EVIDENCE_ONLY = "evidence_only", "Evidence only"


class RulePriceBasis(models.TextChoices):
    CONTRACTED_MONTHLY_PRICE = "contracted_monthly_price", "Contracted monthly price"
    BILLED_RECURRING_AMOUNT = "billed_recurring_amount", "Billed recurring amount"
    CAMPAIGN_ADJUSTED_RECURRING_AMOUNT = (
        "campaign_adjusted_recurring_amount",
        "Campaign adjusted recurring amount",
    )
    PACKAGE_LIST_PRICE = "package_list_price", "Package list price"


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


class RuleSet(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="rule_sets",
    )
    code = models.CharField(max_length=80)
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=160)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    change_reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rules_rule_set"
        ordering = ["data_snapshot", "code", "-version"]
        verbose_name = "Kural seti"
        verbose_name_plural = "Kural setleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "code", "version"],
                name="unique_rule_set_code_version_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="rule_set_effective_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} v{self.version}"

    def clean(self):
        if self.effective_to and self.effective_to <= self.effective_from:
            raise ValidationError(
                {"effective_to": "effective_to must be later than effective_from."}
            )

    def is_effective_at(self, moment) -> bool:
        if not self.active:
            return False
        if moment < self.effective_from:
            return False
        return self.effective_to is None or moment < self.effective_to


class Rule(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="rules",
    )
    rule_set = models.ForeignKey(
        RuleSet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rules",
    )
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    rule_type = models.CharField(max_length=32, choices=RuleType.choices)
    family = models.CharField(
        max_length=32,
        choices=RuleFamily.choices,
        default=RuleFamily.LEGACY,
    )
    conflict_group = models.CharField(max_length=80, blank=True)
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

    def clean(self):
        if (
            self.rule_set_id
            and self.data_snapshot_id
            and self.rule_set.data_snapshot_id != self.data_snapshot_id
        ):
            raise ValidationError({"rule_set": "Rule set must belong to the same data snapshot."})


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
    priority = models.PositiveIntegerField(default=100)
    action_type = models.CharField(
        max_length=40,
        choices=RuleActionType.choices,
        default=RuleActionType.LEGACY_MONTHLY_PRICE_PERCENTAGE,
    )
    price_basis = models.CharField(
        max_length=48,
        choices=RulePriceBasis.choices,
        default=RulePriceBasis.CONTRACTED_MONTHLY_PRICE,
    )
    stackable = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    condition_tree = models.JSONField(default=dict, blank=True)
    action_config = models.JSONField(default=dict, blank=True)
    change_note = models.TextField(blank=True)
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
            self.rule_id
            and self.rule.rule_set_id
            and not self.rule.rule_set.is_effective_at(self.valid_from)
        ):
            errors["valid_from"] = "Rule version must start inside the rule set effective range."
        if (
            self.change_set_id
            and self.data_snapshot_id
            and self.change_set.data_snapshot_id != self.data_snapshot_id
        ):
            errors["change_set"] = "Change set must belong to the same data snapshot."
        if self.rule_id and self._overlaps_existing_version():
            errors["valid_from"] = "Rule version validity overlaps with an existing version."
        if self.action_type != RuleActionType.LEGACY_MONTHLY_PRICE_PERCENTAGE:
            try:
                from apps.rules.services.schema import assert_valid_rule_schema

                assert_valid_rule_schema(
                    condition_tree=self.condition_tree,
                    action_type=self.action_type,
                    action_config=self.action_config,
                )
            except ValueError as exc:
                errors["action_config"] = str(exc)
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
        if self.status != RuleVersionStatus.ACTIVE or not self.active:
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
