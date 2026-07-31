from django.urls import path

from apps.customers import internal_views

app_name = "customer_internal"

urlpatterns = [
    path(
        "customers/<str:customer_number>/profile/",
        internal_views.get_customer_profile,
        name="customer-profile",
    ),
    path(
        "subscriptions/",
        internal_views.get_customer_subscription,
        name="customer-subscription",
    ),
    path(
        "payments/",
        internal_views.get_customer_payment_status,
        name="customer-payment-status",
    ),
    path(
        "outages/history/",
        internal_views.get_customer_outage_history,
        name="customer-outage-history",
    ),
    path(
        "compensation/history/",
        internal_views.get_customer_compensation_history,
        name="customer-compensation-history",
    ),
    path(
        "customers/by-device/<str:device_code>/",
        internal_views.list_customers_by_device,
        name="customers-by-device",
    ),
    path(
        "customers/by-location/",
        internal_views.list_customers_by_location,
        name="customers-by-location",
    ),
]
