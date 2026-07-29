from data_generator.configs.realistic_alarm_catalog_v1 import (
    ALARM_CATALOG,
    DATASET_VOLUME_TARGETS,
    SCENARIO_TEMPLATES,
)


def test_realistic_alarm_catalog_has_exactly_thirty_synthetic_alarm_types():
    alarm_codes = [item["code"] for item in ALARM_CATALOG]

    assert len(alarm_codes) == 30
    assert len(set(alarm_codes)) == 30
    assert DATASET_VOLUME_TARGETS["alarm_types"] == 30
    assert "DEVICE_RESOURCE_HIGH" in alarm_codes
    assert "DSL_LINE_QUALITY_DEGRADED" in alarm_codes
    assert "BACKUP_POWER_DEGRADED" in alarm_codes
    assert "METRO_SERVICE_DEGRADED" not in alarm_codes
    assert "WIDESPREAD_QUALITY_DEGRADATION" not in alarm_codes


def test_realistic_scenario_templates_keep_approved_scope_rules():
    scenarios = {item["code"]: item for item in SCENARIO_TEMPLATES}

    assert len(scenarios) == 22
    assert scenarios["SCN-NOISE-001"]["creates_incident"] is False
    assert scenarios["SCN-ACCESS-NODE-001"]["city"] == "İstanbul"
    assert scenarios["SCN-ACCESS-NODE-001"]["district"] == "Şişli"
    assert "SCN-PON-PORT-001" in scenarios
    assert scenarios["SCN-PLANNED-OVERRUN-001"]["linked_maintenance_window"] is True
    assert scenarios["SCN-FAILOVER-HITLESS-001"]["creates_outage"] is False
    assert scenarios["SCN-FAILOVER-FAILED-001"]["creates_outage"] is True
