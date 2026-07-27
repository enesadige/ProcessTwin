from django.contrib import admin

from apps.operations.models import (
    Alarm,
    AlarmType,
    Incident,
    IncidentAlarm,
    OperationalEvent,
    Outage,
    QualityMeasurement,
)


@admin.register(AlarmType)
class AlarmTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "severity", "category", "data_snapshot")
    list_filter = ("severity", "category")
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot",)
    list_select_related = ("data_snapshot",)
    date_hierarchy = "created_at"


@admin.register(Alarm)
class AlarmAdmin(admin.ModelAdmin):
    list_display = (
        "alarm_id",
        "alarm_type",
        "device",
        "severity",
        "status",
        "detected_at",
        "data_snapshot",
    )
    list_filter = ("severity", "status", "alarm_type__category")
    search_fields = ("alarm_id", "alarm_type__code", "device__code")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "alarm_type", "device")
    list_select_related = ("data_snapshot", "alarm_type", "device")
    date_hierarchy = "detected_at"


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = (
        "incident_number",
        "title",
        "status",
        "severity",
        "primary_device",
        "root_cause_category",
        "started_at",
        "data_snapshot",
    )
    list_filter = ("status", "severity", "root_cause_category")
    search_fields = ("incident_number", "title", "primary_device__code", "root_cause_summary")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "primary_device")
    list_select_related = ("data_snapshot", "primary_device")
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
        "status",
        "root_cause_category",
        "started_at",
        "ended_at",
        "data_snapshot",
    )
    list_filter = ("outage_type", "status", "root_cause_category")
    search_fields = ("outage_code", "source_device__code", "root_cause_summary")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "incident", "source_device")
    list_select_related = ("data_snapshot", "incident", "source_device")
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
    autocomplete_fields = ("data_snapshot", "device", "incident")
    list_select_related = ("data_snapshot", "device", "incident")
    date_hierarchy = "occurred_at"


@admin.register(QualityMeasurement)
class QualityMeasurementAdmin(admin.ModelAdmin):
    list_display = ("device", "metric_type", "measured_at", "value", "unit", "data_snapshot")
    list_filter = ("metric_type", "unit")
    search_fields = ("device__code", "metric_type")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "device")
    list_select_related = ("data_snapshot", "device")
    date_hierarchy = "measured_at"
