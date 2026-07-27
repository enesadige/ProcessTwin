from django.contrib import admin

from apps.compensation.models import CompensationEvaluation


@admin.register(CompensationEvaluation)
class CompensationEvaluationAdmin(admin.ModelAdmin):
    list_display = (
        "evaluation_code",
        "outage",
        "customer",
        "subscription",
        "rule_version",
        "result_type",
        "status",
        "proposed_amount",
        "currency",
        "data_snapshot",
    )
    list_filter = ("result_type", "status", "currency")
    search_fields = (
        "evaluation_code",
        "outage__outage_code",
        "customer__customer_number",
        "subscription__subscription_number",
        "rule_version__rule__code",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "outage", "customer", "subscription", "rule_version")
    list_select_related = ("data_snapshot", "outage", "customer", "subscription", "rule_version")
    date_hierarchy = "created_at"
