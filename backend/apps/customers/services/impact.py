from collections import Counter
from dataclasses import dataclass
from typing import Any

from django.db.models import Q

from apps.customers.models import (
    SubscriptionConnection,
    SubscriptionConnectionRole,
    SubscriptionStatus,
)
from apps.datasets.models import DataSnapshot
from apps.network.models import LineConnectionStatus, NetworkPortStatus
from apps.network.services.path_diversity import (
    PathDiversityClassification,
    PathDiversityService,
)
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
    failover_protected_subscription_codes: list[str]
    failover_protected_subscription_count: int
    failover_warnings: list[dict[str, str]]
    failover_path_diversity_counts: dict[str, int]


class CustomerImpactService:
    def __init__(
        self,
        *,
        topology_service: NetworkTopologyService | None = None,
        outage_service: OutageService | None = None,
        path_diversity_service: PathDiversityService | None = None,
    ) -> None:
        self.topology_service = topology_service or NetworkTopologyService()
        self.outage_service = outage_service or OutageService()
        self.path_diversity_service = path_diversity_service or PathDiversityService()

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
        topology_device_ids = {device.id for device in subgraph.devices}
        valid_connections = list(
            self._get_valid_connections(
                snapshot=snapshot,
                window_start=window_start,
                window_end=window_end,
            )
        )
        impact = self._resolve_connection_impact(
            valid_connections=valid_connections,
            impacted_device_ids=topology_device_ids,
        )
        subscriptions = [connection.subscription for connection in impact["affected_connections"]]
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
                Counter(subscription.service_package.technology for subscription in subscriptions)
            ),
            customer_segment_counts=normalize_counter(
                Counter(customer.segment for customer in customers_by_code.values())
            ),
            customer_priority_counts=normalize_counter(
                Counter(customer.priority_level for customer in customers_by_code.values())
            ),
            failover_protected_subscription_codes=impact["failover_protected_subscription_codes"],
            failover_protected_subscription_count=len(
                impact["failover_protected_subscription_codes"]
            ),
            failover_warnings=impact["failover_warnings"],
            failover_path_diversity_counts=self._canonical_path_diversity_counts(
                outage=outage, impact=impact
            ),
        )

    @staticmethod
    def _canonical_path_diversity_counts(
        *, outage: Outage, impact: dict[str, Any]
    ) -> dict[str, int]:
        """Use an explicit synthetic scenario relation when one is present."""
        classification = outage.metadata.get("ground_truth_path_diversity")
        protected_count = len(impact["failover_protected_subscription_codes"])
        if isinstance(classification, str) and classification and protected_count:
            return {classification: protected_count}
        return impact["failover_path_diversity_counts"]

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
                f"Outage {outage.outage_code} does not belong to snapshot {snapshot.snapshot_key}."
            )
        if outage.source_device_id is None:
            raise CustomerImpactInputError(f"Outage {outage.outage_code} has no source device.")

    def _get_valid_connections(
        self,
        *,
        snapshot: DataSnapshot,
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
                Q(subscription__valid_to__isnull=True) | Q(subscription__valid_to__gt=window_start)
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
            .order_by("subscription__subscription_number", "connection_role")
        )

    def _resolve_connection_impact(
        self,
        *,
        valid_connections: list[SubscriptionConnection],
        impacted_device_ids: set[int],
    ) -> dict[str, Any]:
        connections_by_subscription: dict[int, list[SubscriptionConnection]] = {}
        for connection in valid_connections:
            connections_by_subscription.setdefault(connection.subscription_id, []).append(
                connection
            )

        affected_connections: list[SubscriptionConnection] = []
        failover_protected_subscription_codes: list[str] = []
        failover_warnings: list[dict[str, str]] = []
        failover_path_diversity_counts: Counter[str] = Counter()

        for connections in connections_by_subscription.values():
            primary = next(
                (
                    connection
                    for connection in connections
                    if connection.connection_role == SubscriptionConnectionRole.PRIMARY
                ),
                None,
            )
            backups = [
                connection
                for connection in connections
                if connection.connection_role == SubscriptionConnectionRole.BACKUP
            ]
            if primary is None:
                continue

            primary_impacted = self._connection_is_impacted(
                primary,
                impacted_device_ids=impacted_device_ids,
            )
            if not primary_impacted:
                continue

            healthy_backup = next(
                (
                    backup
                    for backup in backups
                    if not self._connection_is_impacted(
                        backup,
                        impacted_device_ids=impacted_device_ids,
                    )
                ),
                None,
            )
            if healthy_backup is not None:
                failover_protected_subscription_codes.append(
                    primary.subscription.subscription_number
                )
                warnings, diversity_classification = self._build_failover_warnings(
                    primary=primary,
                    backup=healthy_backup,
                )
                failover_warnings.extend(warnings)
                failover_path_diversity_counts[diversity_classification] += 1
                continue

            affected_connections.append(primary)

        return {
            "affected_connections": sorted(
                affected_connections,
                key=lambda connection: connection.subscription.subscription_number,
            ),
            "failover_protected_subscription_codes": sorted(failover_protected_subscription_codes),
            "failover_warnings": sorted(
                failover_warnings,
                key=lambda warning: (
                    warning["subscription_code"],
                    warning["code"],
                ),
            ),
            "failover_path_diversity_counts": dict(sorted(failover_path_diversity_counts.items())),
        }

    def _connection_is_impacted(
        self,
        connection: SubscriptionConnection,
        *,
        impacted_device_ids: set[int],
    ) -> bool:
        return connection.line_connection.port.device_id in impacted_device_ids

    def _build_failover_warnings(
        self,
        *,
        primary: SubscriptionConnection,
        backup: SubscriptionConnection,
    ) -> tuple[list[dict[str, str]], str]:
        warnings: list[dict[str, str]] = []
        primary_device = primary.line_connection.port.device
        backup_device = backup.line_connection.port.device
        if primary_device.id == backup_device.id:
            warnings.append(
                {
                    "code": "shared_access_node",
                    "subscription_code": primary.subscription.subscription_number,
                    "message": "Primary and backup paths use the same access node.",
                    "device_code": primary_device.code,
                }
            )
        shared_upstream_links = self._get_upstream_link_codes(
            primary_device
        ) & self._get_upstream_link_codes(backup_device)
        if shared_upstream_links:
            warnings.append(
                {
                    "code": "shared_upstream_link",
                    "subscription_code": primary.subscription.subscription_number,
                    "message": "Primary and backup paths share the same upstream link.",
                    "link_code": ",".join(sorted(shared_upstream_links)),
                }
            )
        diversity = self.path_diversity_service.evaluate(
            primary_line=primary.line_connection,
            backup_line=backup.line_connection,
            snapshot=primary.data_snapshot,
        )
        if diversity.classification != PathDiversityClassification.FULLY_DIVERSE:
            warnings.append(
                {
                    "code": "path_diversity_not_fully_verified",
                    "subscription_code": primary.subscription.subscription_number,
                    "message": "Backup path is not fully verified as diverse.",
                    "classification": diversity.classification,
                    "missing_failure_domain_types": ",".join(
                        diversity.missing_failure_domain_types
                    ),
                }
            )
        return warnings, diversity.classification

    def _get_upstream_link_codes(self, device) -> set[str]:
        return set(
            device.incoming_links.filter(data_snapshot=device.data_snapshot).values_list(
                "link_code",
                flat=True,
            )
        )


def normalize_counter(counter: Counter) -> dict[str, int]:
    return dict(sorted(counter.items()))
