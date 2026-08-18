from django.urls import path

from apps.simulation import internal_views

app_name = "simulation_internal"

urlpatterns = [
    path("runs/<str:run_code>/status/", internal_views.get_simulation_run_status),
    path("runs/<str:run_code>/result/", internal_views.get_simulation_result),
    path("runs/<str:run_code>/events/", internal_views.get_simulation_events),
    path("runs/<str:run_code>/evidence/", internal_views.get_simulation_evidence),
]
