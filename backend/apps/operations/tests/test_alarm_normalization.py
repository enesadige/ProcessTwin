from apps.operations.alarm_normalization import (
    INSUFFICIENT_SOURCE_CONTEXT,
    UNMAPPED_TITLE,
    normalize_alarm_title,
    resolve_alarm_severity,
)
from apps.operations.models import Severity


def test_dying_gasp_aliases_share_one_family_and_subtype():
    titles = [
        "The dying-gasp of GPON ONTi (DGi) is generated",
        " Dying Gasp ",
        "[GPON Alarm]ONU Dying-Gasp",
    ]
    results = [normalize_alarm_title(title, resource_level="network_port") for title in titles]

    assert {(result.alarm_family, result.canonical_subtype) for result in results} == {
        ("gpon_access_symptom", "ont_dying_gasp")
    }
    assert {result.canonical_alarm_code for result in results} == {"ONT_DISCONNECT_SURGE"}


def test_los_subtypes_are_not_collapsed_and_generic_stays_ambiguous():
    feeder = normalize_alarm_title(
        "The feeder fiber is broken or OLT can not receive any expected optical signals(LOS)"
    )
    onu = normalize_alarm_title("[GPON Alarm]ONU LOS(Loss of Signal)")
    pon = normalize_alarm_title("PON LOS (Last ONU Dropped)")
    generic = normalize_alarm_title("Loss Of Signal")

    assert {feeder.canonical_subtype, onu.canonical_subtype, pon.canonical_subtype} == {
        "feeder_or_olt_los",
        "onu_los",
        "pon_los",
    }
    assert generic.canonical_alarm_code is None
    assert generic.resource_resolution_status == INSUFFICIENT_SOURCE_CONTEXT


def test_conditional_aliases_require_matching_resource_level():
    assert (
        normalize_alarm_title(
            "PON Communication Failure", resource_level="network_port"
        ).canonical_alarm_code
        == "PON_PORT_DOWN"
    )
    assert normalize_alarm_title("PON Communication Failure").canonical_alarm_code is None
    assert (
        normalize_alarm_title(
            "The upstream ethernet port connection fails or the state of it is abnormal"
        ).canonical_alarm_code
        is None
    )


def test_distribution_cable_and_device_not_active_remain_distinct():
    cable = normalize_alarm_title("DISTRIBUTION_CABLE_DOWN", observed_node_type="ACA Korelasyon")
    device = normalize_alarm_title("Device Not Active")

    assert cable.canonical_alarm_code == "DISTRIBUTION_CABLE_DOWN"
    assert cable.producer_type == "correlation_system"
    assert cable.observed_node_type == "aca korelasyon"
    assert device.canonical_subtype == "device_not_active"
    assert device.canonical_alarm_code is None


def test_raw_severity_wins_and_fallback_is_safe():
    assert resolve_alarm_severity("Critical", Severity.MINOR) == Severity.CRITICAL
    assert resolve_alarm_severity(None, Severity.MAJOR) == Severity.MAJOR
    assert resolve_alarm_severity("unexpected", Severity.MAJOR) == Severity.MAJOR


def test_missing_context_and_unknown_title_are_safe_and_deterministic():
    first = normalize_alarm_title("unknown alarm", observed_node_type=None)
    second = normalize_alarm_title(" UNKNOWN ALARM ", observed_node_type=None)

    assert first == second
    assert first.reason_code == UNMAPPED_TITLE
    assert first.observed_node_type is None
