from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice
from apps.network.services.topology import NetworkTopologyService
from apps.operations.contracts import CorrelationRole
from apps.operations.models import Alarm, Outage
from apps.operations.services.alarm_correlation import (
    alarm_matches_causal_root,
    alarm_role_hint,
    causal_reason_codes,
    get_alarm_failure_domain_ids,
)
from apps.operations.services.outages import OutageService, OutageServiceInputError

ROOT_CAUSE_ALARM_WINDOW = timedelta(minutes=30)
STRONG_ALARM_TYPES = frozenset({"BNG_UNREACHABLE", "ACCESS_DEVICE_UNREACHABLE"})
SUPPORTING_LINK_ALARM_TYPE = "LINK_DOWN"


class RootCauseServiceError(Exception):
    """Base error for deterministic root cause analysis failures."""


class RootCauseInputError(RootCauseServiceError):
    """Raised when outage, snapshot, or evaluation time inputs are invalid."""


@dataclass(frozen=True)
class RootCauseCandidate:
    outage_code: str
    candidate_device_code: str
    candidate_device_type: str
    evidence_score: int
    classification: str
    supporting_alarm_codes: list[str]
    evidence: list[dict[str, Any]]
    missing_evidence: list[str]
    snapshot: dict[str, Any]
    evaluation_window: dict[str, str]
    correlation_role: str = CorrelationRole.UNRELATED.value
    reason_codes: list[str] | None = None
    description: str = "No causal root was established."
    candidate_resource_code: str | None = None
    candidate_resource_kind: str | None = None


class RootCauseService:
    def __init__(
        self,
        *,
        topology_service: NetworkTopologyService | None = None,
        outage_service: OutageService | None = None,
    ) -> None:
        self.topology_service = topology_service or NetworkTopologyService()
        self.outage_service = outage_service or OutageService()

    def analyze(
        self,
        *,
        outage: Outage,
        snapshot: DataSnapshot,
        evaluation_time=None,
    ) -> list[RootCauseCandidate]:
        window_start, window_end = self._resolve_window(
            outage=outage,
            snapshot=snapshot,
            evaluation_time=evaluation_time,
        )
        if outage.causal_event_id:
            return self._analyze_causal_event(
                outage=outage,
                snapshot=snapshot,
                window_start=window_start,
                window_end=window_end,
            )
        candidate_devices = self._get_candidate_devices(
            outage=outage,
            snapshot=snapshot,
            window_start=window_start,
            window_end=window_end,
        )
        results = [
            self._score_candidate(
                outage=outage,
                snapshot=snapshot,
                candidate_device=device,
                window_start=window_start,
                window_end=window_end,
            )
            for device in candidate_devices
        ]
        return sorted(
            results,
            key=lambda result: (-result.evidence_score, result.candidate_device_code),
        )

    def _analyze_causal_event(
        self, *, outage: Outage, snapshot: DataSnapshot, window_start, window_end
    ):
        """Rank only alarms in the Outage's causal boundary, never nearby events."""
        causal_event = outage.causal_event
        alarms = list(
            self._get_window_alarms(
                snapshot=snapshot, window_start=window_start, window_end=window_end
            ).filter(causal_event=causal_event)
        )
        devices = {outage.source_device_id: outage.source_device}
        root_device = root_resource_device(causal_event)
        if root_device is not None:
            devices[root_device.id] = root_device
        for alarm in alarms:
            if (device := alarm.get_source_device()) is not None:
                devices[device.id] = device
        results = [
            self._score_causal_candidate(
                outage=outage,
                snapshot=snapshot,
                candidate_device=device,
                alarms=alarms,
                causal_event=causal_event,
                window_start=window_start,
                window_end=window_end,
            )
            for device in devices.values()
        ]
        return sorted(
            results,
            key=lambda result: (
                -result.evidence_score,
                0 if result.candidate_resource_code == causal_event.root_resource_code else 1,
                earliest_candidate_alarm_time(result.supporting_alarm_codes, alarms),
                result.candidate_device_code,
            ),
        )

    def _score_causal_candidate(
        self, *, outage, snapshot, candidate_device, alarms, causal_event, window_start, window_end
    ) -> RootCauseCandidate:
        candidate_alarms = [
            alarm for alarm in alarms if alarm.get_source_device() == candidate_device
        ]
        root_device = root_resource_device(causal_event)
        root_match = root_device is not None and root_device.id == candidate_device.id
        root_alarm_match = any(alarm_matches_causal_root(alarm) for alarm in candidate_alarms)
        earliest = min((alarm.detected_at for alarm in candidate_alarms), default=None)
        early = earliest is not None and earliest <= outage.started_at
        topology_relation = self._get_topology_relation(
            outage.source_device, candidate_device, snapshot
        )
        shared_failure_domain = bool(
            set().union(
                *(get_alarm_failure_domain_ids(alarm, snapshot) for alarm in candidate_alarms)
            )
            & set().union(*(get_alarm_failure_domain_ids(alarm, snapshot) for alarm in alarms))
        ) if candidate_alarms else False
        root_capable = any(is_strong_root_alarm(alarm) for alarm in candidate_alarms)
        symptom_only = bool(candidate_alarms) and all(
            alarm_role_hint(alarm) == CorrelationRole.SYMPTOM.value for alarm in candidate_alarms
        )
        # Fanout is bounded evidence: many access symptoms cannot outweigh a non-root candidate.
        fanout_score = min(10, max(0, len(alarms) - len(candidate_alarms)) * 2) if root_match else 0
        score = min(100, (45 if root_match else 0) + (25 if root_alarm_match else 0)
                    + (15 if early else 0) + (10 if root_capable else 0)
                    + (10 if topology_relation in {"same_device", "direct_parent_child"} else 0)
                    + (10 if shared_failure_domain else 0) + fanout_score)
        if symptom_only:
            score = min(score, 45)
        reasons = causal_reason_codes(
            topology_relation=(
                "shared_failure_domain" if shared_failure_domain else topology_relation
            ),
            time_difference_seconds=0 if early else ROOT_CAUSE_ALARM_WINDOW.seconds + 1,
            clear_consistent=None,
        )
        role = CorrelationRole.ROOT if root_match and not symptom_only else (
            CorrelationRole.SYMPTOM if symptom_only else CorrelationRole.CHILD
        )
        supporting_codes = sorted(alarm.alarm_id for alarm in candidate_alarms)
        missing = []
        if not root_match:
            missing.append("no_causal_root_resource_match")
        if not root_capable:
            missing.append("no_root_capable_alarm")
        if not early:
            missing.append("no_early_alarm_evidence")
        if symptom_only:
            missing.append("symptom_alarm_cannot_establish_root")
        return RootCauseCandidate(
            outage_code=outage.outage_code,
            candidate_device_code=candidate_device.code,
            candidate_device_type=candidate_device.device_type,
            evidence_score=score,
            classification="confirmed" if score >= 70 and root_match and not missing else (
                "probable" if score >= 50 and not symptom_only else "unknown"
            ),
            supporting_alarm_codes=supporting_codes,
            evidence=[
                {"criterion": "causal_root_resource_match", "score": 45 if root_match else 0,
                 "matched": root_match},
                {"criterion": "root_alarm_support", "score": 25 if root_alarm_match else 0,
                 "matched": root_alarm_match},
                {"criterion": "early_alarm_evidence", "score": 15 if early else 0,
                 "matched": early},
                {"criterion": "root_capable_alarm", "score": 10 if root_capable else 0,
                 "matched": root_capable},
                {"criterion": "symptom_fanout", "score": fanout_score,
                 "bounded": True},
            ],
            missing_evidence=missing,
            snapshot={"id": snapshot.id, "snapshot_key": snapshot.snapshot_key,
                      "dataset_slug": snapshot.dataset_version.slug},
            evaluation_window={
                "started_at": window_start.isoformat(),
                "ended_at": window_end.isoformat(),
            },
            correlation_role=role.value,
            reason_codes=[reason.value for reason in reasons],
            description=(
                "Candidate matches the causal event physical root resource."
                if role == CorrelationRole.ROOT
                else "Candidate is retained as causal-chain evidence, not a confirmed root."
            ),
            candidate_resource_code=(
                causal_event.root_resource_code if root_match else candidate_device.code
            ),
            candidate_resource_kind=(
                causal_event.get_root_resource_kind() if root_match else "device"
            ),
        )

    def _resolve_window(
        self,
        *,
        outage: Outage,
        snapshot: DataSnapshot,
        evaluation_time,
    ):
        self._validate_inputs(outage=outage, snapshot=snapshot, evaluation_time=evaluation_time)
        try:
            self.outage_service.calculate_duration(
                outage=outage,
                evaluation_time=evaluation_time,
            )
        except OutageServiceInputError as exc:
            raise RootCauseInputError(str(exc)) from exc
        return outage.started_at, outage.ended_at or evaluation_time

    def _validate_inputs(
        self,
        *,
        outage: Outage,
        snapshot: DataSnapshot,
        evaluation_time,
    ) -> None:
        if snapshot is None:
            raise RootCauseInputError("A DataSnapshot must be provided explicitly.")
        if outage is None:
            raise RootCauseInputError("An Outage must be provided.")
        if not snapshot.pk:
            raise RootCauseInputError("Snapshot must be a persisted DataSnapshot.")
        if not outage.pk:
            raise RootCauseInputError("Outage must be a persisted Outage.")
        if outage.data_snapshot_id != snapshot.id:
            raise RootCauseInputError(
                f"Outage {outage.outage_code} does not belong to snapshot {snapshot.snapshot_key}."
            )
        if not outage.source_device_id:
            raise RootCauseInputError(f"Outage {outage.outage_code} has no source device.")
        if outage.source_device.data_snapshot_id != snapshot.id:
            raise RootCauseInputError(
                f"Outage source device {outage.source_device.code} does not belong to "
                f"snapshot {snapshot.snapshot_key}."
            )
        if evaluation_time is not None and timezone.is_naive(evaluation_time):
            raise RootCauseInputError("evaluation_time must be timezone-aware.")

    def _get_candidate_devices(
        self,
        *,
        outage: Outage,
        snapshot: DataSnapshot,
        window_start,
        window_end,
    ) -> list[NetworkDevice]:
        devices_by_id = {outage.source_device_id: outage.source_device}
        alarms = self._get_window_alarms(
            snapshot=snapshot,
            window_start=window_start,
            window_end=window_end,
        )
        for alarm in alarms:
            alarm_device = alarm.get_source_device()
            if alarm_device is None:
                continue
            relation = self._get_topology_relation(
                outage.source_device,
                alarm_device,
                snapshot,
            )
            if relation != "unrelated":
                devices_by_id[alarm_device.id] = alarm_device
        return sorted(devices_by_id.values(), key=lambda device: device.code)

    def _score_candidate(
        self,
        *,
        outage: Outage,
        snapshot: DataSnapshot,
        candidate_device: NetworkDevice,
        window_start,
        window_end,
    ) -> RootCauseCandidate:
        alarms = list(
            self._get_window_alarms(
                snapshot=snapshot,
                window_start=window_start,
                window_end=window_end,
            )
        )
        alarms = [alarm for alarm in alarms if alarm.get_source_device() == candidate_device]
        source_match = candidate_device.id == outage.source_device_id
        source_match_score = 40 if source_match else 0
        strong_alarm_score = self._score_alarm_support(alarms)
        time_score, nearest_seconds = self._score_time_proximity(alarms, outage.started_at)
        topology_relation = self._get_topology_relation(
            outage.source_device,
            candidate_device,
            snapshot,
        )
        topology_score = self._score_topology_alignment(topology_relation)
        evidence_score = min(
            100,
            source_match_score + strong_alarm_score + time_score + topology_score,
        )
        supporting_alarm_codes = sorted(alarm.alarm_id for alarm in alarms)
        direct_source_alarm = source_match and bool(supporting_alarm_codes)
        missing_evidence = self._get_missing_evidence(
            source_match=source_match,
            direct_source_alarm=direct_source_alarm,
            has_strong_alarm=any(is_strong_root_alarm(alarm) for alarm in alarms),
            has_near_start_alarm=time_score > 0,
            topology_relation=topology_relation,
        )

        return RootCauseCandidate(
            outage_code=outage.outage_code,
            candidate_device_code=candidate_device.code,
            candidate_device_type=candidate_device.device_type,
            evidence_score=evidence_score,
            classification=self._classify(
                evidence_score=evidence_score,
                direct_source_alarm=direct_source_alarm,
                missing_evidence=missing_evidence,
            ),
            supporting_alarm_codes=supporting_alarm_codes,
            evidence=[
                {
                    "criterion": "outage_source_device_match",
                    "score": source_match_score,
                    "matched": source_match,
                },
                {
                    "criterion": "strong_alarm_support",
                    "score": strong_alarm_score,
                    "alarm_type_codes": sorted({alarm.alarm_type.code for alarm in alarms}),
                },
                {
                    "criterion": "alarm_time_proximity",
                    "score": time_score,
                    "nearest_alarm_time_difference_seconds": nearest_seconds,
                },
                {
                    "criterion": "topology_alignment",
                    "score": topology_score,
                    "relation": topology_relation,
                },
            ],
            missing_evidence=missing_evidence,
            snapshot={
                "id": snapshot.id,
                "snapshot_key": snapshot.snapshot_key,
                "dataset_slug": snapshot.dataset_version.slug,
            },
            evaluation_window={
                "started_at": window_start.isoformat(),
                "ended_at": window_end.isoformat(),
            },
        )

    def _get_window_alarms(self, *, snapshot: DataSnapshot, window_start, window_end):
        return (
            Alarm.objects.filter(
                data_snapshot=snapshot,
                detected_at__gte=window_start - ROOT_CAUSE_ALARM_WINDOW,
                detected_at__lte=window_end,
            )
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

    def _score_alarm_support(self, alarms: list[Alarm]) -> int:
        score = 0
        if any(is_strong_root_alarm(alarm) for alarm in alarms):
            score += 25
        if any(is_supporting_link_alarm(alarm) for alarm in alarms):
            score += 15
        return score

    def _score_time_proximity(
        self,
        alarms: list[Alarm],
        outage_started_at,
    ) -> tuple[int, int | None]:
        if not alarms:
            return 0, None
        nearest_seconds = min(
            abs(int((alarm.detected_at - outage_started_at).total_seconds())) for alarm in alarms
        )
        if nearest_seconds <= 5 * 60:
            return 10, nearest_seconds
        if nearest_seconds <= 15 * 60:
            return 5, nearest_seconds
        return 0, nearest_seconds

    def _get_topology_relation(
        self,
        source_device: NetworkDevice,
        candidate_device: NetworkDevice,
        snapshot: DataSnapshot,
    ) -> str:
        if source_device.id == candidate_device.id:
            return "same_device"
        source_children = self.topology_service.get_children(
            device=source_device,
            snapshot=snapshot,
        )
        candidate_children = self.topology_service.get_children(
            device=candidate_device,
            snapshot=snapshot,
        )
        if any(device.id == candidate_device.id for device in source_children) or any(
            device.id == source_device.id for device in candidate_children
        ):
            return "direct_parent_child"
        if self._share_bng_branch(source_device, candidate_device, snapshot):
            return "same_bng_branch"
        return "unrelated"

    def _share_bng_branch(
        self,
        source_device: NetworkDevice,
        candidate_device: NetworkDevice,
        snapshot: DataSnapshot,
    ) -> bool:
        source_bng_codes = self._get_bng_branch_codes(source_device, snapshot)
        candidate_bng_codes = self._get_bng_branch_codes(candidate_device, snapshot)
        return bool(source_bng_codes and source_bng_codes & candidate_bng_codes)

    def _get_bng_branch_code(self, device: NetworkDevice, snapshot: DataSnapshot) -> str | None:
        codes = self._get_bng_branch_codes(device, snapshot)
        return sorted(codes)[0] if codes else None

    def _get_bng_branch_codes(self, device: NetworkDevice, snapshot: DataSnapshot) -> set[str]:
        if device.device_type == "bng":
            return {device.code}
        codes: set[str] = set()
        for ancestor in self.topology_service.get_ancestors(device=device, snapshot=snapshot):
            if ancestor.device_type == "bng":
                codes.add(ancestor.code)
        return codes

    def _score_topology_alignment(self, topology_relation: str) -> int:
        return {
            "same_device": 10,
            "direct_parent_child": 5,
            "same_bng_branch": 0,
            "unrelated": 0,
        }[topology_relation]

    def _get_missing_evidence(
        self,
        *,
        source_match: bool,
        direct_source_alarm: bool,
        has_strong_alarm: bool,
        has_near_start_alarm: bool,
        topology_relation: str,
    ) -> list[str]:
        missing = []
        if source_match and not direct_source_alarm:
            missing.append("no_direct_alarm_on_outage_source_device")
        if not has_strong_alarm:
            missing.append("no_strong_alarm_support")
        if not has_near_start_alarm:
            missing.append("no_near_start_alarm")
        if topology_relation == "unrelated":
            missing.append("no_topology_alignment")
        return missing

    def _classify(
        self,
        *,
        evidence_score: int,
        direct_source_alarm: bool,
        missing_evidence: list[str],
    ) -> str:
        if evidence_score >= 80 and direct_source_alarm and not missing_evidence:
            return "confirmed"
        if evidence_score >= 50 and not missing_evidence:
            return "probable"
        return "unknown"


def is_strong_root_alarm(alarm: Alarm) -> bool:
    return alarm.alarm_type.code in STRONG_ALARM_TYPES or (
        alarm.alarm_type.is_root_candidate and alarm.alarm_type.severity in {"critical", "major"}
    )


def is_supporting_link_alarm(alarm: Alarm) -> bool:
    return alarm.alarm_type.code == SUPPORTING_LINK_ALARM_TYPE or (
        alarm.alarm_type.correlation_family in {"link_down", "fiber_route", "protection"}
        and alarm.alarm_type.code not in STRONG_ALARM_TYPES
    )


def root_resource_device(causal_event):
    """Resolve a physical root to a device without inventing one for a producer."""
    root = causal_event.get_root_resource()
    if root is None:
        return None
    if isinstance(root, NetworkDevice):
        return root
    if hasattr(root, "source_device"):
        return root.source_device
    if hasattr(root, "device"):
        return root.device
    if hasattr(root, "port"):
        return root.port.device
    if hasattr(root, "line_connection"):
        return root.line_connection.port.device
    return None


def earliest_candidate_alarm_time(alarm_codes: list[str], alarms: list[Alarm]):
    by_code = {alarm.alarm_id: alarm.detected_at for alarm in alarms}
    return min(
        (by_code[code] for code in alarm_codes if code in by_code),
        default=datetime.max.replace(tzinfo=timezone.get_current_timezone()),
    )
