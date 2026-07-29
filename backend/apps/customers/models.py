from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.customers.services.technology_compatibility import is_package_line_compatible
from apps.datasets.models import DataSnapshot
from apps.geography.models import City, District, Neighborhood
from apps.network.models import AccessTechnology, LineConnection, validate_location_chain


class CustomerSegment(models.TextChoices):
    INDIVIDUAL = "individual", "Individual"
    SME = "sme", "SME"
    ENTERPRISE = "enterprise", "Enterprise"
    PUBLIC = "public", "Public"


class CustomerPriorityLevel(models.TextChoices):
    STANDARD = "standard", "Standard"
    VIP = "vip", "VIP"


class CustomerStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CHURNED = "churned", "Churned"


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CANCELLED = "cancelled", "Cancelled"
    PENDING = "pending", "Pending"


class ServiceType(models.TextChoices):
    BROADBAND = "broadband", "Broadband"
    METRO_ETHERNET = "metro_ethernet", "Metro Ethernet"


class PaymentStatus(models.TextChoices):
    PAID = "paid", "Paid"
    DUE = "due", "Due"
    OVERDUE = "overdue", "Overdue"
    CANCELLED = "cancelled", "Cancelled"


class CampaignStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


class CompensationHistoryStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    PAID = "paid", "Paid"


class Customer(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="customers",
    )
    customer_number = models.CharField(max_length=80)
    display_name = models.CharField(max_length=160)
    segment = models.CharField(
        max_length=24,
        choices=CustomerSegment.choices,
        default=CustomerSegment.INDIVIDUAL,
    )
    status = models.CharField(
        max_length=24,
        choices=CustomerStatus.choices,
        default=CustomerStatus.ACTIVE,
    )
    priority_level = models.CharField(
        max_length=24,
        choices=CustomerPriorityLevel.choices,
        default=CustomerPriorityLevel.STANDARD,
    )
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name="customers")
    district = models.ForeignKey(
        District,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="customers",
    )
    neighborhood = models.ForeignKey(
        Neighborhood,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="customers",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customers_customer"
        ordering = ["data_snapshot", "customer_number"]
        verbose_name = "Müşteri"
        verbose_name_plural = "Müşteriler"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "customer_number"],
                name="unique_customer_number_per_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.customer_number} - {self.display_name}"

    def clean(self):
        validate_location_chain(self.city, self.district, self.neighborhood)


class ServicePackage(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="service_packages",
    )
    package_code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    technology = models.CharField(max_length=32, choices=AccessTechnology.choices)
    service_type = models.CharField(
        max_length=32,
        choices=ServiceType.choices,
        default=ServiceType.BROADBAND,
    )
    download_mbps = models.PositiveIntegerField(default=0)
    upload_mbps = models.PositiveIntegerField(default=0)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2)
    commitment_months = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customers_service_package"
        ordering = ["data_snapshot", "package_code"]
        verbose_name = "Servis paketi"
        verbose_name_plural = "Servis paketleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "package_code"],
                name="unique_service_package_code_per_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.package_code} - {self.name}"

    def clean(self):
        if self.monthly_price < Decimal("0.00"):
            raise ValidationError({"monthly_price": "Monthly price cannot be negative."})


class Subscription(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    subscription_number = models.CharField(max_length=80)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="subscriptions")
    service_package = models.ForeignKey(
        ServicePackage,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=24,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
    )
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customers_subscription"
        ordering = ["data_snapshot", "subscription_number"]
        verbose_name = "Abonelik"
        verbose_name_plural = "Abonelikler"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "subscription_number"],
                name="unique_subscription_number_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="subscription_valid_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.subscription_number} - {self.customer.customer_number}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.valid_to and self.valid_to <= self.valid_from:
            errors["valid_to"] = "valid_to must be later than valid_from."
        if self.monthly_price < Decimal("0.00"):
            errors["monthly_price"] = "Monthly price cannot be negative."
        if (
            self.customer_id
            and self.data_snapshot_id
            and self.customer.data_snapshot_id != self.data_snapshot_id
        ):
            errors["customer"] = "Customer must belong to the same data snapshot."
        if (
            self.service_package_id
            and self.data_snapshot_id
            and self.service_package.data_snapshot_id != self.data_snapshot_id
        ):
            errors["service_package"] = "Service package must belong to the same data snapshot."
        if (
            self.service_package_id
            and self.monthly_price == Decimal("0.00")
            and self.service_package.monthly_price > Decimal("0.00")
        ):
            self.monthly_price = self.service_package.monthly_price
        if errors:
            raise ValidationError(errors)

    def is_valid_at(self, moment) -> bool:
        if not self.is_active or self.status != SubscriptionStatus.ACTIVE:
            return False
        if moment < self.valid_from:
            return False
        return self.valid_to is None or moment < self.valid_to


class SubscriptionConnection(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="subscription_connections",
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="connections",
    )
    line_connection = models.ForeignKey(
        LineConnection,
        on_delete=models.PROTECT,
        related_name="subscription_connections",
    )
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    port_identifier = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customers_subscription_connection"
        ordering = ["data_snapshot", "subscription__subscription_number", "valid_from"]
        verbose_name = "Abonelik bağlantısı"
        verbose_name_plural = "Abonelik bağlantıları"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="subscription_connection_valid_range",
            ),
            models.UniqueConstraint(
                fields=["subscription"],
                condition=models.Q(is_active=True, valid_to__isnull=True),
                name="unique_open_active_connection_per_subscription",
            ),
            models.UniqueConstraint(
                fields=["line_connection"],
                condition=models.Q(is_active=True, valid_to__isnull=True),
                name="unique_open_active_connection_per_line",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.subscription.subscription_number} -> {self.line_connection.line_code}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.valid_to and self.valid_to <= self.valid_from:
            errors["valid_to"] = "valid_to must be later than valid_from."
        if (
            self.subscription_id
            and self.data_snapshot_id
            and self.subscription.data_snapshot_id != self.data_snapshot_id
        ):
            errors["subscription"] = "Subscription must belong to the same data snapshot."
        if (
            self.line_connection_id
            and self.data_snapshot_id
            and self.line_connection.data_snapshot_id != self.data_snapshot_id
        ):
            errors["line_connection"] = "Line connection must belong to the same data snapshot."
        if (
            self.subscription_id
            and self.line_connection_id
            and not is_package_line_compatible(
                self.subscription.service_package.technology,
                self.line_connection.technology,
                self.subscription.service_package.service_type,
            )
        ):
            errors["line_connection"] = (
                "Line connection technology must be compatible with the subscription package "
                "technology."
            )
        if self.subscription_id:
            if self.valid_from < self.subscription.valid_from:
                errors["valid_from"] = "Connection cannot start before the subscription."
            if self.subscription.valid_to and (
                self.valid_to is None or self.valid_to > self.subscription.valid_to
            ):
                errors["valid_to"] = "Connection cannot extend beyond the subscription."
        if self.line_connection_id:
            if self.valid_from < self.line_connection.valid_from:
                errors["valid_from"] = "Connection cannot start before the line connection."
            if self.line_connection.valid_to and (
                self.valid_to is None or self.valid_to > self.line_connection.valid_to
            ):
                errors["valid_to"] = "Connection cannot extend beyond the line connection."
        if self.is_active:
            if self._overlaps_existing_active_connection("subscription"):
                errors["subscription"] = (
                    "Subscription already has an overlapping active line connection."
                )
            if self._overlaps_existing_active_connection("line_connection"):
                errors["line_connection"] = (
                    "Line connection already has an overlapping active subscription."
                )
        if errors:
            raise ValidationError(errors)

    def _overlaps_existing_active_connection(self, field_name: str) -> bool:
        field_id = getattr(self, f"{field_name}_id")
        if not field_id:
            return False
        connections = SubscriptionConnection.objects.filter(
            data_snapshot_id=self.data_snapshot_id,
            is_active=True,
            **{f"{field_name}_id": field_id},
        ).exclude(pk=self.pk)
        for connection in connections:
            existing_end = connection.valid_to
            current_end = self.valid_to
            starts_before_existing_end = (
                existing_end is None or self.valid_from < existing_end
            )
            existing_starts_before_current_end = (
                current_end is None or connection.valid_from < current_end
            )
            if starts_before_existing_end and existing_starts_before_current_end:
                return True
        return False

    def is_valid_at(self, moment) -> bool:
        if not self.is_active:
            return False
        if moment < self.valid_from:
            return False
        return self.valid_to is None or moment < self.valid_to

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class PaymentRecord(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="payment_records",
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="payment_records",
    )
    period = models.CharField(max_length=16)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=24,
        choices=PaymentStatus.choices,
        default=PaymentStatus.DUE,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customers_payment_record"
        ordering = ["data_snapshot", "subscription__subscription_number", "period"]
        verbose_name = "Ödeme kaydı"
        verbose_name_plural = "Ödeme kayıtları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "subscription", "period"],
                name="unique_payment_record_period_per_subscription",
            )
        ]

    def __str__(self) -> str:
        return f"{self.subscription.subscription_number} - {self.period}"

    def clean(self):
        if self.subscription_id and self.subscription.data_snapshot_id != self.data_snapshot_id:
            raise ValidationError(
                {"subscription": "Subscription must belong to the same data snapshot."}
            )
        if self.amount < Decimal("0.00"):
            raise ValidationError({"amount": "Payment amount cannot be negative."})


class CampaignEnrollment(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="campaign_enrollments",
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="campaign_enrollments",
    )
    campaign_code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    status = models.CharField(
        max_length=24,
        choices=CampaignStatus.choices,
        default=CampaignStatus.ACTIVE,
    )
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customers_campaign_enrollment"
        ordering = ["data_snapshot", "subscription__subscription_number", "campaign_code"]
        verbose_name = "Kampanya katılımı"
        verbose_name_plural = "Kampanya katılımları"

    def __str__(self) -> str:
        return f"{self.subscription.subscription_number} - {self.campaign_code}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.valid_to and self.valid_to <= self.valid_from:
            errors["valid_to"] = "valid_to must be later than valid_from."
        if self.subscription_id and self.subscription.data_snapshot_id != self.data_snapshot_id:
            errors["subscription"] = "Subscription must belong to the same data snapshot."
        if errors:
            raise ValidationError(errors)


class CompensationHistory(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="compensation_history",
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="compensation_history",
    )
    reference_code = models.CharField(max_length=80)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=24,
        choices=CompensationHistoryStatus.choices,
        default=CompensationHistoryStatus.PROPOSED,
    )
    reason = models.CharField(max_length=240, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customers_compensation_history"
        ordering = ["data_snapshot", "subscription__subscription_number", "reference_code"]
        verbose_name = "Telafi geçmişi"
        verbose_name_plural = "Telafi geçmişi"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "reference_code"],
                name="unique_compensation_reference_per_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.reference_code} - {self.subscription.subscription_number}"

    def clean(self):
        if self.subscription_id and self.subscription.data_snapshot_id != self.data_snapshot_id:
            raise ValidationError(
                {"subscription": "Subscription must belong to the same data snapshot."}
            )
        if self.amount < Decimal("0.00"):
            raise ValidationError({"amount": "Compensation amount cannot be negative."})
