import hashlib
import json
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

import pytest
from data_generator.configs import maltepe_mvp_v1 as seed_config
from data_generator.validators.maltepe_mvp import validate_maltepe_mvp_snapshot
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Count

from apps.core.choices import ResultStatus
from apps.customers.models import (
    Customer,
    CustomerPriorityLevel,
    ServicePackage,
    Subscription,
    SubscriptionConnection,
)
from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import (
    DatasetSnapshotStatus,
    DatasetVersion,
    DataSnapshot,
    GroundTruthCase,
    GroundTruthEligibility,
)
from apps.geography.models import City, District, Neighborhood
from apps.network.models import (
    AccessTechnology,
    LineConnection,
    NetworkDevice,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
    NetworkPortStatus,
)
from apps.operations.models import (
    Alarm,
    AlarmCategory,
    AlarmType,
    Incident,
    IncidentAlarm,
    IncidentAlarmRole,
    OperationalEvent,
    OperationalEventType,
    Outage,
    QualityMeasurement,
    Severity,
)
from apps.rules.models import Rule, RuleVersion
from apps.rules.services.version_selection import select_rule_version_for_moment


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_passive_dataset_snapshot_and_geography():
    call_command("seed_maltepe_mvp")

    dataset = DatasetVersion.objects.get(slug=get_target_dataset_slug())
    snapshot = dataset.snapshots.get()
    city = City.objects.get(name="İstanbul")
    district = District.objects.get(city=city, name="Maltepe")
    neighborhoods = list(
        Neighborhood.objects.filter(district=district)
        .order_by("name")
        .values_list("name", flat=True)
    )

    assert dataset.kind == "synthetic"
    assert dataset.generator_version == seed_config.GENERATOR_VERSION
    assert dataset.seed == seed_config.DATASET_SEED
    assert dataset.config["reference_datetime"] == seed_config.DEFAULT_REFERENCE_DATETIME
    assert dataset.config["customer_plan"]["vip_customers"] == 20
    assert snapshot.name == seed_config.SNAPSHOT_NAME
    assert snapshot.status == DatasetSnapshotStatus.VALIDATED
    assert snapshot.validation_status == ResultStatus.EXACT
    assert snapshot.validation_result["seed_stage"] == "027_ground_truth"
    assert snapshot.validation_result["validated"] is True
    assert all(
        {"name", "expected", "actual", "passed"} <= set(check)
        for check in snapshot.validation_result["checks"]
    )
    assert all(check["passed"] is True for check in snapshot.validation_result["checks"])
    assert snapshot.is_active is False
    assert snapshot.activated_at is None
    assert snapshot.row_counts["neighborhoods"] == 5
    assert snapshot.row_counts["network_devices"] == 14
    assert snapshot.row_counts["network_links"] == 12
    assert snapshot.row_counts["network_ports"] == 177
    assert snapshot.row_counts["access_segments"] == 17
    assert snapshot.row_counts["line_connections"] == 240
    assert snapshot.row_counts["customers"] == 225
    assert snapshot.row_counts["service_packages"] == 8
    assert snapshot.row_counts["subscriptions"] == 240
    assert snapshot.row_counts["subscription_connections"] == 240
    assert snapshot.row_counts["alarm_types"] == 3
    assert snapshot.row_counts["alarms"] == 4
    assert snapshot.row_counts["incidents"] == 3
    assert snapshot.row_counts["incident_alarms"] == 4
    assert snapshot.row_counts["outages"] == 3
    assert snapshot.row_counts["operational_events"] == 12
    assert snapshot.row_counts["quality_measurements"] == 0
    assert snapshot.row_counts["rules"] == 1
    assert snapshot.row_counts["rule_versions"] == 2
    assert snapshot.row_counts["ground_truth_cases"] == 3
    assert neighborhoods == sorted(seed_config.NEIGHBORHOODS)


@pytest.mark.django_db
def test_seed_maltepe_mvp_rejects_duplicate_without_reset():
    call_command("seed_maltepe_mvp")

    with pytest.raises(CommandError, match="already exists"):
        call_command("seed_maltepe_mvp")

    assert DatasetVersion.objects.filter(slug=get_target_dataset_slug()).count() == 1


@pytest.mark.django_db
def test_seed_maltepe_mvp_reset_recreates_only_target_dataset_and_keeps_geography():
    call_command("seed_maltepe_mvp")
    city_id = City.objects.get(name="İstanbul").id
    other_dataset = DatasetVersion.objects.create(
        name="Other Dataset",
        generator_version="other-v1",
        seed="other-seed",
    )

    call_command("seed_maltepe_mvp", "--reset")

    assert DatasetVersion.objects.filter(slug=get_target_dataset_slug()).count() == 1
    assert DatasetVersion.objects.filter(id=other_dataset.id).exists()
    assert City.objects.get(name="İstanbul").id == city_id
    assert City.objects.filter(name="İstanbul").count() == 1


@pytest.mark.django_db
def test_seed_maltepe_mvp_rolls_back_when_validation_fails(monkeypatch):
    monkeypatch.setattr(
        "apps.datasets.management.commands.seed_maltepe_mvp.validate_maltepe_mvp_snapshot",
        lambda snapshot: {
            "passed": False,
            "row_counts": {},
            "checks": [
                {
                    "name": "forced_failure",
                    "expected": 1,
                    "actual": 0,
                    "passed": False,
                }
            ],
        },
    )

    with pytest.raises(CommandError, match="forced_failure"):
        call_command("seed_maltepe_mvp")

    assert not DatasetVersion.objects.filter(slug=get_target_dataset_slug()).exists()


@pytest.mark.django_db
def test_seed_maltepe_mvp_can_create_passive_snapshot_when_another_snapshot_is_active():
    other_dataset = DatasetVersion.objects.create(
        name="Other Active Dataset",
        generator_version="other-active-v1",
        seed="other-active-seed",
    )
    DataSnapshot.objects.create(
        dataset_version=other_dataset,
        name="Other active snapshot",
        is_active=True,
    )

    call_command("seed_maltepe_mvp")

    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    assert snapshot.is_active is False
    assert DataSnapshot.objects.filter(is_active=True).get().dataset_version == other_dataset


@pytest.mark.django_db
def test_seed_maltepe_mvp_activate_creates_active_snapshot_when_none_exists():
    call_command("seed_maltepe_mvp", "--activate")

    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    assert snapshot.is_active is True
    assert snapshot.activated_at is not None


@pytest.mark.django_db
def test_seed_maltepe_mvp_activate_rejects_existing_active_snapshot():
    other_dataset = DatasetVersion.objects.create(
        name="Other Active Dataset",
        generator_version="other-active-v1",
        seed="other-active-seed",
    )
    DataSnapshot.objects.create(
        dataset_version=other_dataset,
        name="Other active snapshot",
        is_active=True,
    )

    with pytest.raises(CommandError, match="Another active data snapshot"):
        call_command("seed_maltepe_mvp", "--activate")

    assert not DatasetVersion.objects.filter(slug=get_target_dataset_slug()).exists()


@pytest.mark.django_db
def test_seed_maltepe_mvp_stores_custom_reference_datetime_as_istanbul_iso_string():
    call_command("seed_maltepe_mvp", "--reference-datetime", "2026-09-01T00:00:00+03:00")

    dataset = DatasetVersion.objects.get(slug=get_target_dataset_slug())
    assert dataset.config["reference_datetime"] == "2026-09-01T00:00:00+03:00"


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_expected_network_topology_counts():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    assert NetworkDevice.objects.filter(data_snapshot=snapshot).count() == 14
    assert NetworkDevice.objects.filter(
        data_snapshot=snapshot,
        device_type=NetworkDeviceType.BNG,
        code__in=["BNG-MAL-001", "BNG-MAL-002"],
    ).count() == 2
    assert NetworkDevice.objects.filter(
        data_snapshot=snapshot,
        device_type=NetworkDeviceType.OLT,
    ).count() == 5
    assert NetworkDevice.objects.filter(
        data_snapshot=snapshot,
        device_type=NetworkDeviceType.DSLAM,
    ).count() == 5
    assert NetworkDevice.objects.filter(
        data_snapshot=snapshot,
        device_type=NetworkDeviceType.ACCESS_NODE,
    ).count() == 2
    assert NetworkLink.objects.filter(data_snapshot=snapshot).count() == 12
    assert NetworkPort.objects.filter(data_snapshot=snapshot).count() == 177
    assert LineConnection.objects.filter(data_snapshot=snapshot, is_active=True).count() == 240


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_expected_port_and_line_distribution():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.ACTIVE,
        metadata__seed_role="gpon_pon_port",
    ).count() == 10
    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.RESERVED,
        metadata__seed_role="reserved_gpon_pon_port",
    ).count() == 2
    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.ACTIVE,
        metadata__seed_role__in=["vdsl_customer_port", "adsl_customer_port"],
    ).count() == 110
    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.RESERVED,
        metadata__seed_role="reserved_dslam_customer_port",
    ).count() == 20
    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.ACTIVE,
        metadata__seed_role="general_fiber_customer_port",
    ).count() == 30
    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.RESERVED,
        metadata__seed_role="reserved_general_fiber_customer_port",
    ).count() == 5
    assert LineConnection.objects.filter(
        data_snapshot=snapshot,
        technology=AccessTechnology.GPON,
    ).count() == 100
    assert LineConnection.objects.filter(
        data_snapshot=snapshot,
        technology=AccessTechnology.FIBER,
    ).count() == 30
    assert LineConnection.objects.filter(
        data_snapshot=snapshot,
        technology=AccessTechnology.VDSL,
    ).count() == 90
    assert LineConnection.objects.filter(
        data_snapshot=snapshot,
        technology=AccessTechnology.ADSL,
    ).count() == 20


@pytest.mark.django_db
def test_seed_maltepe_mvp_supports_gpon_fan_out_without_dslam_port_fan_out():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    gpon_port = NetworkPort.objects.filter(
        data_snapshot=snapshot,
        metadata__seed_role="gpon_pon_port",
    ).first()
    assert gpon_port.line_connections.count() > 1

    dslam_active_ports = NetworkPort.objects.filter(
        data_snapshot=snapshot,
        metadata__seed_role__in=["vdsl_customer_port", "adsl_customer_port"],
    )
    assert all(port.line_connections.count() == 1 for port in dslam_active_ports)


@pytest.mark.django_db
def test_seed_maltepe_mvp_reset_recreates_network_without_duplicates():
    call_command("seed_maltepe_mvp")
    call_command("seed_maltepe_mvp", "--reset")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    assert NetworkDevice.objects.filter(data_snapshot=snapshot).count() == 14
    assert NetworkPort.objects.filter(data_snapshot=snapshot).count() == 177
    assert LineConnection.objects.filter(data_snapshot=snapshot).count() == 240
    assert Customer.objects.filter(data_snapshot=snapshot).count() == 225
    assert Subscription.objects.filter(data_snapshot=snapshot).count() == 240
    assert SubscriptionConnection.objects.filter(data_snapshot=snapshot).count() == 240


@pytest.mark.django_db
def test_seed_maltepe_mvp_reset_recreates_deterministic_codes_without_duplicates():
    call_command("seed_maltepe_mvp")
    first_codes = collect_seed_codes()

    call_command("seed_maltepe_mvp", "--reset")
    second_codes = collect_seed_codes()

    assert first_codes == second_codes
    assert DatasetVersion.objects.filter(slug=get_target_dataset_slug()).count() == 1
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    assert snapshot.row_counts["network_devices"] == 14
    assert snapshot.row_counts["network_ports"] == 177
    assert snapshot.row_counts["customers"] == 225
    assert snapshot.row_counts["subscription_connections"] == 240
    assert snapshot.row_counts["outages"] == 3
    assert snapshot.row_counts["rules"] == 1
    assert snapshot.row_counts["rule_versions"] == 2
    assert snapshot.row_counts["ground_truth_cases"] == 3


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_expected_customer_segment_and_priority_distribution():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    customers = Customer.objects.filter(data_snapshot=snapshot).select_related("neighborhood")
    vip_customers = customers.filter(priority_level=CustomerPriorityLevel.VIP)

    assert customers.count() == 225
    assert dict(Counter(customers.values_list("segment", flat=True))) == seed_config.CUSTOMER_PLAN[
        "segment_distribution"
    ]
    assert dict(Counter(customers.values_list("priority_level", flat=True))) == (
        seed_config.CUSTOMER_PLAN["priority_distribution"]
    )
    assert dict(Counter(vip_customers.values_list("segment", flat=True))) == (
        seed_config.CUSTOMER_PLAN["vip_segment_distribution"]
    )
    assert dict(Counter(vip_customers.values_list("neighborhood__name", flat=True))) == (
        seed_config.CUSTOMER_PLAN["vip_neighborhood_distribution"]
    )
    assert count_customers_by_subscription_bng(vip_customers) == seed_config.CUSTOMER_PLAN[
        "vip_bng_distribution"
    ]


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_expected_service_package_catalog():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    packages = ServicePackage.objects.filter(data_snapshot=snapshot)
    subscriptions_by_package = Counter(
        Subscription.objects.filter(data_snapshot=snapshot).values_list(
            "service_package__package_code",
            flat=True,
        )
    )

    assert packages.count() == len(seed_config.SERVICE_PACKAGE_CATALOG)
    for package_config in seed_config.SERVICE_PACKAGE_CATALOG:
        package = packages.get(package_code=package_config["package_code"])
        assert package.name == package_config["name"]
        assert package.technology == package_config["technology"]
        assert package.download_mbps == package_config["download_mbps"]
        assert package.upload_mbps == package_config["upload_mbps"]
        assert str(package.monthly_price) == package_config["monthly_price"]
        assert package.commitment_months == package_config["commitment_months"]
        assert package.metadata["synthetic_catalog"] is True
        assert subscriptions_by_package[package.package_code] == package_config[
            "subscription_count"
        ]
    assert all(
        subscription.monthly_price == subscription.service_package.monthly_price
        for subscription in Subscription.objects.filter(data_snapshot=snapshot).select_related(
            "service_package"
        )
    )


@pytest.mark.django_db
def test_seed_maltepe_mvp_connects_every_active_line_to_one_active_subscription():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    active_lines = LineConnection.objects.filter(data_snapshot=snapshot, is_active=True)
    active_connections = SubscriptionConnection.objects.filter(
        data_snapshot=snapshot,
        is_active=True,
    )
    reserved_ports = NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.RESERVED,
    )

    assert active_lines.count() == 240
    assert active_connections.count() == 240
    assert Subscription.objects.filter(data_snapshot=snapshot, is_active=True).count() == 240
    assert not reserved_ports.filter(
        line_connections__subscription_connections__isnull=False
    ).exists()
    assert all(line.subscription_connections.count() == 1 for line in active_lines)
    assert all(
        connection.subscription.connections.count() == 1 for connection in active_connections
    )


@pytest.mark.django_db
def test_seed_maltepe_mvp_preserves_bng_and_technology_subscription_distribution():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    connections = SubscriptionConnection.objects.filter(data_snapshot=snapshot).select_related(
        "line_connection",
        "line_connection__port",
        "line_connection__port__device",
        "subscription",
        "subscription__service_package",
    )
    bng_counts = Counter(get_connection_bng_code(connection) for connection in connections)
    package_technology_counts = Counter(
        connection.subscription.service_package.technology for connection in connections
    )
    gpon_fiber_package_count = sum(
        1
        for connection in connections
        if connection.line_connection.technology == AccessTechnology.GPON
        and connection.subscription.service_package.technology == AccessTechnology.FIBER
    )
    general_fiber_package_count = sum(
        1
        for connection in connections
        if connection.line_connection.technology == AccessTechnology.FIBER
        and connection.subscription.service_package.technology == AccessTechnology.FIBER
    )

    assert dict(bng_counts) == {"BNG-MAL-001": 150, "BNG-MAL-002": 90}
    assert dict(package_technology_counts) == {
        AccessTechnology.FIBER: 130,
        AccessTechnology.VDSL: 90,
        AccessTechnology.ADSL: 20,
    }
    assert gpon_fiber_package_count == 100
    assert general_fiber_package_count == 30


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_expected_double_subscription_customers():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    customers = Customer.objects.filter(data_snapshot=snapshot).annotate(
        subscription_count=Count("subscriptions")
    )
    double_customers = customers.filter(subscription_count=2)
    single_customers = customers.filter(subscription_count=1)

    assert single_customers.count() == 210
    assert double_customers.count() == 15
    assert not customers.exclude(subscription_count__in=[1, 2]).exists()
    for customer in double_customers:
        connections = SubscriptionConnection.objects.filter(
            subscription__customer=customer,
            data_snapshot=snapshot,
        ).select_related(
            "line_connection",
            "line_connection__port",
            "line_connection__port__device",
        )
        line_ids = {connection.line_connection_id for connection in connections}
        bng_codes = {get_connection_bng_code(connection) for connection in connections}
        assert len(line_ids) == 2
        assert len(bng_codes) == 1


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_minimal_alarm_catalog_without_quality_measurements():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    alarm_types = {
        alarm_type.code: alarm_type
        for alarm_type in AlarmType.objects.filter(data_snapshot=snapshot)
    }

    assert set(alarm_types) == {
        "BNG_UNREACHABLE",
        "ACCESS_DEVICE_UNREACHABLE",
        "LINK_DOWN",
    }
    assert alarm_types["BNG_UNREACHABLE"].severity == Severity.CRITICAL
    assert alarm_types["BNG_UNREACHABLE"].category == AlarmCategory.CORE
    assert alarm_types["ACCESS_DEVICE_UNREACHABLE"].severity == Severity.MAJOR
    assert alarm_types["ACCESS_DEVICE_UNREACHABLE"].category == AlarmCategory.ACCESS
    assert alarm_types["LINK_DOWN"].severity == Severity.MAJOR
    assert alarm_types["LINK_DOWN"].category == AlarmCategory.TRANSPORT
    assert QualityMeasurement.objects.filter(data_snapshot=snapshot).count() == 0


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_expected_outages_and_longest_bng_scenario():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    outages = {
        outage.outage_code: outage
        for outage in Outage.objects.filter(data_snapshot=snapshot).select_related(
            "source_device"
        )
    }
    main_outage = outages["OUT-MAL-BNG-001"]
    secondary_outages = [
        outages["OUT-MAL-OLT-001"],
        outages["OUT-MAL-DSLAM-001"],
    ]

    assert set(outages) == {
        "OUT-MAL-BNG-001",
        "OUT-MAL-OLT-001",
        "OUT-MAL-DSLAM-001",
    }
    assert main_outage.source_device.code == "BNG-MAL-001"
    assert main_outage.duration_seconds == 200 * 60
    assert outages["OUT-MAL-OLT-001"].duration_seconds == 45 * 60
    assert outages["OUT-MAL-DSLAM-001"].duration_seconds == 70 * 60
    assert main_outage.duration_seconds == max(
        outage.duration_seconds for outage in outages.values()
    )
    assert all(
        outage.ended_at <= main_outage.started_at or outage.started_at >= main_outage.ended_at
        for outage in secondary_outages
    )
    assert any(
        outage.source_device.metadata["parent_bng"] == "BNG-MAL-002"
        for outage in secondary_outages
    )
    assert main_outage.impact_scope["customer_impact_calculated"] is False
    assert main_outage.metadata["customer_impact_deferred"] is True


@pytest.mark.django_db
def test_seed_maltepe_mvp_links_alarms_incidents_and_operational_events():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    main_incident = Incident.objects.get(
        data_snapshot=snapshot,
        incident_number="INC-MAL-BNG-001",
    )
    incident_alarm_counts = dict(
        IncidentAlarm.objects.filter(data_snapshot=snapshot)
        .values_list("incident__incident_number")
        .annotate(count=Count("id"))
    )
    main_alarm_roles = set(
        main_incident.incident_alarms.values_list("role", flat=True)
    )

    assert Alarm.objects.filter(data_snapshot=snapshot).count() == 4
    assert Incident.objects.filter(data_snapshot=snapshot).count() == 3
    assert IncidentAlarm.objects.filter(data_snapshot=snapshot).count() == 4
    assert incident_alarm_counts == {
        "INC-MAL-BNG-001": 2,
        "INC-MAL-OLT-001": 1,
        "INC-MAL-DSLAM-001": 1,
    }
    assert main_alarm_roles == {
        IncidentAlarmRole.PRIMARY,
        IncidentAlarmRole.SUPPORTING,
    }
    assert OperationalEvent.objects.filter(data_snapshot=snapshot).count() == 12
    assert OperationalEvent.objects.filter(
        data_snapshot=snapshot,
        event_type=OperationalEventType.AUTO_RECOVERY,
    ).count() == 3
    assert all(
        incident.operational_events.count() == 4
        for incident in Incident.objects.filter(data_snapshot=snapshot)
    )
    assert all(
        event.metadata["does_not_change_customer_impact"] is True
        and event.metadata["does_not_claim_partial_restoration"] is True
        for event in OperationalEvent.objects.filter(data_snapshot=snapshot)
    )


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_refund_rule_versions_and_selects_by_outage_date():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    rule = Rule.objects.get(data_snapshot=snapshot, code="REFUND-001")
    versions = {
        version.version: version
        for version in RuleVersion.objects.filter(data_snapshot=snapshot, rule=rule)
    }
    main_outage = Outage.objects.get(data_snapshot=snapshot, outage_code="OUT-MAL-BNG-001")
    v1_outage = Outage.objects.get(data_snapshot=snapshot, outage_code="OUT-MAL-OLT-001")
    main_selection = select_rule_version_for_moment(
        snapshot=snapshot,
        rule_code="REFUND-001",
        moment=main_outage.started_at,
    )
    v1_selection = select_rule_version_for_moment(
        snapshot=snapshot,
        rule_code="REFUND-001",
        moment=v1_outage.started_at,
    )

    assert rule.metadata["synthetic_demo_policy"] is True
    assert set(versions) == {1, 2}
    assert versions[1].condition_tree["conditions"][-1]["value"] == 180
    assert versions[2].condition_tree["conditions"][-1]["value"] == 120
    assert versions[1].action_config["refund_formula"]["percentage"] == "0.10"
    assert versions[2].action_config["refund_formula"]["percentage"] == "0.10"
    assert versions[1].action_config["result_on_missing_required_data"] == "manual_review"
    assert versions[2].action_config["result_on_missing_required_data"] == "manual_review"
    assert main_selection.status == "selected"
    assert main_selection.selected_version == versions[2]
    assert v1_selection.status == "selected"
    assert v1_selection.selected_version == versions[1]


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_ground_truth_cases_for_all_outages():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    cases = {
        case.outage_code: case
        for case in GroundTruthCase.objects.filter(data_snapshot=snapshot)
    }
    main_case = cases["OUT-MAL-BNG-001"]
    olt_case = cases["OUT-MAL-OLT-001"]
    dslam_case = cases["OUT-MAL-DSLAM-001"]

    assert set(cases) == {
        "OUT-MAL-BNG-001",
        "OUT-MAL-OLT-001",
        "OUT-MAL-DSLAM-001",
    }
    assert main_case.expected_source_device_code == "BNG-MAL-001"
    assert main_case.expected_incident_code == "INC-MAL-BNG-001"
    assert main_case.expected_alarm_type_codes == ["BNG_UNREACHABLE", "LINK_DOWN"]
    assert main_case.expected_duration_minutes == 200
    assert main_case.expected_rule_code == "REFUND-001"
    assert main_case.expected_rule_version == 2
    assert main_case.expected_eligibility == GroundTruthEligibility.ELIGIBLE
    assert main_case.expected_reason_code == "duration_threshold_met"
    assert main_case.affected_subscription_count == 150
    assert main_case.affected_subscription_count >= main_case.affected_customer_count
    assert main_case.unaffected_subscription_count == 90
    assert main_case.unaffected_customer_count == 85
    assert main_case.currency == "TRY"
    assert all(code.startswith("SUB-MAL-") for code in main_case.affected_subscription_codes)
    assert all(code.startswith("CUST-MAL-") for code in main_case.affected_customer_codes)
    assert olt_case.expected_rule_version == 1
    assert olt_case.expected_eligibility == GroundTruthEligibility.INELIGIBLE
    assert olt_case.expected_reason_code == "duration_below_threshold"
    assert str(olt_case.expected_total_refund_amount) == "0.00"
    assert dslam_case.expected_rule_version == 2
    assert dslam_case.expected_eligibility == GroundTruthEligibility.INELIGIBLE
    assert dslam_case.expected_reason_code == "duration_below_threshold"
    assert str(dslam_case.expected_total_refund_amount) == "0.00"


@pytest.mark.django_db
def test_seed_maltepe_mvp_ground_truth_hashes_and_refund_total_are_deterministic():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    main_case = GroundTruthCase.objects.get(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-BNG-001",
    )
    affected_subscriptions = Subscription.objects.filter(
        data_snapshot=snapshot,
        subscription_number__in=main_case.affected_subscription_codes,
    )
    expected_total = sum(
        (
            subscription.monthly_price
            * Decimal(seed_config.REFUND_RULE_PLAN["refund_formula"]["percentage"])
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        for subscription in affected_subscriptions
    )

    assert main_case.affected_subscription_codes == sorted(
        main_case.affected_subscription_codes
    )
    assert main_case.affected_customer_codes == sorted(main_case.affected_customer_codes)
    assert main_case.affected_subscription_hash == hash_codes(
        main_case.affected_subscription_codes
    )
    assert main_case.affected_customer_hash == hash_codes(main_case.affected_customer_codes)
    assert main_case.expected_total_refund_amount == expected_total
    assert len(main_case.metadata["subscription_refund_amounts"]) == 150


@pytest.mark.django_db
def test_maltepe_validator_reports_topology_cycle():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    existing_link = NetworkLink.objects.filter(data_snapshot=snapshot).first()

    NetworkLink.objects.create(
        data_snapshot=snapshot,
        link_code="LINK-VALIDATOR-CYCLE",
        source_device=existing_link.target_device,
        target_device=existing_link.source_device,
        capacity_mbps=10000,
    )

    check = get_validation_check(snapshot, "network_link_topology")
    assert check["passed"] is False
    assert check["actual"]["has_cycle"] is True


@pytest.mark.django_db
def test_maltepe_validator_reports_reserved_port_with_active_line():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    reserved_port = NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.RESERVED,
    ).first()
    template_line = LineConnection.objects.filter(data_snapshot=snapshot).first()

    LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code="LINE-VALIDATOR-RESERVED-001",
        port=reserved_port,
        access_segment=template_line.access_segment,
        technology=template_line.technology,
        status=template_line.status,
        valid_from=template_line.valid_from,
        is_active=True,
    )

    check = get_validation_check(snapshot, "reserved_port_integrity")
    assert check["passed"] is False
    assert check["actual"]["reserved_ports_with_active_lines"] == 1


@pytest.mark.django_db
def test_maltepe_validator_reports_dslam_port_with_multiple_active_lines():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    template_line = LineConnection.objects.filter(
        data_snapshot=snapshot,
        port__device__device_type=NetworkDeviceType.DSLAM,
    ).select_related("port", "access_segment").first()

    LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code="LINE-VALIDATOR-DSLAM-DUP-001",
        port=template_line.port,
        access_segment=template_line.access_segment,
        technology=template_line.technology,
        status=template_line.status,
        valid_from=template_line.valid_from,
        is_active=True,
    )

    check = get_validation_check(snapshot, "dslam_port_line_cardinality")
    assert check["passed"] is False
    assert check["actual"]["active_dslam_ports_with_more_than_one_active_line"] == 1


@pytest.mark.django_db
def test_maltepe_validator_reports_overlapping_rule_versions():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    rule = Rule.objects.get(data_snapshot=snapshot, code="REFUND-001")
    existing_version = RuleVersion.objects.get(data_snapshot=snapshot, rule=rule, version=2)

    RuleVersion.objects.create(
        data_snapshot=snapshot,
        rule=rule,
        version=99,
        status=existing_version.status,
        valid_from=existing_version.valid_from,
        valid_to=existing_version.valid_to,
        condition_tree=existing_version.condition_tree,
        action_config=existing_version.action_config,
    )

    check = get_validation_check(snapshot, "rule_version_overlap_integrity")
    assert check["passed"] is False
    assert check["actual"]["overlapping_rule_version_pairs"] == 1


@pytest.mark.django_db
def test_maltepe_validator_reports_broken_ground_truth_code():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    case = GroundTruthCase.objects.get(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-BNG-001",
    )
    broken_codes = ["SUB-MAL-BROKEN", *case.affected_subscription_codes[1:]]

    GroundTruthCase.objects.filter(pk=case.pk).update(
        affected_subscription_codes=broken_codes,
    )

    check = get_validation_check(snapshot, "ground_truth_case_integrity")
    assert check["passed"] is False
    assert check["actual"]["references_are_valid"] is False
    assert check["actual"]["hashes_are_valid"] is False


def get_connection_bng_code(connection: SubscriptionConnection) -> str:
    device = connection.line_connection.port.device
    if device.device_type == NetworkDeviceType.BNG:
        return device.code
    return device.metadata["parent_bng"]


def count_customers_by_subscription_bng(customers) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for customer in customers:
        connections = SubscriptionConnection.objects.filter(subscription__customer=customer)
        bng_codes = {get_connection_bng_code(connection) for connection in connections}
        assert len(bng_codes) == 1
        counts.update(bng_codes)
    return dict(counts)


def collect_seed_codes() -> dict[str, list[str]]:
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    return {
        "devices": list(
            NetworkDevice.objects.filter(data_snapshot=snapshot)
            .order_by("code")
            .values_list("code", flat=True)
        ),
        "ports": list(
            NetworkPort.objects.filter(data_snapshot=snapshot)
            .order_by("port_code")
            .values_list("port_code", flat=True)
        ),
        "customers": list(
            Customer.objects.filter(data_snapshot=snapshot)
            .order_by("customer_number")
            .values_list("customer_number", flat=True)
        ),
        "subscriptions": list(
            Subscription.objects.filter(data_snapshot=snapshot)
            .order_by("subscription_number")
            .values_list("subscription_number", flat=True)
        ),
        "outages": list(
            Outage.objects.filter(data_snapshot=snapshot)
            .order_by("outage_code")
            .values_list("outage_code", flat=True)
        ),
        "ground_truth_cases": list(
            GroundTruthCase.objects.filter(data_snapshot=snapshot)
            .order_by("case_code")
            .values_list("case_code", flat=True)
        ),
    }


def hash_codes(codes: list[str]) -> str:
    encoded = json.dumps(codes, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def get_validation_check(snapshot: DataSnapshot, name: str) -> dict:
    report = validate_maltepe_mvp_snapshot(snapshot)
    return next(check for check in report["checks"] if check["name"] == name)
