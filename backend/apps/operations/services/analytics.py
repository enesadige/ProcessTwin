"""Deterministic, event-grain operational analytics over a data snapshot."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db.models import Prefetch

from apps.datasets.models import DataSnapshot
from apps.operations.contracts import CustomerImpactStatus, ImpactReason
from apps.operations.models import (
    Alarm,
    CausalEvent,
    CustomerImpactAssessment,
    Outage,
    ServiceImpactClass,
)


class AnalyticsInputError(ValueError):
    """Raised when a requested analytics combination is not meaningful."""


_METRICS = {
    "affected_customers",
    "affected_subscriptions",
    "potential_subscriptions",
    "outage_count",
    "event_count",
    "alarm_count",
    "compensation_amount",
    "failed_failover_count",
    "full_outage_count",
}
_AGGREGATIONS = {"count", "sum", "average", "min", "max"}
_GROUPS = {
    "event",
    "root_alarm_type",
    "city",
    "district",
    "device_type",
    "event_type",
    "full_outage_status",
    "failover_status",
    "time_bucket",
}
_COUNT_ONLY = {
    "outage_count",
    "event_count",
    "alarm_count",
    "failed_failover_count",
    "full_outage_count",
}
_FAILED_FAILOVER_ALARM_TYPE = "FAILOVER_UNSUCCESSFUL"


@dataclass(frozen=True)
class AnalyticsSpec:
    metric: str
    aggregation: str
    group_by: str | None = None
    direction: str = "desc"
    limit: int | None = None
    time_grain: str | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None
    city: str | None = None
    district: str | None = None
    root_alarm_type: str | None = None
    event_type: str | None = None
    device_type: str | None = None
    full_outage: bool | None = None
    failed_failover: bool | None = None

    def validate(self) -> None:
        if self.metric not in _METRICS or self.aggregation not in _AGGREGATIONS:
            raise AnalyticsInputError("unsupported metric or aggregation")
        if self.metric in _COUNT_ONLY and self.aggregation != "count":
            raise AnalyticsInputError("metric only supports count")
        if self.group_by and self.group_by not in _GROUPS:
            raise AnalyticsInputError("unsupported grouping")
        if self.direction not in {"asc", "desc"}:
            raise AnalyticsInputError("invalid ranking direction")
        if self.limit is not None and not 1 <= self.limit <= 100:
            raise AnalyticsInputError("invalid ranking limit")
        if self.time_grain not in {None, "day", "week", "month"}:
            raise AnalyticsInputError("invalid time grain")
        if self.group_by == "time_bucket" and not self.time_grain:
            raise AnalyticsInputError("time bucket requires time grain")


class OperationalAnalyticsService:
    """Computes authoritative aggregates at one causal-event grain.

    Impact is deduplicated inside an event by customer/subscription.  Events
    lacking any authoritative impact assessment are excluded from impact
    aggregates rather than interpreted as zero.
    """

    def analyze(self, *, snapshot: DataSnapshot, spec: AnalyticsSpec) -> dict[str, Any]:
        spec.validate()
        records = [self._record(event) for event in self._events(snapshot, spec)]
        records = [record for record in records if self._matches(record, spec)]
        eligible, excluded_unknown = self._eligible(records, spec.metric)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in eligible:
            grouped[self._group_label(record, spec)].append(record)
        rows = [self._row(label, values, spec) for label, values in grouped.items()]
        if spec.group_by == "time_bucket":
            rows.sort(key=lambda row: row["label"])
            self._add_period_changes(rows)
        else:
            rows.sort(
                key=lambda row: (Decimal(str(row["value"])), row["label"]),
                reverse=spec.direction == "desc",
            )
        if spec.limit:
            rows = rows[: spec.limit]
        return {
            "analysis_type": "operational_analytics",
            "metric": spec.metric,
            "aggregation": spec.aggregation,
            "group_by": spec.group_by,
            "filters": self._filters(spec),
            "time_grain": spec.time_grain,
            "ranking_direction": spec.direction,
            "limit": spec.limit,
            "rows": rows,
            "included_event_count": len(eligible),
            "excluded_unknown_count": excluded_unknown,
            "deduplication_grain": "causal_event",
        }

    @staticmethod
    def _add_period_changes(rows: list[dict[str, Any]]) -> None:
        """Attach safe absolute changes without percentage math over a zero base."""
        previous: Decimal | None = None
        for row in rows:
            current = Decimal(str(row["value"]))
            if previous is None:
                row["trend_direction"] = "unchanged"
                row["absolute_change"] = None
            else:
                difference = current - previous
                row["absolute_change"] = str(difference) if difference % 1 else int(difference)
                row["trend_direction"] = (
                    "increase" if difference > 0 else "decrease" if difference < 0 else "unchanged"
                )
            previous = current

    @staticmethod
    def _events(snapshot: DataSnapshot, spec: AnalyticsSpec):
        queryset = (
            CausalEvent.objects.filter(data_snapshot=snapshot)
            .select_related("root_device__city", "root_device__district")
            .prefetch_related(
                Prefetch("alarms", queryset=Alarm.objects.select_related("alarm_type")),
                Prefetch(
                    "outages",
                    queryset=Outage.objects.select_related(
                        "incident", "source_device"
                    ).prefetch_related("compensation_evaluations"),
                ),
                Prefetch(
                    "customer_impact_assessments",
                    queryset=CustomerImpactAssessment.objects.select_related(
                        "subscription__customer"
                    ),
                ),
            )
        )
        if spec.from_time:
            queryset = queryset.filter(started_at__gte=spec.from_time)
        if spec.to_time:
            queryset = queryset.filter(started_at__lte=spec.to_time)
        return queryset

    @staticmethod
    def _record(event: CausalEvent) -> dict[str, Any]:
        assessments = list(event.customer_impact_assessments.all())
        verified = [
            item
            for item in assessments
            if item.status == CustomerImpactStatus.VERIFIED_IMPACT.value
        ]
        known_impact = bool(assessments) and any(
            item.status
            in {
                CustomerImpactStatus.VERIFIED_IMPACT.value,
                CustomerImpactStatus.VERIFIED_NO_IMPACT.value,
            }
            for item in assessments
        )
        subscriptions = {item.subscription_id for item in verified if item.subscription_id}
        customers = {item.subscription.customer_id for item in verified if item.subscription_id}
        protected = sum(
            ImpactReason.FAILOVER_PROTECTED.value in item.reasons for item in assessments
        )
        outages = list(event.outages.all())
        incident = next((outage.incident for outage in outages if outage.incident_id), None)
        full_outage = any(
            outage.impact_type == ServiceImpactClass.FULL_OUTAGE.value for outage in outages
        )
        alarms = list(event.alarms.all())
        root_alarm = next(
            (
                alarm
                for alarm in alarms
                if alarm.metadata.get("causal_role") == "root"
            ),
            None,
        )
        root_alarm = root_alarm or next(iter(alarms), None)
        root_device = event.root_device or next((outage.source_device for outage in outages), None)
        compensations = [
            evaluation for outage in outages for evaluation in outage.compensation_evaluations.all()
        ]
        amount = sum((evaluation.proposed_amount for evaluation in compensations), Decimal("0.00"))
        failed_failover = bool(incident and incident.failover_result == "failed") or any(
            alarm.alarm_type.code == _FAILED_FAILOVER_ALARM_TYPE for alarm in alarms
        )
        return {
            "event_code": event.event_code,
            "started_at": event.started_at,
            "event_type": event.event_type,
            "city": root_device.city.name if root_device and root_device.city_id else None,
            "district": root_device.district.name
            if root_device and root_device.district_id
            else None,
            "device_type": root_device.device_type if root_device else None,
            "root_alarm_type": root_alarm.alarm_type.code if root_alarm else None,
            "known_impact": known_impact,
            "affected_customers": len(customers),
            "affected_subscriptions": len(subscriptions),
            "potential_subscriptions": len(assessments) if assessments else None,
            "outage_count": len(outages),
            "event_count": 1,
            "alarm_count": 1 if root_alarm else 0,
            "compensation_amount": amount,
            "failed_failover_count": int(failed_failover),
            "full_outage_count": int(full_outage),
            "full_outage": full_outage,
            "failed_failover": failed_failover,
            "failover_protected": protected,
        }

    @staticmethod
    def _matches(record: dict[str, Any], spec: AnalyticsSpec) -> bool:
        return all(
            value is None or record.get(field) == value
            for field, value in {
                "city": spec.city,
                "district": spec.district,
                "root_alarm_type": spec.root_alarm_type,
                "event_type": spec.event_type,
                "device_type": spec.device_type,
                "full_outage": spec.full_outage,
                "failed_failover": spec.failed_failover,
            }.items()
        )

    @staticmethod
    def _eligible(records: list[dict[str, Any]], metric: str) -> tuple[list[dict[str, Any]], int]:
        if metric in {"affected_customers", "affected_subscriptions", "potential_subscriptions"}:
            eligible = [record for record in records if record["known_impact"]]
            return eligible, len(records) - len(eligible)
        return records, 0

    @staticmethod
    def _group_label(record: dict[str, Any], spec: AnalyticsSpec) -> str:
        if spec.group_by == "time_bucket":
            value = record["started_at"]
            if spec.time_grain == "month":
                return value.strftime("%Y-%m")
            if spec.time_grain == "week":
                return value.strftime("%G-W%V")
            return value.date().isoformat()
        if spec.group_by:
            field = "event_code" if spec.group_by == "event" else spec.group_by
            value = record.get(field)
            return str(value) if value is not None else "Bilinmiyor"
        return "Toplam"

    @staticmethod
    def _row(label: str, values: list[dict[str, Any]], spec: AnalyticsSpec) -> dict[str, Any]:
        numeric = [value[spec.metric] for value in values]
        if spec.aggregation == "count":
            result: Any = (
                sum(numeric)
                if spec.metric in {"full_outage_count", "failed_failover_count"}
                else len(values)
            )
        elif spec.aggregation == "sum":
            result = sum(numeric, Decimal("0.00") if spec.metric == "compensation_amount" else 0)
        elif spec.aggregation == "average":
            result = sum(numeric) / len(numeric) if numeric else 0
        elif spec.aggregation == "min":
            result = min(numeric) if numeric else 0
        else:
            result = max(numeric) if numeric else 0
        return {
            "label": label,
            "value": str(result) if isinstance(result, Decimal) else result,
            "event_count": len(values),
        }

    @staticmethod
    def _filters(spec: AnalyticsSpec) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "city": spec.city,
                "district": spec.district,
                "root_alarm_type": spec.root_alarm_type,
                "event_type": spec.event_type,
                "device_type": spec.device_type,
                "full_outage": spec.full_outage,
                "failed_failover": spec.failed_failover,
                "from_time": spec.from_time.isoformat() if spec.from_time else None,
                "to_time": spec.to_time.isoformat() if spec.to_time else None,
            }.items()
            if value is not None
        }
