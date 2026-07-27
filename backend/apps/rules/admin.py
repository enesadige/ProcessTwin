from django.contrib import admin

from apps.rules.models import Rule, RuleChangeSet, RuleTestCase, RuleVersion


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "rule_type", "status", "data_snapshot")
    list_filter = ("rule_type", "status")
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot",)
    list_select_related = ("data_snapshot",)
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
        "valid_from",
        "valid_to",
        "change_set",
        "data_snapshot",
    )
    list_filter = ("status", "rule__rule_type")
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
