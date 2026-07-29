from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.datasets.models import DataSnapshot
from apps.network.models import (
    FailureDomain,
    LineConnection,
    NetworkDevice,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
)


class Severity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    MINOR = "minor", "Minor"
    MAJOR = "major", "Major"
    CRITICAL = "critical", "Critical"


class AlarmStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLEARED = "cleared", "Cleared"
    SUPPRESSED = "suppressed", "Suppressed"


class AlarmCategory(models.TextChoices):
    ACCESS = "access", "Access"
    TRANSPORT = "transport", "Transport"
    CORE = "core", "Core"
    POWER = "power", "Power"
    QUALITY = "quality", "Quality"


class AlarmSourceKind(models.TextChoices):
    DEVICE = "device", "Device"
    NETWORK_LINK = "network_link", "Network link"
    NETWORK_PORT = "network_port", "Network port"
    LINE_CONNECTION = "line_connection", "Line connection"
    FAILURE_DOMAIN = "failure_domain", "Failure domain"
    SUBSCRIPTION_CONNECTION = "subscription_connection", "Subscription connection"


class ServiceImpactClass(models.TextChoices):
    FULL_OUTAGE = "full_outage", "Full outage"
    PARTIAL_OUTAGE = "partial_outage", "Partial outage"
    SHORT_INTERRUPTION = "short_interruption", "Short interruption"
    DEGRADATION = "degradation", "Degradation"
    PROTECTION_LOSS = "protection_loss", "Protection loss"
    NO_DIRECT_CUSTOMER_IMPACT = (
        "no_direct_customer_impact",
        "No direct customer impact",
    )
    UNKNOWN = "unknown", "Unknown"


class AutoClearPolicy(models.TextChoices):
    AUTO = "auto", "Auto"
    MANUAL = "manual", "Manual"
    AUTO_OR_MANUAL = "auto_or_manual", "Auto or manual"


class IncidentType(models.TextChoices):
    NETWORK_OUTAGE = "network_outage", "Network outage"
    SERVICE_DEGRADATION = "service_degradation", "Service degradation"
    PROTECTION_EVENT = "protection_event", "Protection event"
    INTERMITTENT = "intermittent", "Intermittent"
    PLANNED_MAINTENANCE = "planned_maintenance", "Planned maintenance"
    UNKNOWN = "unknown", "Unknown"


class IncidentStatus(models.TextChoices):
    OPEN = "open", "Open"
    INVESTIGATING = "investigating", "Investigating"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


class RootCauseCategory(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    BNG_FAILURE = "bng_failure", "BNG failure"
    LOS = "los", "Loss of signal"
    POWER = "power", "Power"
    FIBER_CUT = "fiber_cut", "Fiber cut"
    CONFIGURATION = "configuration", "Configuration"


class FailoverResult(models.TextChoices):
    HITLESS = "hitless", "Hitless"
    NEAR_HITLESS = "near_hitless", "Near-hitless"
    SHORT_INTERRUPTION = "short_interruption", "Short interruption"
    DEGRADED = "degraded", "Degraded"
    FAILED = "failed", "Failed"
    UNKNOWN = "unknown", "Unknown"


class OutageType(models.TextChoices):
    DEVICE = "device", "Device"
    LINK = "link", "Link"
    ACCESS = "access", "Access"
    PLANNED = "planned", "Planned"


class OutageStatus(models.TextChoices):
    OPEN = "open", "Open"
    RESOLVED = "resolved", "Resolved"
    CANCELLED = "cancelled", "Cancelled"


class IncidentAlarmRole(models.TextChoices):
    PRIMARY = "primary", "Primary"
    SUPPORTING = "supporting", "Supporting"
    CORRELATED = "correlated", "Correlated"


class OperationalEventType(models.TextChoices):
    MAINTENANCE = "maintenance", "Maintenance"
    CONFIG_CHANGE = "config_change", "Config change"
    MANUAL_INTERVENTION = "manual_intervention", "Manual intervention"
    AUTO_RECOVERY = "auto_recovery", "Auto recovery"
    NOTE = "note", "Note"


class MaintenanceWindowStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    OVERRUN = "overrun", "Overrun"
    CANCELLED = "cancelled", "Cancelled"


class QualityMetricType(models.TextChoices):
    LATENCY_MS = "latency_ms", "Latency ms"
    JITTER_MS = "jitter_ms", "Jitter ms"
    PACKET_LOSS_PERCENT = "packet_loss_percent", "Packet loss percent"
    AVAILABILITY_PERCENT = "availability_percent", "Availability percent"
    BANDWIDTH_UTILIZATION_PERCENT = (
        "bandwidth_utilization_percent",
        "Bandwidth utilization percent",
    )


def validate_time_range(
    started_at,
    ended_at,
    *,
    start_field: str = "started_at",
    end_field: str = "ended_at",
) -> None:
    if ended_at and ended_at <= started_at:
        raise ValidationError({end_field: f"{end_field} must be later than {start_field}."})


def duration_seconds(started_at, ended_at) -> int | None:
    if not ended_at:
        return None
    return int((ended_at - started_at).total_seconds())


class AlarmType(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="alarm_types",
    )
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    severity = models.CharField(max_length=24, choices=Severity.choices)
    category = models.CharField(max_length=32, choices=AlarmCategory.choices)
    probable_cause_family = models.CharField(max_length=80, blank=True)
    service_impact_class = models.CharField(
        max_length=40,
        choices=ServiceImpactClass.choices,
        default=ServiceImpactClass.UNKNOWN,
    )
    auto_clear_policy = models.CharField(
        max_length=24,
        choices=AutoClearPolicy.choices,
        default=AutoClearPolicy.AUTO_OR_MANUAL,
    )
    deduplication_window_seconds = models.PositiveIntegerField(default=600)
    correlation_family = models.CharField(max_length=80, blank=True)
    default_incident_type = models.CharField(
        max_length=40,
        choices=IncidentType.choices,
        default=IncidentType.UNKNOWN,
    )
    is_root_candidate = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_alarm_type"
        ordering = ["data_snapshot", "code"]
        verbose_name = "Alarm tipi"
        verbose_name_plural = "Alarm tipleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "code"],
                name="unique_alarm_type_code_per_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class AlarmTypeAllowedSourceKind(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="alarm_type_allowed_source_kinds",
    )
    alarm_type = models.ForeignKey(
        AlarmType,
        on_delete=models.CASCADE,
        related_name="allowed_source_kinds",
    )
    source_kind = models.CharField(max_length=40, choices=AlarmSourceKind.choices)

    class Meta:
        db_table = "operations_alarm_type_allowed_source_kind"
        ordering = ["data_snapshot", "alarm_type__code", "source_kind"]
        verbose_name = "Alarm tipi kaynak türü"
        verbose_name_plural = "Alarm tipi kaynak türleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "alarm_type", "source_kind"],
                name="unique_alarm_type_allowed_source_kind",
            )
        ]

    def clean(self):
        if (
            self.alarm_type_id
            and self.data_snapshot_id
            and self.alarm_type.data_snapshot_id != self.data_snapshot_id
        ):
            raise ValidationError(
                {"alarm_type": "Alarm type must belong to the same data snapshot."}
            )


class AlarmTypeSupportedDeviceType(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="alarm_type_supported_device_types",
    )
    alarm_type = models.ForeignKey(
        AlarmType,
        on_delete=models.CASCADE,
        related_name="supported_device_types",
    )
    device_type = models.CharField(max_length=24, choices=NetworkDeviceType.choices)

    class Meta:
        db_table = "operations_alarm_type_supported_device_type"
        ordering = ["data_snapshot", "alarm_type__code", "device_type"]
        verbose_name = "Alarm tipi cihaz türü"
        verbose_name_plural = "Alarm tipi cihaz türleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "alarm_type", "device_type"],
                name="unique_alarm_type_supported_device_type",
            )
        ]

    def clean(self):
        if (
            self.alarm_type_id
            and self.data_snapshot_id
            and self.alarm_type.data_snapshot_id != self.data_snapshot_id
        ):
            raise ValidationError(
                {"alarm_type": "Alarm type must belong to the same data snapshot."}
            )


class Alarm(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="alarms",
    )
    alarm_id = models.CharField(max_length=100)
    alarm_type = models.ForeignKey(AlarmType, on_delete=models.PROTECT, related_name="alarms")
    device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alarms",
    )
    network_link = models.ForeignKey(
        NetworkLink,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alarms",
    )
    network_port = models.ForeignKey(
        NetworkPort,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alarms",
    )
    line_connection = models.ForeignKey(
        LineConnection,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alarms",
    )
    failure_domain = models.ForeignKey(
        FailureDomain,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alarms",
    )
    subscription_connection = models.ForeignKey(
        "customers.SubscriptionConnection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alarms",
    )
    severity = models.CharField(max_length=24, choices=Severity.choices)
    status = models.CharField(max_length=24, choices=AlarmStatus.choices, default=AlarmStatus.OPEN)
    detected_at = models.DateTimeField()
    received_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    deduplication_key = models.CharField(max_length=180, blank=True)
    suppression_reason = models.CharField(max_length=160, blank=True)
    recurrence_group_key = models.CharField(max_length=180, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_alarm"
        ordering = ["data_snapshot", "-detected_at", "alarm_id"]
        verbose_name = "Alarm"
        verbose_name_plural = "Alarmlar"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "alarm_id"],
                name="unique_alarm_id_per_snapshot",
            ),
            models.UniqueConstraint(
                fields=["data_snapshot", "alarm_type", "deduplication_key"],
                condition=models.Q(status=AlarmStatus.OPEN) & ~models.Q(deduplication_key=""),
                name="unique_open_alarm_per_deduplication_key",
            ),
            models.CheckConstraint(
                condition=models.Q(cleared_at__isnull=True)
                | models.Q(cleared_at__gt=models.F("detected_at")),
                name="alarm_clear_time_after_detected_time",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(device__isnull=False)
                    & models.Q(network_link__isnull=True)
                    & models.Q(network_port__isnull=True)
                    & models.Q(line_connection__isnull=True)
                    & models.Q(failure_domain__isnull=True)
                    & models.Q(subscription_connection__isnull=True)
                )
                | (
                    models.Q(device__isnull=True)
                    & models.Q(network_link__isnull=False)
                    & models.Q(network_port__isnull=True)
                    & models.Q(line_connection__isnull=True)
                    & models.Q(failure_domain__isnull=True)
                    & models.Q(subscription_connection__isnull=True)
                )
                | (
                    models.Q(device__isnull=True)
                    & models.Q(network_link__isnull=True)
                    & models.Q(network_port__isnull=False)
                    & models.Q(line_connection__isnull=True)
                    & models.Q(failure_domain__isnull=True)
                    & models.Q(subscription_connection__isnull=True)
                )
                | (
                    models.Q(device__isnull=True)
                    & models.Q(network_link__isnull=True)
                    & models.Q(network_port__isnull=True)
                    & models.Q(line_connection__isnull=False)
                    & models.Q(failure_domain__isnull=True)
                    & models.Q(subscription_connection__isnull=True)
                )
                | (
                    models.Q(device__isnull=True)
                    & models.Q(network_link__isnull=True)
                    & models.Q(network_port__isnull=True)
                    & models.Q(line_connection__isnull=True)
                    & models.Q(failure_domain__isnull=False)
                    & models.Q(subscription_connection__isnull=True)
                )
                | (
                    models.Q(device__isnull=True)
                    & models.Q(network_link__isnull=True)
                    & models.Q(network_port__isnull=True)
                    & models.Q(line_connection__isnull=True)
                    & models.Q(failure_domain__isnull=True)
                    & models.Q(subscription_connection__isnull=False)
                ),
                name="alarm_has_exactly_one_source",
            ),
            models.CheckConstraint(
                condition=~models.Q(status=AlarmStatus.CLEARED)
                | models.Q(cleared_at__isnull=False),
                name="cleared_alarm_requires_cleared_at",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.alarm_id} - {self.source_label}"

    def clean(self):
        errors: dict[str, str] = {}
        source_kind = self.get_source_kind()
        if source_kind is None:
            errors["device"] = "Alarm must have exactly one structured source."
        if self.cleared_at and self.cleared_at <= self.detected_at:
            errors["cleared_at"] = "cleared_at must be later than detected_at."
        if self.status == AlarmStatus.CLEARED and not self.cleared_at:
            errors["cleared_at"] = "cleared_at is required for cleared alarms."
        if self.received_at and self.received_at < self.detected_at:
            errors["received_at"] = "received_at cannot be earlier than detected_at."
        if self.acknowledged_at and self.acknowledged_at < self.detected_at:
            errors["acknowledged_at"] = "acknowledged_at cannot be earlier than detected_at."
        if self.last_seen_at and self.last_seen_at < self.detected_at:
            errors["last_seen_at"] = "last_seen_at cannot be earlier than detected_at."
        if self.occurrence_count < 1:
            errors["occurrence_count"] = "occurrence_count must be at least 1."
        if (
            self.alarm_type_id
            and self.data_snapshot_id
            and self.alarm_type.data_snapshot_id != self.data_snapshot_id
        ):
            errors["alarm_type"] = "Alarm type must belong to the same data snapshot."
        source_errors = self._validate_source_snapshots()
        errors.update(source_errors)
        if self.alarm_type_id and source_kind:
            allowed_source_kinds = set(
                self.alarm_type.allowed_source_kinds.values_list("source_kind", flat=True)
            )
            if allowed_source_kinds and source_kind not in allowed_source_kinds:
                errors["alarm_type"] = (
                    f"Alarm type {self.alarm_type.code} does not support source kind {source_kind}."
                )
            source_device = self.get_source_device()
            supported_device_types = set(
                self.alarm_type.supported_device_types.values_list("device_type", flat=True)
            )
            if (
                supported_device_types
                and source_device
                and source_device.device_type not in supported_device_types
            ):
                errors["alarm_type"] = (
                    f"Alarm type {self.alarm_type.code} does not support device type "
                    f"{source_device.device_type}."
                )
        if errors:
            raise ValidationError(errors)

    @property
    def duration_seconds(self) -> int | None:
        return duration_seconds(self.detected_at, self.cleared_at)

    @property
    def source_label(self) -> str:
        source = self.get_source()
        if source is None:
            return "no-source"
        return (
            getattr(source, "code", None)
            or getattr(source, "link_code", None)
            or getattr(source, "port_code", None)
            or getattr(source, "line_code", None)
            or getattr(getattr(source, "subscription", None), "subscription_number", None)
            or str(source)
        )

    def get_source(self):
        for field_name in ALARM_SOURCE_FIELDS:
            source = getattr(self, field_name)
            if source is not None:
                return source
        return None

    def get_source_kind(self) -> str | None:
        filled = [
            source_kind
            for field_name, source_kind in ALARM_SOURCE_FIELDS.items()
            if getattr(self, f"{field_name}_id")
        ]
        if len(filled) != 1:
            return None
        return filled[0]

    def get_source_device(self) -> NetworkDevice | None:
        if self.device_id:
            return self.device
        if self.network_link_id:
            return self.network_link.source_device
        if self.network_port_id:
            return self.network_port.device
        if self.line_connection_id:
            return self.line_connection.port.device
        if self.subscription_connection_id:
            return self.subscription_connection.line_connection.port.device
        return None

    def _validate_source_snapshots(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        for field_name in ALARM_SOURCE_FIELDS:
            source = getattr(self, field_name)
            if (
                source is not None
                and self.data_snapshot_id
                and source.data_snapshot_id != self.data_snapshot_id
            ):
                errors[field_name] = f"{field_name} must belong to the same data snapshot."
        return errors

    def save(self, *args, **kwargs):
        if self._state.adding and self.status == AlarmStatus.OPEN and self.deduplication_key:
            existing = (
                Alarm.objects.filter(
                    data_snapshot=self.data_snapshot,
                    alarm_type=self.alarm_type,
                    deduplication_key=self.deduplication_key,
                    status=AlarmStatus.OPEN,
                )
                .order_by("detected_at", "alarm_id")
                .first()
            )
            if existing:
                existing.last_seen_at = self.last_seen_at or self.detected_at
                existing.occurrence_count += max(self.occurrence_count, 1)
                existing.raw_payload = self.raw_payload or existing.raw_payload
                existing.metadata = {**existing.metadata, **self.metadata}
                existing.full_clean()
                existing.save(
                    update_fields=[
                        "last_seen_at",
                        "occurrence_count",
                        "raw_payload",
                        "metadata",
                        "updated_at",
                    ]
                )
                self.pk = existing.pk
                self.id = existing.id
                self._state.adding = False
                return
        if self.last_seen_at is None:
            self.last_seen_at = self.detected_at
        if self.received_at is None:
            self.received_at = self.detected_at
        self.full_clean()
        super().save(*args, **kwargs)


class Incident(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="incidents",
    )
    incident_number = models.CharField(max_length=100)
    title = models.CharField(max_length=200)
    status = models.CharField(
        max_length=24,
        choices=IncidentStatus.choices,
        default=IncidentStatus.OPEN,
    )
    severity = models.CharField(max_length=24, choices=Severity.choices)
    incident_type = models.CharField(
        max_length=40,
        choices=IncidentType.choices,
        default=IncidentType.NETWORK_OUTAGE,
    )
    service_impact_class = models.CharField(
        max_length=40,
        choices=ServiceImpactClass.choices,
        default=ServiceImpactClass.UNKNOWN,
    )
    correlation_method = models.CharField(max_length=80, blank=True)
    failover_result = models.CharField(
        max_length=32,
        choices=FailoverResult.choices,
        default=FailoverResult.UNKNOWN,
    )
    transition_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    primary_device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.PROTECT,
        related_name="primary_incidents",
    )
    root_cause_category = models.CharField(
        max_length=40,
        choices=RootCauseCategory.choices,
        default=RootCauseCategory.UNKNOWN,
    )
    root_cause_summary = models.CharField(max_length=240, blank=True)
    detected_at = models.DateTimeField()
    started_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    restored_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_incident"
        ordering = ["data_snapshot", "-started_at", "incident_number"]
        verbose_name = "Olay"
        verbose_name_plural = "Olaylar"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "incident_number"],
                name="unique_incident_number_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(resolved_at__isnull=True)
                | models.Q(resolved_at__gt=models.F("started_at")),
                name="incident_resolved_after_started",
            ),
            models.CheckConstraint(
                condition=models.Q(closed_at__isnull=True)
                | models.Q(closed_at__gt=models.F("started_at")),
                name="incident_closed_after_started",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.incident_number} - {self.title}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.detected_at < self.started_at:
            errors["detected_at"] = "detected_at cannot be earlier than started_at."
        if self.resolved_at and self.resolved_at <= self.started_at:
            errors["resolved_at"] = "resolved_at must be later than started_at."
        if self.restored_at and self.restored_at < self.started_at:
            errors["restored_at"] = "restored_at cannot be earlier than started_at."
        if self.closed_at and self.closed_at <= self.started_at:
            errors["closed_at"] = "closed_at must be later than started_at."
        if (
            self.primary_device_id
            and self.data_snapshot_id
            and self.primary_device.data_snapshot_id != self.data_snapshot_id
        ):
            errors["primary_device"] = "Primary device must belong to the same data snapshot."
        if errors:
            raise ValidationError(errors)

    @property
    def duration_seconds(self) -> int | None:
        return duration_seconds(self.started_at, self.resolved_at)


class IncidentAlarm(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="incident_alarms",
    )
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="incident_alarms")
    alarm = models.ForeignKey(Alarm, on_delete=models.CASCADE, related_name="incident_alarms")
    role = models.CharField(
        max_length=24,
        choices=IncidentAlarmRole.choices,
        default=IncidentAlarmRole.CORRELATED,
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_incident_alarm"
        ordering = ["data_snapshot", "incident__incident_number", "alarm__alarm_id"]
        verbose_name = "Olay alarmı"
        verbose_name_plural = "Olay alarmları"
        constraints = [
            models.UniqueConstraint(
                fields=["incident", "alarm"],
                name="unique_alarm_per_incident",
            )
        ]

    def __str__(self) -> str:
        return f"{self.incident.incident_number} -> {self.alarm.alarm_id}"

    def clean(self):
        errors: dict[str, str] = {}
        if (
            self.incident_id
            and self.data_snapshot_id
            and self.incident.data_snapshot_id != self.data_snapshot_id
        ):
            errors["incident"] = "Incident must belong to the same data snapshot."
        if (
            self.alarm_id
            and self.data_snapshot_id
            and self.alarm.data_snapshot_id != self.data_snapshot_id
        ):
            errors["alarm"] = "Alarm must belong to the same data snapshot."
        if errors:
            raise ValidationError(errors)


class Outage(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="outages",
    )
    outage_code = models.CharField(max_length=100)
    incident = models.ForeignKey(
        Incident,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="outages",
    )
    source_device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.PROTECT,
        related_name="outages",
    )
    outage_type = models.CharField(max_length=24, choices=OutageType.choices)
    impact_type = models.CharField(
        max_length=40,
        choices=ServiceImpactClass.choices,
        default=ServiceImpactClass.FULL_OUTAGE,
    )
    status = models.CharField(
        max_length=24,
        choices=OutageStatus.choices,
        default=OutageStatus.OPEN,
    )
    root_cause_category = models.CharField(
        max_length=40,
        choices=RootCauseCategory.choices,
        default=RootCauseCategory.UNKNOWN,
    )
    root_cause_summary = models.CharField(max_length=240, blank=True)
    detected_at = models.DateTimeField()
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    restored_at = models.DateTimeField(null=True, blank=True)
    transition_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    impact_scope = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_outage"
        ordering = ["data_snapshot", "-started_at", "outage_code"]
        verbose_name = "Kesinti"
        verbose_name_plural = "Kesintiler"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "outage_code"],
                name="unique_outage_code_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True)
                | models.Q(ended_at__gt=models.F("started_at")),
                name="outage_end_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(resolved_at__isnull=True)
                | models.Q(resolved_at__gte=models.F("started_at")),
                name="outage_resolved_at_or_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.outage_code} - {self.source_device.code}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.detected_at < self.started_at:
            errors["detected_at"] = "detected_at cannot be earlier than started_at."
        if self.ended_at and self.ended_at <= self.started_at:
            errors["ended_at"] = "ended_at must be later than started_at."
        if self.resolved_at and self.resolved_at < self.started_at:
            errors["resolved_at"] = "resolved_at cannot be earlier than started_at."
        if self.restored_at and self.restored_at < self.started_at:
            errors["restored_at"] = "restored_at cannot be earlier than started_at."
        if self.impact_type not in {
            ServiceImpactClass.FULL_OUTAGE,
            ServiceImpactClass.PARTIAL_OUTAGE,
            ServiceImpactClass.SHORT_INTERRUPTION,
        }:
            errors["impact_type"] = (
                "Outage records are only allowed for full outage, partial outage, "
                "or short interruption impacts."
            )
        if (
            self.source_device_id
            and self.data_snapshot_id
            and self.source_device.data_snapshot_id != self.data_snapshot_id
        ):
            errors["source_device"] = "Source device must belong to the same data snapshot."
        if (
            self.incident_id
            and self.data_snapshot_id
            and self.incident.data_snapshot_id != self.data_snapshot_id
        ):
            errors["incident"] = "Incident must belong to the same data snapshot."
        if errors:
            raise ValidationError(errors)

    @property
    def duration_seconds(self) -> int | None:
        return duration_seconds(self.started_at, self.ended_at)


class OperationalEvent(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="operational_events",
    )
    event_code = models.CharField(max_length=100)
    event_type = models.CharField(max_length=40, choices=OperationalEventType.choices)
    occurred_at = models.DateTimeField()
    device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="operational_events",
    )
    incident = models.ForeignKey(
        Incident,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operational_events",
    )
    source = models.CharField(max_length=80, blank=True)
    summary = models.CharField(max_length=240)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_operational_event"
        ordering = ["data_snapshot", "-occurred_at", "event_code"]
        verbose_name = "Operasyon olayı"
        verbose_name_plural = "Operasyon olayları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "event_code"],
                name="unique_operational_event_code_per_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.event_code} - {self.get_event_type_display()}"

    def clean(self):
        errors: dict[str, str] = {}
        if (
            self.device_id
            and self.data_snapshot_id
            and self.device.data_snapshot_id != self.data_snapshot_id
        ):
            errors["device"] = "Device must belong to the same data snapshot."
        if (
            self.incident_id
            and self.data_snapshot_id
            and self.incident.data_snapshot_id != self.data_snapshot_id
        ):
            errors["incident"] = "Incident must belong to the same data snapshot."
        if errors:
            raise ValidationError(errors)


class QualityMeasurement(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="quality_measurements",
    )
    device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quality_measurements",
    )
    network_link = models.ForeignKey(
        NetworkLink,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quality_measurements",
    )
    line_connection = models.ForeignKey(
        LineConnection,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quality_measurements",
    )
    subscription_connection = models.ForeignKey(
        "customers.SubscriptionConnection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="quality_measurements",
    )
    metric_type = models.CharField(max_length=40, choices=QualityMetricType.choices)
    measured_at = models.DateTimeField()
    value = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=24)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_quality_measurement"
        ordering = ["data_snapshot", "-measured_at", "device__code", "metric_type"]
        verbose_name = "Kalite ölçümü"
        verbose_name_plural = "Kalite ölçümleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "device", "metric_type", "measured_at"],
                condition=models.Q(device__isnull=False),
                name="unique_quality_measurement_per_metric_time",
            ),
            models.UniqueConstraint(
                fields=["data_snapshot", "network_link", "metric_type", "measured_at"],
                condition=models.Q(network_link__isnull=False),
                name="unique_quality_measurement_per_link_metric_time",
            ),
            models.UniqueConstraint(
                fields=["data_snapshot", "line_connection", "metric_type", "measured_at"],
                condition=models.Q(line_connection__isnull=False),
                name="unique_quality_measurement_per_line_metric_time",
            ),
            models.UniqueConstraint(
                fields=[
                    "data_snapshot",
                    "subscription_connection",
                    "metric_type",
                    "measured_at",
                ],
                condition=models.Q(subscription_connection__isnull=False),
                name="unique_quality_measurement_per_sub_conn_metric_time",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(device__isnull=False)
                    & models.Q(network_link__isnull=True)
                    & models.Q(line_connection__isnull=True)
                    & models.Q(subscription_connection__isnull=True)
                )
                | (
                    models.Q(device__isnull=True)
                    & models.Q(network_link__isnull=False)
                    & models.Q(line_connection__isnull=True)
                    & models.Q(subscription_connection__isnull=True)
                )
                | (
                    models.Q(device__isnull=True)
                    & models.Q(network_link__isnull=True)
                    & models.Q(line_connection__isnull=False)
                    & models.Q(subscription_connection__isnull=True)
                )
                | (
                    models.Q(device__isnull=True)
                    & models.Q(network_link__isnull=True)
                    & models.Q(line_connection__isnull=True)
                    & models.Q(subscription_connection__isnull=False)
                ),
                name="quality_measurement_has_exactly_one_source",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_label} - {self.metric_type} @ {self.measured_at}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.get_source_kind() is None:
            errors["device"] = "Quality measurement must have exactly one structured source."
        for field_name in QUALITY_SOURCE_FIELDS:
            source = getattr(self, field_name)
            if (
                source is not None
                and self.data_snapshot_id
                and source.data_snapshot_id != self.data_snapshot_id
            ):
                errors[field_name] = f"{field_name} must belong to the same data snapshot."
        if self.value < Decimal("0.0000"):
            errors["value"] = "Quality measurement value cannot be negative."
        if errors:
            raise ValidationError(errors)

    @property
    def source_label(self) -> str:
        source = self.get_source()
        if source is None:
            return "no-source"
        return (
            getattr(source, "code", None)
            or getattr(source, "link_code", None)
            or getattr(
                source,
                "line_code",
                None,
            )
            or getattr(
                getattr(source, "subscription", None),
                "subscription_number",
                None,
            )
            or str(source)
        )

    def get_source(self):
        for field_name in QUALITY_SOURCE_FIELDS:
            source = getattr(self, field_name)
            if source is not None:
                return source
        return None

    def get_source_kind(self) -> str | None:
        filled = [
            source_kind
            for field_name, source_kind in QUALITY_SOURCE_FIELDS.items()
            if getattr(self, f"{field_name}_id")
        ]
        if len(filled) != 1:
            return None
        return filled[0]


class MaintenanceWindow(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="maintenance_windows",
    )
    reference_code = models.CharField(max_length=100)
    status = models.CharField(
        max_length=24,
        choices=MaintenanceWindowStatus.choices,
        default=MaintenanceWindowStatus.PLANNED,
    )
    planned_start_at = models.DateTimeField()
    planned_end_at = models.DateTimeField()
    actual_start_at = models.DateTimeField(null=True, blank=True)
    actual_end_at = models.DateTimeField(null=True, blank=True)
    expected_impact_class = models.CharField(
        max_length=40,
        choices=ServiceImpactClass.choices,
        default=ServiceImpactClass.NO_DIRECT_CUSTOMER_IMPACT,
    )
    actual_impact_class = models.CharField(
        max_length=40,
        choices=ServiceImpactClass.choices,
        default=ServiceImpactClass.UNKNOWN,
    )
    overrun_minutes = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    linked_incident = models.ForeignKey(
        Incident,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_windows",
    )

    class Meta:
        db_table = "operations_maintenance_window"
        ordering = ["data_snapshot", "planned_start_at", "reference_code"]
        verbose_name = "Bakım penceresi"
        verbose_name_plural = "Bakım pencereleri"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "reference_code"],
                name="unique_maintenance_window_reference_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(planned_end_at__gt=models.F("planned_start_at")),
                name="maintenance_planned_end_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(actual_end_at__isnull=True)
                | models.Q(actual_start_at__isnull=False),
                name="maintenance_actual_end_requires_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference_code} - {self.status}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.planned_end_at <= self.planned_start_at:
            errors["planned_end_at"] = "planned_end_at must be later than planned_start_at."
        if self.actual_end_at and not self.actual_start_at:
            errors["actual_start_at"] = "actual_start_at is required when actual_end_at is set."
        if (
            self.actual_start_at
            and self.actual_end_at
            and self.actual_end_at <= self.actual_start_at
        ):
            errors["actual_end_at"] = "actual_end_at must be later than actual_start_at."
        if (
            self.linked_incident_id
            and self.data_snapshot_id
            and self.linked_incident.data_snapshot_id != self.data_snapshot_id
        ):
            errors["linked_incident"] = "Linked incident must belong to the same data snapshot."
        if errors:
            raise ValidationError(errors)


class MaintenanceWindowDevice(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="maintenance_window_devices",
    )
    maintenance_window = models.ForeignKey(
        MaintenanceWindow,
        on_delete=models.CASCADE,
        related_name="device_scopes",
    )
    device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.CASCADE,
        related_name="maintenance_windows",
    )

    class Meta:
        db_table = "operations_maintenance_window_device"
        ordering = ["data_snapshot", "maintenance_window__reference_code", "device__code"]
        verbose_name = "Bakım cihaz kapsamı"
        verbose_name_plural = "Bakım cihaz kapsamları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "maintenance_window", "device"],
                name="unique_maintenance_window_device",
            )
        ]

    def clean(self):
        validate_maintenance_scope_snapshot(
            data_snapshot_id=self.data_snapshot_id,
            maintenance_window_snapshot_id=(
                self.maintenance_window.data_snapshot_id if self.maintenance_window_id else None
            ),
            target_snapshot_id=self.device.data_snapshot_id if self.device_id else None,
            target_field="device",
        )


class MaintenanceWindowNetworkLink(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="maintenance_window_network_links",
    )
    maintenance_window = models.ForeignKey(
        MaintenanceWindow,
        on_delete=models.CASCADE,
        related_name="network_link_scopes",
    )
    network_link = models.ForeignKey(
        NetworkLink,
        on_delete=models.CASCADE,
        related_name="maintenance_windows",
    )

    class Meta:
        db_table = "operations_maintenance_window_network_link"
        ordering = [
            "data_snapshot",
            "maintenance_window__reference_code",
            "network_link__link_code",
        ]
        verbose_name = "Bakım ağ bağlantısı kapsamı"
        verbose_name_plural = "Bakım ağ bağlantısı kapsamları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "maintenance_window", "network_link"],
                name="unique_maintenance_window_network_link",
            )
        ]

    def clean(self):
        validate_maintenance_scope_snapshot(
            data_snapshot_id=self.data_snapshot_id,
            maintenance_window_snapshot_id=(
                self.maintenance_window.data_snapshot_id if self.maintenance_window_id else None
            ),
            target_snapshot_id=(
                self.network_link.data_snapshot_id if self.network_link_id else None
            ),
            target_field="network_link",
        )


def validate_maintenance_scope_snapshot(
    *,
    data_snapshot_id: int | None,
    maintenance_window_snapshot_id: int | None,
    target_snapshot_id: int | None,
    target_field: str,
) -> None:
    errors: dict[str, str] = {}
    if (
        data_snapshot_id
        and maintenance_window_snapshot_id
        and maintenance_window_snapshot_id != data_snapshot_id
    ):
        errors["maintenance_window"] = "Maintenance window must belong to the same data snapshot."
    if data_snapshot_id and target_snapshot_id and target_snapshot_id != data_snapshot_id:
        errors[target_field] = "Maintenance scope target must belong to the same data snapshot."
    if errors:
        raise ValidationError(errors)


ALARM_SOURCE_FIELDS = {
    "device": AlarmSourceKind.DEVICE,
    "network_link": AlarmSourceKind.NETWORK_LINK,
    "network_port": AlarmSourceKind.NETWORK_PORT,
    "line_connection": AlarmSourceKind.LINE_CONNECTION,
    "failure_domain": AlarmSourceKind.FAILURE_DOMAIN,
    "subscription_connection": AlarmSourceKind.SUBSCRIPTION_CONNECTION,
}

QUALITY_SOURCE_FIELDS = {
    "device": AlarmSourceKind.DEVICE,
    "network_link": AlarmSourceKind.NETWORK_LINK,
    "line_connection": AlarmSourceKind.LINE_CONNECTION,
    "subscription_connection": AlarmSourceKind.SUBSCRIPTION_CONNECTION,
}
