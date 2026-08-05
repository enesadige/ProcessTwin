from datetime import timedelta

import pytest
from data_generator.configs.realistic_alarm_catalog_v1 import ALARM_CATALOG
from data_generator.seeders.multicity_realism import seed_alarm_types
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.geography.models import AreaProfileType, City, District
from apps.network.models import (
    AccessSegment,
    AccessTechnology,
    FailureDomain,
    FailureDomainType,
    LineConnection,
    NetworkDevice,
    NetworkDeviceAccessRole,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
)
from apps.operations.alarm_topology import (
    INVALID_DEDICATED_PORT_SOURCE,
    INVALID_DEVICE_SOURCE,
    INVALID_DSL_LINE_SOURCE,
    INVALID_DSL_PORT_SOURCE,
    INVALID_PON_PORT_SOURCE,
    VALID,
    topology_policy_for,
    validate_alarm_topology,
)
from apps.operations.models import Alarm, AlarmSourceKind, Severity


@pytest.fixture
def topology_context(db):
    dataset = DatasetVersion.objects.create(
        name="REV-04 topology test",
        generator_version="test",
        seed="rev04-topology",
    )
    snapshot = DataSnapshot.objects.create(dataset_version=dataset, name="Initial")
    city = City.objects.create(name="Istanbul", plate_code="34")
    district = District.objects.create(
        city=city,
        name="Maltepe",
        profile_type=AreaProfileType.MIXED,
    )
    olt = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="OLT-REV04-001",
        device_type=NetworkDeviceType.OLT,
        city=city,
        district=district,
    )
    dslam = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="DSLAM-REV04-001",
        device_type=NetworkDeviceType.DSLAM,
        city=city,
        district=district,
    )
    access_node = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="AN-REV04-001",
        device_type=NetworkDeviceType.ACCESS_NODE,
        access_role=NetworkDeviceAccessRole.CORPORATE_FIBER_AGGREGATION,
        city=city,
        district=district,
    )
    olt_port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=olt,
        port_code="PON-1/1/1",
    )
    dslam_port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=dslam,
        port_code="DSL-1/1/1",
    )
    dedicated_port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=access_node,
        port_code="DED-1/1/1",
    )
    gpon_segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code="GPON-REV04-001",
        name="GPON segment",
        technology=AccessTechnology.GPON,
        serving_device=olt,
        city=city,
        district=district,
    )
    xdsl_segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code="XDSL-REV04-001",
        name="xDSL segment",
        technology=AccessTechnology.VDSL,
        serving_device=dslam,
        city=city,
        district=district,
    )
    now = timezone.now()
    gpon_line = LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code="LINE-GPON-REV04-001",
        port=olt_port,
        access_segment=gpon_segment,
        technology=AccessTechnology.GPON,
        valid_from=now - timedelta(days=1),
    )
    xdsl_line = LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code="LINE-XDSL-REV04-001",
        port=dslam_port,
        access_segment=xdsl_segment,
        technology=AccessTechnology.VDSL,
        valid_from=now - timedelta(days=1),
    )
    uplink = NetworkLink.objects.create(
        data_snapshot=snapshot,
        link_code="UPLINK-REV04-001",
        source_device=olt,
        target_device=access_node,
    )
    failure_domain = FailureDomain.objects.create(
        data_snapshot=snapshot,
        code="FD-REV04-001",
        name="Distribution fiber route",
        domain_type=FailureDomainType.FIBER_ROUTE,
    )
    alarm_types = seed_alarm_types(snapshot)
    return {
        "snapshot": snapshot,
        "olt": olt,
        "dslam": dslam,
        "access_node": access_node,
        "olt_port": olt_port,
        "dslam_port": dslam_port,
        "dedicated_port": dedicated_port,
        "gpon_line": gpon_line,
        "xdsl_line": xdsl_line,
        "uplink": uplink,
        "failure_domain": failure_domain,
        "alarm_types": alarm_types,
    }


def make_alarm(context, code, **source):
    return Alarm(
        data_snapshot=context["snapshot"],
        alarm_id=f"REV04-{code}-{len(source)}",
        alarm_type=context["alarm_types"][code],
        severity=Severity.MAJOR,
        detected_at=timezone.now(),
        **source,
    )


@pytest.mark.django_db
def test_gpon_alarm_sources_are_constrained_to_olt_and_gpon_resources(topology_context):
    context = topology_context
    olt_alarm = make_alarm(context, "OLT_UNREACHABLE", device=context["olt"])
    pon_alarm = make_alarm(context, "PON_PORT_DOWN", network_port=context["olt_port"])
    optical_alarm = make_alarm(context, "OPTICAL_SIGNAL_LOW", line_connection=context["gpon_line"])

    for alarm in (olt_alarm, pon_alarm, optical_alarm):
        result = validate_alarm_topology(alarm)
        assert result.valid is True
        assert result.reason_code == VALID
        alarm.full_clean()


@pytest.mark.django_db
def test_pon_port_alarm_rejects_dslam_port(topology_context):
    alarm = make_alarm(
        topology_context,
        "PON_PORT_DOWN",
        network_port=topology_context["dslam_port"],
    )

    result = validate_alarm_topology(alarm)

    assert result.valid is False
    assert result.reason_code == INVALID_PON_PORT_SOURCE
    with pytest.raises(ValidationError):
        alarm.full_clean()


@pytest.mark.django_db
def test_distribution_temperature_and_uplink_source_rules(topology_context):
    context = topology_context
    distribution = make_alarm(
        context,
        "DISTRIBUTION_CABLE_DOWN",
        failure_domain=context["failure_domain"],
    )
    high_temperature = make_alarm(context, "HIGH_TEMPERATURE", device=context["olt"])
    invalid_temperature = make_alarm(context, "HIGH_TEMPERATURE", network_port=context["olt_port"])
    uplink = make_alarm(context, "UPLINK_DOWN", network_link=context["uplink"])

    assert validate_alarm_topology(distribution).valid is True
    assert validate_alarm_topology(high_temperature).valid is True
    assert validate_alarm_topology(uplink).valid is True
    assert validate_alarm_topology(invalid_temperature).reason_code == INVALID_DEVICE_SOURCE


@pytest.mark.django_db
def test_dsl_and_dedicated_alarm_sources_remain_compatible(topology_context):
    context = topology_context
    dsl_port = make_alarm(context, "DSL_PORT_DOWN", network_port=context["dslam_port"])
    dsl_line = make_alarm(
        context,
        "DSL_LINE_QUALITY_DEGRADED",
        line_connection=context["xdsl_line"],
    )
    dedicated = make_alarm(
        context,
        "DEDICATED_PORT_DOWN",
        network_port=context["dedicated_port"],
    )

    assert validate_alarm_topology(dsl_port).reason_code == VALID
    assert validate_alarm_topology(dsl_line).reason_code == VALID
    assert validate_alarm_topology(dedicated).reason_code == VALID
    assert (
        validate_alarm_topology(
            make_alarm(context, "DSL_PORT_DOWN", network_port=context["olt_port"])
        ).reason_code
        == INVALID_DSL_PORT_SOURCE
    )
    assert (
        validate_alarm_topology(
            make_alarm(context, "DSL_LINE_QUALITY_DEGRADED", line_connection=context["gpon_line"])
        ).reason_code
        == INVALID_DSL_LINE_SOURCE
    )
    assert (
        validate_alarm_topology(
            make_alarm(context, "DEDICATED_PORT_DOWN", network_port=context["olt_port"])
        ).reason_code
        == INVALID_DEDICATED_PORT_SOURCE
    )


@pytest.mark.django_db
def test_catalog_seed_is_idempotent_and_persists_topology_policy(topology_context):
    context = topology_context
    first_count = len(context["alarm_types"])
    high_temperature = context["alarm_types"]["HIGH_TEMPERATURE"]
    high_temperature.allowed_source_kinds.create(
        data_snapshot=context["snapshot"],
        source_kind=AlarmSourceKind.FAILURE_DOMAIN,
    )
    second = seed_alarm_types(context["snapshot"])

    assert first_count == 31
    assert len(second) == 31
    assert context["snapshot"].alarm_types.count() == 31
    policy = second["DISTRIBUTION_CABLE_DOWN"].metadata["topology_policy"]
    assert policy["allowed_technologies"] == ["fiber", "gpon"]
    assert policy["direct_outage"] is False
    assert policy["session_verification_required"] is True
    assert list(
        second["HIGH_TEMPERATURE"].allowed_source_kinds.values_list("source_kind", flat=True)
    ) == [AlarmSourceKind.DEVICE]


def test_catalog_has_unique_codes_and_no_alarm_is_a_direct_verified_outage():
    codes = [item["code"] for item in ALARM_CATALOG]

    assert len(codes) == 31
    assert len(codes) == len(set(codes))
    assert "DISTRIBUTION_CABLE_DOWN" in codes
    assert all(topology_policy_for(code).direct_outage is False for code in codes)
