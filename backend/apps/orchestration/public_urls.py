from django.urls import path

from apps.orchestration.public_views import (
    analysis_status,
    decision_evidence_detail,
    execute_authenticated_query,
    topology_summary,
)

urlpatterns = [
    path("queries/execute/", execute_authenticated_query, name="authenticated-query-execute"),
    path("queries/status/", analysis_status, name="authenticated-query-status"),
    path("decision-evidence/", decision_evidence_detail, name="decision-evidence-detail"),
    path("topology-summary/", topology_summary, name="topology-summary"),
]
