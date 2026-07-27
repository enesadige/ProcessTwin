from django.contrib import admin

from apps.datasets.models import DatasetVersion, DataSnapshot


@admin.register(DatasetVersion)
class DatasetVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "generator_version", "seed", "created_at")
    list_filter = ("kind", "generator_version")
    search_fields = ("name", "slug", "seed", "generator_version")
    readonly_fields = ("created_at", "updated_at")


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
