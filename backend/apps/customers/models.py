from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.customers.services.technology_compatibility import is_package_line_compatible
from apps.datasets.models import DataSnapshot
from apps.geography.models import City, District, Neighborhood
from apps.network.models import (
    AccessTechnology,
    LineConnection,
    NetworkDeviceAccessRole,
    NetworkDeviceType,
    validate_location_chain,
)


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


class SuspensionReason(models.TextChoices):
    CUSTOMER_REQUEST = "customer_request", "Customer request"
    PAYMENT_RELATED = "payment_related", "Payment related"
    ADMINISTRATIVE = "administrative", "Administrative"
    PROVIDER_FAULT = "provider_fault", "Provider fault"
    UNKNOWN = "unknown", "Unknown"


class ServiceType(models.TextChoices):
    BROADBAND = "broadband", "Broadband"
    METRO_ETHERNET = "metro_ethernet", "Metro Ethernet"


class SubscriptionConnectionRole(models.TextChoices):
    PRIMARY = "primary", "Primary"
    BACKUP = "backup", "Backup"


class PaymentStatus(models.TextChoices):
    PAID_ON_TIME = "paid_on_time", "Paid on time"
    PAID_LATE = "paid_late", "Paid late"
    OVERDUE = "overdue", "Overdue"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"
    REVERSED = "reversed", "Reversed"
    VOIDED = "voided", "Voided"


class CampaignStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


class CompensationDecisionStatus(models.TextChoices):
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    MANUAL_REVIEW = "manual_review", "Manual review"


class CompensationSettlementStatus(models.TextChoices):
    NOT_APPLICABLE = "not_applicable", "Not applicable"
    PENDING = "pending", "Pending"
    CREDITED = "credited", "Credited"
    PAID = "paid", "Paid"


class ServicePackageStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    RETIRED = "retired", "Retired"


class SLABackupRequirement(models.TextChoices):
    NONE = "none", "None"
    OPTIONAL = "optional", "Optional"
    RECOMMENDED = "recommended", "Recommended"
    REQUIRED = "required", "Required"


class SLAPathDiversityRequirement(models.TextChoices):
    NOT_REQUIRED = "not_required", "Not required"
    PARTIALLY_DIVERSE = "partially_diverse", "Partially diverse"
    FULLY_DIVERSE = "fully_diverse", "Fully diverse"


class SLAMonitoringLevel(models.TextChoices):
    STANDARD = "standard", "Standard"
    ENHANCED = "enhanced", "Enhanced"
    PROACTIVE = "proactive", "Proactive"
    CONTINUOUS = "continuous", "Continuous"


class CampaignDiscountType(models.TextChoices):
    PERCENT = "percent", "Percent"
    FIXED_AMOUNT = "fixed_amount", "Fixed amount"
    FREE_MONTH = "free_month", "Free month"


class CampaignCatalogStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    RETIRED = "retired", "Retired"


class SLAProfile(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="sla_profiles",
    )
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    availability_target_percent = models.DecimalField(max_digits=5, decimal_places=2)
    support_window = models.CharField(max_length=40)
    response_target_minutes = models.PositiveIntegerField()
    restoration_target_minutes = models.PositiveIntegerField()
    latency_threshold_ms = models.PositiveIntegerField()
    jitter_threshold_ms = models.PositiveIntegerField()
    packet_loss_threshold_percent = models.DecimalField(max_digits=5, decimal_places=2)
    backup_requirement = models.CharField(
        max_length=24,
        choices=SLABackupRequirement.choices,
        default=SLABackupRequirement.NONE,
    )
    required_path_diversity = models.CharField(
        max_length=32,
        choices=SLAPathDiversityRequirement.choices,
        default=SLAPathDiversityRequirement.NOT_REQUIRED,
    )
    monitoring_level = models.CharField(
        max_length=24,
        choices=SLAMonitoringLevel.choices,
        default=SLAMonitoringLevel.STANDARD,
    )
    is_contractual = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customers_sla_profile"
        ordering = ["data_snapshot", "code"]
        verbose_name = "SLA profili"
        verbose_name_plural = "SLA profilleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "code"],
                name="unique_sla_profile_code_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(availability_target_percent__gte=Decimal("0.00"))
                & models.Q(availability_target_percent__lte=Decimal("100.00")),
                name="sla_availability_target_percent_range",
            ),
            models.CheckConstraint(
                condition=models.Q(packet_loss_threshold_percent__gte=Decimal("0.00"))
                & models.Q(packet_loss_threshold_percent__lte=Decimal("100.00")),
                name="sla_packet_loss_threshold_percent_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    def clean(self):
        errors: dict[str, str] = {}
        if not Decimal("0.00") <= self.availability_target_percent <= Decimal("100.00"):
            errors["availability_target_percent"] = "Availability target must be between 0 and 100."
        if not Decimal("0.00") <= self.packet_loss_threshold_percent <= Decimal("100.00"):
            errors["packet_loss_threshold_percent"] = (
                "Packet loss threshold must be between 0 and 100."
            )
        if (
            self.backup_requirement == SLABackupRequirement.REQUIRED
            and self.required_path_diversity == SLAPathDiversityRequirement.NOT_REQUIRED
        ):
            errors["required_path_diversity"] = (
                "Required backup SLA profiles must define a path diversity target."
            )
        if errors:
            raise ValidationError(errors)


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
    status = models.CharField(
        max_length=24,
        choices=ServicePackageStatus.choices,
        default=ServicePackageStatus.ACTIVE,
    )
    default_sla_profile = models.ForeignKey(
        SLAProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="default_service_packages",
    )
    download_mbps = models.PositiveIntegerField(default=0)
    upload_mbps = models.PositiveIntegerField(default=0)
    symmetric = models.BooleanField(default=False)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2)
    commitment_months = models.PositiveIntegerField(default=0)
    backup_eligible = models.BooleanField(default=False)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
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
        errors: dict[str, str] = {}
        if self.monthly_price < Decimal("0.00"):
            errors["monthly_price"] = "Monthly price cannot be negative."
        if self.valid_to and self.valid_from and self.valid_to <= self.valid_from:
            errors["valid_to"] = "valid_to must be later than valid_from."
        if (
            self.default_sla_profile_id
            and self.data_snapshot_id
            and self.default_sla_profile.data_snapshot_id != self.data_snapshot_id
        ):
            errors["default_sla_profile"] = (
                "Default SLA profile must belong to the same data snapshot."
            )
        if self.service_type == ServiceType.METRO_ETHERNET:
            if self.technology != AccessTechnology.FIBER:
                errors["technology"] = "Metro Ethernet packages must use fiber technology."
            if not self.backup_eligible:
                errors["backup_eligible"] = (
                    "Metro Ethernet packages must explicitly be backup eligible."
                )
        if errors:
            raise ValidationError(errors)


class ServicePackageAllowedSegment(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="service_package_allowed_segments",
    )
    service_package = models.ForeignKey(
        ServicePackage,
        on_delete=models.CASCADE,
        related_name="allowed_segments",
    )
    segment = models.CharField(max_length=24, choices=CustomerSegment.choices)

    class Meta:
        db_table = "customers_service_package_allowed_segment"
        ordering = ["data_snapshot", "service_package__package_code", "segment"]
        verbose_name = "Servis paketi uygun segmenti"
        verbose_name_plural = "Servis paketi uygun segmentleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "service_package", "segment"],
                name="unique_service_package_allowed_segment",
            )
        ]

    def clean(self):
        if (
            self.service_package_id
            and self.data_snapshot_id
            and self.service_package.data_snapshot_id != self.data_snapshot_id
        ):
            raise ValidationError(
                {"service_package": "Service package must belong to the same data snapshot."}
            )


class ServicePackagePriceVersion(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="service_package_price_versions",
    )
    service_package = models.ForeignKey(
        ServicePackage,
        on_delete=models.CASCADE,
        related_name="price_versions",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="TRY")
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    version_number = models.PositiveIntegerField()
    active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customers_service_package_price_version"
        ordering = ["data_snapshot", "service_package__package_code", "version_number"]
        verbose_name = "Servis paketi fiyat versiyonu"
        verbose_name_plural = "Servis paketi fiyat versiyonları"
        constraints = [
            models.UniqueConstraint(
                fields=["service_package", "version_number"],
                name="unique_service_package_price_version_number",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="service_package_price_version_valid_range",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gte=Decimal("0.00")),
                name="service_package_price_version_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.service_package.package_code} v{self.version_number} "
            f"{self.amount} {self.currency}"
        )

    def clean(self):
        errors: dict[str, str] = {}
        if self.amount < Decimal("0.00"):
            errors["amount"] = "Price amount cannot be negative."
        if len(self.currency) != 3:
            errors["currency"] = "Currency must be a three-letter ISO code."
        if self.valid_to and self.valid_to <= self.valid_from:
            errors["valid_to"] = "valid_to must be later than valid_from."
        if (
            self.service_package_id
            and self.data_snapshot_id
            and self.service_package.data_snapshot_id != self.data_snapshot_id
        ):
            errors["service_package"] = "Service package must belong to the same data snapshot."
        if self.service_package_id and self._overlaps_existing_price_version():
            errors["valid_from"] = (
                "Service package price version validity overlaps with an existing version."
            )
        if errors:
            raise ValidationError(errors)

    def _overlaps_existing_price_version(self) -> bool:
        versions = ServicePackagePriceVersion.objects.filter(
            service_package_id=self.service_package_id
        ).exclude(pk=self.pk)
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
    sla_profile = models.ForeignKey(
        SLAProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=24,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
    )
    suspension_reason = models.CharField(
        max_length=32,
        choices=SuspensionReason.choices,
        blank=True,
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
        if self.status == SubscriptionStatus.SUSPENDED and not self.suspension_reason:
            errors["suspension_reason"] = "Suspended subscriptions require a suspension reason."
        if self.status != SubscriptionStatus.SUSPENDED and self.suspension_reason:
            errors["suspension_reason"] = (
                "suspension_reason must be empty unless the subscription is suspended."
            )
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
            self.sla_profile_id
            and self.data_snapshot_id
            and self.sla_profile.data_snapshot_id != self.data_snapshot_id
        ):
            errors["sla_profile"] = "SLA profile must belong to the same data snapshot."
        if self.service_package_id and not self.sla_profile_id:
            self.sla_profile = self.service_package.default_sla_profile
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

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


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
    connection_role = models.CharField(
        max_length=16,
        choices=SubscriptionConnectionRole.choices,
        default=SubscriptionConnectionRole.PRIMARY,
    )
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
                fields=["subscription", "connection_role"],
                condition=models.Q(is_active=True, valid_to__isnull=True),
                name="unique_open_active_connection_per_subscription_role",
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
        if (
            self.subscription_id
            and self.line_connection_id
            and self.subscription.service_package.service_type == ServiceType.METRO_ETHERNET
        ):
            errors.update(self._validate_metro_ethernet_path())
        if self.subscription_id:
            if self.subscription.status == SubscriptionStatus.PENDING:
                errors["subscription"] = (
                    "Pending subscriptions cannot have subscription connections."
                )
            if self.subscription.status == SubscriptionStatus.CANCELLED and (
                self.is_active or self.valid_to is None
            ):
                errors["subscription"] = (
                    "Cancelled subscriptions can only have closed historical connections."
                )
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
            if self._overlaps_existing_active_connection(
                "subscription",
                same_role=True,
            ):
                errors["connection_role"] = (
                    "Subscription already has an overlapping active connection with the same role."
                )
            if self._overlaps_existing_active_connection("line_connection"):
                errors["line_connection"] = (
                    "Line connection already has an overlapping active subscription."
                )
            if (
                self.connection_role == SubscriptionConnectionRole.BACKUP
                and not self._has_overlapping_primary_connection()
            ):
                errors["connection_role"] = (
                    "A backup connection requires an overlapping active primary connection."
                )
        if errors:
            raise ValidationError(errors)

    def _overlaps_existing_active_connection(
        self,
        field_name: str,
        *,
        same_role: bool = False,
    ) -> bool:
        field_id = getattr(self, f"{field_name}_id")
        if not field_id:
            return False
        connections = SubscriptionConnection.objects.filter(
            data_snapshot_id=self.data_snapshot_id,
            is_active=True,
            **{f"{field_name}_id": field_id},
        ).exclude(pk=self.pk)
        if same_role:
            connections = connections.filter(connection_role=self.connection_role)
        return self._has_temporal_overlap(connections)

    def _has_overlapping_primary_connection(self) -> bool:
        if not self.subscription_id:
            return False
        connections = SubscriptionConnection.objects.filter(
            data_snapshot_id=self.data_snapshot_id,
            subscription_id=self.subscription_id,
            connection_role=SubscriptionConnectionRole.PRIMARY,
            is_active=True,
        ).exclude(pk=self.pk)
        return self._has_temporal_overlap(connections)

    def _has_temporal_overlap(self, connections) -> bool:
        for connection in connections:
            existing_end = connection.valid_to
            current_end = self.valid_to
            starts_before_existing_end = existing_end is None or self.valid_from < existing_end
            existing_starts_before_current_end = (
                current_end is None or connection.valid_from < current_end
            )
            if starts_before_existing_end and existing_starts_before_current_end:
                return True
        return False

    def _validate_metro_ethernet_path(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        line = self.line_connection
        device = line.port.device
        port_active_line_count = (
            line.port.line_connections.filter(
                data_snapshot_id=self.data_snapshot_id,
                is_active=True,
            )
            .exclude(pk=line.pk)
            .count()
        )
        if line.technology != AccessTechnology.FIBER:
            errors["line_connection"] = "Metro Ethernet subscriptions require a fiber line."
        if device.device_type != NetworkDeviceType.ACCESS_NODE:
            errors["line_connection"] = (
                "Metro Ethernet subscriptions must terminate on an access node."
            )
        elif device.access_role != NetworkDeviceAccessRole.CORPORATE_FIBER_AGGREGATION:
            errors["line_connection"] = (
                "Metro Ethernet subscriptions require a corporate fiber aggregation access node."
            )
        if port_active_line_count:
            errors["line_connection"] = (
                "Metro Ethernet subscriptions require a dedicated port with one active line."
            )
        return errors

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
    billing_period_start = models.DateField(null=True, blank=True)
    billing_period_end = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    recurring_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    one_time_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    billed_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    paid_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    outstanding_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    currency = models.CharField(max_length=3, default="TRY")
    status = models.CharField(
        max_length=24,
        choices=PaymentStatus.choices,
        default=PaymentStatus.OVERDUE,
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
        errors: dict[str, str] = {}
        if self.subscription_id and self.subscription.data_snapshot_id != self.data_snapshot_id:
            errors["subscription"] = "Subscription must belong to the same data snapshot."
        if self.billing_period_end and self.billing_period_start:
            if self.billing_period_end <= self.billing_period_start:
                errors["billing_period_end"] = (
                    "billing_period_end must be later than billing_period_start."
                )
        for field_name in (
            "amount",
            "recurring_amount",
            "one_time_amount",
            "discount_amount",
            "billed_amount",
            "paid_amount",
            "outstanding_amount",
        ):
            if getattr(self, field_name) < Decimal("0.00"):
                errors[field_name] = f"{field_name} cannot be negative."
        if len(self.currency) != 3:
            errors["currency"] = "Currency must be a three-letter ISO code."
        expected_billed = self.recurring_amount + self.one_time_amount - self.discount_amount
        if self.billing_period_start and self.billing_period_end:
            if self.billed_amount != expected_billed:
                errors["billed_amount"] = (
                    "billed_amount must equal recurring_amount + one_time_amount - discount_amount."
                )
            if self.outstanding_amount != self.billed_amount - self.paid_amount:
                errors["outstanding_amount"] = (
                    "outstanding_amount must equal billed_amount - paid_amount."
                )
        if self.subscription_id:
            if self.subscription.status == SubscriptionStatus.PENDING:
                errors["subscription"] = "Pending subscriptions cannot have payment records."
            if self.billing_period_start:
                subscription_start = self.subscription.valid_from.date()
                if self.billing_period_start < subscription_start:
                    errors["billing_period_start"] = (
                        "Billing period cannot start before subscription validity."
                    )
                if self.subscription.valid_to and (
                    self.billing_period_start >= self.subscription.valid_to.date()
                ):
                    errors["billing_period_start"] = (
                        "Billing period cannot start after subscription termination."
                    )
        if self.status in {PaymentStatus.PAID_ON_TIME, PaymentStatus.PAID_LATE}:
            if not self.paid_at:
                errors["paid_at"] = "paid_at is required for paid payment records."
            if self.outstanding_amount != Decimal("0.00"):
                errors["outstanding_amount"] = "Paid records cannot have outstanding amount."
        if (
            self.status == PaymentStatus.PAID_ON_TIME
            and self.paid_at
            and self.due_date
            and self.paid_at.date() > self.due_date
        ):
            errors["paid_at"] = "paid_on_time records must be paid on or before due_date."
        if (
            self.status == PaymentStatus.PAID_LATE
            and self.paid_at
            and self.due_date
            and self.paid_at.date() <= self.due_date
        ):
            errors["paid_at"] = "paid_late records must be paid after due_date."
        if self.status == PaymentStatus.PARTIAL and (
            self.paid_amount <= Decimal("0.00") or self.outstanding_amount <= Decimal("0.00")
        ):
            errors["status"] = "partial records require both paid and outstanding amounts."
        if self.status == PaymentStatus.VOIDED and (
            self.billed_amount != Decimal("0.00")
            or self.paid_amount != Decimal("0.00")
            or self.outstanding_amount != Decimal("0.00")
        ):
            errors["status"] = (
                "voided records must have zero billed, paid, and outstanding amounts."
            )
        if errors:
            raise ValidationError(errors)


class Campaign(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="campaigns",
    )
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    discount_type = models.CharField(max_length=24, choices=CampaignDiscountType.choices)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    duration_months = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    stackable = models.BooleanField(default=False)
    status = models.CharField(
        max_length=24,
        choices=CampaignCatalogStatus.choices,
        default=CampaignCatalogStatus.ACTIVE,
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customers_campaign"
        ordering = ["data_snapshot", "code"]
        verbose_name = "Kampanya"
        verbose_name_plural = "Kampanyalar"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "code"],
                name="unique_campaign_code_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="campaign_valid_range",
            ),
            models.CheckConstraint(
                condition=models.Q(discount_value__gte=Decimal("0.00")),
                name="campaign_discount_value_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.valid_to and self.valid_to <= self.valid_from:
            errors["valid_to"] = "valid_to must be later than valid_from."
        if self.discount_value < Decimal("0.00"):
            errors["discount_value"] = "Discount value cannot be negative."
        if self.discount_type == CampaignDiscountType.PERCENT and self.discount_value > Decimal(
            "100.00"
        ):
            errors["discount_value"] = "Percent discount cannot exceed 100."
        if errors:
            raise ValidationError(errors)


class CampaignAllowedSegment(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="campaign_allowed_segments",
    )
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="segments")
    segment = models.CharField(max_length=24, choices=CustomerSegment.choices)

    class Meta:
        db_table = "customers_campaign_allowed_segment"
        ordering = ["data_snapshot", "campaign__code", "segment"]
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "campaign", "segment"],
                name="unique_campaign_allowed_segment",
            )
        ]

    def clean(self):
        if (
            self.campaign_id
            and self.data_snapshot_id
            and self.campaign.data_snapshot_id != self.data_snapshot_id
        ):
            raise ValidationError({"campaign": "Campaign must belong to the same data snapshot."})


class CampaignAllowedServiceType(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="campaign_allowed_service_types",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="service_types",
    )
    service_type = models.CharField(max_length=32, choices=ServiceType.choices)

    class Meta:
        db_table = "customers_campaign_allowed_service_type"
        ordering = ["data_snapshot", "campaign__code", "service_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "campaign", "service_type"],
                name="unique_campaign_allowed_service_type",
            )
        ]

    def clean(self):
        if (
            self.campaign_id
            and self.data_snapshot_id
            and self.campaign.data_snapshot_id != self.data_snapshot_id
        ):
            raise ValidationError({"campaign": "Campaign must belong to the same data snapshot."})


class CampaignAllowedTechnology(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="campaign_allowed_technologies",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="technologies",
    )
    technology = models.CharField(max_length=32, choices=AccessTechnology.choices)

    class Meta:
        db_table = "customers_campaign_allowed_technology"
        ordering = ["data_snapshot", "campaign__code", "technology"]
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "campaign", "technology"],
                name="unique_campaign_allowed_technology",
            )
        ]

    def clean(self):
        if (
            self.campaign_id
            and self.data_snapshot_id
            and self.campaign.data_snapshot_id != self.data_snapshot_id
        ):
            raise ValidationError({"campaign": "Campaign must belong to the same data snapshot."})


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
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="enrollments",
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
        if (
            self.campaign_id
            and self.data_snapshot_id
            and self.campaign.data_snapshot_id != self.data_snapshot_id
        ):
            errors["campaign"] = "Campaign must belong to the same data snapshot."
        if self.campaign_id and self.subscription_id:
            if not self.campaign_code:
                self.campaign_code = self.campaign.code
            if not self.name:
                self.name = self.campaign.name
            eligibility_errors = self._validate_campaign_eligibility()
            errors.update(eligibility_errors)
            if (
                self.status == CampaignStatus.ACTIVE
                and not self.campaign.stackable
                and self._has_overlapping_non_stackable_enrollment()
            ):
                errors["campaign"] = (
                    "Subscription already has an overlapping active non-stackable campaign."
                )
        if errors:
            raise ValidationError(errors)

    def _validate_campaign_eligibility(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        subscription = self.subscription
        campaign = self.campaign
        allowed_segments = set(campaign.segments.values_list("segment", flat=True))
        if allowed_segments and subscription.customer.segment not in allowed_segments:
            errors["campaign"] = "Campaign is not allowed for the customer segment."
        allowed_service_types = set(campaign.service_types.values_list("service_type", flat=True))
        if (
            allowed_service_types
            and subscription.service_package.service_type not in allowed_service_types
        ):
            errors["campaign"] = "Campaign is not allowed for the service type."
        allowed_technologies = set(campaign.technologies.values_list("technology", flat=True))
        if (
            allowed_technologies
            and subscription.service_package.technology not in allowed_technologies
        ):
            errors["campaign"] = "Campaign is not allowed for the package technology."
        return errors

    def _has_overlapping_non_stackable_enrollment(self) -> bool:
        enrollments = (
            CampaignEnrollment.objects.filter(
                data_snapshot_id=self.data_snapshot_id,
                subscription_id=self.subscription_id,
                status=CampaignStatus.ACTIVE,
                campaign__stackable=False,
            )
            .exclude(pk=self.pk)
            .select_related("campaign")
        )
        for enrollment in enrollments:
            existing_end = enrollment.valid_to
            current_end = self.valid_to
            starts_before_existing_end = existing_end is None or self.valid_from < existing_end
            existing_starts_before_current_end = (
                current_end is None or enrollment.valid_from < current_end
            )
            if starts_before_existing_end and existing_starts_before_current_end:
                return True
        return False


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
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="compensation_history",
    )
    incident = models.ForeignKey(
        "operations.Incident",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="compensation_history",
    )
    outage = models.ForeignKey(
        "operations.Outage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compensation_history",
    )
    rule_version = models.ForeignKey(
        "rules.RuleVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="compensation_history",
    )
    compensation_conflict_group = models.CharField(max_length=80, blank=True)
    reference_code = models.CharField(max_length=80)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    decision_status = models.CharField(
        max_length=24,
        choices=CompensationDecisionStatus.choices,
        default=CompensationDecisionStatus.MANUAL_REVIEW,
    )
    settlement_status = models.CharField(
        max_length=24,
        choices=CompensationSettlementStatus.choices,
        default=CompensationSettlementStatus.NOT_APPLICABLE,
    )
    currency = models.CharField(max_length=3, default="TRY")
    reason = models.CharField(max_length=240, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=160, blank=True)
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
            ),
            models.UniqueConstraint(
                fields=["subscription", "incident", "rule_version"],
                condition=(
                    models.Q(incident__isnull=False)
                    & models.Q(rule_version__isnull=False)
                    & models.Q(
                        decision_status__in=[
                            CompensationDecisionStatus.APPROVED,
                            CompensationDecisionStatus.REJECTED,
                        ]
                    )
                ),
                name="unique_final_compensation_per_sub_incident_rule",
            ),
            models.UniqueConstraint(
                fields=["subscription", "incident", "compensation_conflict_group"],
                condition=(
                    models.Q(incident__isnull=False)
                    & ~models.Q(compensation_conflict_group="")
                    & models.Q(
                        decision_status__in=[
                            CompensationDecisionStatus.APPROVED,
                            CompensationDecisionStatus.REJECTED,
                        ]
                    )
                ),
                name="unique_final_compensation_per_sub_incident_group",
            ),
            models.UniqueConstraint(
                fields=["data_snapshot", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="unique_compensation_history_idempotency_key",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference_code} - {self.subscription.subscription_number}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.subscription_id and self.subscription.data_snapshot_id != self.data_snapshot_id:
            errors["subscription"] = "Subscription must belong to the same data snapshot."
        if (
            self.customer_id
            and self.data_snapshot_id
            and self.customer.data_snapshot_id != self.data_snapshot_id
        ):
            errors["customer"] = "Customer must belong to the same data snapshot."
        if (
            self.incident_id
            and self.data_snapshot_id
            and self.incident.data_snapshot_id != self.data_snapshot_id
        ):
            errors["incident"] = "Incident must belong to the same data snapshot."
        if (
            self.outage_id
            and self.data_snapshot_id
            and self.outage.data_snapshot_id != self.data_snapshot_id
        ):
            errors["outage"] = "Outage must belong to the same data snapshot."
        if (
            self.rule_version_id
            and self.data_snapshot_id
            and self.rule_version.data_snapshot_id != self.data_snapshot_id
        ):
            errors["rule_version"] = "Rule version must belong to the same data snapshot."
        if self.rule_version_id and not self.compensation_conflict_group:
            self.compensation_conflict_group = self.rule_version.rule.conflict_group
        if self.subscription_id:
            if not self.customer_id:
                self.customer = self.subscription.customer
            elif self.subscription.customer_id != self.customer_id:
                errors["customer"] = "Customer must match the subscription customer."
        if self.amount < Decimal("0.00"):
            errors["amount"] = "Compensation amount cannot be negative."
        if len(self.currency) != 3:
            errors["currency"] = "Currency must be a three-letter ISO code."
        if not self.incident_id:
            errors["incident"] = "Incident is required for compensation history."
        if not self.rule_version_id:
            errors["rule_version"] = "Rule version is required for compensation history."
        if (
            self.decision_status
            in {
                CompensationDecisionStatus.REJECTED,
                CompensationDecisionStatus.MANUAL_REVIEW,
            }
            and self.settlement_status != CompensationSettlementStatus.NOT_APPLICABLE
        ):
            errors["settlement_status"] = (
                "Rejected and manual review decisions must use not_applicable settlement."
            )
        if (
            self.decision_status == CompensationDecisionStatus.APPROVED
            and self.settlement_status == CompensationSettlementStatus.NOT_APPLICABLE
        ):
            errors["settlement_status"] = (
                "Approved decisions require a pending, credited, or paid settlement."
            )
        if self.settled_at and self.settlement_status not in {
            CompensationSettlementStatus.CREDITED,
            CompensationSettlementStatus.PAID,
        }:
            errors["settled_at"] = "settled_at is only valid for credited or paid settlements."
        if self.settled_at and self.decided_at and self.settled_at < self.decided_at:
            errors["settled_at"] = "settled_at cannot be earlier than decided_at."
        if errors:
            raise ValidationError(errors)
