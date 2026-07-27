from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel
from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice


class Severity(models.TextChoices):
    INFO = "info", "Info"
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


class QualityMetricType(models.TextChoices):
    LATENCY_MS = "latency_ms", "Latency ms"
    JITTER_MS = "jitter_ms", "Jitter ms"
    PACKET_LOSS_PERCENT = "packet_loss_percent", "Packet loss percent"
    AVAILABILITY_PERCENT = "availability_percent", "Availability percent"


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
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_alarm_type"
        ordering = ["data_snapshot", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "code"],
                name="unique_alarm_type_code_per_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Alarm(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="alarms",
    )
    alarm_id = models.CharField(max_length=100)
    alarm_type = models.ForeignKey(AlarmType, on_delete=models.PROTECT, related_name="alarms")
    device = models.ForeignKey(NetworkDevice, on_delete=models.PROTECT, related_name="alarms")
    severity = models.CharField(max_length=24, choices=Severity.choices)
    status = models.CharField(max_length=24, choices=AlarmStatus.choices, default=AlarmStatus.OPEN)
    detected_at = models.DateTimeField()
    cleared_at = models.DateTimeField(null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_alarm"
        ordering = ["data_snapshot", "-detected_at", "alarm_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "alarm_id"],
                name="unique_alarm_id_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(cleared_at__isnull=True)
                | models.Q(cleared_at__gt=models.F("detected_at")),
                name="alarm_clear_time_after_detected_time",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.alarm_id} - {self.device.code}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.cleared_at and self.cleared_at <= self.detected_at:
            errors["cleared_at"] = "cleared_at must be later than detected_at."
        if (
            self.alarm_type_id
            and self.data_snapshot_id
            and self.alarm_type.data_snapshot_id != self.data_snapshot_id
        ):
            errors["alarm_type"] = "Alarm type must belong to the same data snapshot."
        if (
            self.device_id
            and self.data_snapshot_id
            and self.device.data_snapshot_id != self.data_snapshot_id
        ):
            errors["device"] = "Device must belong to the same data snapshot."
        if errors:
            raise ValidationError(errors)

    @property
    def duration_seconds(self) -> int | None:
        return duration_seconds(self.detected_at, self.cleared_at)


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
    closed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_incident"
        ordering = ["data_snapshot", "-started_at", "incident_number"]
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
    impact_scope = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_outage"
        ordering = ["data_snapshot", "-started_at", "outage_code"]
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
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "device", "metric_type", "measured_at"],
                name="unique_quality_measurement_per_metric_time",
            )
        ]

    def __str__(self) -> str:
        return f"{self.device.code} - {self.metric_type} @ {self.measured_at}"

    def clean(self):
        if self.device_id and self.device.data_snapshot_id != self.data_snapshot_id:
            raise ValidationError({"device": "Device must belong to the same data snapshot."})
        if self.value < Decimal("0.0000"):
            raise ValidationError({"value": "Quality measurement value cannot be negative."})
