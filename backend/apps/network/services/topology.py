from dataclasses import dataclass

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice, NetworkLink


class NetworkTopologyError(Exception):
    """Base error for deterministic network topology traversal failures."""


class NetworkTopologyCycleError(NetworkTopologyError):
    """Raised when topology traversal detects a cycle."""


class NetworkTopologyInputError(NetworkTopologyError):
    """Raised when snapshot, device, or evaluation time input is invalid."""


@dataclass(frozen=True)
class NetworkSubgraph:
    devices: list[NetworkDevice]
    links: list[NetworkLink]


class NetworkTopologyService:
    def get_children(
        self,
        *,
        device: NetworkDevice,
        snapshot: DataSnapshot,
        evaluation_time=None,
    ) -> list[NetworkDevice]:
        self._validate_inputs(device=device, snapshot=snapshot, evaluation_time=evaluation_time)
        return list(
            NetworkDevice.objects.filter(
                data_snapshot=snapshot,
                incoming_links__data_snapshot=snapshot,
                incoming_links__source_device=device,
            )
            .distinct()
            .order_by("code")
        )

    def get_ancestors(
        self,
        *,
        device: NetworkDevice,
        snapshot: DataSnapshot,
        evaluation_time=None,
    ) -> list[NetworkDevice]:
        self._validate_inputs(device=device, snapshot=snapshot, evaluation_time=evaluation_time)
        ancestors: list[NetworkDevice] = []
        visited_device_ids = {device.id}
        current = device

        while True:
            parent_links = list(
                NetworkLink.objects.filter(
                    data_snapshot=snapshot,
                    target_device=current,
                )
                .select_related("source_device")
                .order_by("source_device__code", "link_code")
            )
            if not parent_links:
                return ancestors
            if len(parent_links) > 1:
                raise NetworkTopologyInputError(
                    f"Device {current.code} has multiple parent links in snapshot "
                    f"{snapshot.snapshot_key}."
                )
            parent = parent_links[0].source_device
            if parent.id in visited_device_ids:
                raise NetworkTopologyCycleError(
                    f"Topology cycle detected while resolving ancestors for {device.code}."
                )
            ancestors.append(parent)
            visited_device_ids.add(parent.id)
            current = parent

    def get_subgraph(
        self,
        *,
        device: NetworkDevice,
        snapshot: DataSnapshot,
        evaluation_time=None,
    ) -> NetworkSubgraph:
        self._validate_inputs(device=device, snapshot=snapshot, evaluation_time=evaluation_time)
        devices_by_id = {device.id: device}
        links_by_id: dict[int, NetworkLink] = {}
        visiting: set[int] = set()
        visited: set[int] = set()

        def walk(current: NetworkDevice) -> None:
            if current.id in visiting:
                raise NetworkTopologyCycleError(
                    f"Topology cycle detected while resolving subgraph for {device.code}."
                )
            if current.id in visited:
                return
            visiting.add(current.id)
            child_links = (
                NetworkLink.objects.filter(data_snapshot=snapshot, source_device=current)
                .select_related("target_device")
                .order_by("target_device__code", "link_code")
            )
            for link in child_links:
                links_by_id[link.id] = link
                child = link.target_device
                devices_by_id[child.id] = child
                walk(child)
            visiting.remove(current.id)
            visited.add(current.id)

        walk(device)
        return NetworkSubgraph(
            devices=sorted(devices_by_id.values(), key=lambda item: item.code),
            links=sorted(links_by_id.values(), key=lambda item: item.link_code),
        )

    def _validate_inputs(
        self,
        *,
        device: NetworkDevice,
        snapshot: DataSnapshot,
        evaluation_time,
    ):
        if snapshot is None:
            raise NetworkTopologyInputError("A DataSnapshot must be provided explicitly.")
        if device is None:
            raise NetworkTopologyInputError("A NetworkDevice must be provided.")
        if not snapshot.pk:
            raise NetworkTopologyInputError("Snapshot must be a persisted DataSnapshot.")
        if not device.pk:
            raise NetworkTopologyInputError("Device must be a persisted NetworkDevice.")
        if device.data_snapshot_id != snapshot.id:
            raise NetworkTopologyInputError(
                f"Device {device.code} does not belong to snapshot {snapshot.snapshot_key}."
            )
        resolved_time = self._resolve_evaluation_time(snapshot, evaluation_time)
        if timezone.is_naive(resolved_time):
            raise NetworkTopologyInputError("evaluation_time must be timezone-aware.")
        return resolved_time

    def _resolve_evaluation_time(self, snapshot: DataSnapshot, evaluation_time):
        if evaluation_time is not None:
            return evaluation_time
        reference_datetime = snapshot.dataset_version.config.get("reference_datetime")
        if not reference_datetime:
            raise NetworkTopologyInputError(
                "evaluation_time is required when snapshot config has no reference_datetime."
            )
        parsed = parse_datetime(reference_datetime)
        if parsed is None:
            raise NetworkTopologyInputError(
                "snapshot config reference_datetime must be a valid ISO datetime."
            )
        return parsed
