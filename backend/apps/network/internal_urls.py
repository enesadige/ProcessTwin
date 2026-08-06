from django.urls import path

from apps.network import internal_views

app_name = "network_internal"

urlpatterns = [
    path(
        "devices/<str:device_code>/",
        internal_views.get_device_details,
        name="device-details",
    ),
    path(
        "devices/<str:device_code>/topology/",
        internal_views.get_device_topology,
        name="device-topology",
    ),
    path("alarms/", internal_views.search_alarms, name="alarm-search"),
    path(
        "alarms/<str:anchor_alarm_id>/correlations/",
        internal_views.correlate_alarms,
        name="alarm-correlations",
    ),
    path("outages/", internal_views.search_outages, name="outage-search"),
    path(
        "outages/aggregate-impact/",
        internal_views.aggregate_location_impact,
        name="aggregate-impact",
    ),
    path("outages/longest/", internal_views.get_longest_outage, name="longest-outage"),
    path(
        "outages/<str:outage_code>/",
        internal_views.get_outage_details,
        name="outage-details",
    ),
    path(
        "outages/<str:outage_code>/customer-impact/",
        internal_views.calculate_customer_impact,
        name="customer-impact",
    ),
    path(
        "outages/<str:outage_code>/root-cause-candidates/",
        internal_views.rank_root_cause_candidates,
        name="root-cause-candidates",
    ),
]
