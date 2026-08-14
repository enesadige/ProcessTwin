from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.compensation.services.calculation import CompensationService
from apps.operations.tests.test_operations_models import create_snapshot

ENDPOINT = "/api/orchestration/decision-evidence/"


def _create_evidence(snapshot):
    return CompensationService().create_decision_evidence(
        data_snapshot=snapshot,
        price_basis="contracted_monthly_price",
        selected_price=Decimal("399.90"),
        unrounded_amount=Decimal("31.992"),
        final_amount=Decimal("31.99"),
        decision="eligible",
        matched_conditions=[{"field": "impact_class", "matched": True}],
        failed_conditions=[{"field": "telemetry", "matched": False}],
        manual_review_reasons=["operator_review"],
    )


@pytest.mark.django_db
def test_decision_evidence_endpoint_returns_only_exact_snapshot_record():
    snapshot = create_snapshot("decision-evidence-public")
    evidence = _create_evidence(snapshot)
    user = get_user_model().objects.create_user(
        username="evidence-analyst",
        password="correct-pass-123",
        role="analyst",
    )
    client = Client()
    client.force_login(user)

    response = client.get(
        ENDPOINT,
        {"snapshot_identifier": snapshot.snapshot_key, "evidence_hash": evidence.evidence_hash},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["snapshot_key"] == snapshot.snapshot_key
    assert payload["decision_evidence"]["evidence_hash"] == evidence.evidence_hash
    assert payload["decision_evidence"]["decision"] == "eligible"
    assert payload["decision_evidence"]["finalized"] is True
    assert payload["decision_evidence"]["matched_conditions"] == [
        {"field": "impact_class", "matched": True}
    ]
    assert payload["decision_evidence"]["compensation_evaluation"] is None


@pytest.mark.django_db
def test_decision_evidence_endpoint_rejects_missing_and_cross_snapshot_hashes():
    snapshot = create_snapshot("decision-evidence-source")
    other_snapshot = create_snapshot("decision-evidence-other")
    evidence = _create_evidence(snapshot)
    user = get_user_model().objects.create_user(
        username="evidence-reader",
        password="correct-pass-123",
        role="analyst",
    )
    client = Client()
    client.force_login(user)

    cross_snapshot = client.get(
        ENDPOINT,
        {
            "snapshot_identifier": other_snapshot.snapshot_key,
            "evidence_hash": evidence.evidence_hash,
        },
    )
    missing = client.get(
        ENDPOINT,
        {"snapshot_identifier": snapshot.snapshot_key, "evidence_hash": "0" * 64},
    )

    assert cross_snapshot.status_code == 404
    assert missing.status_code == 404
    assert cross_snapshot.json()["error"]["code"] == "not_found"
    assert missing.json()["error"]["code"] == "not_found"
