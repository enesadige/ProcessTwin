from datetime import timedelta

import pytest
from django.utils import timezone

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.geography.models import City, District
from apps.network.models import (
    AccessSegment,
    AccessTechnology,
    FailureDomain,
    FailureDomainType,
    LineConnection,
    LineConnectionFailureDomainMembership,
    NetworkDevice,
    NetworkDeviceAccessRole,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
)
from apps.network.services.path_diversity import (
    PathDiversityClassification,
    PathDiversityService,
)


@pytest.mark.django_db
def test_same_access_node_paths_are_not_fully_diverse():
    context = create_diversity_context()
    primary = create_line_path(
        context,
        bng_code="BNG-MAL-001",
        aggregation_code="MAGG-MAL-001",
        access_code="AN-MAL-001",
        suffix="PRIMARY",
    )
    backup = create_line_path(
        context,
        bng_code="BNG-MAL-002",
        aggregation_code="MAGG-MAL-002",
        access_code="AN-MAL-001",
        suffix="BACKUP",
    )

    result = PathDiversityService().evaluate(
        primary_line=primary,
        backup_line=backup,
        snapshot=context["snapshot"],
    )

    assert result.classification == PathDiversityClassification.PARTIALLY_DIVERSE


@pytest.mark.django_db
def test_same_aggregation_node_paths_are_not_fully_diverse():
    context = create_diversity_context()
    primary = create_line_path(
        context,
        bng_code="BNG-MAL-001",
        aggregation_code="MAGG-MAL-001",
        access_code="AN-MAL-001",
        suffix="PRIMARY",
    )
    backup = create_line_path(
        context,
        bng_code="BNG-MAL-001",
        aggregation_code="MAGG-MAL-001",
        access_code="AN-MAL-002",
        suffix="BACKUP",
    )

    result = PathDiversityService().evaluate(
        primary_line=primary,
        backup_line=backup,
        snapshot=context["snapshot"],
    )

    assert result.classification == PathDiversityClassification.PARTIALLY_DIVERSE
    assert not next(
        item for item in result.evidence if item["code"] == "aggregation_comparison"
    )["passed"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "domain_type",
    [FailureDomainType.POWER_ZONE, FailureDomainType.FIBER_ROUTE],
)
def test_shared_failure_domain_produces_shared_risk(domain_type):
    context = create_diversity_context()
    primary = create_line_path(
        context,
        bng_code="BNG-MAL-001",
        aggregation_code="MAGG-MAL-001",
        access_code="AN-MAL-001",
        suffix="PRIMARY",
    )
    backup = create_line_path(
        context,
        bng_code="BNG-MAL-002",
        aggregation_code="MAGG-MAL-002",
        access_code="AN-MAL-002",
        suffix="BACKUP",
    )
    add_required_domains(context, primary, "PRIMARY")
    add_required_domains(context, backup, "BACKUP")
    shared = FailureDomain.objects.create(
        data_snapshot=context["snapshot"],
        code=f"{domain_type.upper()}-SHARED",
        name=f"Shared {domain_type}",
        domain_type=domain_type,
    )
    LineConnectionFailureDomainMembership.objects.create(
        data_snapshot=context["snapshot"],
        line_connection=primary,
        failure_domain=shared,
    )
    LineConnectionFailureDomainMembership.objects.create(
        data_snapshot=context["snapshot"],
        line_connection=backup,
        failure_domain=shared,
    )

    result = PathDiversityService().evaluate(
        primary_line=primary,
        backup_line=backup,
        snapshot=context["snapshot"],
    )

    assert result.classification == PathDiversityClassification.SHARED_RISK
    assert shared.code in result.shared_failure_domains[domain_type]


@pytest.mark.django_db
def test_distinct_paths_with_complete_risk_data_are_fully_diverse():
    context = create_diversity_context()
    primary = create_line_path(
        context,
        bng_code="BNG-MAL-001",
        aggregation_code="MAGG-MAL-001",
        access_code="AN-MAL-001",
        suffix="PRIMARY",
    )
    backup = create_line_path(
        context,
        bng_code="BNG-MAL-002",
        aggregation_code="MAGG-MAL-002",
        access_code="AN-MAL-002",
        suffix="BACKUP",
    )
    add_required_domains(context, primary, "PRIMARY")
    add_required_domains(context, backup, "BACKUP")

    result = PathDiversityService().evaluate(
        primary_line=primary,
        backup_line=backup,
        snapshot=context["snapshot"],
    )

    assert result.classification == PathDiversityClassification.FULLY_DIVERSE
    assert result.missing_failure_domain_types == []


@pytest.mark.django_db
def test_missing_failure_domain_data_does_not_report_fully_diverse():
    context = create_diversity_context()
    primary = create_line_path(
        context,
        bng_code="BNG-MAL-001",
        aggregation_code="MAGG-MAL-001",
        access_code="AN-MAL-001",
        suffix="PRIMARY",
    )
    backup = create_line_path(
        context,
        bng_code="BNG-MAL-002",
        aggregation_code="MAGG-MAL-002",
        access_code="AN-MAL-002",
        suffix="BACKUP",
    )

    result = PathDiversityService().evaluate(
        primary_line=primary,
        backup_line=backup,
        snapshot=context["snapshot"],
    )

    assert result.classification == PathDiversityClassification.UNKNOWN
    assert result.missing_failure_domain_types == [
        FailureDomainType.FIBER_ROUTE,
        FailureDomainType.POWER_ZONE,
        FailureDomainType.SITE,
    ]


def create_diversity_context():
    dataset = DatasetVersion.objects.create(
        name="Path diversity dataset",
        generator_version="path-diversity-v1",
        seed="path-diversity-seed",
    )
    snapshot = DataSnapshot.objects.create(dataset_version=dataset, name="Initial snapshot")
    city = City.objects.create(name="İstanbul", plate_code="34")
    district = District.objects.create(city=city, name="Maltepe")
    return {"snapshot": snapshot, "city": city, "district": district, "devices": {}}


def create_line_path(
    context,
    *,
    bng_code: str,
    aggregation_code: str,
    access_code: str,
    suffix: str,
) -> LineConnection:
    snapshot = context["snapshot"]
    bng = get_or_create_device(context, bng_code, NetworkDeviceType.BNG)
    aggregation = get_or_create_device(
        context,
        aggregation_code,
        NetworkDeviceType.METRO_AGGREGATION,
    )
    access_node = get_or_create_device(
        context,
        access_code,
        NetworkDeviceType.ACCESS_NODE,
        access_role=NetworkDeviceAccessRole.CORPORATE_FIBER_AGGREGATION,
    )
    NetworkLink.objects.get_or_create(
        data_snapshot=snapshot,
        link_code=f"LINK-{bng_code}-{aggregation_code}",
        defaults={"source_device": bng, "target_device": aggregation},
    )
    NetworkLink.objects.get_or_create(
        data_snapshot=snapshot,
        link_code=f"LINK-{aggregation_code}-{access_code}",
        defaults={"source_device": aggregation, "target_device": access_node},
    )
    port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=access_node,
        port_code=f"PORT-{suffix}",
    )
    segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code=f"SEG-{suffix}",
        name=f"Segment {suffix}",
        technology=AccessTechnology.FIBER,
        serving_device=access_node,
        city=context["city"],
        district=context["district"],
    )
    return LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code=f"LINE-{suffix}",
        port=port,
        access_segment=segment,
        technology=AccessTechnology.FIBER,
        valid_from=timezone.now() - timedelta(days=1),
    )


def get_or_create_device(context, code, device_type, access_role=None):
    if code in context["devices"]:
        return context["devices"][code]
    device = NetworkDevice.objects.create(
        data_snapshot=context["snapshot"],
        code=code,
        device_type=device_type,
        access_role=access_role,
        city=context["city"],
        district=context["district"],
    )
    context["devices"][code] = device
    return device


def add_required_domains(context, line: LineConnection, suffix: str) -> None:
    for domain_type in (
        FailureDomainType.SITE,
        FailureDomainType.POWER_ZONE,
        FailureDomainType.FIBER_ROUTE,
    ):
        domain = FailureDomain.objects.create(
            data_snapshot=context["snapshot"],
            code=f"{domain_type.upper()}-{suffix}",
            name=f"{domain_type} {suffix}",
            domain_type=domain_type,
        )
        LineConnectionFailureDomainMembership.objects.create(
            data_snapshot=context["snapshot"],
            line_connection=line,
            failure_domain=domain,
        )
