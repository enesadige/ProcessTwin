from django.contrib import admin

from apps.network.models import AccessSegment, NetworkDevice, NetworkLink


@admin.register(NetworkDevice)
class NetworkDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "device_type",
        "status",
        "city",
        "district",
        "neighborhood",
        "data_snapshot",
    )
    list_filter = ("device_type", "status", "city", "district")
    search_fields = ("code", "name", "vendor", "model_name", "city__name", "district__name")
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
