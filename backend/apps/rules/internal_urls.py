from django.urls import path

from apps.rules import internal_views

app_name = "rules_internal"

urlpatterns = [
    path("", internal_views.search_rules, name="search-rules"),
    path("effective-at/", internal_views.get_rules_effective_at, name="rules-effective-at"),
    path("related/", internal_views.find_related_rules, name="find-related-rules"),
    path("conflicts/", internal_views.detect_rule_conflicts, name="detect-rule-conflicts"),
    path("evidence/", internal_views.get_rule_evidence, name="rule-evidence"),
    path("<str:rule_code>/", internal_views.get_rule, name="get-rule"),
    path(
        "<str:rule_code>/versions/",
        internal_views.get_rule_version_history,
        name="rule-version-history",
    ),
]
