#!/usr/bin/env python
"""Emit a read-only, PII-free snapshot of the ProcessTwin Django system."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path[:0] = [str(BACKEND_ROOT), str(REPO_ROOT)]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.migrations.executor import MigrationExecutor  # noqa: E402
from django.db.models import Count  # noqa: E402
from django.urls import URLPattern, URLResolver, get_resolver  # noqa: E402

PROJECT_APPS = {
    "accounts",
    "compensation",
    "core",
    "customers",
    "datasets",
    "geography",
    "network",
    "operations",
    "rag",
    "rules",
}


def field_record(field) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": field.name,
        "type": field.get_internal_type(),
        "null": field.null,
        "blank": field.blank,
        "primary_key": field.primary_key,
    }
    if field.is_relation:
        related_model = getattr(field, "related_model", None)
        record["relation"] = (
            related_model._meta.label if related_model is not None else "unresolved"
        )
        record["many_to_many"] = field.many_to_many
        record["one_to_many"] = field.one_to_many
        record["many_to_one"] = field.many_to_one
        record["one_to_one"] = field.one_to_one
        remote_field = getattr(field, "remote_field", None)
        on_delete = getattr(remote_field, "on_delete", None)
        if on_delete:
            record["on_delete"] = getattr(on_delete, "__name__", str(on_delete))
    return record


def constraint_record(constraint) -> dict[str, Any]:
    return {
        "name": constraint.name,
        "type": constraint.__class__.__name__,
        "fields": list(getattr(constraint, "fields", ())),
        "condition": str(getattr(constraint, "condition", "")),
    }


def model_inventory() -> list[dict[str, Any]]:
    inventory = []
    for model in apps.get_models():
        if model._meta.app_label not in PROJECT_APPS:
            continue
        inventory.append(
            {
                "app": model._meta.app_label,
                "model": model.__name__,
                "table": model._meta.db_table,
                "source": str(Path(sys.modules[model.__module__].__file__).relative_to(REPO_ROOT)),
                "row_count": model.objects.count(),
                "fields": [
                    field_record(field)
                    for field in model._meta.get_fields()
                    if not field.auto_created or field.concrete
                ],
                "constraints": [
                    constraint_record(constraint) for constraint in model._meta.constraints
                ],
            }
        )
    return sorted(inventory, key=lambda item: (item["app"], item["model"]))


def url_inventory() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []

    def walk(patterns, prefix: str = "") -> None:
        for entry in patterns:
            route = f"{prefix}{entry.pattern}"
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, route)
            elif isinstance(entry, URLPattern):
                callback = entry.callback
                records.append(
                    {
                        "route": route,
                        "name": entry.name or "",
                        "view": (
                            f"{callback.__module__}."
                            f"{getattr(callback, '__name__', callback.__class__.__name__)}"
                        ),
                    }
                )

    walk(get_resolver().url_patterns)
    return records


def grouped_counts(model_label: str, field: str) -> dict[str, int]:
    model = apps.get_model(model_label)
    return dict(
        sorted(
            Counter(model.objects.values_list(field, flat=True)).items(),
            key=lambda item: str(item[0]),
        )
    )


def database_summary() -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version()")
        postgres_version = cursor.fetchone()[0]
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        vector_row = cursor.fetchone()

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    pending = executor.migration_plan(leaf_nodes)
    return {
        "vendor": connection.vendor,
        "postgres_version": postgres_version,
        "pgvector_version": vector_row[0] if vector_row else None,
        "applied_migrations": len(executor.loader.applied_migrations),
        "pending_migrations": [
            f"{migration.app_label}.{migration.name}" for migration, _ in pending
        ],
    }


def distributions() -> dict[str, Any]:
    alarm = apps.get_model("operations.Alarm")
    return {
        "customer_segments": grouped_counts("customers.Customer", "segment"),
        "customer_statuses": grouped_counts("customers.Customer", "status"),
        "subscription_statuses": grouped_counts("customers.Subscription", "status"),
        "subscription_connection_roles": grouped_counts(
            "customers.SubscriptionConnection", "connection_role"
        ),
        "service_package_technologies": grouped_counts(
            "customers.ServicePackage", "technology"
        ),
        "network_device_types": grouped_counts("network.NetworkDevice", "device_type"),
        "line_technologies": grouped_counts("network.LineConnection", "technology"),
        "alarm_severities": grouped_counts("operations.Alarm", "severity"),
        "alarm_statuses": grouped_counts("operations.Alarm", "status"),
        "alarms_by_type": dict(
            alarm.objects.values_list("alarm_type__code")
            .order_by("alarm_type__code")
            .annotate(count=Count("id"))
        ),
        "incident_types": grouped_counts("operations.Incident", "incident_type"),
        "outage_types": grouped_counts("operations.Outage", "outage_type"),
        "rule_families": grouped_counts("rules.Rule", "family"),
        "embedding_providers": grouped_counts("rag.DocumentChunkEmbedding", "provider"),
        "embedding_models": grouped_counts("rag.DocumentChunkEmbedding", "model"),
    }


def snapshot_summaries() -> list[dict[str, Any]]:
    snapshot_model = apps.get_model("datasets.DataSnapshot")
    snapshot_models = []
    for model in apps.get_models():
        if model._meta.app_label not in PROJECT_APPS:
            continue
        if any(field.name == "data_snapshot" for field in model._meta.fields):
            snapshot_models.append(model)

    summaries = []
    for snapshot in snapshot_model.objects.select_related("dataset_version").order_by(
        "dataset_version__slug",
        "id",
    ):
        counts = {
            model._meta.label: model.objects.filter(data_snapshot=snapshot).count()
            for model in snapshot_models
        }
        summaries.append(
            {
                "dataset_slug": snapshot.dataset_version.slug,
                "dataset_kind": snapshot.dataset_version.kind,
                "generator_version": snapshot.dataset_version.generator_version,
                "seed": snapshot.dataset_version.seed,
                "snapshot_key": snapshot.snapshot_key,
                "status": snapshot.status,
                "is_active": snapshot.is_active,
                "stored_row_counts": snapshot.row_counts,
                "actual_counts": dict(sorted(counts.items())),
            }
        )
    return summaries


def main() -> None:
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "repository": str(REPO_ROOT),
        "database": database_summary(),
        "models": model_inventory(),
        "distributions": distributions(),
        "snapshots": snapshot_summaries(),
        "urls": url_inventory(),
    }
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
