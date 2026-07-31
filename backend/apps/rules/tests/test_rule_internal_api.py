import pytest
from data_generator.seeders.rule_policy import seed_synthetic_compensation_policy
from django.core.management import call_command

from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion, DataSnapshot

SERVICE_TOKEN = "rule-internal-test-token"


@pytest.mark.django_db
def test_rule_internal_api_requires_explicit_snapshot(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN

    response = client.get(
        "/api/internal/v1/rules/",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-rule-no-snapshot",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_rule_dataset_slug_with_multiple_snapshots_is_rejected(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()
    DatasetVersion.objects.get(slug=snapshot.dataset_version.slug).snapshots.create(
        name="Second Rule Snapshot",
        snapshot_key="second-rule-test-snapshot",
    )

    response = authorized_get(client, "/api/internal/v1/rules/", snapshot.dataset_version.slug)

    assert response.status_code == 400
    assert response.json()["error"]["details"]["snapshot_count"] == 2


@pytest.mark.django_db
def test_search_rules_uses_active_at_for_effective_version_summary(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/",
        snapshot.snapshot_key,
        {
            "rule_code": "REFUND-001",
            "active_at": "2026-07-20T12:00:00+03:00",
        },
    )

    payload = response.json()["data"]["rules"][0]
    assert response.status_code == 200
    assert payload["rule"]["code"] == "REFUND-001"
    assert payload["effective_version_summary"]["version"] == 2


@pytest.mark.django_db
def test_search_rules_without_active_at_uses_latest_version_label(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/",
        snapshot.snapshot_key,
        {"rule_code": "REFUND-001"},
    )

    payload = response.json()["data"]["rules"][0]
    assert response.status_code == 200
    assert "latest_version_summary" in payload
    assert "effective_version_summary" not in payload


@pytest.mark.django_db
def test_get_rule_rejects_version_and_effective_at_together(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/REFUND-001/",
        snapshot.snapshot_key,
        {"version": "2", "effective_at": "2026-07-20T12:00:00+03:00"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_get_rule_effective_at_selects_refund_v2_and_hides_raw_config_by_default(
    client,
    settings,
):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/REFUND-001/",
        snapshot.snapshot_key,
        {"effective_at": "2026-07-20T12:00:00+03:00"},
    )

    selected = response.json()["data"]["selected_version"]
    assert response.status_code == 200
    assert selected["version"] == 2
    assert "condition_tree" not in selected
    assert "action_config" not in selected
    assert selected["schema_summary"]


@pytest.mark.django_db
def test_get_rule_returns_raw_config_only_when_requested(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/REFUND-001/",
        snapshot.snapshot_key,
        {"version": "2", "include_raw_config": "true"},
    )

    selected = response.json()["data"]["selected_version"]
    assert response.status_code == 200
    assert selected["condition_tree"]
    assert selected["action_config"]


@pytest.mark.django_db
def test_get_rule_without_version_or_time_rejects_ambiguous_active_versions(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/REFUND-001/",
        snapshot.snapshot_key,
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["active_version_count"] == 2


@pytest.mark.django_db
def test_get_rules_effective_at_returns_synthetic_policy_versions(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = create_policy_snapshot()
    seed_synthetic_compensation_policy(snapshot)

    response = authorized_get(
        client,
        "/api/internal/v1/rules/effective-at/",
        snapshot.snapshot_key,
        {
            "evaluation_time": "2026-07-20T12:00:00+03:00",
            "rule_set_code": "SYN-COMP-2026",
            "limit": "50",
        },
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["result_count"] == 25
    assert {row["rule_set"]["code"] for row in payload["effective_versions"]} == {
        "SYN-COMP-2026"
    }
    assert payload["note"] == "Conditions are not evaluated by this endpoint."


@pytest.mark.django_db
def test_get_rules_effective_at_rejects_naive_datetime(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/effective-at/",
        snapshot.snapshot_key,
        {"evaluation_time": "2026-07-20T12:00:00"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_get_rule_version_history_is_ordered_and_reports_overlap_warnings(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/REFUND-001/versions/",
        snapshot.snapshot_key,
    )

    payload = response.json()
    assert response.status_code == 200
    assert [row["version"] for row in payload["data"]["versions"]] == [1, 2]
    assert payload["warnings"] == []


@pytest.mark.django_db
def test_find_related_rules_requires_relation_input(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(client, "/api/internal/v1/rules/related/", snapshot.snapshot_key)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_find_related_rules_returns_relation_reasons(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = create_policy_snapshot()
    seed_synthetic_compensation_policy(snapshot)

    response = authorized_get(
        client,
        "/api/internal/v1/rules/related/",
        snapshot.snapshot_key,
        {"rule_code": "BB-FULL-OUTAGE-TIERED", "limit": "5"},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["related_rules"]
    assert "relation_reason" in payload["related_rules"][0]


@pytest.mark.django_db
def test_detect_rule_conflicts_requires_scope_filter(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(client, "/api/internal/v1/rules/conflicts/", snapshot.snapshot_key)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_detect_rule_conflicts_returns_ordering_hint_without_final_decision(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = create_policy_snapshot()
    seed_synthetic_compensation_policy(snapshot)

    response = authorized_get(
        client,
        "/api/internal/v1/rules/conflicts/",
        snapshot.snapshot_key,
        {
            "conflict_group": "broadband_outage",
            "evaluation_time": "2026-07-20T12:00:00+03:00",
            "limit": "10",
        },
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["candidate_order"]
    assert payload["ordering_hint"]
    assert "final_decision" not in payload
    assert "winner" not in payload


@pytest.mark.django_db
def test_rule_evidence_requires_identifier(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(client, "/api/internal/v1/rules/evidence/", snapshot.snapshot_key)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_rule_evidence_hash_not_found_returns_not_found(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/evidence/",
        snapshot.snapshot_key,
        {"evidence_hash": "missing-evidence-hash"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_rule_evidence_broad_filter_can_return_empty_page(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/evidence/",
        snapshot.snapshot_key,
        {"rule_code": "REFUND-001"},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["decision_evidence"] == []
    assert payload["result_count"] == 0


@pytest.mark.django_db
def test_rule_internal_api_does_not_leak_traceback_or_sql(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_maltepe_snapshot()

    response = authorized_get(
        client,
        "/api/internal/v1/rules/REFUND-001/",
        snapshot.snapshot_key,
        {"version": "not-an-int"},
    )

    body = response.content.decode()
    assert response.status_code == 400
    assert "Traceback" not in body
    assert "SELECT " not in body
    assert "token" not in body.lower()


def seed_maltepe_snapshot():
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def create_policy_snapshot() -> DataSnapshot:
    dataset = DatasetVersion.objects.create(
        name="Rule MCP Synthetic Policy Dataset",
        generator_version="rule-mcp-test",
        seed="rule-mcp-test",
    )
    return DataSnapshot.objects.create(
        dataset_version=dataset,
        name="Rule MCP Policy Snapshot",
        snapshot_key="rule-mcp-policy-snapshot",
    )


def authorized_get(client, path: str, snapshot_identifier: str, params: dict | None = None):
    query = {"snapshot_identifier": snapshot_identifier, **(params or {})}
    return client.get(
        path,
        query,
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-rule-internal",
    )
