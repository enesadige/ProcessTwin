from django.urls import path

from apps.orchestration.public_views import (
    analysis_status,
    decision_evidence_detail,
    evidence_record_detail,
    evidence_record_list,
    execute_authenticated_query,
    topology_summary,
)

urlpatterns = [
    path("queries/execute/", execute_authenticated_query, name="authenticated-query-execute"),
    path("queries/status/", analysis_status, name="authenticated-query-status"),
    path("decision-evidence/", decision_evidence_detail, name="decision-evidence-detail"),
    path("evidence-records/", evidence_record_list, name="evidence-record-list"),
    path("evidence-records/detail/", evidence_record_detail, name="evidence-record-detail"),
    path("topology-summary/", topology_summary, name="topology-summary"),
]
