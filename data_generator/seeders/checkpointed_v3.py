"""Checkpointed V3 builder over an immutable accepted base snapshot."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime

from django.db import transaction
from django.db.models import Count, F
from django.utils import timezone

from apps.compensation.services.verified_impact import VerifiedImpactCompensationService
from apps.core.choices import ResultStatus
from apps.customers.models import (
    Campaign,
    CampaignAllowedSegment,
    CampaignAllowedServiceType,
    CampaignAllowedTechnology,
    CampaignEnrollment,
    Customer,
    PaymentRecord,
    ServicePackage,
    ServicePackageAllowedSegment,
    ServicePackagePriceVersion,
    SLAProfile,
    Subscription,
    SubscriptionConnection,
)
from apps.datasets.models import DatasetSnapshotStatus, DataSnapshot
from apps.network.models import (
    AccessSegment,
    DeviceFailureDomainMembership,
    FailureDomain,
    LineConnection,
    LineConnectionFailureDomainMembership,
    NetworkDevice,
    NetworkLink,
    NetworkLinkFailureDomainMembership,
    NetworkPort,
)
from apps.operations.models import (
    Alarm,
    AlarmType,
    AlarmTypeAllowedSourceKind,
    AlarmTypeSupportedDeviceType,
    CausalEvent,
    CustomerImpactAssessment,
    Incident,
    IncidentAlarm,
    Outage,
    SessionEvent,
)
from apps.rules.models import Rule, RuleSet, RuleVersion
from data_generator.seeders.causal_timeline import (
    CausalTimelineContext,
    create_scheduled_scenario_instance,
    scheduled_timeline,
)
from data_generator.seeders.multicity_realism import collect_seed_counts, load_existing_seed_world

RUN_KEY = "checkpointed_v3"
_CORRELATION_HELPER_EVENT_CODES = (
    "CE-XREG-0001",
    "CE-XREG-0002",
    "CE-XREG-0003",
)


def schedule_fingerprint() -> str:
    payload = [entry.__dict__ for entry in scheduled_timeline()]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def clone_base_world(*, source: DataSnapshot, target: DataSnapshot, batch_size: int) -> dict:
    """Copy accepted base-world rows only; operational event rows are not copied."""
    mappings: dict[type, dict[int, int]] = {}
    for model in _BASE_WORLD_ORDER:
        mappings[model] = _clone_model_rows(
            model=model,
            source=source,
            target=target,
            mappings=mappings,
            batch_size=batch_size,
        )
    return mappings


def clone_correlation_helpers(
    *, source: DataSnapshot, target: DataSnapshot, mappings, batch_size: int
) -> int:
    """Copy the bounded cross-region acceptance helpers outside the 91-event timeline."""
    source_events = list(
        CausalEvent.objects.filter(
            data_snapshot=source,
            event_code__in=_CORRELATION_HELPER_EVENT_CODES,
        ).order_by("event_code")
    )
    if not source_events:
        return 0
    mappings[CausalEvent] = _clone_model_rows(
        model=CausalEvent,
        source=source,
        target=target,
        mappings=mappings,
        batch_size=batch_size,
        source_rows=source_events,
    )
    _clone_model_rows(
        model=Alarm,
        source=source,
        target=target,
        mappings=mappings,
        batch_size=batch_size,
        source_rows=list(
            Alarm.objects.filter(
                data_snapshot=source,
                causal_event_id__in=mappings[CausalEvent],
            ).order_by("alarm_id")
        ),
    )
    return len(source_events)


def build_context(snapshot: DataSnapshot, batch_size: int) -> CausalTimelineContext:
    from apps.geography.models import City, District, Neighborhood

    cities = {item.name: item for item in City.objects.all()}
    districts = {item.name: item for item in District.objects.all()}
    neighborhoods: dict[str, list] = {}
    for item in Neighborhood.objects.select_related("district"):
        neighborhoods.setdefault(item.district.name, []).append(item)
    world = load_existing_seed_world(snapshot, cities, districts)
    (
        _sla_profiles,
        _service_packages,
        _campaigns,
        _rule_set,
        _rule_versions,
        devices,
        links,
        ports_by_role,
        _access_segments,
        failure_domains,
        _link_by_pair,
        _customers_by_district,
        _subscriptions,
        primary_connections,
        backup_connections,
        alarm_types,
    ) = world
    reference_datetime = snapshot.dataset_version.config["reference_datetime"]
    from data_generator.seeders.multicity_realism import parse_reference_datetime

    return CausalTimelineContext(
        snapshot=snapshot,
        devices=devices,
        links=links,
        ports_by_role=ports_by_role,
        failure_domains=failure_domains,
        primary_connections=primary_connections,
        backup_connections=backup_connections,
        alarm_types=alarm_types,
        reference_datetime=parse_reference_datetime(reference_datetime),
        batch_size=batch_size,
    )


def initialize_run(*, snapshot: DataSnapshot, source: DataSnapshot) -> dict:
    state = _state(snapshot)
    if state:
        return state
    state = {
        "run_id": hashlib.sha256(f"{snapshot.id}:{schedule_fingerprint()}".encode()).hexdigest()[
            :20
        ],
        "state": "running",
        "phase": "base_world",
        "source_snapshot_id": source.id,
        "schedule_fingerprint": schedule_fingerprint(),
        "total_events": len(scheduled_timeline()),
        "completed_events": 0,
        "started_at": timezone.now().isoformat(),
        "recent_events": [],
        "last_error": None,
    }
    _save_state(snapshot, state)
    return state


def resume_or_build(
    *, snapshot: DataSnapshot, source: DataSnapshot, batch_size: int, stdout
) -> dict:
    state = initialize_run(snapshot=snapshot, source=source)
    if (
        state["source_snapshot_id"] != source.id
        or state["schedule_fingerprint"] != schedule_fingerprint()
    ):
        raise ValueError("V3 checkpoint source snapshot or schedule fingerprint does not match.")
    if state["phase"] == "base_world":
        stdout.write("[phase] base-world clone start")
        with transaction.atomic():
            mappings = clone_base_world(source=source, target=snapshot, batch_size=batch_size)
            helper_count = clone_correlation_helpers(
                source=source,
                target=snapshot,
                mappings=mappings,
                batch_size=batch_size,
            )
            state.update(
                {
                    "phase": "causal_timeline",
                    "base_world_completed_at": timezone.now().isoformat(),
                    "correlation_helper_count": helper_count,
                }
            )
            _save_state(snapshot, state)
        stdout.write("[phase] base-world complete")

    context = build_context(snapshot, batch_size)
    entries = scheduled_timeline()
    completed = _completed_indices(snapshot)
    if completed and completed != set(range(1, max(completed) + 1)):
        raise ValueError("V3 checkpoint has a non-contiguous committed event sequence.")
    try:
        for index, entry in enumerate(entries, start=1):
            if index in completed:
                continue
            _run_event(snapshot=snapshot, context=context, entry=entry, index=index, stdout=stdout)
        _finalize_persisted_snapshot(snapshot=snapshot, stdout=stdout)
    except KeyboardInterrupt:
        state = _state(snapshot)
        state.update(
            {
                "state": "stopped",
                "phase": "stopped",
                "stopped_at": timezone.now().isoformat(),
                "last_error": "operator_interrupted",
            }
        )
        _save_state(snapshot, state)
        stdout.write("[phase] checkpointed-v3 stopped; resume with --checkpointed-v3 --resume")
    return _state(snapshot)


def status(snapshot: DataSnapshot) -> dict:
    state = _state(snapshot)
    if not state:
        return {"snapshot_id": snapshot.id, "state": "not_initialized"}
    elapsed = _elapsed_seconds(state)
    durations = [item["duration_seconds"] for item in state.get("recent_events", [])]
    average = sum(durations) / len(durations) if durations else None
    remaining = state["total_events"] - state["completed_events"]
    return {
        **state,
        "snapshot_id": snapshot.id,
        "elapsed_seconds": elapsed,
        "estimated_remaining_seconds": round(average * remaining, 1) if average else None,
        "resume_point": state["completed_events"] + 1,
    }


def _run_event(*, snapshot, context, entry, index, stdout) -> None:
    state = _state(snapshot)
    started_at = time.monotonic()
    _save_state(
        snapshot,
        {
            **state,
            "state": "running",
            "phase": "scope",
            "current": {
                "index": index,
                "scenario": entry.scenario_code,
                "city": entry.city_name,
                "month": entry.month,
            },
            "last_error": None,
        },
    )
    total = len(scheduled_timeline())
    stdout.write(
        f"[v3 {index}/{total}] START scenario={entry.scenario_code} "
        f"city={entry.city_name} month={entry.month} phase=scope"
    )
    try:
        with transaction.atomic():
            result = create_scheduled_scenario_instance(context=context, entry=entry, index=index)
            causal_event = result["causal_event"]
            cached = context.impact_evidence_cache[causal_event.id]
            stdout.write(
                f"[v3 {index}/{total}] scope={len(cached['potential_connections'])} "
                f"selected_evidence={len(cached['selected_connections'])}"
            )
            _save_event_phase(snapshot, "impact")
            _, summary = context.customer_impact_service.evaluate(
                causal_event=causal_event,
                snapshot=snapshot,
                potential_connections=cached["potential_connections"],
                session_events=cached["session_events"],
                batch_size=context.batch_size,
            )
            _save_event_phase(snapshot, "compensation")
            if result["outage"] is not None:
                VerifiedImpactCompensationService().evaluate_outage(
                    outage=result["outage"], snapshot=snapshot
                )
            _validate_event(causal_event=causal_event, snapshot=snapshot)
            duration = round(time.monotonic() - started_at, 3)
            event_state = {
                "index": index,
                "event_code": causal_event.event_code,
                "scenario": entry.scenario_code,
                "city": entry.city_name,
                "month": entry.month,
                "duration_seconds": duration,
                "scope_count": summary.potential_connection_count,
                "selected_evidence": len(cached["selected_connections"]),
                "impacted": summary.verified_impacted_count,
                "protected": summary.failover_protected_count,
                "unknown": summary.insufficient_evidence_count,
                "committed_at": timezone.now().isoformat(),
            }
            state = _state(snapshot)
            recent = [*state.get("recent_events", []), event_state][-10:]
            state.update(
                {
                    "phase": "causal_timeline",
                    "completed_events": index,
                    "last_committed": event_state,
                    "recent_events": recent,
                    "current": None,
                }
            )
            _save_state(snapshot, state)
        stdout.write(
            f"[v3 {index}/{total}] COMMITTED event_seconds={duration} "
            f"impacted={event_state['impacted']} protected={event_state['protected']} "
            f"unknown={event_state['unknown']} checkpoint={index}/{total} "
            f"elapsed={_elapsed_seconds(_state(snapshot))} "
            f"eta={status(snapshot)['estimated_remaining_seconds']}"
        )
    except Exception as exc:
        state = _state(snapshot)
        state.update(
            {
                "state": "failed",
                "phase": "failed",
                "last_error": f"{type(exc).__name__}: {exc}",
            }
        )
        _save_state(snapshot, state)
        raise


def _validate_event(*, causal_event, snapshot) -> None:
    causal_event.full_clean()
    invalid = (
        CustomerImpactAssessment.objects.filter(causal_event=causal_event)
        .exclude(data_snapshot=snapshot)
        .exists()
    )
    if invalid:
        raise ValueError(f"{causal_event.event_code} has a cross-snapshot impact assessment.")


def _finalize_persisted_snapshot(*, snapshot, stdout) -> None:
    stdout.write("[phase] validation start")
    state = _state(snapshot)
    state["phase"] = "validation"
    _save_state(snapshot, state)
    checks = _persisted_validation_checks(snapshot=snapshot)
    failed = [check for check in checks if not check["passed"]]
    if failed:
        names = ", ".join(check["name"] for check in failed)
        raise ValueError(f"Persisted V3 validation failed: {names}.")
    state.update(
        {
            "state": "completed",
            "phase": "completed",
            "completed_at": timezone.now().isoformat(),
            "validation_checks": checks,
        }
    )
    _save_state(snapshot, state)
    snapshot.refresh_from_db(fields=["validation_result"])
    snapshot.status = DatasetSnapshotStatus.VALIDATED
    snapshot.validation_status = ResultStatus.EXACT
    snapshot.row_counts = {
        **collect_seed_counts(snapshot),
        "customer_impact_assessments": CustomerImpactAssessment.objects.filter(
            data_snapshot=snapshot
        ).count(),
    }
    snapshot.source_finished_at = timezone.now()
    snapshot.save(
        update_fields=[
            "status",
            "validation_status",
            "row_counts",
            "source_finished_at",
            "updated_at",
        ]
    )
    stdout.write("[phase] validation complete")


def _persisted_validation_checks(*, snapshot: DataSnapshot) -> list[dict]:
    """Validate only persisted V3 rows; do not recompute topology or impact."""
    expected_entries = {index: entry for index, entry in enumerate(scheduled_timeline(), start=1)}
    scheduled_events = list(
        CausalEvent.objects.filter(
            data_snapshot=snapshot,
            metadata__v3_schedule_index__isnull=False,
        ).values("event_code", "metadata")
    )
    actual_indexes = {event["metadata"].get("v3_schedule_index") for event in scheduled_events}
    metadata_matches = True
    for event in scheduled_events:
        metadata = event["metadata"]
        index = metadata.get("v3_schedule_index")
        entry = expected_entries.get(index)
        if entry is None or (
            metadata.get("scenario_code") != entry.scenario_code
            or metadata.get("scheduled_city") != entry.city_name
            or metadata.get("scheduled_month") != entry.month
            or metadata.get("v3_schedule_fingerprint") != _entry_fingerprint(entry)
        ):
            metadata_matches = False
            break
    helper_count = CausalEvent.objects.filter(
        data_snapshot=snapshot,
        event_code__in=_CORRELATION_HELPER_EVENT_CODES,
    ).count()
    cross_snapshot_relation = any(
        (
            Alarm.objects.filter(data_snapshot=snapshot)
            .exclude(causal_event__isnull=True)
            .exclude(causal_event__data_snapshot=snapshot)
            .exists(),
            Incident.objects.filter(data_snapshot=snapshot)
            .exclude(causal_event__isnull=True)
            .exclude(causal_event__data_snapshot=snapshot)
            .exists(),
            IncidentAlarm.objects.filter(data_snapshot=snapshot)
            .exclude(incident__data_snapshot=snapshot)
            .exists(),
            Outage.objects.filter(data_snapshot=snapshot)
            .exclude(causal_event__isnull=True)
            .exclude(causal_event__data_snapshot=snapshot)
            .exists(),
            SessionEvent.objects.filter(data_snapshot=snapshot)
            .exclude(causal_event__data_snapshot=snapshot)
            .exists(),
            CustomerImpactAssessment.objects.filter(data_snapshot=snapshot)
            .exclude(causal_event__data_snapshot=snapshot)
            .exists(),
            CustomerImpactAssessment.objects.filter(data_snapshot=snapshot)
            .exclude(subscription_connection__data_snapshot=snapshot)
            .exists(),
        )
    )
    duplicate_assessments = (
        CustomerImpactAssessment.objects.filter(data_snapshot=snapshot)
        .values("causal_event_id", "subscription_connection_id")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .exists()
    )
    invalid_timestamp = any(
        (
            CausalEvent.objects.filter(
                data_snapshot=snapshot, ended_at__lt=F("started_at")
            ).exists(),
            Outage.objects.filter(data_snapshot=snapshot, ended_at__lt=F("started_at")).exists(),
        )
    )
    expected_indexes_set = set(expected_entries)
    return [
        _check("scheduled_event_count", len(expected_entries), len(scheduled_events)),
        _check("scheduled_event_indexes", expected_indexes_set, actual_indexes),
        _check("scheduled_event_metadata", True, metadata_matches),
        _check("correlation_helpers", len(_CORRELATION_HELPER_EVENT_CODES), helper_count),
        _check("cross_snapshot_relations", False, cross_snapshot_relation),
        _check("duplicate_impact_assessments", False, duplicate_assessments),
        _check("impossible_event_timestamps", False, invalid_timestamp),
    ]


def _check(name: str, expected, actual) -> dict:
    return {
        "name": name,
        "expected": _json_value(expected),
        "actual": _json_value(actual),
        "passed": expected == actual,
    }


def _json_value(value):
    if isinstance(value, set):
        return sorted(value)
    return value


def _entry_fingerprint(entry) -> str:
    return hashlib.sha256(
        f"{entry.city_name}:{entry.month}:{entry.day}:{entry.hour}:{entry.scenario_code}".encode()
    ).hexdigest()


def _completed_indices(snapshot: DataSnapshot) -> set[int]:
    return set(
        CausalEvent.objects.filter(
            data_snapshot=snapshot,
            metadata__v3_schedule_index__isnull=False,
        ).values_list("metadata__v3_schedule_index", flat=True)
    )


def _state(snapshot: DataSnapshot) -> dict:
    return dict((snapshot.validation_result or {}).get(RUN_KEY, {}))


def _save_state(snapshot: DataSnapshot, state: dict) -> None:
    snapshot.refresh_from_db(fields=["validation_result"])
    result = dict(snapshot.validation_result or {})
    result[RUN_KEY] = state
    snapshot.validation_result = result
    snapshot.save(update_fields=["validation_result", "updated_at"])


def _save_event_phase(snapshot: DataSnapshot, phase: str) -> None:
    state = _state(snapshot)
    state["phase"] = phase
    _save_state(snapshot, state)


def _elapsed_seconds(state: dict) -> float:
    started = datetime.fromisoformat(state["started_at"])
    finished = datetime.fromisoformat(state.get("completed_at", timezone.now().isoformat()))
    return round((finished - started).total_seconds(), 1)


def _clone_model_rows(
    *, model, source, target, mappings, batch_size: int, source_rows=None
) -> dict[int, int]:
    if source_rows is None:
        source_rows = list(model.objects.filter(data_snapshot=source).order_by("pk"))
    if not source_rows:
        return {}
    clone_rows = []
    for row in source_rows:
        values = {"data_snapshot": target}
        for field in model._meta.concrete_fields:
            if field.primary_key or field.name in {"data_snapshot", "created_at", "updated_at"}:
                continue
            value = getattr(row, field.attname)
            related_model = getattr(field, "related_model", None)
            if related_model in mappings and value is not None:
                value = mappings[related_model][value]
            values[field.attname] = value
        clone_rows.append(model(**values))
    model.objects.bulk_create(clone_rows, batch_size=batch_size)
    return {
        source_row.pk: clone_row.pk
        for source_row, clone_row in zip(source_rows, clone_rows, strict=True)
    }


_BASE_WORLD_ORDER: tuple[type, ...] = (
    SLAProfile,
    ServicePackage,
    ServicePackageAllowedSegment,
    ServicePackagePriceVersion,
    Campaign,
    CampaignAllowedSegment,
    CampaignAllowedServiceType,
    CampaignAllowedTechnology,
    RuleSet,
    Rule,
    RuleVersion,
    NetworkDevice,
    NetworkPort,
    AccessSegment,
    NetworkLink,
    FailureDomain,
    LineConnection,
    DeviceFailureDomainMembership,
    LineConnectionFailureDomainMembership,
    NetworkLinkFailureDomainMembership,
    Customer,
    Subscription,
    SubscriptionConnection,
    PaymentRecord,
    CampaignEnrollment,
    AlarmType,
    AlarmTypeAllowedSourceKind,
    AlarmTypeSupportedDeviceType,
)
