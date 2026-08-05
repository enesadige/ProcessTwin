from __future__ import annotations

import random

from data_generator.seeders.causal_timeline import (
    GPON_SCENARIOS,
    _legacy_scenarios,
    _scenario_sequence,
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
