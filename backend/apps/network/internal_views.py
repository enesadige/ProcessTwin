from __future__ import annotations

from collections import Counter
from dataclasses import asdict, is_dataclass
from typing import Any

from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from apps.core.internal_api import internal_service_required
from apps.customers.services.impact import CustomerImpactService, CustomerImpactServiceError
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.network.internal_serializers import (
    alarm_summary,
    device_summary,
    failure_domain_list,
    iso_or_none,
    json_safe,
    link_summary,
    outage_summary,
    snapshot_summary,
    status_counts,
)
from apps.network.models import (
    NetworkDevice,
    NetworkLink,
    NetworkPort,
)
from apps.network.services.topology import (
    NetworkTopologyCycleError,
    NetworkTopologyService,
)
from apps.operations.contracts import CustomerImpactStatus, ImpactReason
from apps.operations.models import (
    Alarm,
    CustomerImpactAssessment,
    IncidentAlarm,
    MaintenanceWindow,
    Outage,
)
from apps.operations.services.alarm_correlation import (
    AlarmCorrelationService,
    AlarmCorrelationServiceError,
)
from apps.operations.services.analytics import (
    AnalyticsInputError,
    AnalyticsSpec,
    OperationalAnalyticsService,
)
from apps.operations.services.outages import OutageService, OutageServiceError
from apps.operations.services.root_cause import RootCauseService, RootCauseServiceError

DEFAULT_LIMIT = 50
MAX_SEARCH_LIMIT = 100
MAX_TOPOLOGY_DEPTH = 8
MAX_TOPOLOGY_RESULT_LIMIT = 500
MAX_LONGEST_OUTAGE_LIMIT = 10


class InternalNetworkAPIError(Exception):
    def __init__(self, code: str, message: str, *, status: int, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def _ok(
    *,
    request,
    snapshot: DataSnapshot,
    data: dict[str, Any],
    warnings: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> JsonResponse:
    return JsonResponse(
        {
            "data": json_safe(data),
            "warnings": warnings or [],
            "evidence": evidence or [],
            "metadata": {
                "correlation_id": getattr(request, "correlation_id", None),
                "snapshot": snapshot_summary(snapshot),
            },
        }
    )


def _error(exc: InternalNetworkAPIError) -> JsonResponse:
    return JsonResponse(
        {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
        status=exc.status,
    )


def _sanitize_error(exc: Exception) -> JsonResponse:
    return _error(
        InternalNetworkAPIError(
            "internal_error",
            "Network internal API failed.",
            status=500,
            details={"reason": exc.__class__.__name__},
        )
    )


def _resolve_snapshot(identifier: str | None) -> DataSnapshot:
    if not identifier:
        raise InternalNetworkAPIError(
            "validation_error",
            "snapshot_identifier is required.",
            status=400,
            details={"field": "snapshot_identifier"},
        )
    snapshot = (
        DataSnapshot.objects.select_related("dataset_version")
        .filter(snapshot_key=identifier)
        .first()
    )
    if snapshot:
        return snapshot
    dataset = DatasetVersion.objects.filter(slug=identifier).first()
    if dataset is None:
        raise InternalNetworkAPIError(
            "not_found",
            "Snapshot or dataset slug was not found.",
            status=404,
            details={"snapshot_identifier": identifier},
        )
    snapshots = list(
        DataSnapshot.objects.select_related("dataset_version")
        .filter(dataset_version=dataset)
        .order_by("snapshot_key")
    )
    if len(snapshots) != 1:
        raise InternalNetworkAPIError(
            "validation_error",
            "Dataset slug must resolve to exactly one snapshot.",
            status=400,
            details={"dataset_slug": identifier, "snapshot_count": len(snapshots)},
        )
    return snapshots[0]


def _parse_dt(value: str | None, *, field_name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise InternalNetworkAPIError(
                "validation_error",
                f"{field_name} is required.",
                status=400,
                details={"field": field_name},
            )
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise InternalNetworkAPIError(
            "validation_error",
            f"{field_name} must be a valid ISO 8601 datetime.",
            status=400,
            details={"field": field_name},
        )
    if timezone.is_naive(parsed):
        raise InternalNetworkAPIError(
            "validation_error",
            f"{field_name} must be timezone-aware.",
            status=400,
            details={"field": field_name},
        )
    return parsed


def _parse_date_range(request):
    from_time = _parse_dt(request.GET.get("from_time"), field_name="from_time")
    to_time = _parse_dt(request.GET.get("to_time"), field_name="to_time")
    if from_time and to_time and from_time > to_time:
        raise InternalNetworkAPIError(
            "validation_error",
            "from_time cannot be later than to_time.",
            status=400,
            details={"fields": ["from_time", "to_time"]},
        )
    return from_time, to_time


def _parse_limit(request, *, default: int = DEFAULT_LIMIT, maximum: int = MAX_SEARCH_LIMIT) -> int:
    value = request.GET.get("limit", str(default))
    try:
        limit = int(value)
    except ValueError as exc:
        raise InternalNetworkAPIError(
            "validation_error",
            "limit must be an integer.",
            status=400,
            details={"field": "limit"},
        ) from exc
    if limit < 1 or limit > maximum:
        raise InternalNetworkAPIError(
            "validation_error",
            f"limit must be between 1 and {maximum}.",
            status=400,
            details={"field": "limit", "maximum": maximum},
        )
    return limit


def _parse_cursor(request) -> int:
    value = request.GET.get("cursor", "0")
    if value in ("", None):
        return 0
    try:
        cursor = int(value)
    except ValueError as exc:
        raise InternalNetworkAPIError(
            "validation_error",
            "cursor must be an integer offset.",
            status=400,
            details={"field": "cursor"},
        ) from exc
    if cursor < 0:
        raise InternalNetworkAPIError(
            "validation_error",
            "cursor must be zero or greater.",
            status=400,
            details={"field": "cursor"},
        )
    return cursor


def _get_device(snapshot: DataSnapshot, code: str) -> NetworkDevice:
    try:
        return (
            NetworkDevice.objects.select_related("city", "district", "neighborhood")
            .prefetch_related("failure_domain_memberships__failure_domain")
            .get(data_snapshot=snapshot, code=code)
        )
    except NetworkDevice.DoesNotExist as exc:
        raise InternalNetworkAPIError(
            "not_found",
            "Network device was not found.",
            status=404,
            details={"device_code": code},
        ) from exc


def _get_outage(snapshot: DataSnapshot, code: str) -> Outage:
    try:
        return Outage.objects.select_related(
            "incident",
            "incident__primary_device",
            "incident__primary_device__city",
            "incident__primary_device__district",
            "incident__primary_device__neighborhood",
            "source_device",
            "source_device__city",
            "source_device__district",
            "source_device__neighborhood",
        ).get(data_snapshot=snapshot, outage_code=code)
    except Outage.DoesNotExist as exc:
        raise InternalNetworkAPIError(
            "not_found",
            "Outage was not found.",
            status=404,
            details={"outage_code": code},
        ) from exc


def _duration_payload(service: OutageService, outage: Outage, evaluation_time) -> dict[str, Any]:
    duration = service.calculate_duration(outage=outage, evaluation_time=evaluation_time)
    return {
        "seconds": duration.seconds,
        "minutes": duration.minutes,
        "is_ongoing": duration.is_ongoing,
        "evaluation_time": iso_or_none(evaluation_time),
    }


def _dataclass_payload(value) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    return dict(value)


@require_GET
@internal_service_required
def get_device_details(request, device_code: str):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        device = _get_device(snapshot, device_code)
        incoming_links = list(
            NetworkLink.objects.filter(data_snapshot=snapshot, target_device=device)
            .select_related("source_device", "target_device")
            .order_by("link_code")
        )
        outgoing_links = list(
            NetworkLink.objects.filter(data_snapshot=snapshot, source_device=device)
            .select_related("source_device", "target_device")
            .order_by("link_code")
        )
        ports = NetworkPort.objects.filter(data_snapshot=snapshot, device=device).order_by(
            "port_code"
        )
        failure_domains = [
            membership.failure_domain
            for membership in device.failure_domain_memberships.select_related(
                "failure_domain"
            ).all()
        ]
        data = {
            "device": device_summary(device),
            "upstream_links": [link_summary(link) for link in incoming_links],
            "downstream_links": [link_summary(link) for link in outgoing_links],
            "port_counts": {
                "total": ports.count(),
                "by_status": status_counts(list(ports.values_list("inventory_status", flat=True))),
                "by_type": status_counts(list(ports.values_list("port_type", flat=True))),
            },
            "failure_domains": failure_domain_list(failure_domains),
        }
        return _ok(request=request, snapshot=snapshot, data=data)
    except InternalNetworkAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def get_device_topology(request, device_code: str):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        evaluation_time = _parse_dt(
            request.GET.get("evaluation_time"),
            field_name="evaluation_time",
        )
        mode = request.GET.get("mode", "descendants")
        if mode not in {"ancestors", "descendants", "subgraph"}:
            raise InternalNetworkAPIError(
                "validation_error",
                "mode must be ancestors, descendants, or subgraph.",
                status=400,
                details={"field": "mode"},
            )
        max_depth = min(
            int(request.GET.get("max_depth", "4")),
            MAX_TOPOLOGY_DEPTH,
        )
        result_limit = _parse_limit(
            request,
            default=100,
            maximum=MAX_TOPOLOGY_RESULT_LIMIT,
        )
        include_links = request.GET.get("include_links", "true").lower() != "false"
        device = _get_device(snapshot, device_code)
        service = NetworkTopologyService()
        warnings: list[dict[str, Any]] = []
        if mode == "ancestors":
            service.get_ancestors(
                device=device,
                snapshot=snapshot,
                evaluation_time=evaluation_time,
            )
            devices_with_depth, links = _topology_ancestors(
                snapshot=snapshot,
                start=device,
                max_depth=max_depth,
            )
        else:
            service.get_subgraph(
                device=device,
                snapshot=snapshot,
                evaluation_time=evaluation_time,
            )
            devices_with_depth, links = _topology_descendants(
                snapshot=snapshot,
                start=device,
                max_depth=max_depth,
            )
        all_devices = sorted(devices_with_depth, key=lambda item: (item[1], item[0].code))
        truncated = len(all_devices) > result_limit
        if truncated:
            warnings.append(
                {
                    "code": "result_truncated",
                    "message": "Topology result limit was reached.",
                    "details": {"result_limit": result_limit},
                }
            )
        visible_devices = all_devices[:result_limit]
        visible_device_ids = {item[0].id for item in visible_devices}
        visible_links = [
            link
            for link in links
            if link.source_device_id in visible_device_ids
            and link.target_device_id in visible_device_ids
        ]
        data = {
            "start_device": device_summary(device),
            "mode": mode,
            "max_depth": max_depth,
            "truncated": truncated,
            "device_count": len(visible_devices),
            "link_count": len(visible_links) if include_links else 0,
            "devices": [
                {
                    **device_summary(item),
                    "depth": depth,
                    "relation": "start" if item.id == device.id else mode,
                }
                for item, depth in visible_devices
            ],
            "links": [link_summary(link) for link in visible_links] if include_links else [],
        }
        return _ok(request=request, snapshot=snapshot, data=data, warnings=warnings)
    except NetworkTopologyCycleError as exc:
        return _error(
            InternalNetworkAPIError(
                "conflict",
                "Topology cycle detected.",
                status=409,
                details={"reason": str(exc)},
            )
        )
    except (ValueError, InternalNetworkAPIError) as exc:
        if isinstance(exc, InternalNetworkAPIError):
            return _error(exc)
        return _error(
            InternalNetworkAPIError(
                "validation_error",
                "max_depth must be an integer.",
                status=400,
                details={"field": "max_depth"},
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


def _topology_descendants(*, snapshot: DataSnapshot, start: NetworkDevice, max_depth: int):
    devices: dict[int, tuple[NetworkDevice, int]] = {start.id: (start, 0)}
    links_by_id: dict[int, NetworkLink] = {}
    queue: list[tuple[NetworkDevice, int]] = [(start, 0)]
    seen_edges: set[int] = set()
    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        links = (
            NetworkLink.objects.filter(data_snapshot=snapshot, source_device=current)
            .select_related("source_device", "target_device", "target_device__city")
            .order_by("link_code")
        )
        for link in links:
            if link.id in seen_edges:
                continue
            seen_edges.add(link.id)
            links_by_id[link.id] = link
            child = link.target_device
            if child.id in devices:
                continue
            devices[child.id] = (child, depth + 1)
            queue.append((child, depth + 1))
    return list(devices.values()), sorted(links_by_id.values(), key=lambda link: link.link_code)


def _topology_ancestors(*, snapshot: DataSnapshot, start: NetworkDevice, max_depth: int):
    devices: dict[int, tuple[NetworkDevice, int]] = {start.id: (start, 0)}
    links_by_id: dict[int, NetworkLink] = {}
    queue: list[tuple[NetworkDevice, int]] = [(start, 0)]
    seen_edges: set[int] = set()
    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        links = (
            NetworkLink.objects.filter(data_snapshot=snapshot, target_device=current)
            .select_related("source_device", "target_device", "source_device__city")
            .order_by("link_code")
        )
        for link in links:
            if link.id in seen_edges:
                continue
            seen_edges.add(link.id)
            links_by_id[link.id] = link
            parent = link.source_device
            if parent.id in devices:
                continue
            devices[parent.id] = (parent, depth + 1)
            queue.append((parent, depth + 1))
    return list(devices.values()), sorted(links_by_id.values(), key=lambda link: link.link_code)


@require_GET
@internal_service_required
def search_alarms(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        from_time, to_time = _parse_date_range(request)
        queryset = (
            Alarm.objects.filter(data_snapshot=snapshot)
            .select_related(
                "alarm_type",
                "device",
                "device__city",
                "device__district",
                "device__neighborhood",
                "network_link",
                "network_link__source_device",
                "network_link__target_device",
                "network_port",
                "network_port__device",
                "line_connection",
                "line_connection__port",
                "line_connection__port__device",
                "line_connection__access_segment",
                "failure_domain",
                "subscription_connection",
                "subscription_connection__line_connection",
                "subscription_connection__line_connection__port",
                "subscription_connection__line_connection__port__device",
            )
            .prefetch_related("incident_alarms__incident")
        )
        if request.GET.get("alarm_id"):
            queryset = queryset.filter(alarm_id=request.GET["alarm_id"])
        if request.GET.get("alarm_type_code"):
            queryset = queryset.filter(alarm_type__code=request.GET["alarm_type_code"])
        if request.GET.get("severity"):
            queryset = queryset.filter(severity=request.GET["severity"])
        if request.GET.get("status"):
            queryset = queryset.filter(status=request.GET["status"])
        if request.GET.get("source_kind"):
            queryset = _filter_alarm_source_kind(queryset, request.GET["source_kind"])
        if request.GET.get("device_code"):
            device_code = request.GET["device_code"]
            queryset = queryset.filter(
                Q(device__code=device_code)
                | Q(network_link__source_device__code=device_code)
                | Q(network_link__target_device__code=device_code)
                | Q(network_port__device__code=device_code)
                | Q(line_connection__port__device__code=device_code)
                | Q(subscription_connection__line_connection__port__device__code=device_code)
            )
        if request.GET.get("network_link_code"):
            queryset = queryset.filter(network_link__link_code=request.GET["network_link_code"])
        if request.GET.get("incident_code"):
            queryset = queryset.filter(
                incident_alarms__incident__incident_number=request.GET["incident_code"]
            )
        if from_time:
            queryset = queryset.filter(detected_at__gte=from_time)
        if to_time:
            queryset = queryset.filter(detected_at__lte=to_time)
        queryset = queryset.order_by("-detected_at", "alarm_id").distinct()
        items = list(queryset[cursor : cursor + limit + 1])
        page = items[:limit]
        next_cursor = str(cursor + limit) if len(items) > limit else None
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "alarms": [alarm_summary(alarm) for alarm in page],
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
        )
    except InternalNetworkAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


def _filter_alarm_source_kind(queryset, source_kind: str):
    mapping = {
        "device": Q(device__isnull=False),
        "network_link": Q(network_link__isnull=False),
        "network_port": Q(network_port__isnull=False),
        "line_connection": Q(line_connection__isnull=False),
        "failure_domain": Q(failure_domain__isnull=False),
        "subscription_connection": Q(subscription_connection__isnull=False),
    }
    condition = mapping.get(source_kind)
    if condition is None:
        raise InternalNetworkAPIError(
            "validation_error",
            "source_kind is not supported.",
            status=400,
            details={"source_kind": source_kind},
        )
    return queryset.filter(condition)


@require_GET
@internal_service_required
def search_outages(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        evaluation_time = _parse_dt(
            request.GET.get("evaluation_time"),
            field_name="evaluation_time",
        )
        from_time, to_time = _parse_date_range(request)
        queryset = _filtered_outages(snapshot=snapshot, request=request)
        if from_time:
            queryset = queryset.filter(started_at__gte=from_time)
        if to_time:
            queryset = queryset.filter(started_at__lte=to_time)
        queryset = queryset.order_by("-started_at", "outage_code")
        service = OutageService()
        items = list(queryset[cursor : cursor + limit + 1])
        page = items[:limit]
        durations = [_duration_payload(service, outage, evaluation_time) for outage in page]
        next_cursor = str(cursor + limit) if len(items) > limit else None
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "outages": [
                    outage_summary(outage, duration=duration)
                    for outage, duration in zip(page, durations, strict=True)
                ],
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
        )
    except (OutageServiceError, InternalNetworkAPIError) as exc:
        if isinstance(exc, InternalNetworkAPIError):
            return _error(exc)
        return _error(
            InternalNetworkAPIError(
                "validation_error",
                str(exc),
                status=400,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


def _filtered_outages(*, snapshot: DataSnapshot, request):
    queryset = Outage.objects.filter(data_snapshot=snapshot).select_related(
        "incident",
        "incident__primary_device",
        "source_device",
        "source_device__city",
        "source_device__district",
        "source_device__neighborhood",
    )
    if request.GET.get("outage_type"):
        queryset = queryset.filter(outage_type=request.GET["outage_type"])
    if request.GET.get("status"):
        queryset = queryset.filter(status=request.GET["status"])
    if request.GET.get("source_device_code"):
        queryset = queryset.filter(source_device__code=request.GET["source_device_code"])
    if request.GET.get("incident_code"):
        queryset = queryset.filter(incident__incident_number=request.GET["incident_code"])
    if request.GET.get("city"):
        queryset = queryset.filter(source_device__city__name=request.GET["city"])
    if request.GET.get("district"):
        queryset = queryset.filter(source_device__district__name=request.GET["district"])
    if request.GET.get("device_type"):
        queryset = queryset.filter(source_device__device_type=request.GET["device_type"])
    return queryset


@require_GET
@internal_service_required
def get_outage_details(request, outage_code: str):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        evaluation_time = _parse_dt(
            request.GET.get("evaluation_time"),
            field_name="evaluation_time",
        )
        outage = _get_outage(snapshot, outage_code)
        duration = _duration_payload(OutageService(), outage, evaluation_time)
        alarm_links = (
            IncidentAlarm.objects.filter(data_snapshot=snapshot, incident=outage.incident)
            .select_related(
                "alarm",
                "alarm__alarm_type",
                "alarm__device",
                "alarm__network_link",
                "alarm__network_link__source_device",
                "alarm__network_link__target_device",
                "alarm__network_port",
                "alarm__network_port__device",
                "alarm__line_connection",
                "alarm__line_connection__port",
                "alarm__line_connection__port__device",
                "alarm__line_connection__access_segment",
                "alarm__failure_domain",
                "incident",
            )
            .order_by("role", "alarm__alarm_id")
        )
        maintenance = None
        if outage.incident_id:
            maintenance = (
                MaintenanceWindow.objects.filter(
                    data_snapshot=snapshot,
                    linked_incident=outage.incident,
                )
                .select_related("linked_incident")
                .first()
            )
        data = {
            "outage": outage_summary(outage, duration=duration),
            "alarms": [{"role": item.role, **alarm_summary(item.alarm)} for item in alarm_links],
            "maintenance_window": (
                None
                if maintenance is None
                else {
                    "reference_code": maintenance.reference_code,
                    "status": maintenance.status,
                    "planned_start_at": iso_or_none(maintenance.planned_start_at),
                    "planned_end_at": iso_or_none(maintenance.planned_end_at),
                    "actual_start_at": iso_or_none(maintenance.actual_start_at),
                    "actual_end_at": iso_or_none(maintenance.actual_end_at),
                    "expected_impact_class": maintenance.expected_impact_class,
                    "actual_impact_class": maintenance.actual_impact_class,
                    "overrun_minutes": maintenance.overrun_minutes,
                }
            ),
        }
        return _ok(request=request, snapshot=snapshot, data=data)
    except (OutageServiceError, InternalNetworkAPIError) as exc:
        if isinstance(exc, InternalNetworkAPIError):
            return _error(exc)
        return _error(InternalNetworkAPIError("validation_error", str(exc), status=400))
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def calculate_customer_impact(request, outage_code: str):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        evaluation_time = _parse_dt(
            request.GET.get("evaluation_time"),
            field_name="evaluation_time",
        )
        outage = _get_outage(snapshot, outage_code)
        assessments = CustomerImpactAssessment.objects.filter(
            data_snapshot=snapshot,
            causal_event=outage.causal_event,
        ).select_related(
            "subscription__customer",
            "subscription__service_package",
        )
        if outage.causal_event_id and assessments.exists():
            rows = list(assessments)
            impacted = [
                assessment
                for assessment in rows
                if assessment.status == CustomerImpactStatus.VERIFIED_IMPACT.value
            ]
            impacted_subscriptions = {
                assessment.subscription.subscription_number: assessment.subscription
                for assessment in impacted
                if assessment.subscription_id
            }
            impacted_customers = {
                subscription.customer.customer_number: subscription.customer
                for subscription in impacted_subscriptions.values()
            }
            status_counts = Counter(assessment.status for assessment in rows)
            protected_count = sum(
                ImpactReason.FAILOVER_PROTECTED.value in assessment.reasons
                for assessment in rows
            )
            unknown_count = (
                status_counts[CustomerImpactStatus.INSUFFICIENT_EVIDENCE.value]
                + status_counts[CustomerImpactStatus.POTENTIAL_IMPACT.value]
            )
            data = {
                "outage_code": outage.outage_code,
                "source_device_code": outage.source_device.code,
                "evaluation_window": {
                    "started_at": outage.started_at.isoformat(),
                    "ended_at": (outage.ended_at or evaluation_time).isoformat()
                    if outage.ended_at or evaluation_time
                    else None,
                },
                "potential_connection_count": len(rows),
                "verified_impacted_count": len(impacted),
                "verified_no_impact_count": status_counts[
                    CustomerImpactStatus.VERIFIED_NO_IMPACT.value
                ],
                "insufficient_evidence_count": unknown_count,
                "affected_subscription_count": len(impacted_subscriptions),
                "affected_customer_count": len(impacted_customers),
                "segment_distribution": dict(
                    sorted(
                        Counter(
                            customer.segment for customer in impacted_customers.values()
                        ).items()
                    )
                ),
                "priority_distribution": dict(
                    sorted(
                        Counter(
                            customer.priority_level for customer in impacted_customers.values()
                        ).items()
                    )
                ),
                "technology_distribution": dict(
                    sorted(
                        Counter(
                            subscription.service_package.technology
                            for subscription in impacted_subscriptions.values()
                        ).items()
                    )
                ),
                "primary_backup": {
                    "failover_protected_subscription_count": protected_count,
                },
                "protected_failover": {"subscription_count": protected_count},
                "failover_path_diversity_counts": {},
                "impact_source": "customer_impact_assessment",
            }
            warnings = []
        else:
            result = CustomerImpactService().calculate_impact(
                outage=outage,
                snapshot=snapshot,
                evaluation_time=evaluation_time,
            )
            payload = _dataclass_payload(result)
            data = {
                "outage_code": payload["outage_code"],
                "source_device_code": payload["source_device_code"],
                "evaluation_window": payload["evaluation_window"],
                "affected_subscription_count": payload["affected_subscription_count"],
                "affected_customer_count": payload["affected_customer_count"],
                "segment_distribution": payload["customer_segment_counts"],
                "priority_distribution": payload["customer_priority_counts"],
                "technology_distribution": payload["package_technology_counts"],
                "primary_backup": {
                    "failover_protected_subscription_count": payload[
                        "failover_protected_subscription_count"
                    ],
                },
                "protected_failover": {
                    "subscription_count": payload["failover_protected_subscription_count"],
                },
                "failover_path_diversity_counts": payload["failover_path_diversity_counts"],
                "impact_source": "topology_fallback",
            }
            warnings = [
                {
                    "code": "failover_path_diversity_warning",
                    "message": "A protected subscription has incomplete path diversity evidence.",
                    "details": warning,
                }
                for warning in payload["failover_warnings"]
            ]
        return _ok(request=request, snapshot=snapshot, data=data, warnings=warnings)
    except (CustomerImpactServiceError, OutageServiceError, InternalNetworkAPIError) as exc:
        if isinstance(exc, InternalNetworkAPIError):
            return _error(exc)
        return _error(InternalNetworkAPIError("validation_error", str(exc), status=400))
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def aggregate_location_impact(request):
    """Return only canonical aggregate assessment counts for an explicit scope."""
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        from_time, to_time = _parse_date_range(request)
        city = request.GET.get("city")
        district = request.GET.get("district")
        if from_time is None or to_time is None or not (city or district):
            raise InternalNetworkAPIError(
                "validation_error",
                "A date range and city or district are required.",
                status=400,
            )
        outages = Outage.objects.filter(
            data_snapshot=snapshot,
            started_at__gte=from_time,
            started_at__lte=to_time,
        )
        assessments = CustomerImpactAssessment.objects.filter(
            data_snapshot=snapshot,
            causal_event__started_at__gte=from_time,
            causal_event__started_at__lte=to_time,
        )
        if city:
            outages = outages.filter(source_device__city__name=city)
            assessments = assessments.filter(causal_event__root_device__city__name=city)
        if district:
            outages = outages.filter(source_device__district__name=district)
            assessments = assessments.filter(causal_event__root_device__district__name=district)
        assessment_count = assessments.count()
        status_counts = dict(assessments.values_list("status").annotate(count=Count("id")))
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "outage_count": outages.count(),
                "potential_connection_count": assessment_count if assessment_count else None,
                "verified_impacted_count": (
                    status_counts.get(CustomerImpactStatus.VERIFIED_IMPACT.value, 0)
                    if assessment_count
                    else None
                ),
                "verified_no_impact_count": (
                    status_counts.get(CustomerImpactStatus.VERIFIED_NO_IMPACT.value, 0)
                    if assessment_count
                    else None
                ),
                "insufficient_evidence_count": (
                    status_counts.get(CustomerImpactStatus.INSUFFICIENT_EVIDENCE.value, 0)
                    if assessment_count
                    else None
                ),
                "failover_protected_count": (
                    assessments.filter(
                        reasons__contains=[ImpactReason.FAILOVER_PROTECTED.value]
                    ).count()
                    if assessment_count
                    else None
                ),
            },
        )
    except InternalNetworkAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def analyze_operational_analytics(request):
    """Return a backend-owned aggregate result; raw alarm rows never reach the LLM."""
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))

        def optional_bool(name: str) -> bool | None:
            value = request.GET.get(name)
            if value is None:
                return None
            if value.lower() not in {"true", "false"}:
                raise InternalNetworkAPIError("validation_error", f"{name} is invalid.", status=400)
            return value.lower() == "true"

        spec = AnalyticsSpec(
            metric=request.GET.get("metric", ""),
            aggregation=request.GET.get("aggregation", ""),
            group_by=request.GET.get("group_by") or None,
            direction=request.GET.get("direction", "desc"),
            limit=_parse_limit(request) if request.GET.get("limit") else None,
            time_grain=request.GET.get("time_grain") or None,
            from_time=_parse_dt(request.GET.get("from_time"), field_name="from_time"),
            to_time=_parse_dt(request.GET.get("to_time"), field_name="to_time"),
            city=request.GET.get("city") or None,
            district=request.GET.get("district") or None,
            root_alarm_type=request.GET.get("root_alarm_type") or None,
            event_type=request.GET.get("event_type") or None,
            device_type=request.GET.get("device_type") or None,
            full_outage=optional_bool("full_outage"),
            failed_failover=optional_bool("failed_failover"),
        )
        return _ok(
            request=request,
            snapshot=snapshot,
            data=OperationalAnalyticsService().analyze(snapshot=snapshot, spec=spec),
        )
    except (AnalyticsInputError, InternalNetworkAPIError) as exc:
        if isinstance(exc, InternalNetworkAPIError):
            return _error(exc)
        return _error(InternalNetworkAPIError("validation_error", str(exc), status=400))
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def correlate_alarms(request, anchor_alarm_id: str):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        limit = _parse_limit(request)
        try:
            anchor = Alarm.objects.select_related("alarm_type", "device").get(
                data_snapshot=snapshot, alarm_id=anchor_alarm_id
            )
        except Alarm.DoesNotExist as exc:
            raise InternalNetworkAPIError(
                "not_found",
                "Anchor alarm was not found.",
                status=404,
                details={"anchor_alarm_id": anchor_alarm_id},
            ) from exc
        results = AlarmCorrelationService().find_correlations(
            anchor_alarm=anchor,
            snapshot=snapshot,
        )[:limit]
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "anchor_alarm": alarm_summary(anchor),
                "candidate_alarms": [_dataclass_payload(result) for result in results],
                "result_count": len(results),
            },
        )
    except (AlarmCorrelationServiceError, InternalNetworkAPIError) as exc:
        if isinstance(exc, InternalNetworkAPIError):
            return _error(exc)
        return _error(InternalNetworkAPIError("validation_error", str(exc), status=400))
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def rank_root_cause_candidates(request, outage_code: str):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        evaluation_time = _parse_dt(
            request.GET.get("evaluation_time"),
            field_name="evaluation_time",
        )
        limit = _parse_limit(request)
        outage = _get_outage(snapshot, outage_code)
        results = RootCauseService().analyze(
            outage=outage,
            snapshot=snapshot,
            evaluation_time=evaluation_time,
        )[:limit]
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "outage_code": outage.outage_code,
                "candidates": [_dataclass_payload(result) for result in results],
                "result_count": len(results),
            },
        )
    except (RootCauseServiceError, OutageServiceError, InternalNetworkAPIError) as exc:
        if isinstance(exc, InternalNetworkAPIError):
            return _error(exc)
        return _error(InternalNetworkAPIError("validation_error", str(exc), status=400))
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def get_longest_outage(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        limit = _parse_limit(request, default=1, maximum=MAX_LONGEST_OUTAGE_LIMIT)
        evaluation_time = _parse_dt(
            request.GET.get("evaluation_time"),
            field_name="evaluation_time",
        )
        from_time, to_time = _parse_date_range(request)
        technology = request.GET.get("technology")
        queryset = _filtered_outages(snapshot=snapshot, request=request)
        if from_time:
            queryset = queryset.filter(Q(ended_at__isnull=True) | Q(ended_at__gte=from_time))
        if to_time:
            queryset = queryset.filter(started_at__lte=to_time)
        outage_service = OutageService()
        impact_service = CustomerImpactService()
        candidates = []
        for outage in queryset.order_by("outage_code"):
            duration = _duration_payload(outage_service, outage, evaluation_time)
            impact = None
            if technology:
                impact = _dataclass_payload(
                    impact_service.calculate_impact(
                        outage=outage,
                        snapshot=snapshot,
                        evaluation_time=evaluation_time,
                    )
                )
                if impact["package_technology_counts"].get(technology, 0) == 0:
                    continue
            candidates.append((outage, duration, impact))
        candidates.sort(key=lambda item: (-item[1]["seconds"], item[0].outage_code))
        ranked = []
        for rank, (outage, duration, impact) in enumerate(candidates[:limit], start=1):
            if impact is None:
                impact = _dataclass_payload(
                    impact_service.calculate_impact(
                        outage=outage,
                        snapshot=snapshot,
                        evaluation_time=evaluation_time,
                    )
                )
            ranked.append(
                {
                    "rank": rank,
                    "outage": outage_summary(outage, duration=duration),
                    "location": device_summary(outage.source_device)["location"],
                    "affected_subscription_count": impact["affected_subscription_count"],
                    "affected_customer_count": impact["affected_customer_count"],
                }
            )
        return _ok(
            request=request,
            snapshot=snapshot,
            data={"outages": ranked, "result_count": len(ranked)},
        )
    except (
        CustomerImpactServiceError,
        OutageServiceError,
        InternalNetworkAPIError,
    ) as exc:
        if isinstance(exc, InternalNetworkAPIError):
            return _error(exc)
        return _error(InternalNetworkAPIError("validation_error", str(exc), status=400))
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)
