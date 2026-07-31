from datetime import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.customers.models import PaymentRecord, Subscription
from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion

SERVICE_TOKEN = "customer-internal-test-token"


@pytest.mark.django_db
def test_customer_internal_api_requires_explicit_snapshot(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN

    response = client.get(
        "/api/internal/v1/customer/customers/CUST-MAL-0001/profile/",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-customer-no-snapshot",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_customer_profile_masks_display_name_by_default(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/customer/customers/CUST-MAL-0001/profile/",
        snapshot.snapshot_key,
    )

    payload = response.json()
    assert response.status_code == 200
    customer = payload["data"]["customer"]
    assert customer["customer_number"] == "CUST-MAL-0001"
    assert customer["masked_display_name"]
    assert "display_name" not in customer
    assert payload["metadata"]["snapshot"]["snapshot_key"] == snapshot.snapshot_key


@pytest.mark.django_db
def test_customer_profile_can_return_display_name_for_explicit_synthetic_request(
    client,
    settings,
):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/customer/customers/CUST-MAL-0001/profile/",
        snapshot.snapshot_key,
        {"include_display_name": "true", "include_subscriptions": "true"},
    )

    customer = response.json()["data"]["customer"]
    assert response.status_code == 200
    assert customer["display_name"]
    assert customer["subscription_count"] >= 1
    assert customer["subscriptions"][0]["subscription_number"].startswith("SUB-MAL-")


@pytest.mark.django_db
def test_get_customer_subscription_rejects_missing_or_duplicate_identifier(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    missing = authorized_get(
        client,
        "/api/internal/v1/customer/subscriptions/",
        snapshot.snapshot_key,
    )
    duplicate = authorized_get(
        client,
        "/api/internal/v1/customer/subscriptions/",
        snapshot.snapshot_key,
        {"customer_number": "CUST-MAL-0001", "subscription_number": "SUB-MAL-0001"},
    )

    assert missing.status_code == 400
    assert duplicate.status_code == 400
    assert missing.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_get_customer_subscription_returns_package_sla_and_connection_summary(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/customer/subscriptions/",
        snapshot.snapshot_key,
        {"subscription_number": "SUB-MAL-0001"},
    )

    payload = response.json()["data"]["subscriptions"][0]
    assert response.status_code == 200
    assert payload["subscription_number"] == "SUB-MAL-0001"
    assert payload["service_package"]["package_code"]
    assert "sla_profile" in payload
    assert payload["connections"][0]["connection_role"] == "primary"
    assert "access_device_code" in payload["connections"][0]


@pytest.mark.django_db
def test_get_customer_payment_status_uses_stable_cursor_and_aggregate(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    subscription = Subscription.objects.get(
        data_snapshot=snapshot,
        subscription_number="SUB-MAL-0001",
    )
    PaymentRecord.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        period="2026-07",
        amount="399.90",
        billing_period_start="2026-07-01",
        billing_period_end="2026-08-01",
        due_date="2026-07-15",
        recurring_amount="399.90",
        one_time_amount="0.00",
        discount_amount="0.00",
        billed_amount="399.90",
        paid_amount="399.90",
        outstanding_amount="0.00",
        status="paid_on_time",
        paid_at=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.get_current_timezone()),
    )

    response = authorized_get(
        client,
        "/api/internal/v1/customer/payments/",
        snapshot.snapshot_key,
        {"customer_number": "CUST-MAL-0001", "limit": "1"},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["result_count"] == 1
    assert payload["aggregate"]["status_counts"]
    assert "total_outstanding" in payload["aggregate"]


@pytest.mark.django_db
def test_get_customer_outage_history_uses_existing_impact_relationship(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/customer/outages/history/",
        snapshot.snapshot_key,
        {"subscription_number": "SUB-MAL-0001"},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["outages"][0]["outage_code"] == "OUT-MAL-BNG-001"
    assert payload["outages"][0]["relationship"] == (
        "subscription_in_deterministic_customer_impact"
    )


@pytest.mark.django_db
def test_compensation_history_endpoint_returns_existing_records_read_only(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/customer/compensation/history/",
        snapshot.snapshot_key,
        {"subscription_number": "SUB-MAL-0001"},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["compensation_history"] == []
    assert payload["result_count"] == 0


@pytest.mark.django_db
def test_list_customers_by_location_requires_location_filter(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/customer/customers/by-location/",
        snapshot.snapshot_key,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_list_customers_by_location_returns_masked_paginated_customers(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/customer/customers/by-location/",
        snapshot.snapshot_key,
        {"city": "İstanbul", "limit": "2"},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["result_count"] == 2
    assert payload["customers"][0]["masked_display_name"]
    assert "display_name" not in payload["customers"][0]
    assert payload["aggregates"]["total"] >= 2


@pytest.mark.django_db
def test_list_customers_by_device_uses_served_device_subgraph(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/customer/customers/by-device/BNG-MAL-001/",
        snapshot.snapshot_key,
        {"limit": "5"},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["device"]["code"] == "BNG-MAL-001"
    assert payload["result_count"] == 5
    assert payload["customers"][0]["served_relationship"]["relationship"] == (
        "served_by_device_subgraph"
    )


@pytest.mark.django_db
def test_customer_dataset_slug_with_multiple_snapshots_is_rejected(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    DatasetVersion.objects.get(slug=snapshot.dataset_version.slug).snapshots.create(
        name="Second Customer Snapshot",
        snapshot_key="second-customer-test-snapshot",
    )

    response = authorized_get(
        client,
        "/api/internal/v1/customer/customers/CUST-MAL-0001/profile/",
        snapshot.dataset_version.slug,
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["snapshot_count"] == 2


def seed_snapshot():
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def authorized_get(client, path: str, snapshot_identifier: str, params: dict | None = None):
    query = {"snapshot_identifier": snapshot_identifier, **(params or {})}
    return client.get(
        path,
        query,
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-customer-internal",
    )
