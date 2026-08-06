from django.urls import path

from apps.orchestration import internal_views

app_name = "orchestration_internal"

urlpatterns = [
    path("queries/execute/", internal_views.execute_query, name="query-execute"),
]
