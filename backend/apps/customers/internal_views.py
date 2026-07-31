from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from apps.core.internal_api import internal_service_required
from apps.customers.internal_serializers import (
    compact_subscription_summary,
    compensation_history_summary,
    counts_by,
    customer_summary,
    payment_aggregate,
    payment_summary,
    safe_payload,
    subscription_summary,
)
from apps.customers.models import (
    CompensationHistory,
    Customer,
    PaymentRecord,
    Subscription,
    SubscriptionConnection,
)
from apps.customers.services.impact import CustomerImpactService, CustomerImpactServiceError
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.network.internal_serializers import (
    device_summary,
    iso_or_none,
    snapshot_summary,
)
from apps.network.models import NetworkDevice
from apps.network.services.topology import NetworkTopologyCycleError, NetworkTopologyService
from apps.operations.models import Outage
from apps.operations.services.outages import OutageService, OutageServiceError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_OUTAGE_SCAN = 300


class InternalCustomerAPIError(Exception):
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
            "data": safe_payload(data),
            "warnings": warnings or [],
            "evidence": evidence or [],
            "metadata": {
                "correlation_id": getattr(request, "correlation_id", None),
                "snapshot": snapshot_summary(snapshot),
            },
        }
    )


def _error(exc: InternalCustomerAPIError) -> JsonResponse:
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
        InternalCustomerAPIError(
            "internal_error",
            "Customer internal API failed.",
            status=500,
            details={"reason": exc.__class__.__name__},
        )
    )


def _resolve_snapshot(identifier: str | None) -> DataSnapshot:
    if not identifier:
        raise InternalCustomerAPIError(
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
        raise InternalCustomerAPIError(
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
        raise InternalCustomerAPIError(
            "validation_error",
            "Dataset slug must resolve to exactly one snapshot.",
            status=400,
            details={"dataset_slug": identifier, "snapshot_count": len(snapshots)},
        )
    return snapshots[0]


def _parse_dt(value: str | None, *, field_name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise InternalCustomerAPIError(
                "validation_error",
                f"{field_name} is required.",
                status=400,
                details={"field": field_name},
            )
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise InternalCustomerAPIError(
            "validation_error",
            f"{field_name} must be a valid ISO 8601 datetime.",
            status=400,
            details={"field": field_name},
        )
    if timezone.is_naive(parsed):
        raise InternalCustomerAPIError(
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
        raise InternalCustomerAPIError(
            "validation_error",
            "from_time cannot be later than to_time.",
            status=400,
            details={"fields": ["from_time", "to_time"]},
        )
    return from_time, to_time


def _parse_bool(request, field_name: str, *, default: bool = False) -> bool:
    value = request.GET.get(field_name)
    if value in (None, ""):
        return default
    if value.lower() in {"true", "1", "yes"}:
        return True
    if value.lower() in {"false", "0", "no"}:
        return False
    raise InternalCustomerAPIError(
        "validation_error",
        f"{field_name} must be a boolean.",
        status=400,
        details={"field": field_name},
    )


def _parse_limit(request, *, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    value = request.GET.get("limit", str(default))
    try:
        limit = int(value)
    except ValueError as exc:
        raise InternalCustomerAPIError(
            "validation_error",
            "limit must be an integer.",
            status=400,
            details={"field": "limit"},
        ) from exc
    if limit < 1 or limit > maximum:
        raise InternalCustomerAPIError(
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
        raise InternalCustomerAPIError(
            "validation_error",
            "cursor must be an integer offset.",
            status=400,
            details={"field": "cursor"},
        ) from exc
    if cursor < 0:
        raise InternalCustomerAPIError(
            "validation_error",
            "cursor must be zero or greater.",
            status=400,
            details={"field": "cursor"},
        )
    return cursor


def _reference_time(snapshot: DataSnapshot):
    reference_datetime = snapshot.dataset_version.config.get("reference_datetime")
    if not reference_datetime:
        return None
    parsed = parse_datetime(reference_datetime)
    if parsed is None or timezone.is_naive(parsed):
        return None
    return parsed


def _page(items: list[Any], *, cursor: int, limit: int) -> tuple[list[Any], str | None]:
    page = items[cursor : cursor + limit]
    next_cursor = str(cursor + limit) if len(items) > cursor + limit else None
    return page, next_cursor


def _exactly_one_identifier(request) -> tuple[str, str]:
    customer_number = request.GET.get("customer_number")
    subscription_number = request.GET.get("subscription_number")
    if bool(customer_number) == bool(subscription_number):
        raise InternalCustomerAPIError(
            "validation_error",
            "Exactly one of customer_number or subscription_number is required.",
            status=400,
            details={"fields": ["customer_number", "subscription_number"]},
        )
    if customer_number:
        return "customer_number", customer_number
    return "subscription_number", subscription_number


def _get_customer(snapshot: DataSnapshot, customer_number: str) -> Customer:
    try:
        return (
            Customer.objects.select_related("city", "district", "neighborhood")
            .get(data_snapshot=snapshot, customer_number=customer_number)
        )
    except Customer.DoesNotExist as exc:
        raise InternalCustomerAPIError(
            "not_found",
            "Customer was not found.",
            status=404,
            details={"customer_number": customer_number},
        ) from exc


def _get_subscription(snapshot: DataSnapshot, subscription_number: str) -> Subscription:
    try:
        return (
            _subscription_queryset(snapshot)
            .get(subscription_number=subscription_number)
        )
    except Subscription.DoesNotExist as exc:
        raise InternalCustomerAPIError(
            "not_found",
            "Subscription was not found.",
            status=404,
            details={"subscription_number": subscription_number},
        ) from exc


def _subscription_queryset(snapshot: DataSnapshot):
    return (
        Subscription.objects.filter(data_snapshot=snapshot)
        .select_related(
            "customer",
            "customer__city",
            "customer__district",
            "customer__neighborhood",
            "service_package",
            "sla_profile",
        )
        .prefetch_related(
            "connections__line_connection__access_segment",
            "connections__line_connection__port__device",
            "campaign_enrollments",
        )
        .order_by("subscription_number")
    )


def _subscriptions_for_identifier(snapshot: DataSnapshot, request) -> list[Subscription]:
    field_name, value = _exactly_one_identifier(request)
    if field_name == "subscription_number":
        return [_get_subscription(snapshot, value)]
    customer = _get_customer(snapshot, value)
    return list(_subscription_queryset(snapshot).filter(customer=customer))


def _dataclass_payload(value) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    return dict(value)


def _duration_payload(service: OutageService, outage: Outage, evaluation_time) -> dict[str, Any]:
    duration = service.calculate_duration(outage=outage, evaluation_time=evaluation_time)
    return {
        "seconds": duration.seconds,
        "minutes": duration.minutes,
        "is_ongoing": duration.is_ongoing,
        "evaluation_time": iso_or_none(evaluation_time),
    }


@require_GET
@internal_service_required
def get_customer_profile(request, customer_number: str):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        include_subscriptions = _parse_bool(
            request,
            "include_subscriptions",
            default=False,
        )
        include_display_name = _parse_bool(
            request,
            "include_display_name",
            default=False,
        )
        customer = _get_customer(snapshot, customer_number)
        subscriptions = list(_subscription_queryset(snapshot).filter(customer=customer))
        data = {
            "customer": {
                **customer_summary(
                    customer,
                    include_display_name=include_display_name,
                    snapshot=snapshot,
                ),
                "subscription_count": len(subscriptions),
                "subscription_status_counts": counts_by(
                    [subscription.status for subscription in subscriptions]
                ),
            }
        }
        if include_subscriptions:
            data["customer"]["subscriptions"] = [
                compact_subscription_summary(subscription)
                for subscription in subscriptions
            ]
        return _ok(request=request, snapshot=snapshot, data=data)
    except InternalCustomerAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def get_customer_subscription(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        include_connections = _parse_bool(request, "include_connections", default=True)
        include_campaigns = _parse_bool(request, "include_campaigns", default=False)
        subscriptions = _subscriptions_for_identifier(snapshot, request)
        page, next_cursor = _page(subscriptions, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "subscriptions": [
                    subscription_summary(
                        subscription,
                        include_connections=include_connections,
                        include_campaigns=include_campaigns,
                    )
                    for subscription in page
                ],
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
        )
    except InternalCustomerAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def get_customer_payment_status(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        subscriptions = _subscriptions_for_identifier(snapshot, request)
        queryset = (
            PaymentRecord.objects.filter(
                data_snapshot=snapshot,
                subscription__in=subscriptions,
            )
            .select_related("subscription")
            .order_by("subscription__subscription_number", "period")
        )
        if request.GET.get("from_period"):
            queryset = queryset.filter(period__gte=request.GET["from_period"])
        if request.GET.get("to_period"):
            queryset = queryset.filter(period__lte=request.GET["to_period"])
        if request.GET.get("status"):
            queryset = queryset.filter(status=request.GET["status"])
        payments = list(queryset)
        page, next_cursor = _page(payments, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "payments": [payment_summary(payment) for payment in page],
                "aggregate": payment_aggregate(payments),
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
        )
    except InternalCustomerAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def get_customer_outage_history(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        evaluation_time = _parse_dt(
            request.GET.get("evaluation_time"),
            field_name="evaluation_time",
        )
        from_time, to_time = _parse_date_range(request)
        subscriptions = _subscriptions_for_identifier(snapshot, request)
        target_subscription_numbers = {
            subscription.subscription_number for subscription in subscriptions
        }
        queryset = (
            Outage.objects.filter(data_snapshot=snapshot)
            .select_related("incident", "source_device", "source_device__city")
            .order_by("-started_at", "outage_code")
        )
        if from_time:
            queryset = queryset.filter(started_at__gte=from_time)
        if to_time:
            queryset = queryset.filter(started_at__lte=to_time)
        if request.GET.get("impact_class"):
            queryset = queryset.filter(impact_type=request.GET["impact_class"])
        warnings: list[dict[str, Any]] = []
        outage_service = OutageService()
        impact_service = CustomerImpactService(outage_service=outage_service)
        rows: list[dict[str, Any]] = []
        for outage in list(queryset[:MAX_OUTAGE_SCAN]):
            try:
                impact = impact_service.calculate_impact(
                    outage=outage,
                    snapshot=snapshot,
                    evaluation_time=evaluation_time,
                )
                impacted = sorted(
                    target_subscription_numbers
                    & set(impact.affected_subscription_codes)
                )
                if not impacted:
                    continue
                duration = _duration_payload(outage_service, outage, evaluation_time)
            except (CustomerImpactServiceError, OutageServiceError) as exc:
                warnings.append(
                    {
                        "code": "outage_history_item_skipped",
                        "message": "One outage could not be evaluated safely.",
                        "details": {
                            "outage_code": outage.outage_code,
                            "reason": exc.__class__.__name__,
                        },
                    }
                )
                continue
            for subscription_number in impacted:
                rows.append(
                    {
                        "affected_subscription_number": subscription_number,
                        "outage_code": outage.outage_code,
                        "incident_code": (
                            outage.incident.incident_number
                            if outage.incident_id
                            else None
                        ),
                        "source_device_code": (
                            outage.source_device.code
                            if outage.source_device_id
                            else None
                        ),
                        "impact_class": outage.impact_type,
                        "started_at": iso_or_none(outage.started_at),
                        "ended_at": iso_or_none(outage.ended_at),
                        "duration": duration,
                        "relationship": "subscription_in_deterministic_customer_impact",
                    }
                )
        page, next_cursor = _page(rows, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "outages": page,
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
            warnings=warnings,
        )
    except InternalCustomerAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def get_customer_compensation_history(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        from_time, to_time = _parse_date_range(request)
        subscriptions = _subscriptions_for_identifier(snapshot, request)
        queryset = (
            CompensationHistory.objects.filter(
                data_snapshot=snapshot,
                subscription__in=subscriptions,
            )
            .select_related(
                "subscription",
                "incident",
                "outage",
                "rule_version",
                "rule_version__rule",
            )
            .order_by("-decided_at", "reference_code")
        )
        if request.GET.get("decision_status"):
            queryset = queryset.filter(decision_status=request.GET["decision_status"])
        if request.GET.get("settlement_status"):
            queryset = queryset.filter(settlement_status=request.GET["settlement_status"])
        if from_time:
            queryset = queryset.filter(decided_at__gte=from_time)
        if to_time:
            queryset = queryset.filter(decided_at__lte=to_time)
        items = list(queryset)
        page, next_cursor = _page(items, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "compensation_history": [
                    compensation_history_summary(history)
                    for history in page
                ],
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
        )
    except InternalCustomerAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


@require_GET
@internal_service_required
def list_customers_by_device(request, device_code: str):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        include_display_name = _parse_bool(
            request,
            "include_display_name",
            default=False,
        )
        evaluation_time = _parse_dt(
            request.GET.get("evaluation_time"),
            field_name="evaluation_time",
        ) or _reference_time(snapshot)
        device = (
            NetworkDevice.objects.select_related("city", "district", "neighborhood")
            .filter(data_snapshot=snapshot, code=device_code)
            .first()
        )
        if device is None:
            raise InternalCustomerAPIError(
                "not_found",
                "Network device was not found.",
                status=404,
                details={"device_code": device_code},
            )
        service = NetworkTopologyService()
        subgraph = service.get_subgraph(
            device=device,
            snapshot=snapshot,
            evaluation_time=evaluation_time,
        )
        device_ids = {item.id for item in subgraph.devices}
        connections = _valid_served_connections(snapshot=snapshot, evaluation_time=evaluation_time)
        connections = connections.filter(line_connection__port__device_id__in=device_ids)
        if request.GET.get("segment"):
            connections = connections.filter(subscription__customer__segment=request.GET["segment"])
        if request.GET.get("priority_level"):
            connections = connections.filter(
                subscription__customer__priority_level=request.GET["priority_level"]
            )
        if request.GET.get("subscription_status"):
            connections = connections.filter(
                subscription__status=request.GET["subscription_status"]
            )
        grouped: dict[str, dict[str, Any]] = {}
        for connection in connections:
            customer = connection.subscription.customer
            entry = grouped.setdefault(
                customer.customer_number,
                {
                    "customer": customer,
                    "subscription_numbers": set(),
                    "technology_counts": {},
                },
            )
            entry["subscription_numbers"].add(connection.subscription.subscription_number)
            technology = connection.subscription.service_package.technology
            entry["technology_counts"][technology] = (
                entry["technology_counts"].get(technology, 0) + 1
            )
        items = [
            {
                **customer_summary(
                    item["customer"],
                    include_display_name=include_display_name,
                    snapshot=snapshot,
                    related_subscription_count=len(item["subscription_numbers"]),
                    technology_counts=dict(sorted(item["technology_counts"].items())),
                ),
                "served_relationship": {
                    "device_code": device.code,
                    "relationship": "served_by_device_subgraph",
                },
            }
            for item in sorted(grouped.values(), key=lambda item: item["customer"].customer_number)
        ]
        page, next_cursor = _page(items, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "device": device_summary(device),
                "customers": page,
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
        )
    except NetworkTopologyCycleError as exc:
        return _error(
            InternalCustomerAPIError(
                "conflict",
                "Topology cycle detected.",
                status=409,
                details={"reason": str(exc)},
            )
        )
    except InternalCustomerAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)


def _valid_served_connections(*, snapshot: DataSnapshot, evaluation_time):
    queryset = (
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            subscription__data_snapshot=snapshot,
            line_connection__data_snapshot=snapshot,
        )
        .select_related(
            "subscription",
            "subscription__customer",
            "subscription__customer__city",
            "subscription__customer__district",
            "subscription__customer__neighborhood",
            "subscription__service_package",
            "line_connection",
            "line_connection__port",
            "line_connection__port__device",
        )
        .order_by("subscription__customer__customer_number", "subscription__subscription_number")
    )
    if evaluation_time:
        queryset = (
            queryset.filter(valid_from__lte=evaluation_time)
            .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=evaluation_time))
            .filter(subscription__valid_from__lte=evaluation_time)
            .filter(
                Q(subscription__valid_to__isnull=True)
                | Q(subscription__valid_to__gt=evaluation_time)
            )
        )
    return queryset


@require_GET
@internal_service_required
def list_customers_by_location(request):
    try:
        snapshot = _resolve_snapshot(request.GET.get("snapshot_identifier"))
        if not any(
            request.GET.get(field_name)
            for field_name in ("city", "district", "neighborhood")
        ):
            raise InternalCustomerAPIError(
                "validation_error",
                "At least one location filter is required.",
                status=400,
                details={"fields": ["city", "district", "neighborhood"]},
            )
        limit = _parse_limit(request)
        cursor = _parse_cursor(request)
        include_display_name = _parse_bool(
            request,
            "include_display_name",
            default=False,
        )
        queryset = Customer.objects.filter(data_snapshot=snapshot).select_related(
            "city",
            "district",
            "neighborhood",
        )
        if request.GET.get("city"):
            queryset = queryset.filter(city__name=request.GET["city"])
        if request.GET.get("district"):
            queryset = queryset.filter(district__name=request.GET["district"])
        if request.GET.get("neighborhood"):
            queryset = queryset.filter(neighborhood__name=request.GET["neighborhood"])
        if request.GET.get("segment"):
            queryset = queryset.filter(segment=request.GET["segment"])
        if request.GET.get("priority_level"):
            queryset = queryset.filter(priority_level=request.GET["priority_level"])
        if request.GET.get("status"):
            queryset = queryset.filter(status=request.GET["status"])
        queryset = queryset.order_by("customer_number")
        aggregates = queryset.aggregate(total=Count("id"))
        customers = list(queryset)
        page, next_cursor = _page(customers, cursor=cursor, limit=limit)
        return _ok(
            request=request,
            snapshot=snapshot,
            data={
                "location": {
                    "city": request.GET.get("city"),
                    "district": request.GET.get("district"),
                    "neighborhood": request.GET.get("neighborhood"),
                },
                "aggregates": {
                    "total": aggregates["total"],
                    "segment_counts": counts_by([customer.segment for customer in customers]),
                    "priority_counts": counts_by(
                        [customer.priority_level for customer in customers]
                    ),
                    "status_counts": counts_by([customer.status for customer in customers]),
                },
                "customers": [
                    customer_summary(
                        customer,
                        include_display_name=include_display_name,
                        snapshot=snapshot,
                    )
                    for customer in page
                ],
                "result_count": len(page),
                "next_cursor": next_cursor,
            },
        )
    except InternalCustomerAPIError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _sanitize_error(exc)
