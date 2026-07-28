from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from apps.customers.models import (
    Customer,
    CustomerPriorityLevel,
    ServicePackage,
    Subscription,
    SubscriptionConnection,
    SubscriptionStatus,
)
from apps.datasets.models import DataSnapshot
from apps.geography.models import City, District, Neighborhood
from apps.network.models import AccessTechnology, LineConnection, NetworkDeviceType
from data_generator.configs import maltepe_mvp_v1 as seed_config


@dataclass(frozen=True)
class CustomerSeedSpec:
    customer: Customer
    bng_code: str
    subscription_slots: int


def seed_customer_subscriptions(
    *,
    snapshot: DataSnapshot,
    city: City,
    district: District,
    neighborhoods_by_name: dict[str, Neighborhood],
    reference_datetime,
) -> dict[str, int]:
    packages_by_technology = create_service_packages(snapshot)
    customer_specs = create_customers(snapshot, city, district, neighborhoods_by_name)
    lines_by_bng_and_package_technology = group_lines_by_bng_and_package_technology(snapshot)
    package_queues = expand_package_queues(packages_by_technology)
    subscriptions_created, connections_created = create_subscriptions_and_connections(
        snapshot=snapshot,
        customer_specs=customer_specs,
        lines_by_bng_and_package_technology=lines_by_bng_and_package_technology,
        package_queues=package_queues,
        reference_datetime=reference_datetime,
    )

    return {
        "customers": len(customer_specs),
        "service_packages": sum(len(packages) for packages in packages_by_technology.values()),
        "subscriptions": subscriptions_created,
        "subscription_connections": connections_created,
        "vip_customers": Customer.objects.filter(
            data_snapshot=snapshot,
            priority_level=CustomerPriorityLevel.VIP,
        ).count(),
    }


def create_service_packages(snapshot: DataSnapshot) -> dict[str, list[ServicePackage]]:
    packages_by_technology: dict[str, list[ServicePackage]] = defaultdict(list)
    for package_config in seed_config.SERVICE_PACKAGE_CATALOG:
        package = save_clean(
            ServicePackage(
                data_snapshot=snapshot,
                package_code=package_config["package_code"],
                name=package_config["name"],
                technology=package_config["technology"],
                download_mbps=package_config["download_mbps"],
                upload_mbps=package_config["upload_mbps"],
                monthly_price=Decimal(package_config["monthly_price"]),
                commitment_months=package_config["commitment_months"],
                metadata={
                    **seed_config.SERVICE_PACKAGE_METADATA,
                    "seed_role": "service_package",
                    "subscription_count_target": package_config["subscription_count"],
                },
            )
        )
        packages_by_technology[package.technology].append(package)
    return dict(packages_by_technology)


def create_customers(
    snapshot: DataSnapshot,
    city: City,
    district: District,
    neighborhoods_by_name: dict[str, Neighborhood],
) -> list[CustomerSeedSpec]:
    customer_rows = build_customer_rows()
    bng_sequence = [row["bng_code"] for row in customer_rows]
    multi_subscription_indexes = set(build_multi_subscription_indexes(bng_sequence))
    customer_specs: list[CustomerSeedSpec] = []

    for index, row in enumerate(customer_rows):
        neighborhood_name = row["neighborhood"]
        customer = save_clean(
            Customer(
                data_snapshot=snapshot,
                customer_number=f"CUST-MAL-{index + 1:04d}",
                display_name=f"Maltepe Synthetic Customer {index + 1:04d}",
                segment=row["segment"],
                priority_level=row["priority_level"],
                city=city,
                district=district,
                neighborhood=neighborhoods_by_name[neighborhood_name],
                metadata={
                    "seed_role": "customer",
                    "synthetic": True,
                    "location_scope": "customer_record_location",
                },
            )
        )
        customer_specs.append(
            CustomerSeedSpec(
                customer=customer,
                bng_code=row["bng_code"],
                subscription_slots=2 if index in multi_subscription_indexes else 1,
            )
        )

    return customer_specs


def build_customer_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for bng_code, neighborhood_names in seed_config.BNG_DISTRIBUTION.items():
        for neighborhood_name in neighborhood_names:
            segment_counts = seed_config.CUSTOMER_PLAN["customer_segment_by_neighborhood"][
                neighborhood_name
            ]
            vip_segment_counts = seed_config.CUSTOMER_PLAN["vip_segment_by_neighborhood"][
                neighborhood_name
            ]
            for segment, total_count in segment_counts.items():
                vip_count = vip_segment_counts[segment]
                standard_count = total_count - vip_count
                rows.extend(
                    build_customer_rows_for_segment(
                        bng_code=bng_code,
                        neighborhood_name=neighborhood_name,
                        segment=segment,
                        priority_level=CustomerPriorityLevel.VIP,
                        count=vip_count,
                    )
                )
                rows.extend(
                    build_customer_rows_for_segment(
                        bng_code=bng_code,
                        neighborhood_name=neighborhood_name,
                        segment=segment,
                        priority_level=CustomerPriorityLevel.STANDARD,
                        count=standard_count,
                    )
                )
    validate_customer_rows(rows)
    return rows


def build_customer_rows_for_segment(
    *,
    bng_code: str,
    neighborhood_name: str,
    segment: str,
    priority_level: str,
    count: int,
) -> list[dict[str, str]]:
    return [
        {
            "bng_code": bng_code,
            "neighborhood": neighborhood_name,
            "segment": segment,
            "priority_level": priority_level,
        }
        for _index in range(count)
    ]


def validate_customer_rows(rows: list[dict[str, str]]) -> None:
    if len(rows) != seed_config.CUSTOMER_PLAN["unique_customers"]:
        raise ValueError("Customer row count does not match config.")
    if Counter(row["segment"] for row in rows) != seed_config.CUSTOMER_PLAN["segment_distribution"]:
        raise ValueError("Customer segment distribution does not match config.")
    if (
        Counter(row["priority_level"] for row in rows)
        != seed_config.CUSTOMER_PLAN["priority_distribution"]
    ):
        raise ValueError("Customer priority distribution does not match config.")
    vip_rows = [row for row in rows if row["priority_level"] == CustomerPriorityLevel.VIP]
    if (
        Counter(row["segment"] for row in vip_rows)
        != seed_config.CUSTOMER_PLAN["vip_segment_distribution"]
    ):
        raise ValueError("VIP segment distribution does not match config.")
    if (
        Counter(row["neighborhood"] for row in vip_rows)
        != seed_config.CUSTOMER_PLAN["vip_neighborhood_distribution"]
    ):
        raise ValueError("VIP neighborhood distribution does not match config.")
    if Counter(row["bng_code"] for row in vip_rows) != seed_config.CUSTOMER_PLAN[
        "vip_bng_distribution"
    ]:
        raise ValueError("VIP BNG distribution does not match config.")


def build_multi_subscription_indexes(bng_sequence: list[str]) -> list[int]:
    positions: list[int] = []
    for bng_code, plan in seed_config.CUSTOMER_PLAN["bng_customer_distribution"].items():
        bng_positions = [index for index, value in enumerate(bng_sequence) if value == bng_code]
        positions.extend(bng_positions[-plan["multi_subscription_customers"] :])
    return positions


def expand_counts(counts: dict[str, int]) -> list[str]:
    values: list[str] = []
    for key, count in counts.items():
        values.extend([key] * count)
    return values


def group_lines_by_bng_and_package_technology(
    snapshot: DataSnapshot,
) -> dict[str, dict[str, deque[LineConnection]]]:
    grouped: dict[str, dict[str, deque[LineConnection]]] = defaultdict(lambda: defaultdict(deque))
    lines = (
        LineConnection.objects.filter(data_snapshot=snapshot, is_active=True)
        .select_related("port", "port__device", "access_segment")
        .order_by("line_code")
    )
    for line in lines:
        bng_code = get_line_bng_code(line)
        package_technology = get_package_technology_for_line(line)
        grouped[bng_code][package_technology].append(line)
    return grouped


def get_line_bng_code(line: LineConnection) -> str:
    device = line.port.device
    if device.device_type == NetworkDeviceType.BNG:
        return device.code
    parent_bng = device.metadata.get("parent_bng")
    if not parent_bng:
        raise ValueError(f"Line {line.line_code} device has no parent_bng metadata.")
    return parent_bng


def get_package_technology_for_line(line: LineConnection) -> str:
    if line.technology in {AccessTechnology.GPON, AccessTechnology.FIBER}:
        return AccessTechnology.FIBER
    return line.technology


def expand_package_queues(
    packages_by_technology: dict[str, list[ServicePackage]],
) -> dict[str, deque[ServicePackage]]:
    queues: dict[str, deque[ServicePackage]] = {}
    for package_config in seed_config.SERVICE_PACKAGE_CATALOG:
        package = next(
            package
            for package in packages_by_technology[package_config["technology"]]
            if package.package_code == package_config["package_code"]
        )
        queues.setdefault(package.technology, deque()).extend(
            [package] * package_config["subscription_count"]
        )
    return queues


def create_subscriptions_and_connections(
    *,
    snapshot: DataSnapshot,
    customer_specs: list[CustomerSeedSpec],
    lines_by_bng_and_package_technology: dict[str, dict[str, deque[LineConnection]]],
    package_queues: dict[str, deque[ServicePackage]],
    reference_datetime,
) -> tuple[int, int]:
    valid_from = reference_datetime - timedelta(days=45)
    subscription_count = 0
    connection_count = 0
    for bng_code in seed_config.BNG_DISTRIBUTION:
        specs = [spec for spec in customer_specs if spec.bng_code == bng_code]
        subscription_customers = [
            spec.customer for spec in specs for _slot in range(spec.subscription_slots)
        ]
        for customer in subscription_customers:
            line = pop_next_line(lines_by_bng_and_package_technology[bng_code])
            package_technology = get_package_technology_for_line(line)
            package = package_queues[package_technology].popleft()
            subscription_count += 1
            subscription = save_clean(
                Subscription(
                    data_snapshot=snapshot,
                    subscription_number=f"SUB-MAL-{subscription_count:04d}",
                    customer=customer,
                    service_package=package,
                    status=SubscriptionStatus.ACTIVE,
                    valid_from=valid_from,
                    is_active=True,
                    monthly_price=package.monthly_price,
                    metadata={
                        "seed_role": "subscription",
                        "synthetic": True,
                        "line_technology": line.technology,
                        "source_bng": bng_code,
                        "monthly_price_copied_from_package": package.package_code,
                    },
                )
            )
            save_clean(
                SubscriptionConnection(
                    data_snapshot=snapshot,
                    subscription=subscription,
                    line_connection=line,
                    valid_from=valid_from,
                    is_active=True,
                    port_identifier=f"{line.port.device.code}/{line.port.port_code}",
                    metadata={
                        "seed_role": "subscription_connection",
                        "source_bng": bng_code,
                        "line_code": line.line_code,
                    },
                )
            )
            connection_count += 1

    if any(package_queue for package_queue in package_queues.values()):
        raise ValueError("Not all service package subscription slots were consumed.")
    return subscription_count, connection_count


def pop_next_line(line_groups: dict[str, deque[LineConnection]]) -> LineConnection:
    for technology in (
        AccessTechnology.GPON,
        AccessTechnology.FIBER,
        AccessTechnology.VDSL,
        AccessTechnology.ADSL,
    ):
        package_technology = get_package_technology_value(technology)
        if line_groups[package_technology]:
            return line_groups[package_technology].popleft()
    raise ValueError("No line connection left for subscription allocation.")


def get_package_technology_value(line_technology: str) -> str:
    if line_technology in {AccessTechnology.GPON, AccessTechnology.FIBER}:
        return AccessTechnology.FIBER
    return line_technology


def save_clean(instance):
    instance.full_clean()
    instance.save()
    return instance
