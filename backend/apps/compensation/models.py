from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.customers.models import Customer, Subscription
from apps.datasets.models import DataSnapshot
from apps.operations.models import Outage
from apps.rules.models import RulePriceBasis, RuleSet, RuleVersion


class CompensationResultType(models.TextChoices):
    ELIGIBLE = "eligible", "Eligible"
    NOT_ELIGIBLE = "not_eligible", "Not eligible"
    MANUAL_REVIEW = "manual_review", "Manual review"
    INSUFFICIENT_DATA = "insufficient_data", "Insufficient data"


class CompensationEvaluationStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    CALCULATED = "calculated", "Calculated"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    PAID = "paid", "Paid"


class DecisionEvidenceDecision(models.TextChoices):
    ELIGIBLE = "eligible", "Eligible"
    INELIGIBLE = "ineligible", "Ineligible"
    MANUAL_REVIEW = "manual_review", "Manual review"
    EVIDENCE_ONLY = "evidence_only", "Evidence only"


class CompensationEvaluation(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="compensation_evaluations",
    )
    evaluation_code = models.CharField(max_length=100)
    outage = models.ForeignKey(
        Outage,
        on_delete=models.CASCADE,
        related_name="compensation_evaluations",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="compensation_evaluations",
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="compensation_evaluations",
    )
    rule_version = models.ForeignKey(
        RuleVersion,
        on_delete=models.PROTECT,
        related_name="compensation_evaluations",
    )
    result_type = models.CharField(max_length=32, choices=CompensationResultType.choices)
    status = models.CharField(
        max_length=24,
        choices=CompensationEvaluationStatus.choices,
        default=CompensationEvaluationStatus.DRAFT,
    )
    proposed_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="TRY")
    explanation = models.TextField(blank=True)
    calculation_trace = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "compensation_evaluation"
        ordering = ["data_snapshot", "-created_at", "evaluation_code"]
        verbose_name = "Telafi değerlendirmesi"
        verbose_name_plural = "Telafi değerlendirmeleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "evaluation_code"],
                name="unique_compensation_evaluation_code_per_snapshot",
            ),
            models.UniqueConstraint(
                fields=["outage", "subscription", "rule_version"],
                name="unique_compensation_evaluation_per_outage_subscription_rule",
            ),
            models.CheckConstraint(
                condition=models.Q(proposed_amount__gte=Decimal("0.00")),
                name="compensation_proposed_amount_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.evaluation_code} - {self.subscription.subscription_number}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.proposed_amount < Decimal("0.00"):
            errors["proposed_amount"] = "Proposed amount cannot be negative."
        if len(self.currency) != 3:
            errors["currency"] = "Currency must be a three-letter ISO code."
        if (
            self.outage_id
            and self.data_snapshot_id
            and self.outage.data_snapshot_id != self.data_snapshot_id
        ):
            errors["outage"] = "Outage must belong to the same data snapshot."
        if (
            self.customer_id
            and self.data_snapshot_id
            and self.customer.data_snapshot_id != self.data_snapshot_id
        ):
            errors["customer"] = "Customer must belong to the same data snapshot."
        if (
            self.subscription_id
            and self.data_snapshot_id
            and self.subscription.data_snapshot_id != self.data_snapshot_id
        ):
            errors["subscription"] = "Subscription must belong to the same data snapshot."
        if (
            self.rule_version_id
            and self.data_snapshot_id
            and self.rule_version.data_snapshot_id != self.data_snapshot_id
        ):
            errors["rule_version"] = "Rule version must belong to the same data snapshot."
        if (
            self.subscription_id
            and self.customer_id
            and self.subscription.customer_id != self.customer_id
        ):
            errors["subscription"] = "Subscription must belong to the selected customer."
        if errors:
            raise ValidationError(errors)


class DecisionEvidence(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="decision_evidence_records",
    )
    compensation_evaluation = models.OneToOneField(
        CompensationEvaluation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="decision_evidence",
    )
    rule_set = models.ForeignKey(
        RuleSet,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decision_evidence_records",
    )
    selected_rule_version = models.ForeignKey(
        RuleVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decision_evidence_records",
    )
    price_basis = models.CharField(
        max_length=48,
        choices=RulePriceBasis.choices,
        blank=True,
    )
    selected_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    unrounded_amount = models.DecimalField(
        max_digits=14,
        decimal_places=6,
        null=True,
        blank=True,
    )
    final_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="TRY")
    decision = models.CharField(max_length=32, choices=DecisionEvidenceDecision.choices)
    evidence_schema_version = models.PositiveIntegerField(default=1)
    evidence_hash = models.CharField(max_length=64)
    matched_conditions = models.JSONField(default=list, blank=True)
    failed_conditions = models.JSONField(default=list, blank=True)
    excluded_rules = models.JSONField(default=list, blank=True)
    candidate_base_rules = models.JSONField(default=list, blank=True)
    applied_modifiers = models.JSONField(default=list, blank=True)
    formula_inputs = models.JSONField(default=dict, blank=True)
    cap_floor_trace = models.JSONField(default=list, blank=True)
    manual_review_reasons = models.JSONField(default=list, blank=True)
    context_snapshot = models.JSONField(default=dict, blank=True)
    finalized = models.BooleanField(default=True)

    class Meta:
        db_table = "compensation_decision_evidence"
        ordering = ["data_snapshot", "-created_at"]
        verbose_name = "Karar kanıtı"
        verbose_name_plural = "Karar kanıtları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "evidence_hash"],
                name="unique_decision_evidence_hash_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(final_amount__gte=Decimal("0.00")),
                name="decision_evidence_final_amount_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.decision} - {self.evidence_hash[:12]}"

    def clean(self):
        errors: dict[str, str] = {}
        if len(self.currency) != 3:
            errors["currency"] = "Currency must be a three-letter ISO code."
        if self.final_amount < Decimal("0.00"):
            errors["final_amount"] = "Final amount cannot be negative."
        if (
            self.compensation_evaluation_id
            and self.data_snapshot_id
            and self.compensation_evaluation.data_snapshot_id != self.data_snapshot_id
        ):
            errors["compensation_evaluation"] = (
                "Compensation evaluation must belong to the same data snapshot."
            )
        if (
            self.rule_set_id
            and self.data_snapshot_id
            and self.rule_set.data_snapshot_id != self.data_snapshot_id
        ):
            errors["rule_set"] = "Rule set must belong to the same data snapshot."
        if (
            self.selected_rule_version_id
            and self.data_snapshot_id
            and self.selected_rule_version.data_snapshot_id != self.data_snapshot_id
        ):
            errors["selected_rule_version"] = (
                "Selected rule version must belong to the same data snapshot."
            )
        if self.pk:
            existing = DecisionEvidence.objects.only("finalized").get(pk=self.pk)
            if existing.finalized:
                errors["finalized"] = "Finalized decision evidence is immutable."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)
