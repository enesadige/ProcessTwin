from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any

from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice, NetworkDeviceType
from apps.network.services.topology import NetworkTopologyService
from apps.operations.contracts import CorrelationReason, CorrelationRole
from apps.operations.models import Alarm, AlarmSourceKind, CausalEvent

TIME_WINDOW_SECONDS = 30 * 60
CAUSAL_PROPAGATION_WINDOW_SECONDS = 2 * 60 * 60
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


class CrossIncidentCorrelationStatus(StrEnum):
    VERIFIED_RELATION = "verified_relation"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_RELATION = "no_relation"


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
    correlation_role: str = CorrelationRole.UNRELATED.value
    reason_codes: list[str] | None = None
    description: str = "No causal correlation was established."


@dataclass(frozen=True)
class CrossIncidentCorrelationResult:
    """Backend-owned evidence for a bounded comparison between two causal events."""

    anchor_event_code: str
    candidate_event_code: str
    correlation_status: CrossIncidentCorrelationStatus
    time_difference_seconds: int
    within_window: bool
    requested_window_seconds: int
    topology_relation: str
    resource_relation: str
    event_relation: str | None
    root_symptom_status: str
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
        window_seconds = (
            CAUSAL_PROPAGATION_WINDOW_SECONDS
            if anchor_alarm.causal_event_id
            else TIME_WINDOW_SECONDS
        )
        window_start = anchor_alarm.detected_at - timedelta(seconds=window_seconds)
        window_end = anchor_alarm.detected_at + timedelta(seconds=window_seconds)
        candidates = (
            Alarm.objects.filter(
                data_snapshot=snapshot,
                detected_at__gte=window_start,
                detected_at__lte=window_end,
            )
            .exclude(pk=anchor_alarm.pk)
            .select_related(
                "alarm_type",
                "causal_event",
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

    def find_cross_incident_correlations(
        self,
        *,
        anchor_event: CausalEvent,
        snapshot: DataSnapshot,
        window_seconds: int,
        direction: str = "both",
        other_region_only: bool = False,
    ) -> list[CrossIncidentCorrelationResult]:
        """Discover only event candidates inside an explicit bounded time window."""
        self._validate_event(anchor_event=anchor_event, snapshot=snapshot)
        if window_seconds <= 0:
            raise AlarmCorrelationInputError("Correlation window must be positive.")
        if direction not in {"before", "after", "both"}:
            raise AlarmCorrelationInputError("Correlation direction is invalid.")
        lower = anchor_event.started_at - timedelta(seconds=window_seconds)
        upper = anchor_event.started_at + timedelta(seconds=window_seconds)
        candidates = (
            CausalEvent.objects.filter(
                data_snapshot=snapshot,
                started_at__gte=lower,
                started_at__lte=upper,
            )
            .exclude(pk=anchor_event.pk)
            .select_related("root_device", "root_device__city")
        )
        if direction == "before":
            candidates = candidates.filter(started_at__lt=anchor_event.started_at)
        elif direction == "after":
            candidates = candidates.filter(started_at__gt=anchor_event.started_at)
        anchor_city_id = getattr(anchor_event.root_device, "city_id", None)
        if other_region_only and anchor_city_id is not None:
            candidates = candidates.exclude(root_device__city_id=anchor_city_id)
        results = [
            self.correlate_events(
                anchor_event=anchor_event,
                candidate_event=candidate,
                snapshot=snapshot,
                window_seconds=window_seconds,
            )
            for candidate in candidates.order_by("started_at", "event_code")
        ]
        return sorted(
            results,
            key=lambda result: (
                result.correlation_status != CrossIncidentCorrelationStatus.VERIFIED_RELATION,
                result.time_difference_seconds,
                result.candidate_event_code,
            ),
        )

    def correlate_events(
        self,
        *,
        anchor_event: CausalEvent,
        candidate_event: CausalEvent,
        snapshot: DataSnapshot,
        window_seconds: int,
    ) -> CrossIncidentCorrelationResult:
        """Correlate distinct events from deterministic timestamp and topology evidence.

        A shared graph relation is operational correlation evidence, not proof of a
        shared physical root cause.  Timestamp proximity alone intentionally cannot
        produce ``verified_relation``.
        """
        self._validate_event(anchor_event=anchor_event, snapshot=snapshot)
        self._validate_event(anchor_event=candidate_event, snapshot=snapshot)
        if anchor_event.pk == candidate_event.pk:
            raise AlarmCorrelationInputError("Cross-incident comparison requires two events.")
        if window_seconds <= 0:
            raise AlarmCorrelationInputError("Correlation window must be positive.")

        seconds = abs(int((candidate_event.started_at - anchor_event.started_at).total_seconds()))
        within_window = seconds <= window_seconds
        topology_relation, resource_relation = self._event_topology_relation(
            anchor_event=anchor_event,
            candidate_event=candidate_event,
            snapshot=snapshot,
        )
        event_relation, root_symptom_status = self._explicit_event_relation(
            anchor_event=anchor_event,
            candidate_event=candidate_event,
        )
        has_topology_evidence = topology_relation != "unrelated"
        if event_relation is not None or (within_window and has_topology_evidence):
            status = CrossIncidentCorrelationStatus.VERIFIED_RELATION
        elif within_window or has_topology_evidence:
            status = CrossIncidentCorrelationStatus.INSUFFICIENT_EVIDENCE
        else:
            status = CrossIncidentCorrelationStatus.NO_RELATION
        evidence = [
            {
                "dimension": "temporal",
                "time_difference_seconds": seconds,
                "within_window": within_window,
                "window_seconds": window_seconds,
            },
            {
                "dimension": "topology",
                "relation": topology_relation,
                "verified": has_topology_evidence,
            },
        ]
        if resource_relation != "unrelated":
            evidence.append({"dimension": "resource", "relation": resource_relation})
        if event_relation is not None:
            evidence.append({"dimension": "event_relation", "relation": event_relation})
        return CrossIncidentCorrelationResult(
            anchor_event_code=anchor_event.event_code,
            candidate_event_code=candidate_event.event_code,
            correlation_status=status,
            time_difference_seconds=seconds,
            within_window=within_window,
            requested_window_seconds=window_seconds,
            topology_relation=topology_relation,
            resource_relation=resource_relation,
            event_relation=event_relation,
            root_symptom_status=root_symptom_status,
            evidence=evidence,
            snapshot={
                "id": snapshot.id,
                "snapshot_key": snapshot.snapshot_key,
                "dataset_slug": snapshot.dataset_version.slug,
            },
        )

    def _event_topology_relation(
        self,
        *,
        anchor_event: CausalEvent,
        candidate_event: CausalEvent,
        snapshot: DataSnapshot,
    ) -> tuple[str, str]:
        """Return the strongest existing resource/topology relation across event alarms."""
        anchor_alarms = list(
            Alarm.objects.filter(data_snapshot=snapshot, causal_event=anchor_event)
            .select_related(
                "alarm_type",
                "causal_event",
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
                "subscription_connection__line_connection__port__device",
            )
            .order_by("alarm_id")
        )
        candidate_alarms = list(
            Alarm.objects.filter(data_snapshot=snapshot, causal_event=candidate_event)
            .select_related(
                "alarm_type",
                "causal_event",
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
                "subscription_connection__line_connection__port__device",
            )
            .order_by("alarm_id")
        )
        relations = [
            self._get_topology_relation(anchor_alarm, candidate_alarm, snapshot)
            for anchor_alarm in anchor_alarms
            for candidate_alarm in candidate_alarms
        ]
        topology_relation = max(relations, key=score_topology_relation, default="unrelated")
        anchor_resource = anchor_event.get_root_resource()
        candidate_resource = candidate_event.get_root_resource()
        same_resource = (
            anchor_resource is not None
            and candidate_resource is not None
            and anchor_resource.__class__ == candidate_resource.__class__
            and anchor_resource.pk == candidate_resource.pk
        )
        return topology_relation, "same_resource" if same_resource else topology_relation

    @staticmethod
    def _explicit_event_relation(
        *,
        anchor_event: CausalEvent,
        candidate_event: CausalEvent,
    ) -> tuple[str | None, str]:
        """Read an optional deterministic relation already stored with the event.

        No relation is inferred from timestamps.  Dataset producers can provide an
        explicit cross-event relation without creating a second truth source.
        """
        for event, counterpart in (
            (anchor_event, candidate_event),
            (candidate_event, anchor_event),
        ):
            relations = (event.metadata or {}).get("cross_incident_relations", [])
            if not isinstance(relations, list):
                continue
            for relation in relations:
                if (
                    not isinstance(relation, dict)
                    or relation.get("event_code") != counterpart.event_code
                ):
                    continue
                relation_type = relation.get("relation_type")
                if relation_type not in {"operational_correlation", "root_symptom"}:
                    continue
                direction = relation.get("root_symptom_direction")
                if relation_type == "root_symptom" and direction in {
                    "anchor_root",
                    "candidate_root",
                }:
                    return relation_type, direction
                return relation_type, "not_verified"
        return None, "not_verified"

    @staticmethod
    def _validate_event(*, anchor_event: CausalEvent, snapshot: DataSnapshot) -> None:
        if anchor_event is None or not anchor_event.pk:
            raise AlarmCorrelationInputError("A persisted causal event must be provided.")
        if anchor_event.data_snapshot_id != snapshot.id:
            raise AlarmCorrelationInputError("Causal event does not belong to the snapshot.")

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
        if anchor_alarm.causal_event_id and candidate_alarm.causal_event_id:
            return self._score_causal_pair(
                anchor_alarm=anchor_alarm,
                candidate_alarm=candidate_alarm,
                snapshot=snapshot,
                time_difference_seconds=time_difference_seconds,
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
            correlation_role=(
                CorrelationRole.CHILD.value
                if evidence_score >= CORRELATION_THRESHOLD
                else CorrelationRole.UNRELATED.value
            ),
            reason_codes=legacy_reason_codes(
                topology_relation=topology_relation,
                time_difference_seconds=time_difference_seconds,
            ),
            description=legacy_description(evidence_score >= CORRELATION_THRESHOLD),
        )

    def _score_causal_pair(
        self,
        *,
        anchor_alarm: Alarm,
        candidate_alarm: Alarm,
        snapshot: DataSnapshot,
        time_difference_seconds: int,
    ) -> AlarmCorrelationResult:
        """Score CausalEvent-bound alarms without merging separate event chains."""
        topology_relation = self._get_topology_relation(anchor_alarm, candidate_alarm, snapshot)
        type_compatibility = get_type_compatibility(
            anchor_alarm, candidate_alarm, topology_relation
        )
        same_causal_event = anchor_alarm.causal_event_id == candidate_alarm.causal_event_id
        if not same_causal_event:
            return self._causal_result(
                anchor_alarm,
                candidate_alarm,
                snapshot,
                time_difference_seconds,
                topology_relation,
                type_compatibility,
                0,
                CorrelationRole.UNRELATED,
                [],
                "Alarms belong to different causal events.",
                [{"criterion": "causal_event_boundary", "matched": False, "score": 0}],
            )
        if not technologies_compatible(anchor_alarm, candidate_alarm):
            return self._causal_result(
                anchor_alarm,
                candidate_alarm,
                snapshot,
                time_difference_seconds,
                topology_relation,
                type_compatibility,
                0,
                CorrelationRole.UNRELATED,
                [],
                "Alarm technologies are incompatible for one causal chain.",
                [{"criterion": "technology_compatibility", "matched": False, "score": 0}],
            )

        root_match = alarm_matches_causal_root(candidate_alarm) or alarm_matches_causal_root(
            anchor_alarm
        )
        temporal_score = 25 if time_difference_seconds <= 30 * 60 else 15
        topology_score = score_topology_relation(topology_relation)
        type_score = score_type_compatibility(type_compatibility)
        clear_score, clear_consistent = score_clear_recovery_sequence(anchor_alarm, candidate_alarm)
        role = classify_causal_role(
            anchor_alarm=anchor_alarm,
            candidate_alarm=candidate_alarm,
            topology_relation=topology_relation,
            root_match=root_match,
            time_difference_seconds=time_difference_seconds,
        )
        reasons = causal_reason_codes(
            topology_relation=topology_relation,
            time_difference_seconds=time_difference_seconds,
            clear_consistent=clear_consistent,
        )
        evidence_score = min(100, 25 + temporal_score + topology_score + type_score + clear_score)
        if role in {CorrelationRole.UNRELATED, CorrelationRole.NOISE}:
            evidence_score = min(evidence_score, CORRELATION_THRESHOLD - 1)
        return self._causal_result(
            anchor_alarm,
            candidate_alarm,
            snapshot,
            time_difference_seconds,
            topology_relation,
            type_compatibility,
            evidence_score,
            role,
            reasons,
            causal_description(role),
            [
                {"criterion": "causal_event_boundary", "matched": True, "score": 25},
                {
                    "criterion": "temporal_propagation",
                    "score": temporal_score,
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
                    "criterion": "clear_recovery_sequence",
                    "score": clear_score,
                    "consistent": clear_consistent,
                },
            ],
        )

    def _causal_result(
        self,
        anchor,
        candidate,
        snapshot,
        seconds,
        topology_relation,
        type_compatibility,
        score,
        role,
        reasons,
        description,
        evidence,
    ):
        return AlarmCorrelationResult(
            anchor_alarm_code=anchor.alarm_id,
            candidate_alarm_code=candidate.alarm_id,
            evidence_score=score,
            correlated=score >= CORRELATION_THRESHOLD
            and role not in {CorrelationRole.UNRELATED, CorrelationRole.NOISE},
            time_difference_seconds=seconds,
            topology_relation=topology_relation,
            type_compatibility=type_compatibility,
            evidence=evidence,
            snapshot={
                "id": snapshot.id,
                "snapshot_key": snapshot.snapshot_key,
                "dataset_slug": snapshot.dataset_version.slug,
            },
            correlation_role=role.value,
            reason_codes=[reason.value for reason in reasons],
            description=description,
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
        anchor_bng_codes = get_bng_branch_codes(
            anchor_device,
            self.topology_service.get_ancestors(
                device=anchor_device,
                snapshot=snapshot,
            ),
        )
        candidate_bng_codes = get_bng_branch_codes(
            candidate_device,
            self.topology_service.get_ancestors(
                device=candidate_device,
                snapshot=snapshot,
            ),
        )
        return bool(anchor_bng_codes and anchor_bng_codes & candidate_bng_codes)

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
    codes = get_bng_branch_codes(device, ancestors)
    return sorted(codes)[0] if codes else None


def get_bng_branch_codes(device: NetworkDevice | None, ancestors) -> set[str]:
    if device is None:
        return set()
    codes: set[str] = set()
    if device.device_type == NetworkDeviceType.BNG:
        codes.add(device.code)
    for ancestor in ancestors:
        if ancestor.device_type == NetworkDeviceType.BNG:
            codes.add(ancestor.code)
    return codes


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


def alarm_matches_causal_root(alarm: Alarm) -> bool:
    """Return whether an alarm's structured source is its event's physical root."""
    causal_event = alarm.causal_event
    if causal_event is None:
        return False
    source = alarm.get_source()
    root = causal_event.get_root_resource()
    return (
        source is not None
        and root is not None
        and source.pk == root.pk
        and source.__class__ == root.__class__
    )


def alarm_role_hint(alarm: Alarm) -> str | None:
    normalization = (alarm.metadata or {}).get("normalization", {})
    if isinstance(normalization, dict):
        hint = normalization.get("role_candidate")
        if hint in {role.value for role in CorrelationRole}:
            return hint
    if alarm.alarm_type.code in {"ONT_DISCONNECT_SURGE", "OPTICAL_SIGNAL_LOSS"}:
        return CorrelationRole.SYMPTOM.value
    if alarm.alarm_type.code == "HIGH_TEMPERATURE":
        return CorrelationRole.SUPPORTING.value
    return None


def classify_causal_role(
    *,
    anchor_alarm: Alarm,
    candidate_alarm: Alarm,
    topology_relation: str,
    root_match: bool,
    time_difference_seconds: int,
) -> CorrelationRole:
    """Classify the candidate relative to the anchor, using structured domain fields."""
    candidate_hint = alarm_role_hint(candidate_alarm)
    if candidate_hint == CorrelationRole.SYMPTOM.value:
        return CorrelationRole.SYMPTOM
    if candidate_hint == CorrelationRole.SUPPORTING.value:
        return CorrelationRole.SUPPORTING
    if root_match and alarm_matches_causal_root(candidate_alarm):
        return CorrelationRole.ROOT
    if topology_relation in {
        "same_device",
        "direct_parent_child",
        "shared_failure_domain",
        "same_bng_branch",
    }:
        return CorrelationRole.CHILD
    if time_difference_seconds > TIME_WINDOW_SECONDS:
        return CorrelationRole.NOISE
    return CorrelationRole.UNRELATED


def technologies_compatible(anchor_alarm: Alarm, candidate_alarm: Alarm) -> bool:
    anchor_technology = alarm_technology(anchor_alarm)
    candidate_technology = alarm_technology(candidate_alarm)
    return (
        not anchor_technology
        or not candidate_technology
        or anchor_technology == candidate_technology
    )


def alarm_technology(alarm: Alarm) -> str | None:
    device = alarm.get_source_device()
    if device is None:
        return None
    if device.device_type == NetworkDeviceType.OLT:
        return "gpon"
    if device.device_type == NetworkDeviceType.DSLAM:
        return "xdsl"
    return None


def score_clear_recovery_sequence(
    anchor_alarm: Alarm, candidate_alarm: Alarm
) -> tuple[int, bool | None]:
    if anchor_alarm.cleared_at is None or candidate_alarm.cleared_at is None:
        return 0, None
    # A downstream candidate clearing materially before its earlier alarm weakens the chain.
    consistent = candidate_alarm.cleared_at >= anchor_alarm.cleared_at - timedelta(minutes=5)
    return (10 if consistent else -20), consistent


def causal_reason_codes(
    *,
    topology_relation: str,
    time_difference_seconds: int,
    clear_consistent: bool | None,
) -> list[CorrelationReason]:
    reasons: list[CorrelationReason] = []
    relation_reason = {
        "same_device": CorrelationReason.SAME_RESOURCE,
        "direct_parent_child": CorrelationReason.TOPOLOGY_PARENT_CHILD,
        "same_bng_branch": CorrelationReason.SHARED_UPSTREAM,
        "shared_failure_domain": CorrelationReason.SHARED_FAILURE_DOMAIN,
    }.get(topology_relation)
    if relation_reason:
        reasons.append(relation_reason)
    if time_difference_seconds <= CAUSAL_PROPAGATION_WINDOW_SECONDS:
        reasons.append(CorrelationReason.TEMPORAL_PROPAGATION)
    if clear_consistent:
        reasons.append(CorrelationReason.MATCHING_CLEAR_RECOVERY_SEQUENCE)
    return reasons


def legacy_reason_codes(*, topology_relation: str, time_difference_seconds: int) -> list[str]:
    return [
        reason.value
        for reason in causal_reason_codes(
            topology_relation=topology_relation,
            time_difference_seconds=time_difference_seconds,
            clear_consistent=None,
        )
    ]


def causal_description(role: CorrelationRole) -> str:
    return {
        CorrelationRole.ROOT: "Candidate matches the causal event root resource.",
        CorrelationRole.CHILD: "Candidate is topologically compatible with the causal chain.",
        CorrelationRole.SYMPTOM: "Candidate is a downstream access symptom, not a root assertion.",
        CorrelationRole.SUPPORTING: (
            "Candidate supports the causal chain without proving an outage."
        ),
        CorrelationRole.NOISE: "Candidate is weak or delayed beyond the normal correlation window.",
        CorrelationRole.UNRELATED: "Candidate lacks sufficient causal topology evidence.",
    }[role]


def summarize_causal_event_roles(alarms: list[Alarm]) -> dict[str, int]:
    """Return deterministic role counts for one already-bounded causal event."""
    counts = {role.value: 0 for role in CorrelationRole}
    for alarm in sorted(alarms, key=lambda item: item.alarm_id):
        hint = alarm_role_hint(alarm)
        if hint in counts:
            counts[hint] += 1
        elif alarm_matches_causal_root(alarm):
            counts[CorrelationRole.ROOT.value] += 1
        else:
            counts[CorrelationRole.CHILD.value] += 1
    return counts


def legacy_description(correlated: bool) -> str:
    return (
        "Legacy alarms are conservatively correlated from time and topology evidence."
        if correlated
        else "Legacy alarms lack sufficient time and topology evidence."
    )


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
