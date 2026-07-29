from dataclasses import dataclass
from typing import Any

from apps.datasets.models import DataSnapshot
from apps.network.models import (
    FailureDomainType,
    LineConnection,
    NetworkDevice,
    NetworkDeviceType,
    NetworkLink,
)


class PathDiversityClassification:
    FULLY_DIVERSE = "fully_diverse"
    PARTIALLY_DIVERSE = "partially_diverse"
    SHARED_RISK = "shared_risk"
    UNKNOWN = "unknown"


class PathDiversityError(Exception):
    """Base error for deterministic path diversity evaluation."""


class PathDiversityInputError(PathDiversityError):
    """Raised when line or snapshot inputs are invalid."""


@dataclass(frozen=True)
class PathTrace:
    line_code: str
    access_device_code: str
    access_device_id: int
    aggregation_device_codes: list[str]
    aggregation_device_ids: set[int]
    bng_codes: list[str]
    bng_ids: set[int]
    upstream_link_codes: list[str]
    upstream_link_ids: set[int]
    failure_domains_by_type: dict[str, set[str]]


@dataclass(frozen=True)
class PathDiversityResult:
    classification: str
    evidence: list[dict[str, Any]]
    primary_path: dict[str, Any]
    backup_path: dict[str, Any]
    shared_failure_domains: dict[str, list[str]]
    missing_failure_domain_types: list[str]


class PathDiversityService:
    required_failure_domain_types = {
        FailureDomainType.SITE,
        FailureDomainType.POWER_ZONE,
        FailureDomainType.FIBER_ROUTE,
    }

    def evaluate(
        self,
        *,
        primary_line: LineConnection,
        backup_line: LineConnection,
        snapshot: DataSnapshot,
    ) -> PathDiversityResult:
        self._validate_inputs(
            primary_line=primary_line,
            backup_line=backup_line,
            snapshot=snapshot,
        )
        primary_path = self._trace_path(line=primary_line, snapshot=snapshot)
        backup_path = self._trace_path(line=backup_line, snapshot=snapshot)
        shared_failure_domains = self._collect_shared_failure_domains(
            primary_path,
            backup_path,
        )
        missing_domain_types = self._collect_missing_failure_domain_types(
            primary_path,
            backup_path,
        )
        evidence = self._build_evidence(
            primary_path=primary_path,
            backup_path=backup_path,
            shared_failure_domains=shared_failure_domains,
            missing_domain_types=missing_domain_types,
        )
        classification = self._classify(
            evidence=evidence,
            shared_failure_domains=shared_failure_domains,
            missing_domain_types=missing_domain_types,
        )
        return PathDiversityResult(
            classification=classification,
            evidence=evidence,
            primary_path=self._serialize_path(primary_path),
            backup_path=self._serialize_path(backup_path),
            shared_failure_domains={
                domain_type: sorted(codes)
                for domain_type, codes in sorted(shared_failure_domains.items())
            },
            missing_failure_domain_types=sorted(missing_domain_types),
        )

    def _validate_inputs(
        self,
        *,
        primary_line: LineConnection,
        backup_line: LineConnection,
        snapshot: DataSnapshot,
    ) -> None:
        if snapshot is None or not snapshot.pk:
            raise PathDiversityInputError("A persisted DataSnapshot must be provided.")
        if primary_line is None or not primary_line.pk:
            raise PathDiversityInputError("A persisted primary LineConnection is required.")
        if backup_line is None or not backup_line.pk:
            raise PathDiversityInputError("A persisted backup LineConnection is required.")
        if primary_line.data_snapshot_id != snapshot.id:
            raise PathDiversityInputError("Primary line must belong to the provided snapshot.")
        if backup_line.data_snapshot_id != snapshot.id:
            raise PathDiversityInputError("Backup line must belong to the provided snapshot.")

    def _trace_path(self, *, line: LineConnection, snapshot: DataSnapshot) -> PathTrace:
        access_device = line.port.device
        upstream_links = self._collect_upstream_links(access_device, snapshot=snapshot)
        upstream_devices = self._collect_upstream_devices(upstream_links)
        if access_device.device_type == NetworkDeviceType.BNG:
            upstream_devices.add(access_device)
        aggregation_devices = sorted(
            (
                device
                for device in upstream_devices
                if device.device_type == NetworkDeviceType.METRO_AGGREGATION
            ),
            key=lambda device: device.code,
        )
        bng_devices = sorted(
            (
                device
                for device in upstream_devices
                if device.device_type == NetworkDeviceType.BNG
            ),
            key=lambda device: device.code,
        )
        failure_domains_by_type = self._collect_failure_domains(
            line=line,
            devices={access_device, *upstream_devices},
            links=upstream_links,
        )
        return PathTrace(
            line_code=line.line_code,
            access_device_code=access_device.code,
            access_device_id=access_device.id,
            aggregation_device_codes=[device.code for device in aggregation_devices],
            aggregation_device_ids={device.id for device in aggregation_devices},
            bng_codes=[device.code for device in bng_devices],
            bng_ids={device.id for device in bng_devices},
            upstream_link_codes=sorted(link.link_code for link in upstream_links),
            upstream_link_ids={link.id for link in upstream_links},
            failure_domains_by_type=failure_domains_by_type,
        )

    def _collect_upstream_links(
        self,
        device: NetworkDevice,
        *,
        snapshot: DataSnapshot,
    ) -> set[NetworkLink]:
        links_by_id: dict[int, NetworkLink] = {}
        visited_device_ids: set[int] = set()
        visiting_device_ids: set[int] = set()

        def walk(current: NetworkDevice) -> None:
            if current.id in visiting_device_ids:
                return
            if current.id in visited_device_ids:
                return
            visiting_device_ids.add(current.id)
            incoming_links = (
                NetworkLink.objects.filter(data_snapshot=snapshot, target_device=current)
                .select_related("source_device", "target_device")
                .order_by("link_code")
            )
            for link in incoming_links:
                links_by_id[link.id] = link
                walk(link.source_device)
            visiting_device_ids.remove(current.id)
            visited_device_ids.add(current.id)

        walk(device)
        return set(links_by_id.values())

    def _collect_upstream_devices(self, links: set[NetworkLink]) -> set[NetworkDevice]:
        devices: set[NetworkDevice] = set()
        for link in links:
            devices.add(link.source_device)
        return devices

    def _collect_failure_domains(
        self,
        *,
        line: LineConnection,
        devices: set[NetworkDevice],
        links: set[NetworkLink],
    ) -> dict[str, set[str]]:
        domains_by_type: dict[str, set[str]] = {
            FailureDomainType.SITE: set(),
            FailureDomainType.POWER_ZONE: set(),
            FailureDomainType.FIBER_ROUTE: set(),
        }
        for membership in line.failure_domain_memberships.select_related(
            "failure_domain"
        ):
            domains_by_type.setdefault(membership.failure_domain.domain_type, set()).add(
                membership.failure_domain.code
            )
        for device in devices:
            for membership in device.failure_domain_memberships.select_related(
                "failure_domain"
            ):
                domains_by_type.setdefault(membership.failure_domain.domain_type, set()).add(
                    membership.failure_domain.code
                )
        for link in links:
            for membership in link.failure_domain_memberships.select_related(
                "failure_domain"
            ):
                domains_by_type.setdefault(membership.failure_domain.domain_type, set()).add(
                    membership.failure_domain.code
                )
        return domains_by_type

    def _collect_shared_failure_domains(
        self,
        primary_path: PathTrace,
        backup_path: PathTrace,
    ) -> dict[str, set[str]]:
        shared: dict[str, set[str]] = {}
        for domain_type in self.required_failure_domain_types:
            common_codes = (
                primary_path.failure_domains_by_type.get(domain_type, set())
                & backup_path.failure_domains_by_type.get(domain_type, set())
            )
            if common_codes:
                shared[domain_type] = common_codes
        return shared

    def _collect_missing_failure_domain_types(
        self,
        primary_path: PathTrace,
        backup_path: PathTrace,
    ) -> set[str]:
        missing: set[str] = set()
        for domain_type in self.required_failure_domain_types:
            if not primary_path.failure_domains_by_type.get(
                domain_type
            ) or not backup_path.failure_domains_by_type.get(domain_type):
                missing.add(domain_type)
        return missing

    def _build_evidence(
        self,
        *,
        primary_path: PathTrace,
        backup_path: PathTrace,
        shared_failure_domains: dict[str, set[str]],
        missing_domain_types: set[str],
    ) -> list[dict[str, Any]]:
        evidence = [
            {
                "code": "access_device_comparison",
                "passed": primary_path.access_device_id != backup_path.access_device_id,
                "primary": primary_path.access_device_code,
                "backup": backup_path.access_device_code,
            },
            {
                "code": "aggregation_comparison",
                "passed": not bool(
                    primary_path.aggregation_device_ids & backup_path.aggregation_device_ids
                ),
                "primary": primary_path.aggregation_device_codes,
                "backup": backup_path.aggregation_device_codes,
            },
            {
                "code": "bng_branch_comparison",
                "passed": not bool(primary_path.bng_ids & backup_path.bng_ids),
                "primary": primary_path.bng_codes,
                "backup": backup_path.bng_codes,
            },
            {
                "code": "upstream_link_comparison",
                "passed": not bool(
                    primary_path.upstream_link_ids & backup_path.upstream_link_ids
                ),
                "primary": primary_path.upstream_link_codes,
                "backup": backup_path.upstream_link_codes,
            },
            {
                "code": "failure_domain_comparison",
                "passed": not bool(shared_failure_domains),
                "shared": {
                    domain_type: sorted(codes)
                    for domain_type, codes in sorted(shared_failure_domains.items())
                },
            },
            {
                "code": "failure_domain_completeness",
                "passed": not bool(missing_domain_types),
                "missing": sorted(missing_domain_types),
            },
        ]
        return evidence

    def _classify(
        self,
        *,
        evidence: list[dict[str, Any]],
        shared_failure_domains: dict[str, set[str]],
        missing_domain_types: set[str],
    ) -> str:
        if shared_failure_domains:
            return PathDiversityClassification.SHARED_RISK

        evidence_by_code = {item["code"]: item for item in evidence}
        topology_is_distinct = all(
            evidence_by_code[code]["passed"]
            for code in (
                "access_device_comparison",
                "aggregation_comparison",
                "bng_branch_comparison",
                "upstream_link_comparison",
            )
        )
        if not topology_is_distinct:
            return PathDiversityClassification.PARTIALLY_DIVERSE
        if missing_domain_types:
            return PathDiversityClassification.UNKNOWN
        return PathDiversityClassification.FULLY_DIVERSE

    def _serialize_path(self, path: PathTrace) -> dict[str, Any]:
        return {
            "line_code": path.line_code,
            "access_device_code": path.access_device_code,
            "aggregation_device_codes": path.aggregation_device_codes,
            "bng_codes": path.bng_codes,
            "upstream_link_codes": path.upstream_link_codes,
            "failure_domains": {
                domain_type: sorted(codes)
                for domain_type, codes in sorted(path.failure_domains_by_type.items())
            },
        }
