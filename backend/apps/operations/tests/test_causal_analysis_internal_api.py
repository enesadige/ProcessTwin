import pytest
from django.core.management import call_command

from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion
from apps.operations.contracts import CausalEventStatus, CausalEventType, EventOrigin
from apps.operations.models import CausalEvent, Outage

SERVICE_TOKEN = "operations-internal-test-token"


def seed_event():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    outage = Outage.objects.filter(data_snapshot=snapshot).select_related("source_device").first()
    event = CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-API-001",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=outage.started_at,
        ended_at=outage.ended_at,
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=outage.source_device,
    )
    outage.causal_event = event
    outage.save(update_fields=["causal_event"])
    return snapshot, event


def get(client, snapshot, code):
    return client.get(
        f"/api/internal/v1/operations/causal-events/{code}/analysis/?snapshot={snapshot.snapshot_key}",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-causal-analysis",
    )


@pytest.mark.django_db
def test_causal_analysis_requires_auth_and_returns_pending_safe_public_shape(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot, event = seed_event()
    unauthenticated = client.get(
        f"/api/internal/v1/operations/causal-events/{event.event_code}/analysis/"
    )
    assert unauthenticated.status_code == 401
    response = get(client, snapshot, event.event_code)
    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {
        "causal_event",
        "correlation",
        "alarm_classification",
        "failover",
        "impact",
        "compensation",
        "evidence",
    }
    assert data["compensation"]["status"] == "pending"
    assert data["compensation"]["consideration_count"] == 0
    assert data["impact"]["failover_protected_count"] == 0
    assert data["evidence"] is None
    assert "cust-" not in str(data).lower()
    assert "raw_payload" not in str(data).lower()


@pytest.mark.django_db
def test_causal_analysis_unknown_code_is_404_and_response_is_deterministic(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot, event = seed_event()
    assert get(client, snapshot, "CE-NOT-FOUND").status_code == 404
    first = get(client, snapshot, event.event_code).json()["data"]
    second = get(client, snapshot, event.event_code).json()["data"]
    assert first == second
