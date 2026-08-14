from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.models import QueryRun, QueryRunStatus
from apps.orchestration.services import (
    QueryRunIdempotencyConflictError,
    QueryRunService,
    QueryRunTransitionError,
    sanitize_json,
    sanitize_text,
)


@pytest.fixture
def service():
    return QueryRunService()


def test_sanitize_json_preserves_aggregate_subscription_counts_and_removes_ip_fields():
    sanitized = sanitize_json(
        {
            "affected_subscription_count": 572,
            "affected_customer_count": 495,
            "source_ip": "192.0.2.10",
            "raw_payload": {"token": "secret"},
        }
    )

    assert sanitized == {
        "affected_subscription_count": 572,
        "affected_customer_count": 495,
    }


def test_sanitize_text_preserves_decimal_money_but_redacts_phone_numbers():
    text = sanitize_text("Toplam 204274.61 TRY; telefon +90 (555) 123 45 67.")

    assert "204274.61 TRY" in text
    assert "+90" not in text
    assert "[REDACTED_PHONE]" in text


@pytest.fixture
def snapshot():
    return create_snapshot("query-run-seed-001")


@pytest.mark.django_db
def test_query_run_requires_explicit_snapshot_and_json_defaults_are_not_shared(snapshot, service):
    first, created = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="query-run-defaults-1",
        original_query="Kesinti durumunu incele.",
    )
    second, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="query-run-defaults-2",
        original_query="Başka bir kesintiyi incele.",
    )

    assert created is True
    assert first.data_snapshot_id == snapshot.id
    assert first.structured_query == {}
    assert first.planned_tools == []
    assert first.executed_tools == []
    first.structured_query["intent"] = "outage_analysis"
    assert second.structured_query == {}

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            QueryRun.objects.create(
                idempotency_key="missing-snapshot",
                original_query="Snapshot olmadan kaydedilemez.",
            )


@pytest.mark.django_db
def test_idempotent_create_is_snapshot_scoped_and_database_safe(snapshot, service):
    run, created = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="query-run-idempotency",
        original_query="Alarm kök nedenini göster.",
        request_id="query-run-request-1",
    )
    duplicate, duplicate_created = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="query-run-idempotency",
        original_query="Bu metin saklanmamalı.",
    )
    other_snapshot = create_snapshot("query-run-seed-002")

    assert created is True
    assert duplicate_created is False
    assert duplicate.pk == run.pk
    assert QueryRun.objects.filter(idempotency_key="query-run-idempotency").count() == 1
    with pytest.raises(QueryRunIdempotencyConflictError):
        service.create_or_get(
            data_snapshot=other_snapshot,
            idempotency_key="query-run-idempotency",
            original_query="Farklı snapshot.",
        )


@pytest.mark.django_db
def test_status_lifecycle_completion_and_terminal_immutability(snapshot, service):
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="query-run-lifecycle",
        original_query="Etkilenen abonelikleri incele.",
    )
    planned = service.save_plan(
        run,
        structured_query={"intent": "impact_analysis"},
        planned_tools=[{"tool_name": "network.get_outage", "status": "planned"}],
        model_version="future-model-v1",
        prompt_version="future-prompt-v1",
    )
    executing = service.transition(planned, target_status=QueryRunStatus.EXECUTING)
    service.save_execution_summary(
        executing,
        executed_tools=[
            {
                "tool_name": "network.get_outage",
                "status": "completed",
                "result_summary": "One outage matched.",
                "raw_response": {"token": "must-not-persist"},
            }
        ],
    )
    completed = service.complete(executing, final_result={"summary": "Safe result."})

    assert completed.status == QueryRunStatus.COMPLETED
    assert completed.started_at is not None
    assert completed.completed_at is not None
    assert completed.final_result == {"summary": "Safe result."}
    assert "raw_response" not in completed.executed_tools[0]
    with pytest.raises(QueryRunTransitionError) as exc_info:
        service.transition(completed, target_status=QueryRunStatus.EXECUTING)
    assert exc_info.value.code == "invalid_query_run_transition"
    completed.error_summary = "A later mutation"
    with pytest.raises(ValidationError, match="immutable"):
        completed.full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize("terminal_method", ["complete", "fail"])
def test_stale_terminal_finalization_preserves_execution_audit(snapshot, service, terminal_method):
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key=f"query-run-stale-{terminal_method}",
        original_query="Stale audit regression.",
    )
    planned = service.save_plan(
        run,
        structured_query={"intent": "outage_analysis"},
        planned_tools=[{"tool_name": "network.get_outage", "status": "planned"}],
    )
    executing = service.transition(planned, target_status=QueryRunStatus.EXECUTING)
    stale = QueryRun.objects.get(pk=executing.pk)
    service.append_execution_record(
        executing,
        record={
            "call_id": f"audit-{terminal_method}",
            "server": "network",
            "tool_name": "get_outage_details",
            "status": "completed" if terminal_method == "complete" else "failed",
            "error_code": "tool_failed" if terminal_method == "fail" else "",
        },
    )

    if terminal_method == "complete":
        finalized = service.complete(stale, final_result={"summary": "safe"})
    else:
        finalized = service.fail(stale, error_code="tool_failed", error_summary="tool failed")

    assert finalized.status in {QueryRunStatus.COMPLETED, QueryRunStatus.FAILED}
    assert [record["call_id"] for record in finalized.executed_tools] == [
        f"audit-{terminal_method}"
    ]


@pytest.mark.django_db
def test_failed_lifecycle_and_database_terminal_constraints(snapshot, service):
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="query-run-failed",
        original_query="Yetkisiz sorgu.",
    )
    failed = service.fail(
        run,
        error_code="provider_unavailable",
        error_summary="Bearer secret-value from 192.0.2.10 failed.",
    )

    assert failed.status == QueryRunStatus.FAILED
    assert failed.completed_at is not None
    assert "secret-value" not in failed.error_summary
    assert "192.0.2.10" not in failed.error_summary
    assert "[REDACTED]" in failed.error_summary

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            QueryRun.objects.create(
                data_snapshot=snapshot,
                idempotency_key="invalid-complete",
                original_query="invalid",
                status=QueryRunStatus.COMPLETED,
                completed_at=timezone.now(),
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            QueryRun.objects.create(
                data_snapshot=snapshot,
                idempotency_key="invalid-fail",
                original_query="invalid",
                status=QueryRunStatus.FAILED,
                completed_at=timezone.now(),
            )


@pytest.mark.django_db
def test_retry_creates_a_new_pending_run_and_preserves_terminal_source(snapshot, service):
    source, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="query-run-retry-source",
        original_query="Müşteri 12345 için token=private kontrolü.",
    )
    failed = service.fail(
        source,
        error_code="temporary_failure",
        error_summary="Temporary provider problem.",
    )
    retry, created = service.create_retry(
        failed,
        idempotency_key="query-run-retry-target",
        request_id="retry-request-1",
    )

    assert created is True
    assert retry.pk != failed.pk
    assert retry.retry_of_id == failed.id
    assert retry.status == QueryRunStatus.PENDING
    assert retry.completed_at is None
    assert retry.original_query == failed.original_query
    repeated, repeated_created = service.create_retry(
        failed,
        idempotency_key="query-run-retry-target",
    )
    assert repeated.pk == retry.pk
    assert repeated_created is False


@pytest.mark.django_db
def test_privacy_sanitization_and_snapshot_protect(snapshot, service):
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="query-run-privacy",
        original_query=(
            "Müşteri 12345 için IP 198.51.100.9, MAC AA:BB:CC:DD:EE:FF ve token=private."
        ),
    )
    planned = service.save_plan(
        run,
        structured_query={
            "intent": "outage",
            "subscriber_id": "sensitive",
            "nested": {"authorization": "Bearer secret", "safe": "allowed"},
        },
        planned_tools=[
            {
                "tool_name": "network.get_outage",
                "argument_summary": "IP 203.0.113.7",
                "authorization": "Bearer secret",
                "raw_payload": {"session_id": "sensitive"},
            }
        ],
    )

    assert "198.51.100.9" not in planned.original_query
    assert "AA:BB:CC:DD:EE:FF" not in planned.original_query
    assert "private" not in planned.original_query
    assert "12345" not in planned.original_query
    assert "subscriber_id" not in planned.structured_query
    assert "authorization" not in planned.structured_query["nested"]
    assert "203.0.113.7" not in planned.planned_tools[0]["argument_summary"]
    assert "authorization" not in planned.planned_tools[0]
    assert "raw_payload" not in planned.planned_tools[0]

    with pytest.raises(ProtectedError):
        snapshot.delete()


@pytest.mark.django_db
def test_response_audit_persists_safe_terminal_selection_diagnostics(snapshot, service):
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key="query-run-response-audit",
        original_query="Audit.",
    )
    service.transition(run, target_status=QueryRunStatus.PLANNED)
    service.transition(run, target_status=QueryRunStatus.EXECUTING)
    completed = service.complete(run, final_result={"validation_status": "valid"})

    service.save_response_audit(
        completed,
        audit={
            "status": "rejected",
            "failure_code": "unknown_or_duplicate_statement_id",
            "allowed_statement_ids": ["S1"],
            "returned_statement_ids": ["S999"],
        },
    )

    persisted = QueryRun.objects.get(pk=completed.pk)
    assert persisted.response_audit == {
        "status": "rejected",
        "failure_code": "unknown_or_duplicate_statement_id",
        "allowed_statement_ids": ["S1"],
        "returned_statement_ids": ["S999"],
    }


@pytest.mark.django_db
def test_model_validation_rejects_nonterminal_completed_at_and_wrong_json_types(snapshot):
    run = QueryRun(
        data_snapshot=snapshot,
        idempotency_key="query-run-validation",
        original_query="Validation.",
        completed_at=timezone.now() - timedelta(seconds=1),
        structured_query=[],
        planned_tools={},
        executed_tools={},
    )
    with pytest.raises(ValidationError) as exc_info:
        run.full_clean()
    assert {"completed_at", "structured_query", "planned_tools", "executed_tools"} <= set(
        exc_info.value.message_dict
    )
