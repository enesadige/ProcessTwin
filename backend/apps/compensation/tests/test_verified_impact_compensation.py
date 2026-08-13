import pytest
from django.core.management import call_command

from apps.compensation.models import CompensationEvaluation, DecisionEvidence
from apps.compensation.services.verified_impact import VerifiedImpactCompensationService
from apps.customers.models import SubscriptionConnection
from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion
from apps.operations.contracts import (
    CausalEventStatus,
    CausalEventType,
    CustomerImpactStatus,
    EventOrigin,
)
from apps.operations.models import CausalEvent, CustomerImpactAssessment, Outage


def context():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    outage = Outage.objects.filter(data_snapshot=snapshot).select_related("source_device").first()
    event = CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-REV08-001",
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
    connection = (
        SubscriptionConnection.objects.filter(data_snapshot=snapshot, is_active=True)
        .select_related("subscription")
        .first()
    )
    return snapshot, outage, event, connection


def assessment(snapshot, event, connection, status):
    return CustomerImpactAssessment.objects.create(
        data_snapshot=snapshot,
        causal_event=event,
        subscription=connection.subscription,
        subscription_connection=connection,
        status=status,
        potential_impact=True,
        connection_role=connection.connection_role,
        assessment_started_at=event.started_at,
        assessment_ended_at=event.ended_at,
        reasons=["topology_match"],
    )


@pytest.mark.django_db
def test_only_verified_impact_is_compensation_considered_and_evidence_is_idempotent():
    snapshot, outage, event, connection = context()
    assessment(snapshot, event, connection, CustomerImpactStatus.VERIFIED_IMPACT)

    results, evidence, summary = VerifiedImpactCompensationService().evaluate_outage(
        outage=outage, snapshot=snapshot
    )
    repeated, repeated_evidence, repeated_summary = (
        VerifiedImpactCompensationService().evaluate_outage(outage=outage, snapshot=snapshot)
    )

    assert len(results) == 1
    assert summary.compensation_considered_count == 1
    assert evidence.pk == repeated_evidence.pk
    assert summary == repeated_summary
    assert results == repeated
    assert evidence.context_snapshot["causal_event_code"] == event.event_code
    assert (
        evidence.context_snapshot["deterministic_provenance"] == "services_only_no_model_or_prompt"
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        CustomerImpactStatus.POTENTIAL_IMPACT,
        CustomerImpactStatus.VERIFIED_NO_IMPACT,
        CustomerImpactStatus.INSUFFICIENT_EVIDENCE,
    ],
)
def test_non_verified_statuses_do_not_enter_compensation(status):
    snapshot, outage, event, connection = context()
    assessment(snapshot, event, connection, status)

    results, _, summary = VerifiedImpactCompensationService().evaluate_outage(
        outage=outage, snapshot=snapshot
    )

    assert results == []
    assert summary.compensation_considered_count == 0
    assert summary.eligible_count == 0


@pytest.mark.django_db
def test_materialization_persists_snapshot_local_evaluation_and_evidence_idempotently():
    snapshot, outage, event, connection = context()
    assessment(snapshot, event, connection, CustomerImpactStatus.VERIFIED_IMPACT)
    service = VerifiedImpactCompensationService()

    first = service.materialize_outage(outage=outage, snapshot=snapshot)
    second = service.materialize_outage(outage=outage, snapshot=snapshot)

    evaluations = CompensationEvaluation.objects.filter(data_snapshot=snapshot, outage=outage)
    assert first["created"] == 1
    assert first["reused"] == 0
    assert second["created"] == 0
    assert second["reused"] == 1
    assert evaluations.count() == 1
    evaluation = evaluations.get()
    assert evaluation.subscription == connection.subscription
    assert evaluation.customer == connection.subscription.customer
    assert evaluation.rule_version.data_snapshot == snapshot
    evidence = DecisionEvidence.objects.get(compensation_evaluation=evaluation)
    assert evidence.data_snapshot == snapshot
    assert evidence.selected_rule_version == evaluation.rule_version
