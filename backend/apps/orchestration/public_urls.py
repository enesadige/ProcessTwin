from django.urls import path

from apps.orchestration.public_views import analysis_status, execute_authenticated_query

urlpatterns = [
    path("queries/execute/", execute_authenticated_query, name="authenticated-query-execute"),
    path("queries/status/", analysis_status, name="authenticated-query-status"),
]
