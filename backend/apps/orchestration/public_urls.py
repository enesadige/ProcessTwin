from django.urls import path

from apps.orchestration.public_views import (
    analysis_status,
    execute_authenticated_query,
    topology_summary,
)

urlpatterns = [
    path("queries/execute/", execute_authenticated_query, name="authenticated-query-execute"),
    path("queries/status/", analysis_status, name="authenticated-query-status"),
    path("topology-summary/", topology_summary, name="topology-summary"),
]
