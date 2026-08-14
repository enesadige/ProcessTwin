"""Read-only, snapshot-local topology summaries for analyst-facing results."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.db.models import Count
from django.utils import timezone

from apps.customers.models import SubscriptionConnection
from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice, NetworkLink
from apps.network.services.topology import NetworkTopologyService
from apps.operations.contracts import CustomerImpactStatus
from apps.operations.models import CausalEvent, CustomerImpactAssessment


class TopologySummaryInputError(Exception):
    """Raised when a requested topology summary is outside its snapshot."""


@dataclass(frozen=True)
class TopologySummary:
    snapshot_key: str
    root_device: dict
    upstream_devices: list[dict]
    downstream_devices: list[dict]
    links: list[dict]
    connection_roles: dict[str, int]
    impact_scope: dict | None
    downstream_total: int

    def to_payload(self) -> dict:
        return {
            "snapshot_key": self.snapshot_key,
            "root_device": self.root_device,
            "upstream_devices": self.upstream_devices,
            "downstream_devices": self.downstream_devices,
            "downstream_total": self.downstream_total,
            "links": self.links,
            "connection_roles": self.connection_roles,
            "impact_scope": self.impact_scope,
        }


class TopologySummaryService:
    """Build a deliberately small topology view without deriving operations facts."""

    MAX_DOWNSTREAM_DEVICES = 8

    def build(
        self,
        *,
        snapshot: DataSnapshot,
        device: NetworkDevice,
        causal_event: CausalEvent | None = None,
    ) -> TopologySummary:
        if device.data_snapshot_id != snapshot.id:
            raise TopologySummaryInputError("Device does not belong to the requested snapshot.")
        if causal_event and causal_event.data_snapshot_id != snapshot.id:
            raise TopologySummaryInputError(
                "Causal event does not belong to the requested snapshot."
            )
        if causal_event and causal_event.root_device_id != device.id:
            raise TopologySummaryInputError(
                "Causal event root device does not match the requested device."
            )

        ancestors = NetworkTopologyService().get_ancestors(
            device=device,
            snapshot=snapshot,
            evaluation_time=causal_event.started_at if causal_event else timezone.now(),
        )
        upstream_devices = list(reversed(ancestors))
        downstream_links = list(
            NetworkLink.objects.filter(data_snapshot=snapshot, source_device=device)
            .select_related("target_device")
            .order_by("target_device__code", "link_code")
        )
        first_level_ids = [link.target_device_id for link in downstream_links]
        second_level_links = list(
            NetworkLink.objects.filter(
                data_snapshot=snapshot,
                source_device_id__in=first_level_ids,
            )
            .select_related("target_device")
            .order_by("source_device__code", "target_device__code", "link_code")
        )
        candidate_downstream_links: list[NetworkLink] = []
        seen_downstream_ids = {device.id}
        for link in [*downstream_links, *second_level_links]:
            if link.target_device_id in seen_downstream_ids:
                continue
            candidate_downstream_links.append(link)
            seen_downstream_ids.add(link.target_device_id)
        displayed_downstream_links = candidate_downstream_links[: self.MAX_DOWNSTREAM_DEVICES]
        displayed_downstream_ids = {link.target_device_id for link in displayed_downstream_links}
        displayed_device_ids = {
            device.id,
            *(ancestor.id for ancestor in upstream_devices),
            *displayed_downstream_ids,
        }
        displayed_links = list(
            NetworkLink.objects.filter(
                data_snapshot=snapshot,
                source_device_id__in=displayed_device_ids,
                target_device_id__in=displayed_device_ids,
            )
            .select_related("source_device", "target_device")
            .order_by("link_code")
        )

        return TopologySummary(
            snapshot_key=snapshot.snapshot_key,
            root_device=self._device_payload(device),
            upstream_devices=[self._device_payload(item) for item in upstream_devices],
            downstream_devices=[
                self._device_payload(link.target_device) for link in displayed_downstream_links
            ],
            downstream_total=len(candidate_downstream_links),
            links=[
                self._link_payload(link)
                for link in displayed_links
                if link.source_device_id in displayed_device_ids
                and link.target_device_id in displayed_device_ids
            ],
            connection_roles=self._connection_roles(
                snapshot=snapshot,
                device_ids=displayed_device_ids,
            ),
            impact_scope=self._impact_scope(snapshot=snapshot, causal_event=causal_event),
        )

    @staticmethod
    def _device_payload(device: NetworkDevice) -> dict:
        return {
            "code": device.code,
            "name": device.display_name,
            "device_type": device.device_type,
            "device_type_label": device.get_device_type_display(),
            "location": device.location_name,
        }

    @staticmethod
    def _link_payload(link: NetworkLink) -> dict:
        return {
            "code": link.link_code,
            "source_device_code": link.source_device.code,
            "target_device_code": link.target_device.code,
            "status": link.status,
            "capacity_mbps": link.capacity_mbps,
            "link_layer": link.metadata.get("link_layer"),
        }

    @staticmethod
    def _connection_roles(*, snapshot: DataSnapshot, device_ids: set[int]) -> dict[str, int]:
        rows = (
            SubscriptionConnection.objects.filter(
                data_snapshot=snapshot,
                is_active=True,
                line_connection__port__device_id__in=device_ids,
            )
            .values("connection_role")
            .annotate(count=Count("id"))
        )
        return dict(Counter({row["connection_role"]: row["count"] for row in rows}))

    @staticmethod
    def _impact_scope(*, snapshot: DataSnapshot, causal_event: CausalEvent | None) -> dict | None:
        if causal_event is None:
            return None
        assessments = CustomerImpactAssessment.objects.filter(
            data_snapshot=snapshot,
            causal_event=causal_event,
        )
        if not assessments.exists():
            return None
        verified = assessments.filter(status=CustomerImpactStatus.VERIFIED_IMPACT.value)
        return {
            "potential_connection_count": assessments.filter(potential_impact=True).count(),
            "verified_connection_count": verified.count(),
            "verified_subscription_count": verified.values("subscription_id").distinct().count(),
            "verified_customer_count": verified.values("subscription__customer_id")
            .distinct()
            .count(),
        }
