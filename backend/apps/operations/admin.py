from django.contrib import admin

from apps.operations.models import (
    Alarm,
    AlarmType,
    AlarmTypeAllowedSourceKind,
    AlarmTypeSupportedDeviceType,
    CausalEvent,
    CustomerImpactAssessment,
    Incident,
    IncidentAlarm,
    MaintenanceWindow,
    MaintenanceWindowDevice,
    MaintenanceWindowNetworkLink,
    OperationalEvent,
    Outage,
    QualityMeasurement,
    SessionEvent,
)


@admin.register(AlarmType)
class AlarmTypeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "severity",
        "category",
        "service_impact_class",
        "correlation_family",
        "is_root_candidate",
        "data_snapshot",
    )
    list_filter = (
        "severity",
        "category",
        "service_impact_class",
        "auto_clear_policy",
        "default_incident_type",
        "is_root_candidate",
    )
    search_fields = ("code", "name", "description", "probable_cause_family")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot",)
    list_select_related = ("data_snapshot",)
    date_hierarchy = "created_at"


@admin.register(AlarmTypeAllowedSourceKind)
class AlarmTypeAllowedSourceKindAdmin(admin.ModelAdmin):
    list_display = ("alarm_type", "source_kind", "data_snapshot")
    list_filter = ("source_kind",)
    search_fields = ("alarm_type__code", "source_kind")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "alarm_type")
    list_select_related = ("data_snapshot", "alarm_type")


@admin.register(AlarmTypeSupportedDeviceType)
class AlarmTypeSupportedDeviceTypeAdmin(admin.ModelAdmin):
    list_display = ("alarm_type", "device_type", "data_snapshot")
    list_filter = ("device_type",)
    search_fields = ("alarm_type__code", "device_type")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "alarm_type")
    list_select_related = ("data_snapshot", "alarm_type")


@admin.register(CausalEvent)
class CausalEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_code",
        "event_type",
        "status",
        "source_system",
        "origin",
        "started_at",
        "ended_at",
        "data_snapshot",
    )
    list_filter = ("event_type", "status", "source_system", "origin")
    search_fields = ("event_code", "source_system", "metadata")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = (
        "data_snapshot",
        "root_device",
        "root_network_link",
        "root_network_port",
        "root_line_connection",
        "root_access_segment",
        "root_failure_domain",
        "root_subscription_connection",
    )
    list_select_related = ("data_snapshot",)
    date_hierarchy = "started_at"


@admin.register(Alarm)
class AlarmAdmin(admin.ModelAdmin):
    list_display = (
        "alarm_id",
        "alarm_type",
        "source_kind",
        "source_label",
        "severity",
        "status",
        "occurrence_count",
        "acknowledged_at",
        "detected_at",
        "last_seen_at",
        "data_snapshot",
    )
    list_filter = ("severity", "status", "alarm_type__category", "alarm_type__correlation_family")
    search_fields = (
        "alarm_id",
        "alarm_type__code",
        "device__code",
        "network_link__link_code",
        "network_port__port_code",
        "line_connection__line_code",
        "subscription_connection__subscription__subscription_number",
        "deduplication_key",
        "recurrence_group_key",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = (
        "data_snapshot",
        "causal_event",
        "alarm_type",
        "device",
        "network_link",
        "network_port",
        "line_connection",
        "failure_domain",
        "subscription_connection",
    )
    list_select_related = (
        "data_snapshot",
        "causal_event",
        "alarm_type",
        "device",
        "network_link",
        "network_port",
        "line_connection",
        "failure_domain",
        "subscription_connection",
    )
    date_hierarchy = "detected_at"

    @admin.display(description="Kaynak türü")
    def source_kind(self, obj: Alarm):
        return obj.get_source_kind()


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = (
        "incident_number",
        "title",
        "status",
        "severity",
        "incident_type",
        "service_impact_class",
        "failover_result",
        "primary_device",
        "root_cause_category",
        "started_at",
        "data_snapshot",
    )
    list_filter = (
        "status",
        "severity",
        "incident_type",
        "service_impact_class",
        "failover_result",
        "root_cause_category",
    )
    search_fields = ("incident_number", "title", "primary_device__code", "root_cause_summary")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "causal_event", "primary_device")
    list_select_related = ("data_snapshot", "causal_event", "primary_device")
    date_hierarchy = "started_at"


@admin.register(IncidentAlarm)
class IncidentAlarmAdmin(admin.ModelAdmin):
    list_display = ("incident", "alarm", "role", "data_snapshot")
    list_filter = ("role",)
    search_fields = ("incident__incident_number", "alarm__alarm_id")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "incident", "alarm")
    list_select_related = ("data_snapshot", "incident", "alarm")
    date_hierarchy = "created_at"


@admin.register(Outage)
class OutageAdmin(admin.ModelAdmin):
    list_display = (
        "outage_code",
        "source_device",
        "outage_type",
        "impact_type",
        "status",
        "root_cause_category",
        "started_at",
        "ended_at",
        "data_snapshot",
    )
    list_filter = ("outage_type", "impact_type", "status", "root_cause_category")
    search_fields = ("outage_code", "source_device__code", "root_cause_summary")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "causal_event", "incident", "source_device")
    list_select_related = ("data_snapshot", "causal_event", "incident", "source_device")
    date_hierarchy = "started_at"


@admin.register(OperationalEvent)
class OperationalEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_code",
        "event_type",
        "device",
        "incident",
        "occurred_at",
        "source",
        "data_snapshot",
    )
    list_filter = ("event_type", "source")
    search_fields = ("event_code", "summary", "device__code", "incident__incident_number")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "causal_event", "device", "incident")
    list_select_related = ("data_snapshot", "causal_event", "device", "incident")
    date_hierarchy = "occurred_at"


@admin.register(QualityMeasurement)
class QualityMeasurementAdmin(admin.ModelAdmin):
    list_display = (
        "source_kind",
        "source_label",
        "metric_type",
        "measured_at",
        "value",
        "unit",
        "data_snapshot",
    )
    list_filter = ("metric_type", "unit")
    search_fields = (
        "device__code",
        "network_link__link_code",
        "line_connection__line_code",
        "subscription_connection__subscription__subscription_number",
        "metric_type",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = (
        "data_snapshot",
        "causal_event",
        "device",
        "network_link",
        "line_connection",
        "subscription_connection",
    )
    list_select_related = (
        "data_snapshot",
        "causal_event",
        "device",
        "network_link",
        "line_connection",
        "subscription_connection",
    )
    date_hierarchy = "measured_at"

    @admin.display(description="Kaynak türü")
    def source_kind(self, obj: QualityMeasurement):
        return obj.get_source_kind()


@admin.register(SessionEvent)
class SessionEventAdmin(admin.ModelAdmin):
    list_display = (
        "external_event_id",
        "event_type",
        "source_system",
        "occurred_at",
        "received_at",
        "subscription",
        "subscription_connection",
        "data_snapshot",
    )
    list_filter = ("event_type", "source_system")
    search_fields = (
        "external_event_id",
        "source_system",
        "external_service_reference_hash",
        "nas_identifier",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = (
        "data_snapshot",
        "causal_event",
        "subscription",
        "subscription_connection",
    )
    list_select_related = (
        "data_snapshot",
        "causal_event",
        "subscription",
        "subscription_connection",
    )
    date_hierarchy = "occurred_at"


@admin.register(CustomerImpactAssessment)
class CustomerImpactAssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "causal_event",
        "status",
        "potential_impact",
        "subscription",
        "subscription_connection",
        "assessment_started_at",
        "data_snapshot",
    )
    list_filter = ("status", "potential_impact", "connection_role")
    search_fields = (
        "causal_event__event_code",
        "subscription__subscription_number",
        "subscription_connection__subscription__subscription_number",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = (
        "data_snapshot",
        "causal_event",
        "subscription",
        "subscription_connection",
    )
    list_select_related = (
        "data_snapshot",
        "causal_event",
        "subscription",
        "subscription_connection",
    )
    date_hierarchy = "assessment_started_at"


@admin.register(MaintenanceWindow)
class MaintenanceWindowAdmin(admin.ModelAdmin):
    list_display = (
        "reference_code",
        "status",
        "expected_impact_class",
        "actual_impact_class",
        "planned_start_at",
        "planned_end_at",
        "overrun_minutes",
        "linked_incident",
        "data_snapshot",
    )
    list_filter = ("status", "expected_impact_class", "actual_impact_class")
    search_fields = ("reference_code", "description", "linked_incident__incident_number")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "linked_incident")
    list_select_related = ("data_snapshot", "linked_incident")
    date_hierarchy = "planned_start_at"


@admin.register(MaintenanceWindowDevice)
class MaintenanceWindowDeviceAdmin(admin.ModelAdmin):
    list_display = ("maintenance_window", "device", "data_snapshot")
    search_fields = ("maintenance_window__reference_code", "device__code")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "maintenance_window", "device")
    list_select_related = ("data_snapshot", "maintenance_window", "device")


@admin.register(MaintenanceWindowNetworkLink)
class MaintenanceWindowNetworkLinkAdmin(admin.ModelAdmin):
    list_display = ("maintenance_window", "network_link", "data_snapshot")
    search_fields = ("maintenance_window__reference_code", "network_link__link_code")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "maintenance_window", "network_link")
    list_select_related = ("data_snapshot", "maintenance_window", "network_link")
