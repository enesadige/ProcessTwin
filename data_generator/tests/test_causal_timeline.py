from __future__ import annotations

import random

from data_generator.seeders.causal_timeline import (
    GPON_SCENARIOS,
    _calibrated_symptom_codes,
    _legacy_scenarios,
    _scenario_sequence,
    timeline_schedule_preview,
)


def test_causal_sequence_contains_every_gpon_chain_before_weighted_selection():
    scenarios = _scenario_sequence(random.Random("causal-seed"), 48)

    assert {scenario.code for scenario in GPON_SCENARIOS} <= {
        scenario.code for scenario in scenarios
    }
    assert {scenario.code for scenario in _legacy_scenarios()} <= {
        scenario.code for scenario in scenarios
    }


def test_weighted_causal_selection_is_deterministic_and_not_equalized():
    first = _scenario_sequence(random.Random("causal-seed"), 180)
    second = _scenario_sequence(random.Random("causal-seed"), 180)

    assert [scenario.code for scenario in first] == [scenario.code for scenario in second]
    counts = {
        scenario.code: [item.code for item in first].count(scenario.code) for scenario in first
    }
    assert len(set(counts.values())) > 1


def test_no_impact_and_degradation_gpon_scenarios_do_not_create_outages():
    scenarios = {scenario.code: scenario for scenario in GPON_SCENARIOS}

    assert not scenarios["SCN-GPON-NO-IMPACT-001"].creates_outage
    assert not scenarios["SCN-GPON-TEMPERATURE-DEGRADATION-001"].creates_outage
    assert not scenarios["SCN-GPON-OPTICAL-INTERMITTENT-001"].creates_outage


def test_optical_and_distribution_symptom_fanout_is_deterministic_and_bounded():
    scenario = next(item for item in GPON_SCENARIOS if "DISTRIBUTION-CABLE" in item.code)

    first = _calibrated_symptom_codes(scenario, random.Random("fanout-seed"), 4)
    second = _calibrated_symptom_codes(scenario, random.Random("fanout-seed"), 4)

    assert first == second
    assert 1 <= len(first) <= 4
    assert set(first) <= {"ONT_DISCONNECT_SURGE", "OLT_UNREACHABLE"}


def test_fanout_does_not_change_temperature_no_impact_or_optical_intermitttent():
    for code in {
        "SCN-GPON-TEMPERATURE-DEGRADATION-001",
        "SCN-GPON-NO-IMPACT-001",
        "SCN-GPON-OPTICAL-INTERMITTENT-001",
    }:
        scenario = next(item for item in GPON_SCENARIOS if item.code == code)
        assert _calibrated_symptom_codes(scenario, random.Random("fanout-seed"), 12) == []


def test_checkpointed_v3_schedule_is_complete_and_city_month_balanced():
    preview = timeline_schedule_preview()

    assert preview["main_event_count"] == 91
    assert len(preview["scenario_counts"]) == 28
    assert min(preview["scenario_counts"].values()) >= 2
    assert preview["city_month_counts"] == {
        "Ankara-06": 11,
        "Ankara-07": 11,
        "Kocaeli-06": 11,
        "Kocaeli-07": 11,
        "İstanbul-06": 12,
        "İstanbul-07": 12,
        "İzmir-06": 12,
        "İzmir-07": 11,
    }
    assert preview["base_alarm_count"] == 209
    assert preview["correlation_helpers_included"] is False
