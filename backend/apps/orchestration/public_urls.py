from django.urls import path

from apps.orchestration.public_views import execute_authenticated_query

urlpatterns = [
    path("queries/execute/", execute_authenticated_query, name="authenticated-query-execute"),
]
