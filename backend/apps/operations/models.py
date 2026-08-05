from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.datasets.models import DataSnapshot
from apps.network.models import (
    AccessSegment,
    FailureDomain,
    LineConnection,
    NetworkDevice,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
)
from apps.operations.contracts import (
    CausalEventStatus,
    CausalEventType,
    CustomerImpactStatus,
    EventOrigin,
    ImpactReason,
    ResourceType,
    SessionEventType,
)


def contract_choices(enum_cls):
    return [(member.value, member.value.replace("_", " ").title()) for member in enum_cls]


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


def validate_aware_datetimes(errors: dict[str, str], **values) -> None:
    for field_name, value in values.items():
        if value is not None and timezone.is_naive(value):
            errors[field_name] = f"{field_name} must be timezone-aware."


CAUSAL_ROOT_RESOURCE_FIELDS = {
    "root_device": ResourceType.DEVICE.value,
    "root_network_link": ResourceType.NETWORK_LINK.value,
    "root_network_port": ResourceType.NETWORK_PORT.value,
    "root_line_connection": ResourceType.LINE_CONNECTION.value,
    "root_access_segment": ResourceType.ACCESS_SEGMENT.value,
    "root_failure_domain": ResourceType.FAILURE_DOMAIN.value,
    "root_subscription_connection": ResourceType.SUBSCRIPTION_CONNECTION.value,
}


def zero_or_one_root_resource_condition() -> models.Q:
    conditions = [
        models.Q(**{f"{field_name}__isnull": True for field_name in CAUSAL_ROOT_RESOURCE_FIELDS})
    ]
    for selected_field in CAUSAL_ROOT_RESOURCE_FIELDS:
        condition = models.Q(**{f"{selected_field}__isnull": False})
        for other_field in CAUSAL_ROOT_RESOURCE_FIELDS:
            if other_field != selected_field:
                condition &= models.Q(**{f"{other_field}__isnull": True})
        conditions.append(condition)
    combined = conditions[0]
    for condition in conditions[1:]:
        combined |= condition
    return combined


class CausalEvent(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="causal_events",
    )
    event_code = models.CharField(max_length=120)
    event_type = models.CharField(max_length=40, choices=contract_choices(CausalEventType))
    status = models.CharField(
        max_length=24,
        choices=contract_choices(CausalEventStatus),
        default=CausalEventStatus.DETECTED.value,
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    source_system = models.CharField(max_length=80)
    origin = models.CharField(
        max_length=24,
        choices=contract_choices(EventOrigin),
        default=EventOrigin.SYNTHETIC.value,
    )
    root_device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="root_causal_events",
    )
    root_network_link = models.ForeignKey(
        NetworkLink,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="root_causal_events",
    )
    root_network_port = models.ForeignKey(
        NetworkPort,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="root_causal_events",
    )
    root_line_connection = models.ForeignKey(
        LineConnection,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="root_causal_events",
    )
    root_access_segment = models.ForeignKey(
        AccessSegment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="root_causal_events",
    )
    root_failure_domain = models.ForeignKey(
        FailureDomain,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="root_causal_events",
    )
    root_subscription_connection = models.ForeignKey(
        "customers.SubscriptionConnection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="root_causal_events",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_causal_event"
        ordering = ["data_snapshot", "-started_at", "event_code"]
        verbose_name = "Nedensel operasyon olayı"
        verbose_name_plural = "Nedensel operasyon olayları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "event_code"],
                name="unique_causal_event_code_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True)
                | models.Q(ended_at__gte=models.F("started_at")),
                name="causal_event_end_at_or_after_start",
            ),
            models.CheckConstraint(
                condition=~models.Q(
                    status__in=[
                        CausalEventStatus.RESOLVED.value,
                        CausalEventStatus.CLOSED.value,
                        CausalEventStatus.CANCELLED.value,
                    ]
                )
                | models.Q(ended_at__isnull=False),
                name="causal_event_terminal_status_requires_end",
            ),
            models.CheckConstraint(
                condition=zero_or_one_root_resource_condition(),
                name="causal_event_has_zero_or_one_root_resource",
            ),
        ]
        indexes = [
            models.Index(
                fields=["data_snapshot", "event_type", "status"],
                name="causal_evt_type_status_idx",
            ),
            models.Index(
                fields=["data_snapshot", "started_at"],
                name="causal_evt_snapshot_start_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_code} - {self.event_type}"

    def clean(self):
        errors: dict[str, str] = {}
        validate_aware_datetimes(errors, started_at=self.started_at, ended_at=self.ended_at)
        if (
            self.ended_at
            and "started_at" not in errors
            and "ended_at" not in errors
            and self.ended_at < self.started_at
        ):
            errors["ended_at"] = "ended_at cannot be earlier than started_at."
        if (
            self.status
            in {
                CausalEventStatus.RESOLVED.value,
                CausalEventStatus.CLOSED.value,
                CausalEventStatus.CANCELLED.value,
            }
            and not self.ended_at
        ):
            errors["ended_at"] = "Terminal causal event statuses require ended_at."
        if self.get_root_resource_kind() is False:
            errors["root_device"] = "Causal event can have at most one root resource."
        errors.update(self._validate_root_resource_snapshots())
        if errors:
            raise ValidationError(errors)

    def get_root_resource(self):
        for field_name in CAUSAL_ROOT_RESOURCE_FIELDS:
            source = getattr(self, field_name)
            if source is not None:
                return source
        return None

    def get_root_resource_kind(self) -> str | None | bool:
        filled = [
            resource_type
            for field_name, resource_type in CAUSAL_ROOT_RESOURCE_FIELDS.items()
            if getattr(self, f"{field_name}_id")
        ]
        if len(filled) > 1:
            return False
        return filled[0] if filled else None

    @property
    def root_resource_code(self) -> str | None:
        source = self.get_root_resource()
        if source is None:
            return None
        return (
            getattr(source, "code", None)
            or getattr(source, "link_code", None)
            or getattr(source, "port_code", None)
            or getattr(source, "line_code", None)
            or getattr(source, "segment_code", None)
            or getattr(getattr(source, "subscription", None), "subscription_number", None)
            or str(source)
        )

    def _validate_root_resource_snapshots(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        for field_name in CAUSAL_ROOT_RESOURCE_FIELDS:
            source = getattr(self, field_name)
            if (
                source is not None
                and self.data_snapshot_id
                and source.data_snapshot_id != self.data_snapshot_id
            ):
                errors[field_name] = f"{field_name} must belong to the same data snapshot."
        return errors


class SessionEvent(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="session_events",
    )
    causal_event = models.ForeignKey(
        CausalEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="session_events",
    )
    external_event_id = models.CharField(max_length=160, blank=True)
    event_type = models.CharField(max_length=16, choices=contract_choices(SessionEventType))
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(null=True, blank=True)
    source_system = models.CharField(max_length=80)
    subscription = models.ForeignKey(
        "customers.Subscription",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="session_events",
    )
    subscription_connection = models.ForeignKey(
        "customers.SubscriptionConnection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="session_events",
    )
    external_service_reference_hash = models.CharField(max_length=128, blank=True)
    nas_identifier = models.CharField(max_length=120, blank=True)
    service_identifier_hash = models.CharField(max_length=128, blank=True)
    session_identifier_hash = models.CharField(max_length=128, blank=True)
    subscriber_reference_hash = models.CharField(max_length=128, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_session_event"
        ordering = ["data_snapshot", "occurred_at", "external_event_id"]
        verbose_name = "Session kanıt olayı"
        verbose_name_plural = "Session kanıt olayları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "source_system", "external_event_id"],
                condition=~models.Q(external_event_id=""),
                name="unique_session_source_event_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(received_at__isnull=True)
                | models.Q(received_at__gte=models.F("occurred_at")),
                name="session_event_received_at_or_after_occurred",
            ),
            models.CheckConstraint(
                condition=models.Q(subscription__isnull=False)
                | models.Q(subscription_connection__isnull=False)
                | ~models.Q(external_service_reference_hash=""),
                name="session_event_has_identity_reference",
            ),
        ]
        indexes = [
            models.Index(
                fields=["data_snapshot", "event_type", "occurred_at"],
                name="session_evt_type_time_idx",
            ),
            models.Index(
                fields=["data_snapshot", "subscription_connection", "occurred_at"],
                name="session_evt_conn_time_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_system}:{self.external_event_id or self.pk} - {self.event_type}"

    def clean(self):
        errors: dict[str, str] = {}
        validate_aware_datetimes(
            errors,
            occurred_at=self.occurred_at,
            received_at=self.received_at,
        )
        if (
            self.received_at
            and "occurred_at" not in errors
            and "received_at" not in errors
            and self.received_at < self.occurred_at
        ):
            errors["received_at"] = "received_at cannot be earlier than occurred_at."
        if (
            not self.subscription_id
            and not self.subscription_connection_id
            and not self.external_service_reference_hash
        ):
            errors["subscription"] = (
                "Session event requires a subscription, connection, or hashed service reference."
            )
        for field_name in ("causal_event", "subscription", "subscription_connection"):
            related = getattr(self, field_name)
            if (
                related is not None
                and self.data_snapshot_id
                and related.data_snapshot_id != self.data_snapshot_id
            ):
                errors[field_name] = f"{field_name} must belong to the same data snapshot."
        if errors:
            raise ValidationError(errors)

    def to_public_dict(self) -> dict:
        return {
            "external_event_id": self.external_event_id or None,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "source_system": self.source_system,
            "subscription_code": (
                self.subscription.subscription_number if self.subscription_id else None
            ),
            "subscription_connection_code": (
                self.subscription_connection.subscription.subscription_number
                if self.subscription_connection_id
                else None
            ),
            "nas_identifier": self.nas_identifier or None,
        }


class CustomerImpactAssessment(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="customer_impact_assessments",
    )
    causal_event = models.ForeignKey(
        CausalEvent,
        on_delete=models.PROTECT,
        related_name="customer_impact_assessments",
    )
    subscription = models.ForeignKey(
        "customers.Subscription",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="impact_assessments",
    )
    subscription_connection = models.ForeignKey(
        "customers.SubscriptionConnection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="impact_assessments",
    )
    status = models.CharField(max_length=32, choices=contract_choices(CustomerImpactStatus))
    potential_impact = models.BooleanField(default=True)
    connection_role = models.CharField(max_length=32, blank=True)
    assessment_started_at = models.DateTimeField()
    assessment_ended_at = models.DateTimeField(null=True, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    evidence_session_event_codes = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "operations_customer_impact_assessment"
        ordering = ["data_snapshot", "causal_event__event_code", "subscription_connection_id"]
        verbose_name = "Müşteri etki değerlendirmesi"
        verbose_name_plural = "Müşteri etki değerlendirmeleri"
        constraints = [
            models.UniqueConstraint(
                fields=["causal_event", "subscription_connection"],
                condition=models.Q(subscription_connection__isnull=False),
                name="unique_impact_assessment_per_event_connection",
            ),
            models.UniqueConstraint(
                fields=["causal_event", "subscription"],
                condition=models.Q(
                    subscription__isnull=False,
                    subscription_connection__isnull=True,
                ),
                name="unique_impact_assessment_per_event_subscription",
            ),
            models.CheckConstraint(
                condition=models.Q(assessment_ended_at__isnull=True)
                | models.Q(assessment_ended_at__gte=models.F("assessment_started_at")),
                name="impact_assessment_end_at_or_after_start",
            ),
            models.CheckConstraint(
                condition=~models.Q(
                    status__in=[
                        CustomerImpactStatus.VERIFIED_IMPACT.value,
                        CustomerImpactStatus.VERIFIED_NO_IMPACT.value,
                        CustomerImpactStatus.INSUFFICIENT_EVIDENCE.value,
                    ]
                )
                | models.Q(potential_impact=True),
                name="impact_assessment_verified_requires_potential",
            ),
            models.CheckConstraint(
                condition=~models.Q(status=CustomerImpactStatus.POTENTIAL_IMPACT.value)
                | models.Q(potential_impact=True),
                name="impact_assessment_potential_status_requires_flag",
            ),
            models.CheckConstraint(
                condition=models.Q(subscription__isnull=False)
                | models.Q(subscription_connection__isnull=False),
                name="impact_assessment_has_subscription_or_connection",
            ),
        ]
        indexes = [
            models.Index(
                fields=["data_snapshot", "status"],
                name="impact_assessment_status_idx",
            ),
            models.Index(
                fields=["data_snapshot", "assessment_started_at"],
                name="impact_assessment_start_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.causal_event.event_code} - {self.status}"

    def clean(self):
        errors: dict[str, str] = {}
        validate_aware_datetimes(
            errors,
            assessment_started_at=self.assessment_started_at,
            assessment_ended_at=self.assessment_ended_at,
        )
        if (
            self.assessment_ended_at
            and "assessment_started_at" not in errors
            and "assessment_ended_at" not in errors
            and self.assessment_ended_at < self.assessment_started_at
        ):
            errors["assessment_ended_at"] = (
                "assessment_ended_at cannot be earlier than assessment_started_at."
            )
        if not self.subscription_id and not self.subscription_connection_id:
            errors["subscription"] = "Assessment requires a subscription or connection."
        if (
            self.status
            in {
                CustomerImpactStatus.VERIFIED_IMPACT.value,
                CustomerImpactStatus.VERIFIED_NO_IMPACT.value,
                CustomerImpactStatus.INSUFFICIENT_EVIDENCE.value,
            }
            and not self.potential_impact
        ):
            errors["potential_impact"] = (
                "Verified and insufficient assessments must originate from potential impact."
            )
        if (
            self.status == CustomerImpactStatus.POTENTIAL_IMPACT.value
            and not self.potential_impact
        ):
            errors["potential_impact"] = "potential_impact status requires potential_impact=true."
        normalized_reasons = self._validated_reasons()
        if (
            self.status == CustomerImpactStatus.VERIFIED_NO_IMPACT.value
            and not normalized_reasons
        ):
            errors["reasons"] = "Verified no-impact requires at least one reason."
        for field_name in ("causal_event", "subscription", "subscription_connection"):
            related = getattr(self, field_name)
            if (
                related is not None
                and self.data_snapshot_id
                and related.data_snapshot_id != self.data_snapshot_id
            ):
                errors[field_name] = f"{field_name} must belong to the same data snapshot."
        if self.subscription_connection_id and self.subscription_id:
            if self.subscription_connection.subscription_id != self.subscription_id:
                errors["subscription_connection"] = (
                    "Subscription connection must belong to the selected subscription."
                )
        if errors:
            raise ValidationError(errors)

    def _validated_reasons(self) -> list[str]:
        if not isinstance(self.reasons, list):
            raise ValidationError({"reasons": "reasons must be a list."})
        valid_values = {reason.value for reason in ImpactReason}
        invalid = [reason for reason in self.reasons if reason not in valid_values]
        if invalid:
            raise ValidationError({"reasons": f"Invalid impact reasons: {invalid}."})
        return self.reasons

    def to_public_dict(self) -> dict:
        return {
            "causal_event_code": self.causal_event.event_code,
            "status": self.status,
            "potential_impact": self.potential_impact,
            "subscription_code": (
                self.subscription.subscription_number if self.subscription_id else None
            ),
            "subscription_connection_code": (
                self.subscription_connection.subscription.subscription_number
                if self.subscription_connection_id
                else None
            ),
            "connection_role": self.connection_role or None,
            "assessment_started_at": self.assessment_started_at.isoformat(),
            "assessment_ended_at": (
                self.assessment_ended_at.isoformat() if self.assessment_ended_at else None
            ),
            "reasons": list(self.reasons),
            "evidence_session_event_codes": sorted(set(self.evidence_session_event_codes)),
        }


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
    causal_event = models.ForeignKey(
        CausalEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
        if (
            self.causal_event_id
            and self.data_snapshot_id
            and self.causal_event.data_snapshot_id != self.data_snapshot_id
        ):
            errors["causal_event"] = "Causal event must belong to the same data snapshot."
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
    causal_event = models.ForeignKey(
        CausalEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
        if (
            self.causal_event_id
            and self.data_snapshot_id
            and self.causal_event.data_snapshot_id != self.data_snapshot_id
        ):
            errors["causal_event"] = "Causal event must belong to the same data snapshot."
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
    causal_event = models.ForeignKey(
        CausalEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
        if (
            self.causal_event_id
            and self.data_snapshot_id
            and self.causal_event.data_snapshot_id != self.data_snapshot_id
        ):
            errors["causal_event"] = "Causal event must belong to the same data snapshot."
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
    causal_event = models.ForeignKey(
        CausalEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
        if (
            self.causal_event_id
            and self.data_snapshot_id
            and self.causal_event.data_snapshot_id != self.data_snapshot_id
        ):
            errors["causal_event"] = "Causal event must belong to the same data snapshot."
        if errors:
            raise ValidationError(errors)


class QualityMeasurement(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="quality_measurements",
    )
    causal_event = models.ForeignKey(
        CausalEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
        if (
            self.causal_event_id
            and self.data_snapshot_id
            and self.causal_event.data_snapshot_id != self.data_snapshot_id
        ):
            errors["causal_event"] = "Causal event must belong to the same data snapshot."
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
