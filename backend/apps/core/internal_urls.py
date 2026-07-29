from django.urls import path

from apps.core.internal_views import internal_health

app_name = "internal"

urlpatterns = [
    path("health/", internal_health, name="health"),
]
