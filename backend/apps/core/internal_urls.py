from django.urls import include, path

from apps.core.internal_views import internal_health

app_name = "internal"

urlpatterns = [
    path("health/", internal_health, name="health"),
    path("customer/", include("apps.customers.internal_urls")),
    path("network/", include("apps.network.internal_urls")),
    path("rules/", include("apps.rules.internal_urls")),
]
