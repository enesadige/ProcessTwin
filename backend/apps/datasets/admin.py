from django.contrib import admin

from apps.datasets.models import DatasetVersion, DataSnapshot, GroundTruthCase


@admin.register(DatasetVersion)
class DatasetVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "generator_version", "seed", "created_at")
    list_filter = ("kind", "generator_version")
    search_fields = ("name", "slug", "seed", "generator_version")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(DataSnapshot)
class DataSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "dataset_version",
        "status",
        "is_active",
        "validation_status",
        "created_at",
    )
    list_filter = ("status", "is_active", "validation_status")
    search_fields = ("name", "snapshot_key", "dataset_version__name", "dataset_version__slug")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("dataset_version",)
    list_select_related = ("dataset_version",)
    date_hierarchy = "created_at"


@admin.register(GroundTruthCase)
class GroundTruthCaseAdmin(admin.ModelAdmin):
    list_display = (
        "case_code",
        "outage_code",
        "expected_source_device_code",
        "expected_eligibility",
        "affected_subscription_count",
        "affected_customer_count",
        "expected_total_refund_amount",
        "currency",
    )
    list_filter = ("expected_eligibility", "currency")
    search_fields = (
        "case_code",
        "outage_code",
        "expected_source_device_code",
        "expected_incident_code",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot",)
    list_select_related = ("data_snapshot",)
