from django.contrib import admin

from apps.orchestration.models import TERMINAL_QUERY_RUN_STATUSES, QueryRun


@admin.register(QueryRun)
class QueryRunAdmin(admin.ModelAdmin):
    list_display = (
        "query_run_code",
        "status",
        "data_snapshot",
        "request_id",
        "created_at",
        "completed_at",
    )
    list_filter = ("status",)
    search_fields = ("query_run_code", "request_id", "idempotency_key")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "retry_of")
    list_select_related = ("data_snapshot", "retry_of")

    def has_change_permission(self, request, obj=None):
        if obj and obj.status in TERMINAL_QUERY_RUN_STATUSES:
            return False
        return super().has_change_permission(request, obj=obj)
