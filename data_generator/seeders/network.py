from datetime import timedelta

from apps.datasets.models import DataSnapshot
from apps.geography.models import City, District, Neighborhood
from apps.network.models import (
    AccessSegment,
    AccessTechnology,
    LineConnection,
    LineConnectionStatus,
    NetworkDevice,
    NetworkDeviceStatus,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
    NetworkPortStatus,
    NetworkPortType,
)
from data_generator.configs import maltepe_mvp_v1 as seed_config


def seed_network_topology(
    *,
    snapshot: DataSnapshot,
    city: City,
    district: District,
    neighborhoods_by_name: dict[str, Neighborhood],
    reference_datetime,
) -> dict[str, int]:
    devices = create_network_devices(snapshot, city, district, neighborhoods_by_name)
    links_created = create_network_links(snapshot, devices)
    segments = create_access_segments(snapshot, city, district, neighborhoods_by_name, devices)
    ports_created, lines_created = create_ports_and_lines(
        snapshot=snapshot,
        devices=devices,
        segments=segments,
        reference_datetime=reference_datetime,
    )

    return {
        "network_devices": len(devices),
        "network_links": links_created,
        "network_ports": ports_created,
        "access_segments": len(segments),
        "line_connections": lines_created,
    }


def create_network_devices(
    snapshot: DataSnapshot,
    city: City,
    district: District,
    neighborhoods_by_name: dict[str, Neighborhood],
) -> dict[str, NetworkDevice]:
    devices: dict[str, NetworkDevice] = {}
    for bng_code in seed_config.BNG_DISTRIBUTION:
        devices[bng_code] = save_clean(
            NetworkDevice(
                data_snapshot=snapshot,
                code=bng_code,
                name=bng_code.replace("-", " "),
                device_type=NetworkDeviceType.BNG,
                inventory_status=NetworkDeviceStatus.ACTIVE,
                vendor="Synthetic",
                model_name="BNG logical node",
                city=city,
                district=district,
                metadata={"seed_role": "bng", "mvp_anchor": bng_code == "BNG-MAL-001"},
            )
        )

    for bng_code, neighborhood_names in seed_config.BNG_DISTRIBUTION.items():
        for neighborhood_name in neighborhood_names:
            short_code = seed_config.NEIGHBORHOOD_CODES[neighborhood_name]
            neighborhood = neighborhoods_by_name[neighborhood_name]
            for device_type, prefix, label in (
                (NetworkDeviceType.OLT, "OLT", "OLT"),
                (NetworkDeviceType.DSLAM, "DSLAM", "DSLAM"),
            ):
                code = f"{prefix}-MAL-{short_code}-001"
                devices[code] = save_clean(
                    NetworkDevice(
                        data_snapshot=snapshot,
                        code=code,
                        name=f"Maltepe {neighborhood_name} {label} 001",
                        device_type=device_type,
                        inventory_status=NetworkDeviceStatus.ACTIVE,
                        vendor="Synthetic",
                        model_name=f"{label} logical access node",
                        city=city,
                        district=district,
                        neighborhood=neighborhood,
                        metadata={
                            "seed_role": device_type,
                            "parent_bng": bng_code,
                            "neighborhood": neighborhood_name,
                        },
                    )
                )

    for access_node in seed_config.PORT_CAPACITY_PLAN["general_fiber"]["access_nodes"]:
        neighborhood = neighborhoods_by_name[access_node["neighborhood"]]
        devices[access_node["code"]] = save_clean(
            NetworkDevice(
                data_snapshot=snapshot,
                code=access_node["code"],
                name=access_node["name"],
                device_type=NetworkDeviceType.ACCESS_NODE,
                inventory_status=NetworkDeviceStatus.ACTIVE,
                vendor="Synthetic",
                model_name="General fiber access node",
                city=city,
                district=district,
                neighborhood=neighborhood,
                metadata={
                    "seed_role": "general_fiber_access_node",
                    "parent_bng": access_node["bng_code"],
                    "neighborhood": access_node["neighborhood"],
                },
            )
        )

    return devices


def create_network_links(snapshot: DataSnapshot, devices: dict[str, NetworkDevice]) -> int:
    created = 0
    for bng_code, neighborhood_names in seed_config.BNG_DISTRIBUTION.items():
        bng = devices[bng_code]
        for neighborhood_name in neighborhood_names:
            short_code = seed_config.NEIGHBORHOOD_CODES[neighborhood_name]
            for target_code in (f"OLT-MAL-{short_code}-001", f"DSLAM-MAL-{short_code}-001"):
                save_clean(
                    NetworkLink(
                        data_snapshot=snapshot,
                        link_code=f"LINK-{bng_code}-{target_code}",
                        source_device=bng,
                        target_device=devices[target_code],
                        capacity_mbps=10000,
                        metadata={"seed_role": "bng_to_access_device"},
                    )
                )
                created += 1

    for access_node in seed_config.PORT_CAPACITY_PLAN["general_fiber"]["access_nodes"]:
        bng_code = access_node["bng_code"]
        access_node_code = access_node["code"]
        save_clean(
            NetworkLink(
                data_snapshot=snapshot,
                link_code=f"LINK-{bng_code}-{access_node_code}",
                source_device=devices[bng_code],
                target_device=devices[access_node_code],
                capacity_mbps=10000,
                metadata={"seed_role": "bng_to_general_fiber_access_node"},
            )
        )
        created += 1

    return created


def create_access_segments(
    snapshot: DataSnapshot,
    city: City,
    district: District,
    neighborhoods_by_name: dict[str, Neighborhood],
    devices: dict[str, NetworkDevice],
) -> dict[str, AccessSegment]:
    segments: dict[str, AccessSegment] = {}
    for neighborhood_name in seed_config.NEIGHBORHOODS:
        short_code = seed_config.NEIGHBORHOOD_CODES[neighborhood_name]
        neighborhood = neighborhoods_by_name[neighborhood_name]
        olt_code = f"OLT-MAL-{short_code}-001"
        dslam_code = f"DSLAM-MAL-{short_code}-001"
        gpon_count = sum(seed_config.GPON_FAN_OUT_BY_NEIGHBORHOOD[neighborhood_name])
        dslam_distribution = seed_config.DSLAM_PORT_DISTRIBUTION[neighborhood_name]

        segments[f"SEG-MAL-{short_code}-GPON"] = create_segment(
            snapshot=snapshot,
            code=f"SEG-MAL-{short_code}-GPON",
            name=f"Maltepe {neighborhood_name} GPON access",
            technology=AccessTechnology.GPON,
            serving_device=devices[olt_code],
            city=city,
            district=district,
            neighborhood=neighborhood,
            estimated_customer_count=gpon_count,
            metadata={"seed_role": "gpon_access_segment"},
        )
        segments[f"SEG-MAL-{short_code}-VDSL"] = create_segment(
            snapshot=snapshot,
            code=f"SEG-MAL-{short_code}-VDSL",
            name=f"Maltepe {neighborhood_name} VDSL access",
            technology=AccessTechnology.VDSL,
            serving_device=devices[dslam_code],
            city=city,
            district=district,
            neighborhood=neighborhood,
            estimated_customer_count=dslam_distribution["vdsl"],
            metadata={"seed_role": "vdsl_access_segment"},
        )
        segments[f"SEG-MAL-{short_code}-ADSL"] = create_segment(
            snapshot=snapshot,
            code=f"SEG-MAL-{short_code}-ADSL",
            name=f"Maltepe {neighborhood_name} ADSL access",
            technology=AccessTechnology.ADSL,
            serving_device=devices[dslam_code],
            city=city,
            district=district,
            neighborhood=neighborhood,
            estimated_customer_count=dslam_distribution["adsl"],
            metadata={"seed_role": "adsl_access_segment"},
        )

    for access_node in seed_config.PORT_CAPACITY_PLAN["general_fiber"]["access_nodes"]:
        neighborhood_name = access_node["neighborhood"]
        short_code = seed_config.NEIGHBORHOOD_CODES[neighborhood_name]
        segments[f"SEG-MAL-{short_code}-GF"] = create_segment(
            snapshot=snapshot,
            code=f"SEG-MAL-{short_code}-GF",
            name=f"Maltepe {neighborhood_name} general fiber access",
            technology=AccessTechnology.FIBER,
            serving_device=devices[access_node["code"]],
            city=city,
            district=district,
            neighborhood=neighborhoods_by_name[neighborhood_name],
            estimated_customer_count=access_node["active_ports"],
            metadata={
                "seed_role": "general_fiber_access_segment",
                "parent_bng": access_node["bng_code"],
            },
        )

    return segments


def create_segment(
    *,
    snapshot: DataSnapshot,
    code: str,
    name: str,
    technology: str,
    serving_device: NetworkDevice,
    city: City,
    district: District,
    neighborhood: Neighborhood,
    estimated_customer_count: int,
    metadata: dict,
) -> AccessSegment:
    return save_clean(
        AccessSegment(
            data_snapshot=snapshot,
            segment_code=code,
            name=name,
            technology=technology,
            serving_device=serving_device,
            city=city,
            district=district,
            neighborhood=neighborhood,
            estimated_customer_count=estimated_customer_count,
            metadata=metadata,
        )
    )


def create_ports_and_lines(
    *,
    snapshot: DataSnapshot,
    devices: dict[str, NetworkDevice],
    segments: dict[str, AccessSegment],
    reference_datetime,
) -> tuple[int, int]:
    valid_from = reference_datetime - timedelta(days=90)
    port_count = 0
    line_count = 0

    for neighborhood_name in seed_config.NEIGHBORHOODS:
        short_code = seed_config.NEIGHBORHOOD_CODES[neighborhood_name]
        olt = devices[f"OLT-MAL-{short_code}-001"]
        gpon_segment = segments[f"SEG-MAL-{short_code}-GPON"]
        for port_index, fan_out in enumerate(
            seed_config.GPON_FAN_OUT_BY_NEIGHBORHOOD[neighborhood_name],
            start=1,
        ):
            port = create_port(
                snapshot=snapshot,
                device=olt,
                port_code=f"PON-{port_index:02d}",
                port_type=NetworkPortType.ACCESS,
                status=NetworkPortStatus.ACTIVE,
                capacity_mbps=2500,
                metadata={"seed_role": "gpon_pon_port", "fan_out_target": fan_out},
            )
            port_count += 1
            for line_index in range(1, fan_out + 1):
                line_code = f"LINE-MAL-{short_code}-GPON-{port_index:02d}-{line_index:03d}"
                create_line(
                    snapshot=snapshot,
                    line_code=line_code,
                    port=port,
                    access_segment=gpon_segment,
                    technology=AccessTechnology.GPON,
                    valid_from=valid_from,
                    metadata={"seed_role": "gpon_line", "pon_port": port.port_code},
                )
                line_count += 1

        if neighborhood_name in seed_config.GPON_RESERVED_PORT_NEIGHBORHOODS:
            create_port(
                snapshot=snapshot,
                device=olt,
                port_code="PON-RSV-01",
                port_type=NetworkPortType.ACCESS,
                status=NetworkPortStatus.RESERVED,
                capacity_mbps=2500,
                metadata={"seed_role": "reserved_gpon_pon_port"},
            )
            port_count += 1

    for neighborhood_name in seed_config.NEIGHBORHOODS:
        short_code = seed_config.NEIGHBORHOOD_CODES[neighborhood_name]
        dslam = devices[f"DSLAM-MAL-{short_code}-001"]
        distribution = seed_config.DSLAM_PORT_DISTRIBUTION[neighborhood_name]
        port_sequence = 1
        for technology in (AccessTechnology.VDSL, AccessTechnology.ADSL):
            segment = segments[f"SEG-MAL-{short_code}-{technology.value.upper()}"]
            for line_index in range(1, distribution[technology.value] + 1):
                port = create_port(
                    snapshot=snapshot,
                    device=dslam,
                    port_code=f"CUST-{port_sequence:03d}",
                    port_type=NetworkPortType.CUSTOMER,
                    status=NetworkPortStatus.ACTIVE,
                    capacity_mbps=get_dslam_capacity_mbps(technology),
                    metadata={"seed_role": f"{technology.value}_customer_port"},
                )
                port_count += 1
                create_line(
                    snapshot=snapshot,
                    line_code=f"LINE-MAL-{short_code}-{technology.value.upper()}-{line_index:03d}",
                    port=port,
                    access_segment=segment,
                    technology=technology,
                    valid_from=valid_from,
                    metadata={"seed_role": f"{technology.value}_line"},
                )
                line_count += 1
                port_sequence += 1

        for reserved_index in range(1, distribution["reserved"] + 1):
            create_port(
                snapshot=snapshot,
                device=dslam,
                port_code=f"RSV-{reserved_index:03d}",
                port_type=NetworkPortType.CUSTOMER,
                status=NetworkPortStatus.RESERVED,
                capacity_mbps=0,
                metadata={"seed_role": "reserved_dslam_customer_port"},
            )
            port_count += 1

    for access_node in seed_config.PORT_CAPACITY_PLAN["general_fiber"]["access_nodes"]:
        short_code = seed_config.NEIGHBORHOOD_CODES[access_node["neighborhood"]]
        device = devices[access_node["code"]]
        segment = segments[f"SEG-MAL-{short_code}-GF"]
        for active_index in range(1, access_node["active_ports"] + 1):
            port = create_port(
                snapshot=snapshot,
                device=device,
                port_code=f"GF-{active_index:03d}",
                port_type=NetworkPortType.CUSTOMER,
                status=NetworkPortStatus.ACTIVE,
                capacity_mbps=1000,
                metadata={"seed_role": "general_fiber_customer_port"},
            )
            port_count += 1
            create_line(
                snapshot=snapshot,
                line_code=f"LINE-MAL-{short_code}-GF-{active_index:03d}",
                port=port,
                access_segment=segment,
                technology=AccessTechnology.FIBER,
                valid_from=valid_from,
                metadata={
                    "seed_role": "general_fiber_line",
                    "parent_bng": access_node["bng_code"],
                },
            )
            line_count += 1

        for reserved_index in range(1, access_node["reserved_ports"] + 1):
            create_port(
                snapshot=snapshot,
                device=device,
                port_code=f"GF-RSV-{reserved_index:03d}",
                port_type=NetworkPortType.CUSTOMER,
                status=NetworkPortStatus.RESERVED,
                capacity_mbps=1000,
                metadata={"seed_role": "reserved_general_fiber_customer_port"},
            )
            port_count += 1

    return port_count, line_count


def create_port(
    *,
    snapshot: DataSnapshot,
    device: NetworkDevice,
    port_code: str,
    port_type: str,
    status: str,
    capacity_mbps: int,
    metadata: dict,
) -> NetworkPort:
    return save_clean(
        NetworkPort(
            data_snapshot=snapshot,
            device=device,
            port_code=port_code,
            port_type=port_type,
            inventory_status=status,
            capacity_mbps=capacity_mbps,
            metadata=metadata,
        )
    )


def create_line(
    *,
    snapshot: DataSnapshot,
    line_code: str,
    port: NetworkPort,
    access_segment: AccessSegment,
    technology: str,
    valid_from,
    metadata: dict,
) -> LineConnection:
    return save_clean(
        LineConnection(
            data_snapshot=snapshot,
            line_code=line_code,
            port=port,
            access_segment=access_segment,
            technology=technology,
            status=LineConnectionStatus.ACTIVE,
            valid_from=valid_from,
            is_active=True,
            metadata=metadata,
        )
    )


def get_dslam_capacity_mbps(technology: str) -> int:
    if technology == AccessTechnology.VDSL:
        return 100
    return 24


def save_clean(instance):
    instance.full_clean()
    instance.save()
    return instance
