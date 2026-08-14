import json
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.compensation.models import CompensationEvaluation, DecisionEvidence
from apps.customers.models import Campaign, CampaignEnrollment, Subscription
from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion
from apps.operations.models import Outage, OutageStatus

SERVICE_TOKEN = "compensation-internal-test-token"


@pytest.mark.django_db
def test_compensation_internal_api_requires_explicit_snapshot(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN

    response = client.post(
        "/api/internal/v1/compensation/eligibility/",
        data=json.dumps({
            "outage_code": "OUT-MAL-BNG-001",
            "subscription_number": "SUB-MAL-0001",
            "rule_code": "REFUND-001",
        }),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-comp-no-snapshot",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_compensation_dataset_slug_with_multiple_snapshots_is_rejected(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    DatasetVersion.objects.get(slug=snapshot.dataset_version.slug).snapshots.create(
        name="Second Compensation Snapshot",
        snapshot_key="second-compensation-test-snapshot",
    )

    response = authorized_post(
        client,
        "/api/internal/v1/compensation/eligibility/",
        snapshot.dataset_version.slug,
        {
            "outage_code": "OUT-MAL-BNG-001",
            "subscription_number": "SUB-MAL-0001",
            "rule_code": "REFUND-001",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["snapshot_count"] == 2


@pytest.mark.django_db
def test_eligibility_does_not_calculate_amount_or_write_records(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    counts_before = counts(snapshot)

    response = authorized_post(
        client,
        "/api/internal/v1/compensation/eligibility/",
        snapshot.snapshot_key,
        {
            "outage_code": "OUT-MAL-BNG-001",
            "subscription_number": "SUB-MAL-0001",
            "rule_code": "REFUND-001",
        },
    )

    eligibility = response.json()["data"]["eligibility"]
    assert response.status_code == 200
    assert eligibility["decision"] == "eligible"
    assert eligibility["selected_rule"]["version"] == 2
    assert eligibility["amount_status"] == "not_calculated"
    assert "final_amount" not in eligibility
    assert counts(snapshot) == counts_before


@pytest.mark.django_db
def test_amount_dry_run_does_not_write_evaluation_or_evidence(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    counts_before = counts(snapshot)

    response = authorized_post(
        client,
        "/api/internal/v1/compensation/amount/",
        snapshot.snapshot_key,
        {
            "outage_code": "OUT-MAL-BNG-001",
            "subscription_number": "SUB-MAL-0001",
            "rule_code": "REFUND-001",
        },
    )

    compensation = response.json()["data"]["compensation"]
    assert response.status_code == 200
    assert compensation["decision"] == "eligible"
    assert compensation["final_amount"] == "39.99"
    assert compensation["persisted"] is False
    assert counts(snapshot) == counts_before


@pytest.mark.django_db
def test_amount_persist_creates_evaluation_and_evidence_idempotently(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    payload = {
        "outage_code": "OUT-MAL-BNG-001",
        "subscription_number": "SUB-MAL-0001",
        "rule_code": "REFUND-001",
        "persist": True,
    }

    first = authorized_post(
        client,
        "/api/internal/v1/compensation/amount/",
        snapshot.snapshot_key,
        payload,
    )
    second = authorized_post(
        client,
        "/api/internal/v1/compensation/amount/",
        snapshot.snapshot_key,
        payload,
    )

    first_comp = first.json()["data"]["compensation"]
    assert second.status_code == 200, second.content
    second_comp = second.json()["data"]["compensation"]
    assert first.status_code == 200
    assert first_comp["persisted"] is True
    assert first_comp["existing_result"] is False
    assert first_comp["evaluation"]["evaluation_code"]
    assert first_comp["evidence_hash"]
    assert second.status_code == 200
    assert second_comp["existing_result"] is True
    assert (
        second_comp["evaluation"]["evaluation_code"]
        == first_comp["evaluation"]["evaluation_code"]
    )
    assert CompensationEvaluation.objects.filter(data_snapshot=snapshot).count() == 1
    assert DecisionEvidence.objects.filter(data_snapshot=snapshot).count() == 1


@pytest.mark.django_db
def test_ongoing_outage_requires_evaluation_time_and_rejects_persist(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    outage = Outage.objects.get(data_snapshot=snapshot, outage_code="OUT-MAL-BNG-001")
    outage.status = OutageStatus.OPEN
    outage.ended_at = None
    outage.save(update_fields=["status", "ended_at", "updated_at"])
    payload = {
        "outage_code": "OUT-MAL-BNG-001",
        "subscription_number": "SUB-MAL-0001",
        "rule_code": "REFUND-001",
    }

    missing_time = authorized_post(
        client,
        "/api/internal/v1/compensation/amount/",
        snapshot.snapshot_key,
        payload,
    )
    dry_run = authorized_post(
        client,
        "/api/internal/v1/compensation/amount/",
        snapshot.snapshot_key,
        {**payload, "evaluation_time": "2026-07-20T14:35:00+03:00"},
    )
    persist = authorized_post(
        client,
        "/api/internal/v1/compensation/amount/",
        snapshot.snapshot_key,
        {**payload, "evaluation_time": "2026-07-20T14:35:00+03:00", "persist": True},
    )

    assert missing_time.status_code == 400
    assert dry_run.status_code == 200
    assert dry_run.json()["data"]["compensation"]["persisted"] is False
    assert persist.status_code == 400
    assert CompensationEvaluation.objects.filter(data_snapshot=snapshot).count() == 0
    assert DecisionEvidence.objects.filter(data_snapshot=snapshot).count() == 0


@pytest.mark.django_db
def test_naive_datetime_is_rejected(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()

    response = authorized_post(
        client,
        "/api/internal/v1/compensation/eligibility/",
        snapshot.snapshot_key,
        {
            "outage_code": "OUT-MAL-BNG-001",
            "subscription_number": "SUB-MAL-0001",
            "rule_code": "REFUND-001",
            "evaluation_time": "2026-07-20T12:00:00",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_campaign_check_is_read_only(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    subscription = Subscription.objects.get(
        data_snapshot=snapshot,
        subscription_number="SUB-MAL-0001",
    )
    campaign = Campaign.objects.create(
        data_snapshot=snapshot,
        code="TEST-CAMPAIGN",
        name="Test Campaign",
        discount_type="percent",
        discount_value=Decimal("10.00"),
        duration_months=3,
        valid_from=timezone.now() - timezone.timedelta(days=1),
        stackable=False,
    )
    CampaignEnrollment.objects.create(
        data_snapshot=snapshot,
        subscription=subscription,
        campaign=campaign,
        campaign_code=campaign.code,
        name=campaign.name,
        status="active",
        valid_from=timezone.now() - timezone.timedelta(days=1),
    )
    enrollment_count = CampaignEnrollment.objects.filter(data_snapshot=snapshot).count()

    response = authorized_post(
        client,
        "/api/internal/v1/compensation/campaigns/check/",
        snapshot.snapshot_key,
        {"subscription_number": "SUB-MAL-0001", "campaign_code": "TEST-CAMPAIGN"},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["status"] == "enrolled"
    assert payload["decision_source"] == "campaign_enrollment_read_model"
    assert CampaignEnrollment.objects.filter(data_snapshot=snapshot).count() == enrollment_count


@pytest.mark.django_db
def test_evidence_endpoint_paginates_existing_records(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = seed_snapshot()
    authorized_post(
        client,
        "/api/internal/v1/compensation/amount/",
        snapshot.snapshot_key,
        {
            "outage_code": "OUT-MAL-BNG-001",
            "subscription_number": "SUB-MAL-0001",
            "rule_code": "REFUND-001",
            "persist": True,
        },
    )

    response = authorized_get(
        client,
        "/api/internal/v1/compensation/evidence/",
        snapshot.snapshot_key,
        {"rule_code": "REFUND-001", "limit": "1"},
    )

    payload = response.json()["data"]
    assert response.status_code == 200
    assert payload["result_count"] == 1
    assert payload["decision_evidence"][0]["evidence_hash"]
    assert payload["summary"]["consideration_count"] == 1
    assert payload["summary"]["eligible"] == 1
    assert payload["summary"]["evidence_count"] == 1
    assert (
        payload["summary"]["evidence_reference"]
        == payload["decision_evidence"][0]["evidence_hash"]
    )


@pytest.mark.django_db
def test_rule_set_options_and_ranking_are_read_only(client, settings):
    settings.INTERNAL_API_SERVICE_TOKEN = SERVICE_TOKEN
    snapshot = create_policy_snapshot()
    from data_generator.seeders.rule_policy import seed_synthetic_compensation_policy

    seed_synthetic_compensation_policy(snapshot)
    counts_before = counts(snapshot)
    outage, subscription = create_policy_outage_and_subscription(snapshot)

    options = authorized_post(
        client,
        "/api/internal/v1/compensation/options/",
        snapshot.snapshot_key,
        {
            "outage_code": outage.outage_code,
            "subscription_number": subscription.subscription_number,
            "rule_set_code": "SYN-COMP-2026",
            "evaluation_time": "2026-07-20T12:00:00+03:00",
        },
    )
    ranking = authorized_post(
        client,
        "/api/internal/v1/compensation/options/rank/",
        snapshot.snapshot_key,
        {
            "outage_code": outage.outage_code,
            "subscription_number": subscription.subscription_number,
            "rule_set_code": "SYN-COMP-2026",
            "evaluation_time": "2026-07-20T12:00:00+03:00",
        },
    )

    assert options.status_code == 200
    assert options.json()["data"]["persisted"] is False
    assert ranking.status_code == 200
    assert ranking.json()["data"]["ordering_reason"]
    assert counts(snapshot) == counts_before


def seed_snapshot():
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def counts(snapshot):
    return {
        "evaluations": CompensationEvaluation.objects.filter(data_snapshot=snapshot).count(),
        "evidence": DecisionEvidence.objects.filter(data_snapshot=snapshot).count(),
    }


def authorized_post(client, path: str, snapshot_identifier: str, payload: dict):
    return client.post(
        path,
        data=json.dumps({"snapshot_identifier": snapshot_identifier, **payload}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-comp-internal",
    )


def authorized_get(client, path: str, snapshot_identifier: str, params: dict | None = None):
    return client.get(
        path,
        {"snapshot_identifier": snapshot_identifier, **(params or {})},
        HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}",
        HTTP_X_CORRELATION_ID="req-comp-internal",
    )


def create_policy_snapshot():
    from apps.datasets.models import DataSnapshot

    dataset = DatasetVersion.objects.create(
        name="Compensation MCP Policy Dataset",
        generator_version="compensation-mcp-test",
        seed="compensation-mcp-test",
    )
    return DataSnapshot.objects.create(
        dataset_version=dataset,
        name="Compensation MCP Policy Snapshot",
        snapshot_key="compensation-mcp-policy-snapshot",
    )


def create_policy_outage_and_subscription(snapshot):
    from apps.customers.models import Customer, CustomerSegment, ServicePackage
    from apps.geography.models import AreaProfileType, City, District
    from apps.network.models import AccessTechnology, NetworkDevice, NetworkDeviceType
    from apps.operations.models import OutageType, RootCauseCategory, ServiceImpactClass

    city = City.objects.create(name="Policy City", plate_code="96")
    district = District.objects.create(
        city=city,
        name="Policy District",
        profile_type=AreaProfileType.MIXED,
    )
    device = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="BNG-POL-001",
        name="Policy BNG",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )
    customer = Customer.objects.create(
        data_snapshot=snapshot,
        customer_number="CUST-POL-001",
        display_name="Policy Customer",
        segment=CustomerSegment.INDIVIDUAL,
        city=city,
        district=district,
    )
    package = ServicePackage.objects.create(
        data_snapshot=snapshot,
        package_code="PKG-POL-001",
        name="Policy Fiber",
        technology=AccessTechnology.FIBER,
        service_type="broadband",
        monthly_price=Decimal("399.90"),
    )
    subscription = Subscription.objects.create(
        data_snapshot=snapshot,
        subscription_number="SUB-POL-001",
        customer=customer,
        service_package=package,
        monthly_price=Decimal("399.90"),
        valid_from=timezone.datetime(2026, 7, 1, tzinfo=timezone.get_current_timezone()),
    )
    outage = Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-POL-001",
        source_device=device,
        outage_type=OutageType.DEVICE,
        impact_type=ServiceImpactClass.FULL_OUTAGE,
        status=OutageStatus.RESOLVED,
        root_cause_category=RootCauseCategory.BNG_FAILURE,
        detected_at=timezone.datetime(2026, 7, 20, 8, 0, tzinfo=timezone.get_current_timezone()),
        started_at=timezone.datetime(2026, 7, 20, 8, 0, tzinfo=timezone.get_current_timezone()),
        ended_at=timezone.datetime(2026, 7, 20, 12, 0, tzinfo=timezone.get_current_timezone()),
        resolved_at=timezone.datetime(2026, 7, 20, 12, 0, tzinfo=timezone.get_current_timezone()),
    )
    return outage, subscription
