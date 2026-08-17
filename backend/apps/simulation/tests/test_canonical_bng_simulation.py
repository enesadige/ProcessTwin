from datetime import UTC, datetime, timedelta

import pytest

from apps.compensation.models import CompensationEvaluation
from apps.operations.contracts import (
    CausalEventStatus,
    CausalEventType,
    EventOrigin,
    SessionEventType,
)
from apps.operations.models import (
    Alarm,
    CausalEvent,
    CustomerImpactAssessment,
    Incident,
    Outage,
    SessionEvent,
)
from apps.operations.tests.test_operations_models import (
    create_access_line,
    create_snapshot,
    create_subscription_connection,
)
from apps.rules.models import Rule, RuleStatus, RuleType, RuleVersion, RuleVersionStatus
from apps.simulation.models import SimulationComparisonRole, SimulationRunStatus, SimulationScenario
from apps.simulation.services import CanonicalBNGSimulationService, SimulationService


def clock():
    return datetime(2026, 6, 1, 8, 0, tzinfo=UTC)


def setup_bng_scenario():
    snapshot = create_snapshot("canonical-bng")
    bng, _access, _link, _port, line = create_access_line(snapshot, code_suffix="SIM")
    line.valid_from = clock() - timedelta(days=1)
    line.save(update_fields=["valid_from"])
    connection = create_subscription_connection(snapshot, line)
    source_start = clock() - timedelta(hours=1)
    source_event = CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-SIM-BNG-001",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=source_start,
        ended_at=source_start + timedelta(minutes=30),
        source_system="simulation-test",
        origin=EventOrigin.SYNTHETIC,
        root_device=bng,
    )
    for suffix, event_type, occurred_at in (
        ("PRE", SessionEventType.CONTINUE, source_start - timedelta(minutes=5)),
        ("STOP", SessionEventType.STOP, source_start + timedelta(minutes=5)),
        ("REC", SessionEventType.START, source_start + timedelta(minutes=35)),
    ):
        SessionEvent.objects.create(
            data_snapshot=snapshot,
            causal_event=source_event,
            external_event_id=f"SIM-SES-{suffix}",
            event_type=event_type,
            occurred_at=occurred_at,
            received_at=occurred_at,
            source_system="simulation-test",
            subscription=connection.subscription,
            subscription_connection=connection,
        )
    rule = Rule.objects.create(
        data_snapshot=snapshot,
        code="SIM-REFUND-001",
        name="Simulation compensation rule",
        rule_type=RuleType.COMPENSATION,
        status=RuleStatus.ACTIVE,
    )
    RuleVersion.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        version=1,
        status=RuleVersionStatus.ACTIVE,
        valid_from=clock() - timedelta(days=1),
        condition_tree={"all": []},
        action_config={
            "refund_formula": {
                "type": "monthly_price_percentage",
                "percentage": "0.10",
            }
        },
    )
    scenario = SimulationScenario.objects.create(
        source_snapshot=snapshot,
        scenario_code="SIM-CANONICAL-BNG-001",
        name="Canonical BNG failure",
        scenario_type="bng_failure",
        definition={"source_event_code": source_event.event_code},
        default_parameters={
            "duration_seconds": 600,
            "outage_classification": "full_outage",
            "rule_code": rule.code,
            "sla_target_seconds": 300,
        },
    )
    return snapshot, scenario


@pytest.mark.django_db
def test_canonical_bng_baseline_candidate_chain_delta_and_operational_isolation():
    snapshot, scenario = setup_bng_scenario()
    before = {
        "events": CausalEvent.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "incidents": Incident.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "assessments": CustomerImpactAssessment.objects.filter(data_snapshot=snapshot).count(),
        "compensations": CompensationEvaluation.objects.filter(data_snapshot=snapshot).count(),
    }
    runtime = SimulationService()
    baseline = runtime.create_run(
        scenario=scenario,
        comparison_role=SimulationComparisonRole.BASELINE,
        deterministic_seed="canonical-seed",
        virtual_clock=clock(),
    )
    candidate = runtime.create_candidate(
        baseline_run=baseline,
        input_overrides={"duration_seconds": 1200},
    )
    service = CanonicalBNGSimulationService(runtime=runtime)

    baseline_result = service.execute(baseline)
    candidate_result = service.execute(candidate)
    comparison = service.compare(baseline_run=baseline, candidate_run=candidate)

    baseline.refresh_from_db()
    candidate.refresh_from_db()
    assert baseline.status == candidate.status == SimulationRunStatus.COMPLETED
    assert baseline_result.projection["basis"] == "simulation_projection"
    assert baseline_result.projection["projected_affected_subscriptions"] == 1
    assert baseline_result.projection["projected_unknown_subscriptions"] == 0
    assert baseline_result.historical_evidence["verified_affected_subscriptions"] == 1
    assert baseline_result.compensation["eligibility"] == "eligible"
    assert baseline_result.compensation["amount"] == "39.99"
    assert candidate_result.event["duration_seconds"] == 1200
    assert comparison["duration_seconds_delta"] == 600
    assert [event.event_type for event in baseline.events.order_by("sequence")] == [
        "runtime_started",
        "bng_failure",
        "alarm",
        "incident",
        "outage",
        "customer_impact",
        "compensation_evaluation",
        "simulation_result",
        "runtime_completed",
    ]
    assert baseline.lifecycle_context["canonical_bng_result"] == baseline_result.to_dict()
    assert scenario.default_parameters["duration_seconds"] == 600
    assert baseline.input_parameters == {}
    assert candidate.input_parameters == {"duration_seconds": 1200}
    assert {
        "events": CausalEvent.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "incidents": Incident.objects.filter(data_snapshot=snapshot).count(),
        "outages": Outage.objects.filter(data_snapshot=snapshot).count(),
        "assessments": CustomerImpactAssessment.objects.filter(data_snapshot=snapshot).count(),
        "compensations": CompensationEvaluation.objects.filter(data_snapshot=snapshot).count(),
    } == before


@pytest.mark.django_db
def test_canonical_bng_comparison_reports_explicit_sla_state_change():
    snapshot, scenario = setup_bng_scenario()
    runtime = SimulationService()
    baseline = runtime.create_run(
        scenario=scenario,
        comparison_role=SimulationComparisonRole.BASELINE,
        deterministic_seed="sla-delta-seed",
        virtual_clock=clock(),
    )
    candidate = runtime.create_candidate(
        baseline_run=baseline,
        input_overrides={"sla_target_seconds": 900},
    )
    service = CanonicalBNGSimulationService(runtime=runtime)

    service.execute(baseline)
    service.execute(candidate)
    comparison = service.compare(baseline_run=baseline, candidate_run=candidate)

    assert comparison["sla_target_seconds_delta"] == 600
    assert comparison["sla_breached"] == {
        "baseline": True,
        "candidate": False,
        "changed": True,
    }


@pytest.mark.django_db
def test_canonical_bng_replay_is_deterministic_and_rule_selection_has_no_fallback():
    _snapshot, scenario = setup_bng_scenario()
    runtime = SimulationService()
    original = runtime.create_run(
        scenario=scenario,
        comparison_role=SimulationComparisonRole.BASELINE,
        deterministic_seed="canonical-replay-seed",
        virtual_clock=clock(),
    )
    service = CanonicalBNGSimulationService(runtime=runtime)
    first = service.execute(original)
    replay = runtime.replay(original)
    repeated = service.execute(replay)

    first_payload = first.to_dict()
    repeated_payload = repeated.to_dict()
    first_payload["run"].pop("code")
    repeated_payload["run"].pop("code")
    assert first_payload == repeated_payload
    assert first.event["selected_rule_version"] == repeated.event["selected_rule_version"]
    event_fields = ("sequence", "event_type", "virtual_occurred_at")
    assert list(original.events.values_list(*event_fields)) == list(
        replay.events.values_list(*event_fields)
    )


@pytest.mark.django_db
def test_canonical_bng_device_anchor_resolves_scope_without_inventing_session_impact():
    snapshot = create_snapshot("canonical-bng-device")
    bng, _access, _link, _port, line = create_access_line(snapshot, code_suffix="DEVICE")
    line.valid_from = clock() - timedelta(days=1)
    line.save(update_fields=["valid_from"])
    create_subscription_connection(snapshot, line)
    scenario = SimulationScenario.objects.create(
        source_snapshot=snapshot,
        scenario_code="SIM-CANONICAL-BNG-DEVICE-001",
        name="Canonical BNG device anchor",
        scenario_type="bng_failure",
        definition={"source_device_code": bng.code},
        default_parameters={"duration_seconds": 600, "outage_classification": "full_outage"},
    )
    run = SimulationService().create_run(
        scenario=scenario,
        comparison_role=SimulationComparisonRole.BASELINE,
        deterministic_seed="device-anchor-seed",
        virtual_clock=clock(),
    )

    result = CanonicalBNGSimulationService().execute(run)

    assert result.event["source_event_code"] is None
    assert result.event["source_device_code"] == bng.code
    assert result.projection["potential_subscription_scope"] == 1
    assert result.projection["projected_affected_subscriptions"] == 1
    assert result.projection["projected_unknown_subscriptions"] == 0
    assert result.historical_evidence == {"basis": "not_used_for_device_anchor"}


@pytest.mark.django_db
def test_projection_does_not_turn_missing_historical_evidence_into_unknown_scope():
    snapshot, scenario = setup_bng_scenario()
    SessionEvent.objects.filter(data_snapshot=snapshot).delete()
    run = SimulationService().create_run(
        scenario=scenario,
        comparison_role=SimulationComparisonRole.BASELINE,
        deterministic_seed="historical-evidence-boundary-seed",
        virtual_clock=clock(),
    )

    result = CanonicalBNGSimulationService().execute(run)

    assert result.historical_evidence["verified_affected_subscriptions"] == 0
    assert result.historical_evidence["unknown_or_insufficient_subscriptions"] == 1
    assert result.projection["projected_affected_subscriptions"] == 1
    assert result.projection["projected_unknown_subscriptions"] == 0
