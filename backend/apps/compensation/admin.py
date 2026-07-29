from django.contrib import admin

from apps.compensation.models import CompensationEvaluation, DecisionEvidence


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


@admin.register(DecisionEvidence)
class DecisionEvidenceAdmin(admin.ModelAdmin):
    list_display = (
        "decision",
        "selected_rule_version",
        "rule_set",
        "price_basis",
        "final_amount",
        "currency",
        "finalized",
        "data_snapshot",
    )
    list_filter = ("decision", "price_basis", "currency", "finalized")
    search_fields = ("evidence_hash", "selected_rule_version__rule__code", "rule_set__code")
    readonly_fields = ("created_at", "updated_at", "evidence_hash")
    autocomplete_fields = (
        "data_snapshot",
        "compensation_evaluation",
        "rule_set",
        "selected_rule_version",
    )
    list_select_related = (
        "data_snapshot",
        "compensation_evaluation",
        "rule_set",
        "selected_rule_version",
    )
    date_hierarchy = "created_at"
