"""Checkpointed repair revision for a validated, immutable V3 candidate."""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from apps.compensation.models import CompensationEvaluation
from apps.compensation.services.verified_impact import VerifiedImpactCompensationService
from apps.core.choices import ResultStatus
from apps.customers.models import SubscriptionConnection, SubscriptionConnectionRole
from apps.datasets.models import DatasetSnapshotStatus, DataSnapshot, GroundTruthCase
from apps.operations.contracts import SessionEventType
from apps.operations.models import (
    Alarm,
    CausalEvent,
    CustomerImpactAssessment,
    Incident,
    IncidentAlarm,
    OperationalEvent,
    Outage,
    QualityMeasurement,
    SessionEvent,
)
from apps.operations.services.customer_impact_assessment import CustomerImpactAssessmentService
from data_generator.seeders.checkpointed_v3 import _BASE_WORLD_ORDER, _clone_model_rows
from data_generator.seeders.multicity_realism import collect_seed_counts

RUN_KEY = "v3_repair_r1"
HITLESS_CODES = ("CE-MCR-0041", "CE-MCR-0044", "CE-MCR-0084")

_OPERATIONAL_COPY_ORDER = (
    CausalEvent,
    Alarm,
    Incident,
    Outage,
    IncidentAlarm,
    OperationalEvent,
    QualityMeasurement,
    SessionEvent,
    CustomerImpactAssessment,
    GroundTruthCase,
)


def source_fingerprint(source: DataSnapshot) -> str:
    payload = {
        "snapshot": source.snapshot_key,
        "events": list(
            CausalEvent.objects.filter(data_snapshot=source)
            .order_by("event_code")
            .values_list("event_code", flat=True)
        ),
        "alarms": list(
            Alarm.objects.filter(data_snapshot=source)
            .order_by("alarm_id")
            .values_list("alarm_id", flat=True)
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def initialize(*, snapshot: DataSnapshot, source: DataSnapshot) -> dict:
    state = _state(snapshot)
    if state:
        return state
    state = {
        "run_id": hashlib.sha256(f"repair:{snapshot.id}:{source.id}".encode()).hexdigest()[:20],
        "state": "running",
        "phase": "clone",
        "source_snapshot_id": source.id,
        "source_fingerprint": source_fingerprint(source),
        "started_at": timezone.now().isoformat(),
        "hitless_completed": [],
        "compensation_completed": [],
        "last_error": None,
    }
    _save_state(snapshot, state)
    return state


def run(*, snapshot: DataSnapshot, source: DataSnapshot, batch_size: int, stdout) -> dict:
    state = initialize(snapshot=snapshot, source=source)
    if state["source_snapshot_id"] != source.id or state[
        "source_fingerprint"
    ] != source_fingerprint(source):
        raise ValueError("Repair source snapshot or fingerprint does not match the checkpoint.")

    if state["phase"] == "clone":
        stdout.write("[repair] clone start")
        with transaction.atomic():
            mappings = {}
            for model in _BASE_WORLD_ORDER:
                mappings[model] = _clone_model_rows(
                    model=model,
                    source=source,
                    target=snapshot,
                    mappings=mappings,
                    batch_size=batch_size,
                )
            for model in _OPERATIONAL_COPY_ORDER:
                mappings[model] = _clone_model_rows(
                    model=model,
                    source=source,
                    target=snapshot,
                    mappings=mappings,
                    batch_size=batch_size,
                )
            state = _state(snapshot)
            state.update({"phase": "hitless", "clone_completed_at": timezone.now().isoformat()})
            _save_state(snapshot, state)
        stdout.write("[repair] clone complete")

    for position, event_code in enumerate(HITLESS_CODES, start=1):
        state = _state(snapshot)
        if event_code in state.get("hitless_completed", []):
            continue
        started = time.monotonic()
        stdout.write(f"[repair] hitless {position}/{len(HITLESS_CODES)} START event={event_code}")
        with transaction.atomic():
            summary = repair_hitless_event(snapshot=snapshot, event_code=event_code)
            state = _state(snapshot)
            completed = [*state.get("hitless_completed", []), event_code]
            state.update(
                {
                    "phase": "hitless",
                    "hitless_completed": completed,
                    "last_hitless": {**summary, "seconds": round(time.monotonic() - started, 3)},
                }
            )
            _save_state(snapshot, state)
        stdout.write(
            f"[repair] hitless {position}/{len(HITLESS_CODES)} COMMITTED "
            f"protected={summary['protected']} impacted={summary['impacted']} "
            f"unknown={summary['unknown']} elapsed={_elapsed(_state(snapshot))}"
        )

    outages = list(Outage.objects.filter(data_snapshot=snapshot).order_by("outage_code"))
    for position, outage in enumerate(outages, start=1):
        state = _state(snapshot)
        if outage.outage_code in state.get("compensation_completed", []):
            continue
        started = time.monotonic()
        stdout.write(
            f"[repair] compensation outage {position}/{len(outages)} START {outage.outage_code}"
        )
        with transaction.atomic():
            result = VerifiedImpactCompensationService().materialize_outage(
                outage=outage,
                snapshot=snapshot,
            )
            state = _state(snapshot)
            completed = [*state.get("compensation_completed", []), outage.outage_code]
            state.update(
                {
                    "phase": "compensation",
                    "compensation_completed": completed,
                    "last_compensation": {
                        "outage": outage.outage_code,
                        "evaluations_created": result["created"],
                        "evaluations_reused": result["reused"],
                        "seconds": round(time.monotonic() - started, 3),
                    },
                }
            )
            _save_state(snapshot, state)
        repair_status = status(snapshot)
        stdout.write(
            f"[repair] compensation outage {position}/{len(outages)} COMMITTED "
            f"evaluations_created={result['created']} evaluations_reused={result['reused']} "
            f"elapsed={_elapsed(_state(snapshot))} "
            f"eta={repair_status['estimated_remaining_seconds']}"
        )

    _finalize(snapshot=snapshot, source=source, stdout=stdout)
    return _state(snapshot)


def repair_hitless_event(*, snapshot: DataSnapshot, event_code: str) -> dict:
    event = CausalEvent.objects.get(data_snapshot=snapshot, event_code=event_code)
    incident = Incident.objects.get(data_snapshot=snapshot, causal_event=event)
    if incident.failover_result != "hitless":
        raise ValueError(f"{event_code} is not a hitless failover event.")
    primary, backups = _protected_pair(snapshot=snapshot, event=event)
    _repoint_hitless_topology(event=event, incident=incident, primary=primary)
    SessionEvent.objects.filter(data_snapshot=snapshot, causal_event=event).delete()
    CustomerImpactAssessment.objects.filter(data_snapshot=snapshot, causal_event=event).delete()
    evidence = _protected_session_evidence(
        snapshot=snapshot,
        event=event,
        primary=primary,
        backups=backups,
    )
    SessionEvent.objects.bulk_create(evidence, batch_size=2000)
    _, summary = CustomerImpactAssessmentService().evaluate(
        causal_event=event,
        snapshot=snapshot,
        potential_connections=[primary],
        session_events=evidence,
    )
    if (
        summary.verified_impacted_count
        or not summary.failover_protected_count
        or summary.insufficient_evidence_count
    ):
        raise ValueError(f"{event_code} did not materialize verified hitless protection.")
    return {
        "event": event_code,
        "primary_connection": primary.id,
        "backup_count": len(backups),
        "impacted": summary.verified_impacted_count,
        "protected": summary.failover_protected_count,
        "unknown": summary.insufficient_evidence_count,
    }


def _protected_pair(*, snapshot: DataSnapshot, event: CausalEvent):
    city = event.metadata.get("scheduled_city")
    candidates = list(
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            connection_role=SubscriptionConnectionRole.PRIMARY,
            is_active=True,
            valid_from__lte=event.started_at,
            line_connection__is_active=True,
            line_connection__status="active",
            line_connection__valid_from__lte=event.started_at,
            subscription__is_active=True,
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=event.ended_at))
        .filter(
            Q(line_connection__valid_to__isnull=True)
            | Q(line_connection__valid_to__gt=event.ended_at)
        )
        .filter(
            Q(subscription__valid_to__isnull=True) | Q(subscription__valid_to__gt=event.ended_at)
        )
        .filter(line_connection__port__device__city__name=city)
        .select_related("subscription", "line_connection__port__device")
        .order_by("subscription__subscription_number", "pk")
    )
    backup_rows = list(
        SubscriptionConnection.objects.filter(
            data_snapshot=snapshot,
            connection_role=SubscriptionConnectionRole.BACKUP,
            is_active=True,
            valid_from__lte=event.started_at,
            subscription_id__in=[item.subscription_id for item in candidates],
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=event.ended_at))
        .select_related("subscription", "line_connection__port__device")
        .order_by("subscription_id", "pk")
    )
    backups_by_subscription = defaultdict(list)
    for backup in backup_rows:
        backups_by_subscription[backup.subscription_id].append(backup)
    eligible = [item for item in candidates if backups_by_subscription[item.subscription_id]]
    if not eligible:
        raise ValueError(f"{event.event_code} has no canonical active primary/backup pair.")
    index = int(event.metadata.get("v3_schedule_index", 0))
    primary = eligible[index % len(eligible)]
    return primary, backups_by_subscription[primary.subscription_id]


def _repoint_hitless_topology(*, event, incident, primary) -> None:
    for field_name in (
        "root_device",
        "root_network_link",
        "root_network_port",
        "root_line_connection",
        "root_access_segment",
        "root_failure_domain",
    ):
        setattr(event, field_name, None)
    event.root_subscription_connection = primary
    event.metadata = {
        **event.metadata,
        "topology_scope": {
            "line": primary.line_connection.line_code,
            "device": primary.line_connection.port.device.code,
        },
        "repair": {"hitless_primary_backup_verified": True},
    }
    event.save()
    incident.primary_device = primary.line_connection.port.device
    incident.save(update_fields=["primary_device", "updated_at"])
    for alarm in Alarm.objects.filter(data_snapshot=event.data_snapshot, causal_event=event):
        for field_name in (
            "device",
            "network_link",
            "network_port",
            "line_connection",
            "failure_domain",
        ):
            setattr(alarm, field_name, None)
        alarm.subscription_connection = primary
        alarm.save()


def _protected_session_evidence(*, snapshot, event, primary, backups):
    index = int(event.metadata.get("v3_schedule_index", 0))
    prefix = f"SES-MCR-{index:04d}-HR"
    recovery = event.ended_at - timedelta(minutes=20) if event.ended_at else event.started_at
    records = [
        _session(
            snapshot,
            event,
            primary,
            f"{prefix}-P-PRE",
            SessionEventType.CONTINUE,
            event.started_at - timedelta(minutes=5),
            {},
        ),
        _session(
            snapshot,
            event,
            primary,
            f"{prefix}-P-STOP",
            SessionEventType.STOP,
            event.started_at + timedelta(minutes=12),
            {},
        ),
        _session(snapshot, event, primary, f"{prefix}-P-REC", SessionEventType.START, recovery, {}),
    ]
    for backup_index, backup in enumerate(backups, start=1):
        records.extend(
            [
                _session(
                    snapshot,
                    event,
                    backup,
                    f"{prefix}-B{backup_index:02d}-PRE",
                    SessionEventType.CONTINUE,
                    event.started_at - timedelta(minutes=5),
                    {"failover_protected": True},
                ),
                _session(
                    snapshot,
                    event,
                    backup,
                    f"{prefix}-B{backup_index:02d}-POST",
                    SessionEventType.CONTINUE,
                    event.started_at + timedelta(minutes=12),
                    {"failover_protected": True},
                ),
            ]
        )
    return records


def _session(snapshot, event, connection, external_id, event_type, occurred_at, metadata):
    return SessionEvent(
        data_snapshot=snapshot,
        causal_event=event,
        external_event_id=external_id,
        event_type=event_type,
        occurred_at=occurred_at,
        received_at=occurred_at + timedelta(seconds=10),
        source_system="synthetic_session_adapter",
        subscription=connection.subscription,
        subscription_connection=connection,
        external_service_reference_hash=hashlib.sha256(
            connection.subscription.subscription_number.encode()
        ).hexdigest(),
        metadata=metadata,
    )


def status(snapshot: DataSnapshot) -> dict:
    state = _state(snapshot)
    if not state:
        return {"snapshot_id": snapshot.id, "state": "not_initialized"}
    completed = len(state.get("compensation_completed", []))
    total = Outage.objects.filter(data_snapshot=snapshot).count()
    elapsed = _elapsed(state)
    last = state.get("last_compensation", {})
    average = last.get("seconds")
    return {
        **state,
        "snapshot_id": snapshot.id,
        "elapsed_seconds": elapsed,
        "compensation_progress": f"{completed}/{total}",
        "estimated_remaining_seconds": round((total - completed) * average, 1) if average else None,
    }


def _finalize(*, snapshot: DataSnapshot, source: DataSnapshot, stdout) -> None:
    stdout.write("[repair] validation start")
    checks = _validation_checks(snapshot=snapshot, source=source)
    failed = [item for item in checks if not item["passed"]]
    if failed:
        raise ValueError(
            "V3 repair validation failed: " + ", ".join(item["name"] for item in failed)
        )
    state = _state(snapshot)
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
        "compensation_evaluations": CompensationEvaluation.objects.filter(
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
    stdout.write("[repair] validation complete")


def _validation_checks(*, snapshot: DataSnapshot, source: DataSnapshot):
    def check(name, expected, actual):
        return {"name": name, "expected": expected, "actual": actual, "passed": expected == actual}

    source_counts = {
        "events": CausalEvent.objects.filter(data_snapshot=source).count(),
        "alarms": Alarm.objects.filter(data_snapshot=source).count(),
        "sessions": SessionEvent.objects.filter(data_snapshot=source).count(),
        "assessments": CustomerImpactAssessment.objects.filter(data_snapshot=source).count(),
    }
    current_counts = {
        "events": CausalEvent.objects.filter(data_snapshot=snapshot).count(),
        "alarms": Alarm.objects.filter(data_snapshot=snapshot).count(),
        "sessions": SessionEvent.objects.filter(data_snapshot=snapshot).count(),
        "assessments": CustomerImpactAssessment.objects.filter(data_snapshot=snapshot).count(),
    }
    hitless_ok = True
    for code in HITLESS_CODES:
        assessments = CustomerImpactAssessment.objects.filter(
            data_snapshot=snapshot, causal_event__event_code=code
        )
        statuses = dict(assessments.values_list("status").annotate(n=Count("id")))
        reasons = [
            reason for item in assessments.values_list("reasons", flat=True) for reason in item
        ]
        hitless_ok &= (
            statuses.get("verified_impact", 0) == 0
            and statuses.get("verified_no_impact", 0) > 0
            and statuses.get("insufficient_evidence", 0) == 0
            and "failover_protected" in reasons
        )
    failed = CustomerImpactAssessment.objects.filter(
        data_snapshot=snapshot, causal_event__event_code="CE-MCR-0052"
    )
    failed_statuses = dict(failed.values_list("status").annotate(n=Count("id")))
    cross_snapshot = any(
        (
            Alarm.objects.filter(data_snapshot=snapshot)
            .exclude(causal_event__data_snapshot=snapshot)
            .exists(),
            Incident.objects.filter(data_snapshot=snapshot)
            .exclude(causal_event__data_snapshot=snapshot)
            .exists(),
            Outage.objects.filter(data_snapshot=snapshot)
            .exclude(causal_event__data_snapshot=snapshot)
            .exists(),
            SessionEvent.objects.filter(data_snapshot=snapshot)
            .exclude(causal_event__data_snapshot=snapshot)
            .exists(),
            CustomerImpactAssessment.objects.filter(data_snapshot=snapshot)
            .exclude(causal_event__data_snapshot=snapshot)
            .exists(),
        )
    )
    duplicate_evaluations = (
        CompensationEvaluation.objects.filter(data_snapshot=snapshot)
        .values("outage_id", "subscription_id", "rule_version_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .exists()
    )
    unmatched_evidence = (
        CompensationEvaluation.objects.filter(data_snapshot=snapshot)
        .exclude(decision_evidence__isnull=False)
        .exists()
    )
    state = _state(snapshot)
    repair_session_rows = SessionEvent.objects.filter(
        data_snapshot=snapshot,
        external_event_id__contains="-HR-",
    ).count()
    return [
        check("source_fingerprint", state["source_fingerprint"], source_fingerprint(source)),
        check("operational_event_count", source_counts["events"], current_counts["events"]),
        check("alarm_count", source_counts["alarms"], current_counts["alarms"]),
        check("hitless_repair_session_rows", True, repair_session_rows >= 15),
        check("assessment_count", source_counts["assessments"], current_counts["assessments"]),
        check("hitless_verified_protection", True, hitless_ok),
        check("failed_failover_ce_mcr_0052", 1009, failed_statuses.get("verified_impact", 0)),
        check(
            "compensation_nonempty",
            True,
            CompensationEvaluation.objects.filter(data_snapshot=snapshot).exists(),
        ),
        check("compensation_duplicates", False, duplicate_evaluations),
        check("evaluation_evidence_complete", False, unmatched_evidence),
        check("cross_snapshot_relations", False, cross_snapshot),
        check(
            "impossible_timestamps",
            False,
            CausalEvent.objects.filter(
                data_snapshot=snapshot, ended_at__lt=F("started_at")
            ).exists()
            or Outage.objects.filter(data_snapshot=snapshot, ended_at__lt=F("started_at")).exists(),
        ),
    ]


def _state(snapshot):
    return dict((snapshot.validation_result or {}).get(RUN_KEY, {}))


def _save_state(snapshot, state):
    snapshot.refresh_from_db(fields=["validation_result"])
    payload = dict(snapshot.validation_result or {})
    payload[RUN_KEY] = state
    snapshot.validation_result = payload
    snapshot.save(update_fields=["validation_result", "updated_at"])


def _elapsed(state):
    started = datetime.fromisoformat(state["started_at"])
    ended = datetime.fromisoformat(state.get("completed_at", timezone.now().isoformat()))
    return round((ended - started).total_seconds(), 1)
