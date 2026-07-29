from dataclasses import dataclass
from typing import Any

from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice, NetworkDeviceType
from apps.network.services.topology import NetworkTopologyService
from apps.operations.models import Alarm, AlarmSourceKind

TIME_WINDOW_SECONDS = 30 * 60
CORRELATION_THRESHOLD = 60
TYPE_COMPATIBILITY_PAIRS = frozenset(
    {
        frozenset({"BNG_UNREACHABLE", "LINK_DOWN"}),
        frozenset({"ACCESS_DEVICE_UNREACHABLE", "LINK_DOWN"}),
    }
)


class AlarmCorrelationServiceError(Exception):
    """Base error for deterministic alarm correlation failures."""


class AlarmCorrelationInputError(AlarmCorrelationServiceError):
    """Raised when alarm or snapshot inputs are invalid."""


@dataclass(frozen=True)
class AlarmCorrelationResult:
    anchor_alarm_code: str
    candidate_alarm_code: str
    evidence_score: int
    correlated: bool
    time_difference_seconds: int
    topology_relation: str
    type_compatibility: str
    evidence: list[dict[str, Any]]
    snapshot: dict[str, Any]


class AlarmCorrelationService:
    def __init__(self, *, topology_service: NetworkTopologyService | None = None) -> None:
        self.topology_service = topology_service or NetworkTopologyService()

    def find_correlations(
        self,
        *,
        anchor_alarm: Alarm,
        snapshot: DataSnapshot,
    ) -> list[AlarmCorrelationResult]:
        self._validate_inputs(anchor_alarm=anchor_alarm, snapshot=snapshot)
        candidates = (
            Alarm.objects.filter(data_snapshot=snapshot)
            .exclude(pk=anchor_alarm.pk)
            .select_related(
                "alarm_type",
                "device",
                "device__district",
                "network_link",
                "network_link__source_device",
                "network_link__target_device",
                "network_port",
                "network_port__device",
                "line_connection",
                "line_connection__port",
                "line_connection__port__device",
                "failure_domain",
                "subscription_connection",
                "subscription_connection__line_connection",
                "subscription_connection__line_connection__port",
                "subscription_connection__line_connection__port__device",
            )
            .order_by("alarm_id")
        )
        results = [
            self.score_pair(
                anchor_alarm=anchor_alarm,
                candidate_alarm=candidate,
                snapshot=snapshot,
            )
            for candidate in candidates
        ]
        return sorted(
            results,
            key=lambda result: (-result.evidence_score, result.candidate_alarm_code),
        )

    def score_pair(
        self,
        *,
        anchor_alarm: Alarm,
        candidate_alarm: Alarm,
        snapshot: DataSnapshot,
    ) -> AlarmCorrelationResult:
        self._validate_inputs(anchor_alarm=anchor_alarm, snapshot=snapshot)
        if candidate_alarm is None:
            raise AlarmCorrelationInputError("A candidate Alarm must be provided.")
        if not candidate_alarm.pk:
            raise AlarmCorrelationInputError("Candidate alarm must be a persisted Alarm.")
        if candidate_alarm.data_snapshot_id != snapshot.id:
            raise AlarmCorrelationInputError(
                f"Candidate alarm {candidate_alarm.alarm_id} does not belong to snapshot "
                f"{snapshot.snapshot_key}."
            )
        if candidate_alarm.pk == anchor_alarm.pk:
            raise AlarmCorrelationInputError("Anchor alarm cannot be scored against itself.")

        time_difference_seconds = abs(
            int((candidate_alarm.detected_at - anchor_alarm.detected_at).total_seconds())
        )
        time_score = score_time_proximity(time_difference_seconds)
        topology_relation = self._get_topology_relation(anchor_alarm, candidate_alarm, snapshot)
        topology_score = score_topology_relation(topology_relation)
        type_compatibility = get_type_compatibility(
            anchor_alarm, candidate_alarm, topology_relation
        )
        type_score = score_type_compatibility(type_compatibility)
        anchor_device = anchor_alarm.get_source_device()
        candidate_device = candidate_alarm.get_source_device()
        same_district = (
            anchor_device is not None
            and candidate_device is not None
            and anchor_device.district_id is not None
            and anchor_device.district_id == candidate_device.district_id
        )
        district_score = 10 if same_district else 0
        evidence_score = min(
            100,
            time_score + topology_score + type_score + district_score,
        )
        return AlarmCorrelationResult(
            anchor_alarm_code=anchor_alarm.alarm_id,
            candidate_alarm_code=candidate_alarm.alarm_id,
            evidence_score=evidence_score,
            correlated=evidence_score >= CORRELATION_THRESHOLD,
            time_difference_seconds=time_difference_seconds,
            topology_relation=topology_relation,
            type_compatibility=type_compatibility,
            evidence=[
                {
                    "criterion": "time_proximity",
                    "score": time_score,
                    "time_difference_seconds": time_difference_seconds,
                },
                {
                    "criterion": "topology_relation",
                    "score": topology_score,
                    "relation": topology_relation,
                },
                {
                    "criterion": "alarm_type_compatibility",
                    "score": type_score,
                    "compatibility": type_compatibility,
                },
                {
                    "criterion": "same_district",
                    "score": district_score,
                    "same_district": same_district,
                },
            ],
            snapshot={
                "id": snapshot.id,
                "snapshot_key": snapshot.snapshot_key,
                "dataset_slug": snapshot.dataset_version.slug,
            },
        )

    def _validate_inputs(self, *, anchor_alarm: Alarm, snapshot: DataSnapshot) -> None:
        if snapshot is None:
            raise AlarmCorrelationInputError("A DataSnapshot must be provided explicitly.")
        if anchor_alarm is None:
            raise AlarmCorrelationInputError("An anchor Alarm must be provided.")
        if not snapshot.pk:
            raise AlarmCorrelationInputError("Snapshot must be a persisted DataSnapshot.")
        if not anchor_alarm.pk:
            raise AlarmCorrelationInputError("Anchor alarm must be a persisted Alarm.")
        if anchor_alarm.data_snapshot_id != snapshot.id:
            raise AlarmCorrelationInputError(
                f"Anchor alarm {anchor_alarm.alarm_id} does not belong to snapshot "
                f"{snapshot.snapshot_key}."
            )

    def _get_topology_relation(
        self,
        anchor_alarm: Alarm,
        candidate_alarm: Alarm,
        snapshot: DataSnapshot,
    ) -> str:
        anchor_device = anchor_alarm.get_source_device()
        candidate_device = candidate_alarm.get_source_device()
        if anchor_device is None or candidate_device is None:
            if self._share_failure_domain(anchor_alarm, candidate_alarm, snapshot):
                return "shared_failure_domain"
            return "unrelated"
        if anchor_device.id == candidate_device.id:
            return "same_device"
        anchor_children = self.topology_service.get_children(
            device=anchor_device,
            snapshot=snapshot,
        )
        candidate_children = self.topology_service.get_children(
            device=candidate_device,
            snapshot=snapshot,
        )
        if any(device.id == candidate_device.id for device in anchor_children) or any(
            device.id == anchor_device.id for device in candidate_children
        ):
            return "direct_parent_child"
        if self._share_bng_branch(anchor_alarm, candidate_alarm, snapshot):
            return "same_bng_branch"
        if self._share_failure_domain(anchor_alarm, candidate_alarm, snapshot):
            return "shared_failure_domain"
        return "unrelated"

    def _share_bng_branch(
        self,
        anchor_alarm: Alarm,
        candidate_alarm: Alarm,
        snapshot: DataSnapshot,
    ) -> bool:
        anchor_device = anchor_alarm.get_source_device()
        candidate_device = candidate_alarm.get_source_device()
        if anchor_device is None or candidate_device is None:
            return False
        anchor_bng_code = get_bng_branch_code(
            anchor_device,
            self.topology_service.get_ancestors(
                device=anchor_device,
                snapshot=snapshot,
            ),
        )
        candidate_bng_code = get_bng_branch_code(
            candidate_device,
            self.topology_service.get_ancestors(
                device=candidate_device,
                snapshot=snapshot,
            ),
        )
        return bool(anchor_bng_code and anchor_bng_code == candidate_bng_code)

    def _share_failure_domain(
        self,
        anchor_alarm: Alarm,
        candidate_alarm: Alarm,
        snapshot: DataSnapshot,
    ) -> bool:
        anchor_domains = get_alarm_failure_domain_ids(anchor_alarm, snapshot)
        candidate_domains = get_alarm_failure_domain_ids(candidate_alarm, snapshot)
        return bool(anchor_domains and anchor_domains & candidate_domains)


def get_bng_branch_code(device: NetworkDevice | None, ancestors) -> str | None:
    if device is None:
        return None
    if device.device_type == NetworkDeviceType.BNG:
        return device.code
    for ancestor in ancestors:
        if ancestor.device_type == NetworkDeviceType.BNG:
            return ancestor.code
    return None


def score_time_proximity(time_difference_seconds: int) -> int:
    if time_difference_seconds <= 5 * 60:
        return 30
    if time_difference_seconds <= 15 * 60:
        return 20
    if time_difference_seconds <= TIME_WINDOW_SECONDS:
        return 10
    return 0


def score_topology_relation(topology_relation: str) -> int:
    return {
        "same_device": 40,
        "direct_parent_child": 30,
        "shared_failure_domain": 35,
        "same_bng_branch": 20,
        "unrelated": 0,
    }[topology_relation]


def get_type_compatibility(
    anchor_alarm: Alarm,
    candidate_alarm: Alarm,
    topology_relation: str,
) -> str:
    anchor_alarm_type_code = anchor_alarm.alarm_type.code
    candidate_alarm_type_code = candidate_alarm.alarm_type.code
    pair = frozenset({anchor_alarm_type_code, candidate_alarm_type_code})
    if pair in TYPE_COMPATIBILITY_PAIRS:
        return "known_compatible_pair"
    if anchor_alarm_type_code == candidate_alarm_type_code and topology_relation != "unrelated":
        return "same_type_with_topology"
    if (
        anchor_alarm.alarm_type.correlation_family
        and anchor_alarm.alarm_type.correlation_family
        == candidate_alarm.alarm_type.correlation_family
        and topology_relation != "unrelated"
    ):
        return "same_correlation_family"
    return "none"


def score_type_compatibility(type_compatibility: str) -> int:
    return {
        "known_compatible_pair": 20,
        "same_type_with_topology": 15,
        "same_correlation_family": 20,
        "none": 0,
    }[type_compatibility]


def get_alarm_failure_domain_ids(alarm: Alarm, snapshot: DataSnapshot) -> set[int]:
    source_kind = alarm.get_source_kind()
    if source_kind == AlarmSourceKind.FAILURE_DOMAIN and alarm.failure_domain_id:
        return {alarm.failure_domain_id}
    domain_ids: set[int] = set()
    source_device = alarm.get_source_device()
    if source_device is not None:
        domain_ids.update(
            source_device.failure_domain_memberships.filter(
                data_snapshot=snapshot,
            ).values_list("failure_domain_id", flat=True)
        )
    if source_kind == AlarmSourceKind.NETWORK_LINK and alarm.network_link_id:
        domain_ids.update(
            alarm.network_link.failure_domain_memberships.filter(
                data_snapshot=snapshot,
            ).values_list("failure_domain_id", flat=True)
        )
    if source_kind == AlarmSourceKind.LINE_CONNECTION and alarm.line_connection_id:
        domain_ids.update(
            alarm.line_connection.failure_domain_memberships.filter(
                data_snapshot=snapshot,
            ).values_list("failure_domain_id", flat=True)
        )
    if source_kind == AlarmSourceKind.SUBSCRIPTION_CONNECTION and alarm.subscription_connection_id:
        domain_ids.update(
            alarm.subscription_connection.line_connection.failure_domain_memberships.filter(
                data_snapshot=snapshot,
            ).values_list("failure_domain_id", flat=True)
        )
    return domain_ids
