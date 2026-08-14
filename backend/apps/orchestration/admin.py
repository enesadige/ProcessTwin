from django.contrib import admin

from apps.orchestration.models import (
    TERMINAL_QUERY_RUN_STATUSES,
    EvidenceCalculation,
    EvidenceRAGReference,
    EvidenceRecord,
    EvidenceRuleReference,
    EvidenceToolCall,
    QueryRun,
)


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


class EvidenceToolCallInline(admin.TabularInline):
    model = EvidenceToolCall
    extra = 0
    readonly_fields = ("created_at", "updated_at")


class EvidenceRuleReferenceInline(admin.TabularInline):
    model = EvidenceRuleReference
    extra = 0
    readonly_fields = ("created_at", "updated_at")


class EvidenceCalculationInline(admin.TabularInline):
    model = EvidenceCalculation
    extra = 0
    readonly_fields = ("created_at", "updated_at")


class EvidenceRAGReferenceInline(admin.TabularInline):
    model = EvidenceRAGReference
    extra = 0
    readonly_fields = ("created_at", "updated_at")


@admin.register(EvidenceRecord)
class EvidenceRecordAdmin(admin.ModelAdmin):
    list_display = ("evidence_code", "query_run", "data_snapshot", "finalized", "finalized_at")
    list_filter = ("finalized",)
    search_fields = ("evidence_code", "query_run__query_run_code")
    readonly_fields = ("created_at", "updated_at", "finalized_at")
    autocomplete_fields = ("data_snapshot", "query_run")
    list_select_related = ("data_snapshot", "query_run")
    inlines = (
        EvidenceToolCallInline,
        EvidenceRuleReferenceInline,
        EvidenceCalculationInline,
        EvidenceRAGReferenceInline,
    )

    def has_change_permission(self, request, obj=None):
        if obj and obj.finalized:
            return False
        return super().has_change_permission(request, obj=obj)
