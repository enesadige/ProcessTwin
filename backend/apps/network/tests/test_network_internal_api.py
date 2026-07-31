import pytest
from django.core.management import call_command

from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion
from apps.operations.models import Outage, OutageStatus

SERVICE_TOKEN = "network-internal-test-token"


@pytest.mark.django_db
def test_network_internal_api_requires_explicit_snapshot(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN

    response = client.get(
        "/api/internal/v1/network/devices/BNG-MAL-001/",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-network-no-snapshot",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_get_device_details_returns_links_ports_and_snapshot_metadata(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/network/devices/BNG-MAL-001/",
        snapshot.snapshot_key,
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["data"]["device"]["code"] == "BNG-MAL-001"
    assert payload["data"]["downstream_links"]
    assert "total" in payload["data"]["port_counts"]
    assert payload["metadata"]["snapshot"]["snapshot_key"] == snapshot.snapshot_key


@pytest.mark.django_db
def test_get_device_topology_truncates_without_failing(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/network/devices/BNG-MAL-001/topology/",
        snapshot.snapshot_key,
        {"limit": "2", "mode": "descendants"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["data"]["truncated"] is True
    assert payload["warnings"][0]["code"] == "result_truncated"


@pytest.mark.django_db
def test_search_alarms_uses_stable_cursor_pagination(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/network/alarms/",
        snapshot.dataset_version.slug,
        {"limit": "1"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["data"]["result_count"] == 1
    assert payload["data"]["next_cursor"] == "1"
    assert payload["data"]["alarms"][0]["alarm_type"]["code"]


@pytest.mark.django_db
def test_get_outage_details_requires_evaluation_time_for_ongoing_outage(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    outage = Outage.objects.get(data_snapshot=snapshot, outage_code="OUT-MAL-BNG-001")
    outage.ended_at = None
    outage.status = OutageStatus.OPEN
    outage.save(update_fields=["ended_at", "status", "updated_at"])

    response = authorized_get(
        client,
        "/api/internal/v1/network/outages/OUT-MAL-BNG-001/",
        snapshot.snapshot_key,
    )

    assert response.status_code == 400
    assert "evaluation_time is required" in response.json()["error"]["message"]


@pytest.mark.django_db
def test_customer_impact_returns_aggregate_only_without_commercial_details(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/network/outages/OUT-MAL-BNG-001/customer-impact/",
        snapshot.snapshot_key,
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["affected_subscription_count"] == 150
    assert payload["affected_customer_count"] == 140
    forbidden = {"customer_name", "email", "phone", "payment", "campaign", "compensation"}
    assert forbidden.isdisjoint(payload.keys())


@pytest.mark.django_db
def test_root_cause_endpoint_preserves_deterministic_unknown_or_scored_candidates(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/network/outages/OUT-MAL-BNG-001/root-cause-candidates/",
        snapshot.snapshot_key,
        {"limit": "3"},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["result_count"] >= 1
    assert payload["candidates"][0]["candidate_device_code"] == "BNG-MAL-001"
    assert payload["candidates"][0]["supporting_alarm_codes"]


@pytest.mark.django_db
def test_get_longest_outage_uses_outage_service_duration_and_impact(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/network/outages/longest/",
        snapshot.snapshot_key,
        {
            "from_time": "2026-07-20T00:00:00+03:00",
            "to_time": "2026-07-22T00:00:00+03:00",
        },
    )

    payload = response.json()["data"]["outages"][0]
    assert response.status_code == 200
    assert payload["outage"]["outage_code"] == "OUT-MAL-BNG-001"
    assert payload["outage"]["duration"]["minutes"] == 200
    assert payload["affected_subscription_count"] == 150
    assert payload["affected_customer_count"] == 140


@pytest.mark.django_db
def test_search_outages_rejects_naive_datetime(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/network/outages/",
        snapshot.snapshot_key,
        {"from_time": "2026-07-20T00:00:00"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_dataset_slug_with_multiple_snapshots_is_rejected(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    DatasetVersion.objects.get(slug=snapshot.dataset_version.slug).snapshots.create(
        name="Second Snapshot",
        snapshot_key="second-test-snapshot",
    )

    response = authorized_get(
        client,
        "/api/internal/v1/network/devices/BNG-MAL-001/",
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
        HTTP_X_CORRELATION_ID="req-network-internal",
    )
