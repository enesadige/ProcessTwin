import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.network.models import NetworkDeviceType
from apps.operations.tests.test_operations_models import (
    create_maltepe_bng,
    create_network_device,
    create_snapshot,
)

ENDPOINT = "/api/orchestration/topology-summary/"


@pytest.mark.django_db
def test_topology_summary_endpoint_returns_only_snapshot_local_device_graph():
    snapshot = create_snapshot("topology-summary-endpoint")
    root = create_maltepe_bng(snapshot, code="BNG-ENDPOINT-001")
    create_network_device(
        snapshot,
        code="AN-ENDPOINT-001",
        device_type=NetworkDeviceType.ACCESS_NODE,
        access_role="standard_access",
        city=root.city,
        district=root.district,
    )
    user = get_user_model().objects.create_user(
        username="topology-analyst",
        password="correct-pass-123",
        role="analyst",
    )
    client = Client()
    client.force_login(user)

    response = client.get(
        ENDPOINT,
        {"snapshot_identifier": snapshot.snapshot_key, "device_code": root.code},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["snapshot_key"] == snapshot.snapshot_key
    assert payload["root_device"]["code"] == root.code
    assert payload["upstream_devices"] == []
    assert payload["downstream_devices"] == []
