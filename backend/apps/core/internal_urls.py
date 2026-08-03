from django.urls import include, path

from apps.core.internal_views import internal_health, mcp_health, mcp_registry

app_name = "internal"

urlpatterns = [
    path("health/", internal_health, name="health"),
    path("mcp/registry/", mcp_registry, name="mcp-registry"),
    path("mcp/health/", mcp_health, name="mcp-health"),
    path("customer/", include("apps.customers.internal_urls")),
    path("network/", include("apps.network.internal_urls")),
    path("rules/", include("apps.rules.internal_urls")),
    path("compensation/", include("apps.compensation.internal_urls")),
    path("rag/", include("apps.rag.internal_urls")),
]
