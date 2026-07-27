from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.customers.models import Customer, Subscription
from apps.datasets.models import DataSnapshot
from apps.operations.models import Outage
from apps.rules.models import RuleVersion


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
