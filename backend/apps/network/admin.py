from django.contrib import admin

from apps.network.models import (
    AccessSegment,
    LineConnection,
    NetworkDevice,
    NetworkLink,
    NetworkPort,
)


@admin.register(NetworkDevice)
class NetworkDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "device_type",
        "inventory_status",
        "city",
        "district",
        "neighborhood",
        "data_snapshot",
    )
    list_filter = ("device_type", "inventory_status", "city", "district")
    search_fields = ("code", "name", "vendor", "model_name", "city__name", "district__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(NetworkPort)
class NetworkPortAdmin(admin.ModelAdmin):
    list_display = (
        "port_code",
        "device",
        "port_type",
        "inventory_status",
        "capacity_mbps",
        "data_snapshot",
    )
    list_filter = ("port_type", "inventory_status", "device__device_type")
    search_fields = ("port_code", "device__code", "device__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AccessSegment)
class AccessSegmentAdmin(admin.ModelAdmin):
    list_display = (
        "segment_code",
        "technology",
        "serving_device",
        "city",
        "district",
        "estimated_customer_count",
        "data_snapshot",
    )
    list_filter = ("technology", "city", "district")
    search_fields = (
        "segment_code",
        "name",
        "serving_device__code",
        "city__name",
        "district__name",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(LineConnection)
class LineConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "line_code",
        "port",
        "access_segment",
        "technology",
        "status",
        "is_active",
        "valid_from",
        "valid_to",
        "data_snapshot",
    )
    list_filter = ("technology", "status", "is_active")
    search_fields = (
        "line_code",
        "port__port_code",
        "port__device__code",
        "access_segment__segment_code",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(NetworkLink)
class NetworkLinkAdmin(admin.ModelAdmin):
    list_display = (
        "link_code",
        "source_device",
        "target_device",
        "status",
        "capacity_mbps",
        "data_snapshot",
    )
    list_filter = ("status", "source_device__device_type", "target_device__device_type")
    search_fields = ("link_code", "source_device__code", "target_device__code")
    readonly_fields = ("created_at", "updated_at")
