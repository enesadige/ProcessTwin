from collections import Counter
from dataclasses import dataclass
from typing import Any

from django.db.models import Q

from apps.customers.models import SubscriptionConnection, SubscriptionStatus
from apps.datasets.models import DataSnapshot
from apps.network.models import LineConnectionStatus, NetworkPortStatus
from apps.network.services.topology import NetworkTopologyService
from apps.operations.models import Outage
from apps.operations.services.outages import OutageService


class CustomerImpactServiceError(Exception):
    """Base error for deterministic customer impact calculations."""


class CustomerImpactInputError(CustomerImpactServiceError):
    """Raised when outage, snapshot, or evaluation inputs are invalid."""


@dataclass(frozen=True)
class CustomerImpactResult:
    outage_code: str
    source_device_code: str
    snapshot: dict[str, Any]
    evaluation_window: dict[str, str]
    affected_subscription_codes: list[str]
    affected_subscription_count: int
    affected_customer_codes: list[str]
    affected_customer_count: int
    package_technology_counts: dict[str, int]
    customer_segment_counts: dict[str, int]
    customer_priority_counts: dict[str, int]


class CustomerImpactService:
    def __init__(
        self,
        *,
        topology_service: NetworkTopologyService | None = None,
        outage_service: OutageService | None = None,
    ) -> None:
        self.topology_service = topology_service or NetworkTopologyService()
        self.outage_service = outage_service or OutageService()

    def calculate_impact(
        self,
        *,
        outage: Outage,
        snapshot: DataSnapshot,
        evaluation_time=None,
    ) -> CustomerImpactResult:
        self._validate_inputs(outage=outage, snapshot=snapshot)
        duration = self.outage_service.calculate_duration(
            outage=outage,
            evaluation_time=evaluation_time,
        )
        window_start = outage.started_at
        window_end = evaluation_time if duration.is_ongoing else outage.ended_at
        subgraph = self.topology_service.get_subgraph(
            device=outage.source_device,
            snapshot=snapshot,
            evaluation_time=window_end,
        )
        topology_device_ids = [device.id for device in subgraph.devices]
        connections = list(
            self._get_affected_connections(
                snapshot=snapshot,
                topology_device_ids=topology_device_ids,
                window_start=window_start,
                window_end=window_end,
            )
        )
        subscriptions = [connection.subscription for connection in connections]
        customers_by_code = {
            subscription.customer.customer_number: subscription.customer
            for subscription in subscriptions
        }
        affected_subscription_codes = sorted(
            subscription.subscription_number for subscription in subscriptions
        )
        affected_customer_codes = sorted(customers_by_code)

        return CustomerImpactResult(
            outage_code=outage.outage_code,
            source_device_code=outage.source_device.code,
            snapshot={
                "id": snapshot.id,
                "snapshot_key": snapshot.snapshot_key,
                "dataset_slug": snapshot.dataset_version.slug,
            },
            evaluation_window={
                "started_at": window_start.isoformat(),
                "ended_at": window_end.isoformat(),
                "duration_seconds": str(duration.seconds),
            },
            affected_subscription_codes=affected_subscription_codes,
            affected_subscription_count=len(affected_subscription_codes),
            affected_customer_codes=affected_customer_codes,
            affected_customer_count=len(affected_customer_codes),
            package_technology_counts=normalize_counter(
                Counter(
                    subscription.service_package.technology for subscription in subscriptions
                )
            ),
            customer_segment_counts=normalize_counter(
                Counter(customer.segment for customer in customers_by_code.values())
            ),
            customer_priority_counts=normalize_counter(
                Counter(customer.priority_level for customer in customers_by_code.values())
            ),
        )

    def _validate_inputs(self, *, outage: Outage, snapshot: DataSnapshot) -> None:
        if outage is None:
            raise CustomerImpactInputError("An Outage must be provided.")
        if snapshot is None:
            raise CustomerImpactInputError("A DataSnapshot must be provided explicitly.")
        if not outage.pk:
            raise CustomerImpactInputError("Outage must be a persisted Outage.")
        if not snapshot.pk:
            raise CustomerImpactInputError("Snapshot must be a persisted DataSnapshot.")
        if outage.data_snapshot_id != snapshot.id:
            raise CustomerImpactInputError(
                f"Outage {outage.outage_code} does not belong to snapshot "
                f"{snapshot.snapshot_key}."
            )
        if outage.source_device_id is None:
            raise CustomerImpactInputError(
                f"Outage {outage.outage_code} has no source device."
            )

    def _get_affected_connections(
        self,
        *,
        snapshot: DataSnapshot,
        topology_device_ids: list[int],
        window_start,
        window_end,
    ):
        return (
            SubscriptionConnection.objects.filter(
                data_snapshot=snapshot,
                is_active=True,
                line_connection__data_snapshot=snapshot,
                line_connection__is_active=True,
                line_connection__status=LineConnectionStatus.ACTIVE,
                line_connection__port__data_snapshot=snapshot,
                line_connection__port__inventory_status=NetworkPortStatus.ACTIVE,
                line_connection__port__device_id__in=topology_device_ids,
                subscription__data_snapshot=snapshot,
                subscription__is_active=True,
                subscription__status=SubscriptionStatus.ACTIVE,
                subscription__customer__data_snapshot=snapshot,
                subscription__service_package__data_snapshot=snapshot,
            )
            .filter(valid_from__lt=window_end)
            .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=window_start))
            .filter(subscription__valid_from__lt=window_end)
            .filter(
                Q(subscription__valid_to__isnull=True)
                | Q(subscription__valid_to__gt=window_start)
            )
            .filter(line_connection__valid_from__lt=window_end)
            .filter(
                Q(line_connection__valid_to__isnull=True)
                | Q(line_connection__valid_to__gt=window_start)
            )
            .select_related(
                "subscription",
                "subscription__customer",
                "subscription__service_package",
                "line_connection",
                "line_connection__port",
                "line_connection__port__device",
            )
            .order_by("subscription__subscription_number")
        )


def normalize_counter(counter: Counter) -> dict[str, int]:
    return dict(sorted(counter.items()))
