from django.contrib import admin

from apps.rules.models import Rule, RuleChangeSet, RuleSet, RuleTestCase, RuleVersion


@admin.register(RuleSet)
class RuleSetAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "version",
        "name",
        "active",
        "effective_from",
        "effective_to",
        "data_snapshot",
    )
    list_filter = ("active", "code")
    search_fields = ("code", "name", "change_reason")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot",)
    list_select_related = ("data_snapshot",)
    date_hierarchy = "effective_from"


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "rule_type",
        "family",
        "conflict_group",
        "rule_set",
        "status",
        "data_snapshot",
    )
    list_filter = ("rule_type", "family", "status", "rule_set")
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "rule_set")
    list_select_related = ("data_snapshot", "rule_set")
    date_hierarchy = "created_at"


@admin.register(RuleChangeSet)
class RuleChangeSetAdmin(admin.ModelAdmin):
    list_display = ("change_set_code", "title", "status", "approved_at", "data_snapshot")
    list_filter = ("status",)
    search_fields = ("change_set_code", "title", "reason")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "requested_by", "approved_by")
    list_select_related = ("data_snapshot", "requested_by", "approved_by")
    date_hierarchy = "created_at"


@admin.register(RuleVersion)
class RuleVersionAdmin(admin.ModelAdmin):
    list_display = (
        "rule",
        "version",
        "status",
        "priority",
        "action_type",
        "price_basis",
        "stackable",
        "active",
        "valid_from",
        "valid_to",
        "change_set",
        "data_snapshot",
    )
    list_filter = ("status", "action_type", "price_basis", "stackable", "active", "rule__rule_type")
    search_fields = ("rule__code", "rule__name", "version")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "rule", "change_set", "created_by")
    list_select_related = ("data_snapshot", "rule", "change_set", "created_by")
    date_hierarchy = "valid_from"


@admin.register(RuleTestCase)
class RuleTestCaseAdmin(admin.ModelAdmin):
    list_display = ("rule", "rule_version", "name", "status", "data_snapshot")
    list_filter = ("status", "rule__rule_type")
    search_fields = ("rule__code", "name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "rule", "rule_version")
    list_select_related = ("data_snapshot", "rule", "rule_version")
    date_hierarchy = "created_at"
