from django.urls import path

from apps.operations import internal_views

app_name = "operations_internal"

urlpatterns = [
    path("causal-events/<str:event_code>/analysis/", internal_views.causal_analysis),
    path(
        "causal-events/<str:event_code>/cross-correlations/",
        internal_views.cross_incident_correlations,
    ),
]
