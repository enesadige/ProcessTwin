from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.apps import apps
from django.db import connection, models
from django.db.models import Count, Model, QuerySet

from apps.compensation.models import CompensationEvaluation, DecisionEvidence
from apps.customers.models import (
    Campaign,
    CampaignEnrollment,
    Customer,
    PaymentRecord,
    ServicePackage,
    ServicePackagePriceVersion,
    SLAProfile,
    Subscription,
    SubscriptionConnection,
    SubscriptionConnectionRole,
)
from apps.datasets.models import DatasetVersion, DataSnapshot, GroundTruthCase
from apps.geography.models import City, District, Neighborhood
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
from apps.network.services.path_diversity import PathDiversityService
from apps.operations.models import (
    Alarm,
    AlarmType,
    AlarmTypeAllowedSourceKind,
    AlarmTypeSupportedDeviceType,
    Incident,
    IncidentAlarm,
    MaintenanceWindow,
    OperationalEvent,
    Outage,
    QualityMeasurement,
)
from apps.rules.models import Rule, RuleSet, RuleVersion
from data_generator.configs import multi_city_realism_v1 as realism_config
from data_generator.configs import multicity_ground_truth_v1 as ground_truth_config
from data_generator.configs import realistic_alarm_catalog_v1 as alarm_config
from data_generator.validators.maltepe_mvp import validate_maltepe_mvp_snapshot
from data_generator.validators.multicity_ground_truth import validate_multicity_ground_truth
from data_generator.validators.multicity_realism import validate_multicity_realism_snapshot

SYNTHETIC_NOTE = "Tamamen sentetik inceleme verisi; gerçek operatör veya müşteri verisi değildir."
GENERATED_AT = "2026-08-01T00:00:00+03:00"


@dataclass(frozen=True)
class ExportOptions:
    snapshot_key: str | None
    dataset_slug: str | None
    output_dir: Path
    sample_size: int = 50
    include_full_data: bool = False
    include_maltepe_regression: bool = False
    make_zip: bool = False
    overwrite: bool = False
    progress: Callable[[str], None] | None = None


@dataclass
class CsvInfo:
    relative_path: str
    category: str
    source_model: str
    source_snapshot: str
    row_count: int
    column_count: int
    notes: str = ""
    file_size_bytes: int = 0
    sha256: str = ""


@dataclass
class ExportResult:
    output_dir: Path
    zip_path: Path | None
    zip_size_bytes: int
    snapshot_key: str
    dataset_slug: str
    multicity_table_count: int
    maltepe_table_count: int
    csv_count: int
    total_csv_rows: int
    xlsx_created: bool
    inconsistencies: list[str] = dataclass_field(default_factory=list)
    secret_scan_findings: list[str] = dataclass_field(default_factory=list)
    validation_summary: dict[str, Any] = dataclass_field(default_factory=dict)
    db_counts_unchanged: bool = False


@dataclass(frozen=True)
class ModelSpec:
    model: type[Model]
    category: str
    purpose: str
    data_type_category: str
    natural_key: str
    used_by_services: str = ""
    snapshot_scoped: bool = True


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        DatasetVersion,
        "dataset",
        "Veri seti versiyon kimliği.",
        "master_data",
        "slug",
        snapshot_scoped=False,
    ),
    ModelSpec(
        DataSnapshot,
        "dataset",
        "Veri setinin doğrulanmış anlık görünümü.",
        "master_data",
        "snapshot_key",
        snapshot_scoped=False,
    ),
    ModelSpec(
        GroundTruthCase,
        "validation",
        "Beklenen deterministik doğrulama vakası.",
        "validation_data",
        "case_code",
        used_by_services="validators",
    ),
    ModelSpec(
        City, "geography", "Sentetik şehir referansı.", "master_data", "slug", snapshot_scoped=False
    ),
    ModelSpec(
        District,
        "geography",
        "Sentetik ilçe ve profil referansı.",
        "master_data",
        "slug",
        snapshot_scoped=False,
    ),
    ModelSpec(
        Neighborhood,
        "geography",
        "Sentetik mahalle ve profil referansı.",
        "master_data",
        "slug",
        snapshot_scoped=False,
    ),
    ModelSpec(
        NetworkDevice,
        "network",
        "BNG, metro aggregation ve erişim cihazları.",
        "topology_data",
        "code",
        used_by_services="NetworkTopologyService,RootCauseService",
    ),
    ModelSpec(
        NetworkLink,
        "network",
        "Cihazlar arası yönlü mantıksal ağ bağlantısı.",
        "topology_data",
        "link_code",
        used_by_services="NetworkTopologyService,PathDiversityService",
    ),
    ModelSpec(
        NetworkPort,
        "network",
        "Cihaz port kapasitesi ve durumu.",
        "topology_data",
        "port_code",
        used_by_services="CustomerImpactService",
    ),
    ModelSpec(
        AccessSegment,
        "network",
        "Erişim segmenti ve teknoloji kapsama alanı.",
        "topology_data",
        "segment_code",
        used_by_services="CustomerImpactService",
    ),
    ModelSpec(
        LineConnection,
        "network",
        "Müşteri hattının fiziksel erişim bağlantısı.",
        "topology_data",
        "line_code",
        used_by_services="CustomerImpactService,PathDiversityService",
    ),
    ModelSpec(
        FailureDomain,
        "network",
        "Site, power_zone ve fiber_route ortak risk alanı.",
        "topology_data",
        "code",
        used_by_services="AlarmCorrelationService,PathDiversityService",
    ),
    ModelSpec(
        DeviceFailureDomainMembership,
        "network",
        "Cihaz arıza alanı üyeliği.",
        "topology_data",
        "id",
        used_by_services="PathDiversityService",
    ),
    ModelSpec(
        NetworkLinkFailureDomainMembership,
        "network",
        "NetworkLink arıza alanı üyeliği.",
        "topology_data",
        "id",
        used_by_services="PathDiversityService",
    ),
    ModelSpec(
        LineConnectionFailureDomainMembership,
        "network",
        "Hat arıza alanı üyeliği.",
        "topology_data",
        "id",
        used_by_services="PathDiversityService",
    ),
    ModelSpec(
        SLAProfile,
        "commercial",
        "Sözleşmesel SLA profili.",
        "commercial_data",
        "code",
        used_by_services="CompensationService",
    ),
    ModelSpec(
        Customer,
        "customer",
        "Sentetik müşteri kaydı.",
        "customer_data",
        "customer_number",
        used_by_services="CustomerImpactService,CompensationService",
    ),
    ModelSpec(
        ServicePackage,
        "commercial",
        "Sentetik paket katalog kaydı.",
        "commercial_data",
        "package_code",
        used_by_services="CompensationService",
    ),
    ModelSpec(
        apps.get_model("customers", "ServicePackageAllowedSegment"),
        "commercial",
        "Paketin izinli müşteri segmentleri.",
        "commercial_data",
        "id",
    ),
    ModelSpec(
        ServicePackagePriceVersion,
        "commercial",
        "Paket liste fiyatı zaman versiyonu.",
        "commercial_data",
        "version_number",
    ),
    ModelSpec(
        Subscription,
        "customer",
        "Müşterinin sözleşilmiş aboneliği.",
        "customer_data",
        "subscription_number",
        used_by_services="CustomerImpactService,CompensationService",
    ),
    ModelSpec(
        SubscriptionConnection,
        "customer",
        "Aboneliğin primary/backup fiziksel bağlantısı.",
        "customer_data",
        "id",
        used_by_services="CustomerImpactService,PathDiversityService",
    ),
    ModelSpec(
        Campaign, "commercial", "Sentetik kampanya katalog kaydı.", "commercial_data", "code"
    ),
    ModelSpec(
        apps.get_model("customers", "CampaignAllowedSegment"),
        "commercial",
        "Kampanya izinli segmentleri.",
        "commercial_data",
        "id",
    ),
    ModelSpec(
        apps.get_model("customers", "CampaignAllowedServiceType"),
        "commercial",
        "Kampanya izinli servis tipleri.",
        "commercial_data",
        "id",
    ),
    ModelSpec(
        apps.get_model("customers", "CampaignAllowedTechnology"),
        "commercial",
        "Kampanya izinli teknolojileri.",
        "commercial_data",
        "id",
    ),
    ModelSpec(
        CampaignEnrollment,
        "commercial",
        "Abonelik kampanya katılım durumu.",
        "commercial_data",
        "enrollment_code",
    ),
    ModelSpec(
        PaymentRecord,
        "commercial",
        "Abonelik fatura dönemi tahakkuk/tahsilat durumu.",
        "commercial_data",
        "payment_code",
    ),
    ModelSpec(
        apps.get_model("customers", "CompensationHistory"),
        "compensation",
        "Kesinleşmiş geçmiş telafi kararı ve settlement.",
        "decision_data",
        "id",
    ),
    ModelSpec(
        AlarmType,
        "operations",
        "Alarm katalog tipi.",
        "event_data",
        "code",
        used_by_services="AlarmCorrelationService,RootCauseService",
    ),
    ModelSpec(
        AlarmTypeAllowedSourceKind,
        "operations",
        "Alarm tipinin desteklediği kaynak türü.",
        "event_data",
        "id",
    ),
    ModelSpec(
        AlarmTypeSupportedDeviceType,
        "operations",
        "Alarm tipinin desteklediği cihaz türü.",
        "event_data",
        "id",
    ),
    ModelSpec(
        Alarm,
        "operations",
        "Tekil alarm olayı.",
        "event_data",
        "alarm_id",
        used_by_services="AlarmCorrelationService,RootCauseService",
    ),
    ModelSpec(
        Incident,
        "operations",
        "Korele operasyon olayı.",
        "event_data",
        "incident_number",
        used_by_services="RootCauseService,CompensationService",
    ),
    ModelSpec(
        IncidentAlarm, "operations", "Incident-alarm ilişkisi ve alarm rolü.", "event_data", "id"
    ),
    ModelSpec(
        Outage,
        "operations",
        "Gerçek hizmet erişilebilirliği kaybı.",
        "event_data",
        "outage_id",
        used_by_services="OutageService,CustomerImpactService,CompensationService",
    ),
    ModelSpec(
        MaintenanceWindow,
        "operations",
        "Planlı bakım penceresi.",
        "event_data",
        "reference_code",
        used_by_services="CompensationService",
    ),
    ModelSpec(
        apps.get_model("operations", "MaintenanceWindowDevice"),
        "operations",
        "Planlı bakım cihaz kapsamı.",
        "event_data",
        "id",
    ),
    ModelSpec(
        apps.get_model("operations", "MaintenanceWindowNetworkLink"),
        "operations",
        "Planlı bakım link kapsamı.",
        "event_data",
        "id",
    ),
    ModelSpec(
        OperationalEvent,
        "operations",
        "Incident/outage akışındaki operasyonel zaman izi.",
        "event_data",
        "event_id",
    ),
    ModelSpec(
        QualityMeasurement,
        "operations",
        "Latency, jitter, packet loss ve availability ölçümü.",
        "measurement_data",
        "measurement_id",
        used_by_services="CompensationService",
    ),
    ModelSpec(
        RuleSet,
        "rules",
        "Sentetik politika seti.",
        "rule_data",
        "code",
        used_by_services="RuleEvaluationService",
    ),
    ModelSpec(
        Rule,
        "rules",
        "Kural statik kimliği ve ailesi.",
        "rule_data",
        "code",
        used_by_services="RuleEvaluationService",
    ),
    ModelSpec(
        RuleVersion,
        "rules",
        "Event-time ile seçilen kural versiyonu.",
        "rule_data",
        "version",
        used_by_services="RuleEvaluationService,CompensationService",
    ),
    ModelSpec(
        apps.get_model("rules", "RuleTestCase"),
        "rules",
        "Kural odaklı test senaryosu.",
        "validation_data",
        "name",
    ),
    ModelSpec(
        CompensationEvaluation,
        "compensation",
        "Deterministik telafi değerlendirme adayı.",
        "decision_data",
        "evaluation_code",
        used_by_services="CompensationService",
    ),
    ModelSpec(
        DecisionEvidence,
        "compensation",
        "Immutable karar kanıtı ve hesaplama izi.",
        "decision_data",
        "evidence_hash",
        used_by_services="CompensationService,LLM explanation",
    ),
)


MODEL_SPECS_BY_MODEL = {spec.model: spec for spec in MODEL_SPECS}


def export_synthetic_review_pack(options: ExportOptions) -> ExportResult:
    if options.sample_size < 1:
        raise ValueError("--sample-size must be positive.")

    snapshot = resolve_snapshot(
        snapshot_key=options.snapshot_key,
        dataset_slug=options.dataset_slug,
    )
    maltepe_snapshot = resolve_maltepe_snapshot() if options.include_maltepe_regression else None
    output_dir = options.output_dir.expanduser()
    progress = options.progress or (lambda message: None)
    progress("Resolving snapshots and preparing output directory.")
    if output_dir.exists():
        if not options.overwrite:
            raise FileExistsError(f"Output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_git_commit = current_git_commit()
    row_count_before = collect_db_row_count_fingerprint(snapshot, maltepe_snapshot)
    writer = ReviewPackWriter(
        output_dir=output_dir,
        snapshot=snapshot,
        maltepe_snapshot=maltepe_snapshot,
        sample_size=options.sample_size,
        include_full_data=options.include_full_data,
        source_git_commit=source_git_commit,
        progress=progress,
    )
    progress("Writing catalogs, dictionaries, review CSV files, and data exports.")
    writer.write_all()
    progress("Running dataset, ground-truth, path-diversity, and Maltepe validations.")
    validation_summary = writer.write_validation_outputs()
    progress("Writing model relationship diagram sources.")
    writer.write_diagram()
    progress("Writing optional XLSX feedback workbook if openpyxl is available.")
    xlsx_created = writer.write_feedback_xlsx()
    progress("Running secret/PII scan and export consistency checks.")
    secret_findings = writer.scan_for_secrets()
    writer.write_known_limits()
    writer.write_readme()
    writer.write_manifest_and_checksums()
    export_validation = writer.validate_export(secret_findings)
    writer.write_export_validation_summary(export_validation)
    progress("Writing manifest and SHA256 checksums.")
    writer.write_manifest_and_checksums()

    zip_path = None
    zip_size_bytes = 0
    if options.make_zip:
        progress("Creating zip archive.")
        zip_path = output_dir.with_suffix(".zip")
        if zip_path.exists():
            if options.overwrite:
                zip_path.unlink()
            else:
                raise FileExistsError(f"Zip file already exists: {zip_path}")
        create_zip(output_dir, zip_path)
        zip_size_bytes = zip_path.stat().st_size

    row_count_after = collect_db_row_count_fingerprint(snapshot, maltepe_snapshot)
    progress("Verifying database row-count fingerprint after read-only export.")
    result = ExportResult(
        output_dir=output_dir,
        zip_path=zip_path,
        zip_size_bytes=zip_size_bytes,
        snapshot_key=snapshot.snapshot_key,
        dataset_slug=snapshot.dataset_version.slug,
        multicity_table_count=writer.multicity_table_count,
        maltepe_table_count=writer.maltepe_table_count,
        csv_count=len(writer.csv_infos),
        total_csv_rows=sum(info.row_count for info in writer.csv_infos),
        xlsx_created=xlsx_created,
        inconsistencies=writer.inconsistencies + export_validation["inconsistencies"],
        secret_scan_findings=secret_findings,
        validation_summary=validation_summary | {"export_validation": export_validation},
        db_counts_unchanged=row_count_before == row_count_after,
    )
    if not result.db_counts_unchanged:
        result.inconsistencies.append("Export sonrası DB row count fingerprint değişti.")
    return result


def resolve_snapshot(*, snapshot_key: str | None, dataset_slug: str | None) -> DataSnapshot:
    if not snapshot_key and not dataset_slug:
        raise ValueError("--snapshot-key veya --dataset-slug açıkça verilmelidir.")
    queryset = DataSnapshot.objects.select_related("dataset_version")
    if snapshot_key:
        snapshot = queryset.filter(snapshot_key=snapshot_key).first()
        if snapshot is None:
            raise ValueError(f"Snapshot bulunamadı: {snapshot_key}")
        if dataset_slug and snapshot.dataset_version.slug != dataset_slug:
            raise ValueError(
                "snapshot-key ve dataset-slug aynı dataset'i göstermiyor: "
                f"{snapshot.dataset_version.slug} != {dataset_slug}"
            )
        return snapshot
    dataset = DatasetVersion.objects.filter(slug=dataset_slug).first()
    if dataset is None:
        raise ValueError(f"Dataset bulunamadı: {dataset_slug}")
    snapshots = list(queryset.filter(dataset_version=dataset).order_by("snapshot_key"))
    if len(snapshots) != 1:
        raise ValueError(f"Dataset için tekil snapshot bekleniyordu: {dataset_slug}")
    return snapshots[0]


def resolve_maltepe_snapshot() -> DataSnapshot:
    snapshot = (
        DataSnapshot.objects.select_related("dataset_version")
        .filter(dataset_version__slug__startswith="maltepe-mvp", is_active=True)
        .first()
    )
    if snapshot is None:
        raise ValueError("Aktif Maltepe regression snapshot bulunamadı.")
    return snapshot


class ReviewPackWriter:
    def __init__(
        self,
        *,
        output_dir: Path,
        snapshot: DataSnapshot,
        maltepe_snapshot: DataSnapshot | None,
        sample_size: int,
        include_full_data: bool,
        source_git_commit: str,
        progress: Callable[[str], None],
    ) -> None:
        self.output_dir = output_dir
        self.snapshot = snapshot
        self.maltepe_snapshot = maltepe_snapshot
        self.sample_size = sample_size
        self.include_full_data = include_full_data
        self.source_git_commit = source_git_commit
        self.progress = progress
        self.csv_infos: list[CsvInfo] = []
        self.inconsistencies: list[str] = []
        self.multicity_table_count = 0
        self.maltepe_table_count = 0
        self._validation_summary: dict[str, Any] = {}

    def write_all(self) -> None:
        for relative in [
            "review",
            "sample_data/multicity",
            "sample_data/maltepe_regression",
            "full_data/multicity",
            "full_data/maltepe_regression",
            "validation",
            "diagrams",
        ]:
            (self.output_dir / relative).mkdir(parents=True, exist_ok=True)
        self.progress("Writing table catalog.")
        self.write_table_catalog()
        self.progress("Writing data dictionary.")
        self.write_data_dictionary()
        self.progress("Writing relationship catalog.")
        self.write_relationships()
        self.progress("Writing enum and code catalog.")
        self.write_enum_catalog()
        self.progress("Writing table counts.")
        self.write_table_counts()
        self.progress("Writing human review CSV files.")
        self.write_review_files()
        self.progress("Writing multi-city sample data.")
        self.write_sample_data(self.snapshot, "multicity")
        if self.maltepe_snapshot:
            self.progress("Writing Maltepe regression sample data.")
            self.write_sample_data(self.maltepe_snapshot, "maltepe_regression")
        if self.include_full_data:
            self.progress("Writing multi-city full data CSV files.")
            self.write_full_data(self.snapshot, "multicity")
            if self.maltepe_snapshot:
                self.progress("Writing Maltepe regression full data CSV files.")
                self.write_full_data(self.maltepe_snapshot, "maltepe_regression")

    def write_table_catalog(self) -> None:
        headers = [
            "app",
            "model_name",
            "database_table",
            "Turkish_name",
            "category",
            "purpose",
            "data_type_category",
            "snapshot_scoped",
            "row_count_multicity",
            "row_count_maltepe",
            "primary_key",
            "natural_key_or_code",
            "main_parent_table",
            "main_child_tables",
            "generated_by",
            "used_by_services",
            "notes",
            "Turkcell_table_exists",
            "Turkcell_table_name",
            "Turkcell_notes",
        ]
        rows = []
        for spec in MODEL_SPECS:
            opts = spec.model._meta
            rows.append(
                {
                    "app": opts.app_label,
                    "model_name": opts.object_name,
                    "database_table": opts.db_table,
                    "Turkish_name": str(opts.verbose_name),
                    "category": spec.category,
                    "purpose": spec.purpose,
                    "data_type_category": spec.data_type_category,
                    "snapshot_scoped": spec.snapshot_scoped,
                    "row_count_multicity": scoped_count(spec.model, self.snapshot),
                    "row_count_maltepe": scoped_count(spec.model, self.maltepe_snapshot)
                    if self.maltepe_snapshot
                    else "",
                    "primary_key": opts.pk.name,
                    "natural_key_or_code": spec.natural_key,
                    "main_parent_table": parent_tables(spec.model),
                    "main_child_tables": child_tables(spec.model),
                    "generated_by": "seed_multicity_realism veya seed_maltepe_mvp",
                    "used_by_services": spec.used_by_services,
                    "notes": SYNTHETIC_NOTE,
                    "Turkcell_table_exists": "",
                    "Turkcell_table_name": "",
                    "Turkcell_notes": "",
                }
            )
        self.write_csv("02_table_catalog.csv", headers, rows, "catalog", "Django models", "all")

    def write_data_dictionary(self) -> None:
        headers = [
            "app",
            "model_name",
            "database_table",
            "field_name",
            "database_column",
            "Turkish_description",
            "description_source",
            "Django_field_type",
            "database_type",
            "max_length",
            "nullable",
            "blank",
            "default",
            "primary_key",
            "unique",
            "indexed",
            "relation_type",
            "related_model",
            "related_field",
            "on_delete",
            "choices_or_enum",
            "unit",
            "format",
            "example_value",
            "synthetic_generation_rule",
            "validation_rule",
            "used_by_service",
            "contains_personal_data",
            "notes",
            "Turkcell_field_exists",
            "Turkcell_table_name",
            "Turkcell_field_name",
            "Turkcell_data_type",
            "Turkcell_nullable",
            "Turkcell_enum_or_code",
            "Turkcell_comment",
            "proposed_action",
        ]
        rows = []
        for spec in MODEL_SPECS:
            sample = get_first_object(spec.model, self.snapshot)
            for field in concrete_fields(spec.model):
                description, source = describe_field(field)
                rows.append(
                    {
                        "app": spec.model._meta.app_label,
                        "model_name": spec.model._meta.object_name,
                        "database_table": spec.model._meta.db_table,
                        "field_name": field.name,
                        "database_column": field.column,
                        "Turkish_description": description,
                        "description_source": source,
                        "Django_field_type": field.__class__.__name__,
                        "database_type": field.db_type(connection=connection) or "",
                        "max_length": getattr(field, "max_length", "") or "",
                        "nullable": field.null,
                        "blank": getattr(field, "blank", False),
                        "default": serialize_default(field.default),
                        "primary_key": field.primary_key,
                        "unique": field.unique,
                        "indexed": field.db_index,
                        "relation_type": relation_type(field),
                        "related_model": related_model_name(field),
                        "related_field": related_field_name(field),
                        "on_delete": on_delete_name(field),
                        "choices_or_enum": serialize_choices(field),
                        "unit": infer_unit(field.name),
                        "format": infer_format(field),
                        "example_value": serialize_value(getattr(sample, field.name, None))
                        if sample is not None
                        else "",
                        "synthetic_generation_rule": synthetic_generation_rule(spec, field),
                        "validation_rule": validation_rule_summary(spec.model, field.name),
                        "used_by_service": spec.used_by_services,
                        "contains_personal_data": contains_personal_data_hint(field.name),
                        "notes": "",
                        "Turkcell_field_exists": "",
                        "Turkcell_table_name": "",
                        "Turkcell_field_name": "",
                        "Turkcell_data_type": "",
                        "Turkcell_nullable": "",
                        "Turkcell_enum_or_code": "",
                        "Turkcell_comment": "",
                        "proposed_action": "",
                    }
                )
        self.write_csv(
            "03_data_dictionary.csv", headers, rows, "dictionary", "Django models", "all"
        )

    def write_relationships(self) -> None:
        headers = [
            "source_app",
            "source_model",
            "source_table",
            "source_field",
            "relationship_type",
            "target_app",
            "target_model",
            "target_table",
            "target_field",
            "required",
            "on_delete",
            "cardinality",
            "business_meaning",
            "validation_or_constraint",
            "Turkcell_equivalent",
            "Turkcell_comment",
        ]
        rows = []
        for spec in MODEL_SPECS:
            for field in concrete_fields(spec.model):
                if not field.is_relation or not getattr(field, "remote_field", None):
                    continue
                target = field.remote_field.model
                if isinstance(target, str):
                    continue
                rows.append(
                    {
                        "source_app": spec.model._meta.app_label,
                        "source_model": spec.model._meta.object_name,
                        "source_table": spec.model._meta.db_table,
                        "source_field": field.name,
                        "relationship_type": relation_type(field),
                        "target_app": target._meta.app_label,
                        "target_model": target._meta.object_name,
                        "target_table": target._meta.db_table,
                        "target_field": target._meta.pk.name,
                        "required": not field.null,
                        "on_delete": on_delete_name(field),
                        "cardinality": cardinality(field),
                        "business_meaning": relationship_meaning(spec.model, field),
                        "validation_or_constraint": validation_rule_summary(spec.model, field.name),
                        "Turkcell_equivalent": "",
                        "Turkcell_comment": "",
                    }
                )
        self.write_csv(
            "04_relationships.csv", headers, rows, "dictionary", "Django relations", "all"
        )

    def write_enum_catalog(self) -> None:
        headers = [
            "category",
            "model_or_config",
            "field_name",
            "code",
            "Turkish_description",
            "technical_description",
            "allowed_source",
            "allowed_device_type",
            "severity",
            "service_impact",
            "active",
            "source_file",
            "Turkcell_code",
            "Turkcell_description",
            "Turkcell_comment",
        ]
        rows = []
        for spec in MODEL_SPECS:
            for field in concrete_fields(spec.model):
                if not getattr(field, "choices", None):
                    continue
                for code, label in field.choices:
                    rows.append(
                        {
                            "category": enum_category(field.name),
                            "model_or_config": spec.model._meta.object_name,
                            "field_name": field.name,
                            "code": code,
                            "Turkish_description": enum_turkish_description(
                                field.name, code, label
                            ),
                            "technical_description": label,
                            "allowed_source": "",
                            "allowed_device_type": "",
                            "severity": "",
                            "service_impact": "",
                            "active": True,
                            "source_file": model_source_file(spec.model),
                            "Turkcell_code": "",
                            "Turkcell_description": "",
                            "Turkcell_comment": "",
                        }
                    )
        for item in alarm_config.ALARM_CATALOG:
            rows.append(
                {
                    "category": "alarm_type",
                    "model_or_config": "realistic_alarm_catalog_v1.ALARM_CATALOG",
                    "field_name": "code",
                    "code": item["code"],
                    "Turkish_description": turkish_alarm_description(item),
                    "technical_description": item.get("name", ""),
                    "allowed_source": "|".join(item.get("allowed_source_kinds", [])),
                    "allowed_device_type": "|".join(item.get("supported_device_types", [])),
                    "severity": item.get("severity", ""),
                    "service_impact": item.get("service_impact_class", ""),
                    "active": True,
                    "source_file": "data_generator/configs/realistic_alarm_catalog_v1.py",
                    "Turkcell_code": "",
                    "Turkcell_description": "",
                    "Turkcell_comment": "",
                }
            )
        self.write_csv(
            "05_enum_and_code_catalog.csv",
            headers,
            rows,
            "catalog",
            "choices/config",
            "all",
        )

    def write_table_counts(self) -> None:
        headers = [
            "dataset_slug",
            "snapshot_key",
            "app",
            "model",
            "table",
            "row_count",
            "expected_count",
            "count_status",
            "validation_source",
            "notes",
        ]
        rows = []
        expected = expected_counts_by_model()
        for snapshot in [self.snapshot, self.maltepe_snapshot]:
            if snapshot is None:
                continue
            for spec in MODEL_SPECS:
                count = scoped_count(spec.model, snapshot)
                expected_count = expected.get(spec.model._meta.object_name, "")
                status = "not_applicable"
                if expected_count != "" and snapshot == self.snapshot:
                    status = "match" if count == expected_count else "mismatch"
                    if status == "mismatch":
                        self.inconsistencies.append(
                            f"{spec.model._meta.object_name}: "
                            f"expected={expected_count}, actual={count}"
                        )
                rows.append(
                    {
                        "dataset_slug": snapshot.dataset_version.slug,
                        "snapshot_key": snapshot.snapshot_key,
                        "app": spec.model._meta.app_label,
                        "model": spec.model._meta.object_name,
                        "table": spec.model._meta.db_table,
                        "row_count": count,
                        "expected_count": expected_count,
                        "count_status": status,
                        "validation_source": "multi-city validator/config"
                        if snapshot == self.snapshot
                        else "native DB",
                        "notes": "",
                    }
                )
        self.write_csv("06_table_counts.csv", headers, rows, "validation", "Django models", "all")

    def write_review_files(self) -> None:
        self.write_network_review()
        self.write_alarm_type_review()
        self.write_scenario_review()
        self.write_customer_subscription_review()
        self.write_package_sla_campaign_review()
        self.write_business_rules_review()
        self.write_ground_truth_review()

    def write_network_review(self) -> None:
        headers = [
            "entity_type",
            "code",
            "name",
            "device_type",
            "access_role",
            "city",
            "district",
            "neighborhood",
            "upstream_device",
            "downstream_count",
            "port_count",
            "link_count",
            "primary_path",
            "backup_path",
            "failure_domains",
            "technology",
            "capacity",
            "synthetic_reason",
            "Turkcell_equivalent_name",
            "Turkcell_comment",
        ]
        rows = []
        device_summary = (
            NetworkDevice.objects.filter(data_snapshot=self.snapshot)
            .values("device_type", "access_role")
            .annotate(count=Count("id"))
            .order_by("device_type", "access_role")
        )
        for item in device_summary:
            rows.append(
                {
                    "entity_type": "device_type_summary",
                    "code": f"{item['device_type']}:{item['access_role'] or 'none'}",
                    "name": "Cihaz türü özeti",
                    "device_type": item["device_type"],
                    "access_role": item["access_role"] or "",
                    "city": "multi-city",
                    "district": "",
                    "neighborhood": "",
                    "upstream_device": "",
                    "downstream_count": "",
                    "port_count": item["count"],
                    "link_count": "",
                    "primary_path": "",
                    "backup_path": "",
                    "failure_domains": "",
                    "technology": "",
                    "capacity": "",
                    "synthetic_reason": SYNTHETIC_NOTE,
                    "Turkcell_equivalent_name": "",
                    "Turkcell_comment": "",
                }
            )
        devices = representative_queryset(
            NetworkDevice.objects.filter(data_snapshot=self.snapshot)
            .select_related("city", "district", "neighborhood")
            .order_by("device_type", "city__name", "district__name", "code"),
            self.sample_size,
        )
        for device in devices:
            upstreams = list(
                NetworkLink.objects.filter(data_snapshot=self.snapshot, target_device=device)
                .select_related("source_device")
                .values_list("source_device__code", flat=True)[:5]
            )
            rows.append(
                {
                    "entity_type": "device_sample",
                    "code": device.code,
                    "name": device.name,
                    "device_type": device.device_type,
                    "access_role": device.access_role or "",
                    "city": device.city.name,
                    "district": device.district.name if device.district else "",
                    "neighborhood": device.neighborhood.name if device.neighborhood else "",
                    "upstream_device": "|".join(upstreams),
                    "downstream_count": device.outgoing_links.count(),
                    "port_count": device.ports.count(),
                    "link_count": device.incoming_links.count() + device.outgoing_links.count(),
                    "primary_path": "",
                    "backup_path": "",
                    "failure_domains": "|".join(
                        device.failure_domain_memberships.values_list(
                            "failure_domain__code", flat=True
                        )
                    ),
                    "technology": "",
                    "capacity": "",
                    "synthetic_reason": "Temsilî cihaz kaydı.",
                    "Turkcell_equivalent_name": "",
                    "Turkcell_comment": "",
                }
            )
        self.write_csv(
            "review/01_network_topology_review.csv",
            headers,
            rows,
            "review",
            "NetworkDevice/NetworkLink/FailureDomain",
            self.snapshot.snapshot_key,
        )

    def write_alarm_type_review(self) -> None:
        headers = [
            "alarm_code",
            "Turkish_name",
            "Turkish_description",
            "category",
            "severity",
            "allowed_source_kind",
            "allowed_device_types",
            "probable_cause",
            "service_impact",
            "correlation_family",
            "deduplication_window",
            "auto_clear_behavior",
            "root_cause_candidate",
            "example_source",
            "example_scenario",
            "Turkcell_alarm_exists",
            "Turkcell_alarm_name",
            "Turkcell_alarm_code",
            "Turkcell_severity",
            "Turkcell_source",
            "Turkcell_comment",
            "proposed_action",
        ]
        rows = []
        alarm_types = (
            AlarmType.objects.filter(data_snapshot=self.snapshot)
            .prefetch_related("allowed_source_kinds", "supported_device_types")
            .order_by("code")
        )
        scenario_by_alarm = scenario_lookup_by_alarm()
        for alarm_type in alarm_types:
            allowed_sources = list(
                alarm_type.allowed_source_kinds.values_list("source_kind", flat=True)
            )
            supported_devices = list(
                alarm_type.supported_device_types.values_list("device_type", flat=True)
            )
            rows.append(
                {
                    "alarm_code": alarm_type.code,
                    "Turkish_name": alarm_type.name,
                    "Turkish_description": turkish_alarm_description(
                        {"code": alarm_type.code, "name": alarm_type.name}
                    ),
                    "category": alarm_type.category,
                    "severity": alarm_type.severity,
                    "allowed_source_kind": "|".join(allowed_sources),
                    "allowed_device_types": "|".join(supported_devices),
                    "probable_cause": alarm_type.probable_cause_family,
                    "service_impact": alarm_type.service_impact_class,
                    "correlation_family": alarm_type.correlation_family,
                    "deduplication_window": alarm_type.deduplication_window_seconds,
                    "auto_clear_behavior": alarm_type.auto_clear_policy,
                    "root_cause_candidate": alarm_type.is_root_candidate,
                    "example_source": find_example_alarm_source(alarm_type),
                    "example_scenario": scenario_by_alarm.get(alarm_type.code, ""),
                    "Turkcell_alarm_exists": "",
                    "Turkcell_alarm_name": "",
                    "Turkcell_alarm_code": "",
                    "Turkcell_severity": "",
                    "Turkcell_source": "",
                    "Turkcell_comment": "",
                    "proposed_action": "",
                }
            )
        self.write_csv(
            "review/02_alarm_types_review.csv",
            headers,
            rows,
            "review",
            "AlarmType",
            self.snapshot.snapshot_key,
        )

    def write_scenario_review(self) -> None:
        headers = [
            "scenario_code",
            "Turkish_name",
            "Turkish_description",
            "source_type",
            "source_code_or_type",
            "alarm_codes",
            "expected_incident_type",
            "expected_impact_class",
            "creates_outage",
            "planned",
            "failover_behavior",
            "expected_root_cause_behavior",
            "customer_impact_behavior",
            "compensation_behavior",
            "ground_truth_case",
            "Turkcell_real_scenario_exists",
            "Turkcell_scenario_name",
            "Turkcell_comment",
            "proposed_action",
        ]
        gt_by_scenario = {
            item["scenario_code"]: item["case_code"]
            for item in ground_truth_config.GROUND_TRUTH_CASES
        }
        rows = []
        for item in alarm_config.SCENARIO_TEMPLATES:
            scenario_code = item["code"]
            rows.append(
                {
                    "scenario_code": scenario_code,
                    "Turkish_name": item.get("name", scenario_code),
                    "Turkish_description": item.get("description", "Sentetik olay senaryosu."),
                    "source_type": item.get("source", ""),
                    "source_code_or_type": item.get("source_code_or_type", item.get("source", "")),
                    "alarm_codes": "|".join(item.get("alarm_codes", [])),
                    "expected_incident_type": item.get("incident_type", ""),
                    "expected_impact_class": item.get("service_impact_class", ""),
                    "creates_outage": item.get("creates_outage", ""),
                    "planned": item.get("planned", ""),
                    "failover_behavior": item.get("failover_result", ""),
                    "expected_root_cause_behavior": item.get("expected_root_cause", ""),
                    "customer_impact_behavior": item.get("customer_impact_behavior", ""),
                    "compensation_behavior": item.get("compensation_behavior", ""),
                    "ground_truth_case": gt_by_scenario.get(scenario_code, ""),
                    "Turkcell_real_scenario_exists": "",
                    "Turkcell_scenario_name": "",
                    "Turkcell_comment": "",
                    "proposed_action": "",
                }
            )
        self.write_csv(
            "review/03_scenarios_review.csv",
            headers,
            rows,
            "review",
            "SCENARIO_TEMPLATES",
            self.snapshot.snapshot_key,
        )

    def write_customer_subscription_review(self) -> None:
        headers = [
            "record_type",
            "code",
            "city",
            "district",
            "segment",
            "priority_or_vip",
            "subscription_status",
            "suspension_reason",
            "subscription_count",
            "connection_role",
            "technology",
            "service_type",
            "package_code",
            "sla_profile",
            "description",
            "Turkcell_equivalent",
            "Turkcell_comment",
        ]
        rows = []
        for item in (
            Customer.objects.filter(data_snapshot=self.snapshot)
            .values("segment", "priority_level")
            .annotate(count=Count("id"))
            .order_by("segment", "priority_level")
        ):
            rows.append(
                {
                    "record_type": "customer_summary",
                    "code": f"{item['segment']}:{item['priority_level']}",
                    "city": "multi-city",
                    "district": "",
                    "segment": item["segment"],
                    "priority_or_vip": item["priority_level"],
                    "subscription_status": "",
                    "suspension_reason": "",
                    "subscription_count": item["count"],
                    "connection_role": "",
                    "technology": "",
                    "service_type": "",
                    "package_code": "",
                    "sla_profile": "",
                    "description": "Müşteri segment/öncelik toplamı.",
                    "Turkcell_equivalent": "",
                    "Turkcell_comment": "",
                }
            )
        subscriptions = representative_queryset(
            Subscription.objects.filter(data_snapshot=self.snapshot)
            .select_related(
                "customer", "customer__city", "customer__district", "service_package", "sla_profile"
            )
            .order_by("status", "customer__segment", "subscription_number"),
            self.sample_size,
        )
        for subscription in subscriptions:
            primary = (
                subscription.connections.filter(connection_role=SubscriptionConnectionRole.PRIMARY)
                .select_related("line_connection")
                .first()
            )
            rows.append(
                {
                    "record_type": "subscription_sample",
                    "code": subscription.subscription_number,
                    "city": subscription.customer.city.name,
                    "district": subscription.customer.district.name
                    if subscription.customer.district
                    else "",
                    "segment": subscription.customer.segment,
                    "priority_or_vip": subscription.customer.priority_level,
                    "subscription_status": subscription.status,
                    "suspension_reason": subscription.suspension_reason,
                    "subscription_count": subscription.customer.subscriptions.count(),
                    "connection_role": primary.connection_role if primary else "",
                    "technology": primary.line_connection.technology
                    if primary
                    else subscription.service_package.technology,
                    "service_type": subscription.service_package.service_type,
                    "package_code": subscription.service_package.package_code,
                    "sla_profile": subscription.sla_profile.code
                    if subscription.sla_profile
                    else "",
                    "description": "Temsilî abonelik kaydı.",
                    "Turkcell_equivalent": "",
                    "Turkcell_comment": "",
                }
            )
        self.write_csv(
            "review/04_customer_subscription_review.csv",
            headers,
            rows,
            "review",
            "Customer/Subscription",
            self.snapshot.snapshot_key,
        )

    def write_package_sla_campaign_review(self) -> None:
        headers = [
            "record_type",
            "code",
            "name",
            "service_type",
            "technology",
            "download_speed_mbps",
            "upload_speed_mbps",
            "symmetric",
            "allowed_segments",
            "list_price",
            "commitment_months",
            "default_sla",
            "availability_target",
            "latency_target",
            "jitter_target",
            "packet_loss_target",
            "response_time",
            "restoration_time",
            "backup_requirement",
            "diversity_requirement",
            "discount_type",
            "discount_value",
            "campaign_duration",
            "stackable",
            "status",
            "Turkcell_equivalent",
            "Turkcell_comment",
        ]
        rows = []
        for package in (
            ServicePackage.objects.filter(data_snapshot=self.snapshot)
            .select_related("default_sla_profile")
            .order_by("package_code")
        ):
            rows.append(
                {
                    "record_type": "service_package",
                    "code": package.package_code,
                    "name": package.name,
                    "service_type": package.service_type,
                    "technology": package.technology,
                    "download_speed_mbps": package.download_mbps,
                    "upload_speed_mbps": package.upload_mbps,
                    "symmetric": package.symmetric,
                    "allowed_segments": "|".join(
                        package.allowed_segments.values_list("segment", flat=True)
                    ),
                    "list_price": package.monthly_price,
                    "commitment_months": package.commitment_months,
                    "default_sla": package.default_sla_profile.code
                    if package.default_sla_profile
                    else "",
                    "availability_target": "",
                    "latency_target": "",
                    "jitter_target": "",
                    "packet_loss_target": "",
                    "response_time": "",
                    "restoration_time": "",
                    "backup_requirement": package.default_sla_profile.backup_requirement
                    if package.default_sla_profile
                    else "",
                    "diversity_requirement": package.default_sla_profile.required_path_diversity
                    if package.default_sla_profile
                    else "",
                    "discount_type": "",
                    "discount_value": "",
                    "campaign_duration": "",
                    "stackable": "",
                    "status": package.status,
                    "Turkcell_equivalent": "",
                    "Turkcell_comment": "",
                }
            )
        for sla in SLAProfile.objects.filter(data_snapshot=self.snapshot).order_by("code"):
            rows.append(
                {
                    "record_type": "sla_profile",
                    "code": sla.code,
                    "name": sla.name,
                    "service_type": "",
                    "technology": "",
                    "download_speed_mbps": "",
                    "upload_speed_mbps": "",
                    "symmetric": "",
                    "allowed_segments": "",
                    "list_price": "",
                    "commitment_months": "",
                    "default_sla": "",
                    "availability_target": sla.availability_target_percent,
                    "latency_target": sla.latency_threshold_ms,
                    "jitter_target": sla.jitter_threshold_ms,
                    "packet_loss_target": sla.packet_loss_threshold_percent,
                    "response_time": sla.response_target_minutes,
                    "restoration_time": sla.restoration_target_minutes,
                    "backup_requirement": sla.backup_requirement,
                    "diversity_requirement": sla.required_path_diversity,
                    "discount_type": "",
                    "discount_value": "",
                    "campaign_duration": "",
                    "stackable": "",
                    "status": "active" if sla.active else "inactive",
                    "Turkcell_equivalent": "",
                    "Turkcell_comment": "",
                }
            )
        for campaign in Campaign.objects.filter(data_snapshot=self.snapshot).order_by("code"):
            rows.append(
                {
                    "record_type": "campaign",
                    "code": campaign.code,
                    "name": campaign.name,
                    "service_type": "|".join(
                        campaign.service_types.values_list("service_type", flat=True)
                    ),
                    "technology": "|".join(
                        campaign.technologies.values_list("technology", flat=True)
                    ),
                    "download_speed_mbps": "",
                    "upload_speed_mbps": "",
                    "symmetric": "",
                    "allowed_segments": "|".join(
                        campaign.segments.values_list("segment", flat=True)
                    ),
                    "list_price": "",
                    "commitment_months": "",
                    "default_sla": "",
                    "availability_target": "",
                    "latency_target": "",
                    "jitter_target": "",
                    "packet_loss_target": "",
                    "response_time": "",
                    "restoration_time": "",
                    "backup_requirement": "",
                    "diversity_requirement": "",
                    "discount_type": campaign.discount_type,
                    "discount_value": campaign.discount_value,
                    "campaign_duration": campaign.duration_months,
                    "stackable": campaign.stackable,
                    "status": campaign.status,
                    "Turkcell_equivalent": "",
                    "Turkcell_comment": "",
                }
            )
        self.write_csv(
            "review/05_packages_sla_campaigns_review.csv",
            headers,
            rows,
            "review",
            "ServicePackage/SLAProfile/Campaign",
            self.snapshot.snapshot_key,
        )

    def write_business_rules_review(self) -> None:
        headers = [
            "rule_code",
            "Turkish_name",
            "Turkish_description",
            "family",
            "priority",
            "conflict_group",
            "action_type",
            "price_basis",
            "eligibility_conditions",
            "exclusion_conditions",
            "calculation_summary",
            "tiers_or_thresholds",
            "modifiers",
            "cap_or_floor",
            "manual_review_behavior",
            "duplicate_behavior",
            "evidence_required",
            "example_result",
            "raw_condition_json",
            "raw_action_json",
            "Turkcell_rule_exists",
            "Turkcell_rule_name",
            "Turkcell_comment",
            "proposed_action",
        ]
        rows = []
        for version in (
            RuleVersion.objects.filter(data_snapshot=self.snapshot)
            .select_related("rule")
            .order_by("rule__code", "version")
        ):
            action = version.action_config or {}
            condition = version.condition_tree or {}
            rows.append(
                {
                    "rule_code": version.rule.code,
                    "Turkish_name": version.rule.name,
                    "Turkish_description": version.rule.description,
                    "family": version.rule.family,
                    "priority": version.priority,
                    "conflict_group": version.rule.conflict_group,
                    "action_type": version.action_type,
                    "price_basis": version.price_basis,
                    "eligibility_conditions": summarize_conditions(condition, include="positive"),
                    "exclusion_conditions": summarize_conditions(condition, include="negative"),
                    "calculation_summary": summarize_action(version.action_type, action),
                    "tiers_or_thresholds": summarize_tiers(action),
                    "modifiers": summarize_modifiers(action),
                    "cap_or_floor": summarize_cap_floor(action),
                    "manual_review_behavior": summarize_manual_review(version.rule.code, action),
                    "duplicate_behavior": "conflict_group/idempotency üzerinden tekilleştirme"
                    if "DUPLICATE" in version.rule.code
                    else "",
                    "evidence_required": "|".join(action.get("required_fields", [])),
                    "example_result": example_rule_result(version.rule.code),
                    "raw_condition_json": condition,
                    "raw_action_json": action,
                    "Turkcell_rule_exists": "",
                    "Turkcell_rule_name": "",
                    "Turkcell_comment": "",
                    "proposed_action": "",
                }
            )
        self.write_csv(
            "review/06_business_rules_review.csv",
            headers,
            rows,
            "review",
            "Rule/RuleVersion",
            self.snapshot.snapshot_key,
        )

    def write_ground_truth_review(self) -> None:
        headers = [
            "case_code",
            "category",
            "Turkish_description",
            "scenario_code",
            "source",
            "expected_alarm_codes",
            "expected_incident_type",
            "expected_impact",
            "expected_root_cause",
            "expected_subscription_count",
            "expected_customer_count",
            "expected_rule",
            "expected_decision",
            "expected_amount",
            "actual_result",
            "passed",
            "Turkcell_comment",
        ]
        report = validate_multicity_ground_truth(self.snapshot)
        passed_by_case = {
            item["case_code"]: True for item in ground_truth_config.GROUND_TRUTH_CASES
        }
        for failed in report["failed"]:
            case_code = failed["name"].split(".", 1)[0]
            if case_code.startswith("GT-"):
                passed_by_case[case_code] = False
        cases_by_code = {
            case.case_code: case
            for case in GroundTruthCase.objects.filter(data_snapshot=self.snapshot)
        }
        rows = []
        for item in ground_truth_config.GROUND_TRUTH_CASES:
            db_case = cases_by_code.get(item["case_code"])
            rows.append(
                {
                    "case_code": item["case_code"],
                    "category": item["category"],
                    "Turkish_description": item.get("description", ""),
                    "scenario_code": item["scenario_code"],
                    "source": item.get("source", ""),
                    "expected_alarm_codes": "|".join(item.get("expected_alarm_codes", [])),
                    "expected_incident_type": item.get("expected_incident_type", ""),
                    "expected_impact": item.get("expected_impact_class", ""),
                    "expected_root_cause": item.get("expected_root_cause", ""),
                    "expected_subscription_count": item.get(
                        "expected_affected_subscription_count", ""
                    ),
                    "expected_customer_count": item.get("expected_affected_customer_count", ""),
                    "expected_rule": item.get("expected_selected_rule", ""),
                    "expected_decision": item.get("expected_decision", ""),
                    "expected_amount": item.get("expected_exact_amount", ""),
                    "actual_result": db_case.expected_total_refund_amount if db_case else "missing",
                    "passed": passed_by_case.get(item["case_code"], False),
                    "Turkcell_comment": "",
                }
            )
        self.write_csv(
            "review/07_ground_truth_review.csv",
            headers,
            rows,
            "review",
            "GroundTruthCase",
            self.snapshot.snapshot_key,
        )

    def write_sample_data(self, snapshot: DataSnapshot, folder_name: str) -> None:
        for spec in MODEL_SPECS:
            queryset = model_queryset_for_snapshot(spec.model, snapshot)
            rows = serialize_queryset_rows(
                queryset=representative_queryset(queryset, self.sample_size),
                model=spec.model,
                snapshot=snapshot,
                dataset_slug=snapshot.dataset_version.slug,
            )
            if not rows:
                continue
            headers = list(rows[0].keys())
            self.write_csv(
                f"sample_data/{folder_name}/{spec.model._meta.db_table}.csv",
                headers,
                rows,
                "sample_data",
                spec.model._meta.label,
                snapshot.snapshot_key,
            )

    def write_full_data(self, snapshot: DataSnapshot, folder_name: str) -> None:
        table_count = 0
        for spec in MODEL_SPECS:
            queryset = model_queryset_for_snapshot(spec.model, snapshot)
            if not queryset.exists():
                continue
            headers = generic_export_headers(spec.model)
            rows = stream_queryset_rows(
                queryset=queryset,
                model=spec.model,
                snapshot=snapshot,
                dataset_slug=snapshot.dataset_version.slug,
            )
            self.write_csv(
                f"full_data/{folder_name}/{spec.model._meta.db_table}.csv",
                headers,
                rows,
                "full_data",
                spec.model._meta.label,
                snapshot.snapshot_key,
            )
            table_count += 1
        if folder_name == "multicity":
            self.multicity_table_count = table_count
        else:
            self.maltepe_table_count = table_count

    def write_validation_outputs(self) -> dict[str, Any]:
        realism_report = validate_multicity_realism_snapshot(self.snapshot)
        gt_report = validate_multicity_ground_truth(self.snapshot)
        maltepe_report = (
            validate_maltepe_mvp_snapshot(self.maltepe_snapshot) if self.maltepe_snapshot else None
        )
        self._validation_summary = {
            "multi_city_validator_passed": realism_report["passed"],
            "ground_truth_passed": gt_report["passed"],
            "ground_truth_case_count": gt_report["case_count"],
            "maltepe_regression_passed": bool(maltepe_report and maltepe_report["passed"]),
        }
        self.write_csv(
            "validation/dataset_validation_summary.csv",
            ["name", "expected", "actual", "passed"],
            realism_report["checks"],
            "validation",
            "validate_multicity_realism_snapshot",
            self.snapshot.snapshot_key,
        )
        self.write_csv(
            "validation/ground_truth_cases.csv",
            [
                "case_code",
                "category",
                "scenario_code",
                "expected_selected_rule",
                "expected_decision",
                "expected_exact_amount",
                "expected_root_cause",
            ],
            [
                {
                    "case_code": item["case_code"],
                    "category": item["category"],
                    "scenario_code": item["scenario_code"],
                    "expected_selected_rule": item.get("expected_selected_rule", ""),
                    "expected_decision": item.get("expected_decision", ""),
                    "expected_exact_amount": item.get("expected_exact_amount", ""),
                    "expected_root_cause": item.get("expected_root_cause", ""),
                }
                for item in ground_truth_config.GROUND_TRUTH_CASES
            ],
            "validation",
            "multicity_ground_truth_v1",
            self.snapshot.snapshot_key,
        )
        self.write_csv(
            "validation/ground_truth_results.csv",
            ["name", "expected", "actual", "passed"],
            gt_report["checks"],
            "validation",
            "validate_multicity_ground_truth",
            self.snapshot.snapshot_key,
        )
        self.write_csv(
            "validation/path_diversity_summary.csv",
            ["classification", "count"],
            [
                {"classification": key, "count": value}
                for key, value in collect_path_diversity_summary(self.snapshot).items()
            ],
            "validation",
            "PathDiversityService",
            self.snapshot.snapshot_key,
        )
        if maltepe_report:
            self.write_csv(
                "validation/maltepe_regression_summary.csv",
                ["name", "expected", "actual", "passed"],
                maltepe_report["checks"],
                "validation",
                "validate_maltepe_snapshot",
                self.maltepe_snapshot.snapshot_key,
            )
        ground_truth_pass_count = gt_report["case_count"] - len(gt_report["failed"])
        maltepe_status = "PASS" if maltepe_report and maltepe_report["passed"] else "not included"
        self.write_markdown(
            "07_validation_summary.md",
            [
                "# Validation Summary",
                "",
                f"- Multi-city validator: {'PASS' if realism_report['passed'] else 'FAIL'}",
                f"- Ground truth: {gt_report['case_count']}/{ground_truth_pass_count} pass",
                f"- Maltepe regression: {maltepe_status}",
                "- Export is read-only; seed/reset/activation commands are not called.",
            ],
        )
        return self._validation_summary

    def write_diagram(self) -> None:
        lines = [
            "erDiagram",
        ]
        for spec in MODEL_SPECS:
            lines.append(f"    {spec.model._meta.object_name} {{")
            for field in concrete_fields(spec.model)[:12]:
                dtype = field.__class__.__name__.replace("Field", "")
                lines.append(f"        {dtype} {field.name}")
            lines.append("    }")
        for spec in MODEL_SPECS:
            for field in concrete_fields(spec.model):
                if not field.is_relation or not getattr(field, "remote_field", None):
                    continue
                target = field.remote_field.model
                if isinstance(target, str) or target not in MODEL_SPECS_BY_MODEL:
                    continue
                lines.append(
                    f"    {target._meta.object_name} ||--o{{ "
                    f"{spec.model._meta.object_name} : {field.name}"
                )
        mmd_path = self.output_dir / "diagrams/model_relationships.mmd"
        mmd_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        png_path = self.output_dir / "diagrams/model_relationships.png"
        if shutil.which("mmdc"):
            subprocess.run(
                ["mmdc", "-i", str(mmd_path), "-o", str(png_path)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        if not png_path.exists():
            self.inconsistencies.append(
                "Mermaid PNG render aracı bulunamadı; yalnız .mmd üretildi."
            )

    def write_feedback_xlsx(self) -> bool:
        try:
            from openpyxl import Workbook
        except ImportError:
            self.inconsistencies.append("openpyxl yok; XLSX geri bildirim formu atlandı.")
            return False

        source_files = [
            ("Tablo Kataloğu", "02_table_catalog.csv"),
            ("Kolon Sözlüğü", "03_data_dictionary.csv"),
            ("İlişkiler", "04_relationships.csv"),
            ("Ağ Topolojisi", "review/01_network_topology_review.csv"),
            ("Alarm Tipleri", "review/02_alarm_types_review.csv"),
            ("Senaryolar", "review/03_scenarios_review.csv"),
            ("Müşteri-Abonelik", "review/04_customer_subscription_review.csv"),
            ("Paket-SLA-Kampanya", "review/05_packages_sla_campaigns_review.csv"),
            ("İş Kuralları", "review/06_business_rules_review.csv"),
            ("Ground Truth", "review/07_ground_truth_review.csv"),
        ]
        workbook = Workbook()
        workbook.remove(workbook.active)
        for sheet_name, relative_path in source_files:
            sheet = workbook.create_sheet(sheet_name)
            with (self.output_dir / relative_path).open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    sheet.append(row)
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column_cells in sheet.columns:
                length = max(len(str(cell.value or "")) for cell in column_cells[:100])
                sheet.column_dimensions[column_cells[0].column_letter].width = min(
                    max(length + 2, 12), 48
                )
        workbook.save(self.output_dir / "Turkcell_Sentetik_Veri_Geri_Bildirim_Formu.xlsx")
        return True

    def write_known_limits(self) -> None:
        self.write_markdown(
            "08_known_limits.md",
            [
                "# Bilinen Sınırlar",
                "",
                "- Bu paket gerçek operatör verisi değildir; tamamen sentetik üretimdir.",
                "- Fiyatlar, kampanyalar, alarm isimleri ve iş politikaları sentetiktir.",
                "- Production network entegrasyonu yoktur.",
                "- Kapsamlı SRLG modeli yoktur; site, power_zone ve fiber_route "
                "failure-domain modeli vardır.",
                "- SimulationRun runtime, görev 075-081 kapsamındadır.",
                "- RAG yalnız prosedür/kural dokümanı getirecek; hesaplama deterministik "
                "servislerde kalacaktır.",
            ],
        )

    def write_readme(self) -> None:
        maltepe_key = (
            self.maltepe_snapshot.snapshot_key if self.maltepe_snapshot else "dahil edilmedi"
        )
        self.write_markdown(
            "00_OKU_BENI.md",
            [
                "# ProcessTwin Sentetik Veri İnceleme Paketi",
                "",
                "Bu paket ProcessTwin projesinde üretilen sentetik telekom simülasyon "
                "verisini Turkcell ekibinin incelemesi için hazırlanmıştır.",
                "",
                "Veriler `synthetic=true` kabul edilmelidir. Gerçek müşteri, gerçek "
                "operatör envanteri, canlı ağ kaydı, API credential veya gizli bilgi "
                "içermez.",
                "",
                "## Amaç",
                "",
                "ProcessTwin; ağ topolojisi, alarm ve kesinti akışı, müşteri etkisi, "
                "iş kuralı ve telafi kararlarını deterministik servislerle üreten "
                "canlıya benzer sentetik bir simülasyon çekirdeğidir. MCP, RAG ve LLM "
                "katmanları bu çekirdeğin üzerine daha sonra bağlanacaktır; LLM "
                "hesaplama yapmayacaktır.",
                "",
                "## Dataset Kapsamı",
                "",
                f"- Multi-city dataset: `{self.snapshot.dataset_version.slug}` / "
                f"`{self.snapshot.snapshot_key}`",
                f"- Maltepe regression dataset: `{maltepe_key}`",
                "- Multi-city dataset pasif ve validated durumdadır; Maltepe regression "
                "snapshot aktif kalır.",
                "",
                "## Klasörler",
                "",
                "- `review/`: Turkcell ekibinin yorum yazabilmesi için sadeleştirilmiş "
                "inceleme CSV'leri.",
                "- `sample_data/`: Her ilgili tablodan en fazla örnek kayıtlar.",
                "- `full_data/`: `--include-full-data` ile üretilen tam sentetik veri dökümleri.",
                "- `validation/`: Validator, ground-truth, path-diversity ve regression sonuçları.",
                "- `diagrams/`: Model ilişki diyagramı Mermaid formatında; ortam "
                "destekliyorsa PNG.",
                "",
                "## CSV Formatı",
                "",
                "- Encoding: UTF-8-SIG; Excel'de Türkçe karakterler bozulmadan açılmalıdır.",
                "- Ayırıcı: virgül.",
                "- Tarihler: ISO 8601.",
                "- Decimal değerler: nokta ayracıyla string.",
                "- Boolean değerler: `true`/`false`.",
                "- JSON alanları: geçerli JSON string'i.",
                "- Null değerler: boş hücre.",
                "",
                "## ID, Code ve Foreign Key",
                "",
                "Numeric ID alanları teknik referanstır. İnceleme için mümkün olduğunda "
                "`code`, `name`, `snapshot_key`, `subscription_number`, "
                "`customer_number`, `alarm_id`, `incident_number` gibi okunabilir "
                "alanlar ayrıca export edilmiştir.",
                "",
                "## Beklenen Geri Bildirim",
                "",
                "Turkcell ekibinden her tablo/kolon/alarm/kural için özellikle şu "
                "yorumlar beklenir:",
                "",
                "- Gerçek sistemdeki tablo adı",
                "- Gerçek kolon adı",
                "- Gerçek veri tipi",
                "- Zorunluluk/null davranışı",
                "- Enum/kod karşılığı",
                "- Alarm ve cihaz terminolojisi",
                "- İlişkinin doğruluğu",
                "- Eksik veya gereksiz alan",
                "- Önerilen düzeltme",
            ],
        )

    def write_manifest_and_checksums(self) -> None:
        for info in self.csv_infos:
            path = self.output_dir / info.relative_path
            if path.exists():
                info.file_size_bytes = path.stat().st_size
                info.sha256 = sha256_file(path)
        manifest_headers = [
            "relative_path",
            "category",
            "source_model",
            "source_snapshot",
            "row_count",
            "column_count",
            "file_size_bytes",
            "sha256",
            "generated_at",
            "source_git_commit",
            "synthetic",
            "notes",
        ]
        csv_info_by_path = {info.relative_path: info for info in self.csv_infos}
        manifest_rows = []
        for info in sorted(self.csv_infos, key=lambda item: item.relative_path):
            if info.relative_path == "01_export_manifest.csv":
                continue
            manifest_rows.append(
                {
                    "relative_path": info.relative_path,
                    "category": info.category,
                    "source_model": info.source_model,
                    "source_snapshot": info.source_snapshot,
                    "row_count": info.row_count,
                    "column_count": info.column_count,
                    "file_size_bytes": info.file_size_bytes,
                    "sha256": info.sha256,
                    "generated_at": GENERATED_AT,
                    "source_git_commit": self.source_git_commit,
                    "synthetic": True,
                    "notes": info.notes,
                }
            )
        for path in sorted(self.output_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = str(path.relative_to(self.output_dir))
            if is_ignored_export_artifact(path):
                continue
            if relative in csv_info_by_path or relative in {
                "01_export_manifest.csv",
                "09_SHA256SUMS.txt",
            }:
                continue
            manifest_rows.append(
                {
                    "relative_path": relative,
                    "category": file_category(relative),
                    "source_model": "export_synthetic_review_pack",
                    "source_snapshot": "all",
                    "row_count": file_row_count(path),
                    "column_count": "",
                    "file_size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "generated_at": GENERATED_AT,
                    "source_git_commit": self.source_git_commit,
                    "synthetic": True,
                    "notes": "Generated review-pack support file.",
                }
            )
        manifest_rows = sorted(manifest_rows, key=lambda item: item["relative_path"])
        self._write_csv_file("01_export_manifest.csv", manifest_headers, manifest_rows)
        manifest_info = CsvInfo(
            relative_path="01_export_manifest.csv",
            category="manifest",
            source_model="export_synthetic_review_pack",
            source_snapshot="all",
            row_count=len(manifest_rows),
            column_count=len(manifest_headers),
            notes="Export manifest.",
            file_size_bytes=(self.output_dir / "01_export_manifest.csv").stat().st_size,
            sha256=sha256_file(self.output_dir / "01_export_manifest.csv"),
        )
        self.csv_infos = [
            info for info in self.csv_infos if info.relative_path != "01_export_manifest.csv"
        ] + [manifest_info]
        checksum_lines = []
        for path in sorted(self.output_dir.rglob("*")):
            if (
                path.is_file()
                and path.name != "09_SHA256SUMS.txt"
                and not is_ignored_export_artifact(path)
            ):
                checksum_lines.append(f"{sha256_file(path)}  {path.relative_to(self.output_dir)}")
        (self.output_dir / "09_SHA256SUMS.txt").write_text(
            "\n".join(checksum_lines) + "\n",
            encoding="utf-8",
        )

    def scan_for_secrets(self) -> list[str]:
        findings: list[str] = []
        secret_patterns = [
            re.compile(r"(?i)(DATABASE_URL|SECRET_KEY|API[_-]?KEY|PASSWORD)\s*[:=]\s*[^,\s]+"),
            re.compile(r"postgres(?:ql)?://[^,\s]+", re.IGNORECASE),
            re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-]{20,}"),
        ]
        email_pattern = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
        for path in self.output_dir.rglob("*"):
            if (
                not path.is_file()
                or is_ignored_export_artifact(path)
                or path.suffix.lower() in {".png", ".xlsx", ".zip"}
            ):
                continue
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
            for pattern in secret_patterns:
                if pattern.search(text):
                    findings.append(f"{path.relative_to(self.output_dir)}: possible secret pattern")
                    break
            if email_pattern.search(text):
                findings.append(f"{path.relative_to(self.output_dir)}: possible email/PII pattern")
        return sorted(set(findings))

    def validate_export(self, secret_findings: list[str]) -> dict[str, Any]:
        inconsistencies = []
        csv_count = 0
        row_total = 0
        for info in self.csv_infos:
            path = self.output_dir / info.relative_path
            if not path.exists():
                inconsistencies.append(f"Manifest entry missing file: {info.relative_path}")
                continue
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                try:
                    headers = next(reader)
                except StopIteration:
                    inconsistencies.append(f"Empty CSV: {info.relative_path}")
                    continue
                if len(headers) != len(set(headers)):
                    inconsistencies.append(f"Duplicate CSV header: {info.relative_path}")
                rows = sum(1 for _ in reader)
                if rows != info.row_count and info.relative_path != "01_export_manifest.csv":
                    inconsistencies.append(
                        f"Row count mismatch {info.relative_path}: "
                        f"manifest={info.row_count}, actual={rows}"
                    )
                csv_count += 1
                row_total += rows
        required_counts = {
            "review/02_alarm_types_review.csv": 30,
            "review/03_scenarios_review.csv": 22,
            "review/05_packages_sla_campaigns_review.csv": 42,
            "review/06_business_rules_review.csv": 25,
            "review/07_ground_truth_review.csv": 30,
        }
        for relative_path, expected_count in required_counts.items():
            actual = count_csv_rows(self.output_dir / relative_path)
            if actual != expected_count:
                inconsistencies.append(
                    f"{relative_path}: expected {expected_count}, actual {actual}"
                )
        if secret_findings:
            inconsistencies.extend(secret_findings)
        return {
            "passed": not inconsistencies,
            "csv_count": csv_count,
            "row_total": row_total,
            "inconsistencies": inconsistencies,
        }

    def write_export_validation_summary(self, export_validation: dict[str, Any]) -> None:
        self.write_markdown(
            "validation/export_validation_summary.md",
            [
                "# Export Validation Summary",
                "",
                f"- Result: {'PASS' if export_validation['passed'] else 'FAIL'}",
                f"- CSV count: {export_validation['csv_count']}",
                f"- CSV data rows: {export_validation['row_total']}",
                f"- Inconsistency count: {len(export_validation['inconsistencies'])}",
                "",
                "## Inconsistencies",
                "",
                *(
                    [f"- {item}" for item in export_validation["inconsistencies"]]
                    if export_validation["inconsistencies"]
                    else ["Doğrulanmış tutarsızlık bulunmadı."]
                ),
            ],
        )

    def write_csv(
        self,
        relative_path: str,
        headers: list[str],
        rows: Iterable[dict[str, Any]],
        category: str,
        source_model: str,
        source_snapshot: str,
        notes: str = "",
    ) -> None:
        row_count = self._write_csv_file(relative_path, headers, rows)
        self.csv_infos.append(
            CsvInfo(
                relative_path=relative_path,
                category=category,
                source_model=source_model,
                source_snapshot=source_snapshot,
                row_count=row_count,
                column_count=len(headers),
                notes=notes,
            )
        )

    def _write_csv_file(
        self,
        relative_path: str,
        headers: list[str],
        rows: Iterable[dict[str, Any]],
    ) -> int:
        if len(headers) != len(set(headers)):
            raise ValueError(f"Duplicate headers for {relative_path}")
        path = self.output_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        row_count = 0
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {header: serialize_value(row.get(header, "")) for header in headers}
                )
                row_count += 1
        return row_count

    def write_markdown(self, relative_path: str, lines: list[str]) -> None:
        path = self.output_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def model_queryset_for_snapshot(model: type[Model], snapshot: DataSnapshot) -> QuerySet:
    if has_field(model, "data_snapshot"):
        queryset = model.objects.filter(data_snapshot=snapshot)
    elif model is DatasetVersion:
        queryset = model.objects.filter(pk=snapshot.dataset_version_id)
    elif model is DataSnapshot:
        queryset = model.objects.filter(pk=snapshot.pk)
    elif model is City:
        queryset = model.objects.filter(name__in=realism_config.CITY_PROFILES)
    elif model is District:
        queryset = model.objects.filter(name__in=realism_config.DISTRICT_TECHNOLOGY_DISTRIBUTION)
    elif model is Neighborhood:
        district_names = realism_config.DISTRICT_TECHNOLOGY_DISTRIBUTION.keys()
        queryset = model.objects.filter(district__name__in=district_names)
    else:
        queryset = model.objects.none()
    fk_names = foreign_key_field_names(model)
    if fk_names:
        queryset = queryset.select_related(*fk_names)
    return queryset.order_by(*safe_ordering(model))


def serialize_queryset_rows(
    *,
    queryset: Iterable[Model],
    model: type[Model],
    snapshot: DataSnapshot,
    dataset_slug: str,
) -> list[dict[str, Any]]:
    return list(
        stream_queryset_rows(
            queryset=queryset,
            model=model,
            snapshot=snapshot,
            dataset_slug=dataset_slug,
        )
    )


def stream_queryset_rows(
    *,
    queryset: Iterable[Model],
    model: type[Model],
    snapshot: DataSnapshot,
    dataset_slug: str,
) -> Iterable[dict[str, Any]]:
    headers = generic_export_headers(model)
    for obj in iterable_queryset(queryset):
        row = {
            "export_snapshot_key": snapshot.snapshot_key,
            "export_dataset_slug": dataset_slug,
            "export_is_synthetic": True,
        }
        for field in concrete_fields(model):
            value = getattr(obj, field.name, None)
            if field.is_relation and getattr(field, "remote_field", None):
                row[f"{field.name}_id"] = getattr(obj, f"{field.name}_id", "")
                related = value if getattr(obj, f"{field.name}_id", None) else None
                row[f"{field.name}_fk_code"] = readable_code(related)
                row[f"{field.name}_fk_name"] = readable_name(related)
                row[f"{field.name}_fk_snapshot_key"] = readable_snapshot_key(related)
            else:
                row[field.name] = value
        yield {header: row.get(header, "") for header in headers}


def generic_export_headers(model: type[Model]) -> list[str]:
    headers = ["export_snapshot_key", "export_dataset_slug", "export_is_synthetic"]
    for field in concrete_fields(model):
        if field.is_relation and getattr(field, "remote_field", None):
            headers.extend(
                [
                    f"{field.name}_id",
                    f"{field.name}_fk_code",
                    f"{field.name}_fk_name",
                    f"{field.name}_fk_snapshot_key",
                ]
            )
        else:
            headers.append(field.name)
    return headers


def representative_queryset(queryset: QuerySet | Iterable[Model], limit: int) -> list[Model]:
    if not isinstance(queryset, QuerySet):
        return list(queryset)[:limit]
    count = queryset.count()
    if count <= limit:
        return list(queryset)
    if limit == 1:
        return [queryset.first()]
    step = max(count // limit, 1)
    ids = list(queryset.values_list("pk", flat=True)[::step][:limit])
    return list(queryset.model.objects.filter(pk__in=ids).order_by(*safe_ordering(queryset.model)))


def concrete_fields(model: type[Model]) -> list[models.Field]:
    return [field for field in model._meta.fields if not field.auto_created or field.concrete]


def foreign_key_field_names(model: type[Model]) -> list[str]:
    names = []
    for field in concrete_fields(model):
        if isinstance(field, (models.ForeignKey, models.OneToOneField)):
            names.append(field.name)
    return names


def has_field(model: type[Model], field_name: str) -> bool:
    return any(field.name == field_name for field in model._meta.fields)


def scoped_count(model: type[Model], snapshot: DataSnapshot | None) -> int | str:
    if snapshot is None:
        return ""
    return model_queryset_for_snapshot(model, snapshot).count()


def get_first_object(model: type[Model], snapshot: DataSnapshot) -> Model | None:
    return model_queryset_for_snapshot(model, snapshot).first()


def iterable_queryset(queryset: QuerySet | Iterable[Model]) -> Iterable[Model]:
    if isinstance(queryset, QuerySet):
        return queryset.iterator(chunk_size=1000)
    return queryset


def safe_ordering(model: type[Model]) -> list[str]:
    fields = [field.name for field in concrete_fields(model)]
    for candidate in [
        "code",
        "snapshot_key",
        "slug",
        "case_code",
        "customer_number",
        "subscription_number",
        "package_code",
        "alarm_id",
        "incident_number",
        "outage_id",
        "reference_code",
        "event_id",
        "measurement_id",
        "evaluation_code",
        "id",
    ]:
        if candidate in fields:
            return [candidate]
    return ["pk"]


def serialize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=serialize_value)
    return str(value)


def serialize_default(value: Any) -> str:
    if value is models.NOT_PROVIDED:
        return ""
    if callable(value):
        return getattr(value, "__name__", str(value))
    return serialize_value(value)


def readable_code(obj: Any) -> str:
    if obj is None:
        return ""
    for attr in [
        "code",
        "snapshot_key",
        "slug",
        "case_code",
        "customer_number",
        "subscription_number",
        "package_code",
        "line_code",
        "link_code",
        "port_code",
        "alarm_id",
        "incident_number",
        "outage_id",
        "reference_code",
        "event_id",
        "measurement_id",
        "evaluation_code",
        "evidence_hash",
    ]:
        if hasattr(obj, attr):
            return serialize_value(getattr(obj, attr))
    return str(getattr(obj, "pk", ""))


def readable_name(obj: Any) -> str:
    if obj is None:
        return ""
    for attr in ["name", "title", "display_name"]:
        if hasattr(obj, attr):
            return serialize_value(getattr(obj, attr))
    return str(obj)


def readable_snapshot_key(obj: Any) -> str:
    if obj is None:
        return ""
    if hasattr(obj, "snapshot_key"):
        return obj.snapshot_key
    if hasattr(obj, "data_snapshot_id") and obj.data_snapshot_id:
        try:
            return obj.data_snapshot.snapshot_key
        except Exception:
            return ""
    return ""


def describe_field(field: models.Field) -> tuple[str, str]:
    if getattr(field, "help_text", ""):
        return str(field.help_text), "help_text"
    if getattr(field, "choices", None):
        return f"{field.name} için izinli enum/kod değeri.", "choices"
    descriptions = {
        "data_snapshot": "Kaydın ait olduğu deterministik veri snapshot'ı.",
        "metadata": "Ek yapılandırılmış sentetik açıklama alanı.",
        "created_at": "Kaydın oluşturulma zamanı.",
        "updated_at": "Kaydın güncellenme zamanı.",
        "valid_from": "Kaydın geçerlilik başlangıcı.",
        "valid_to": "Kaydın geçerlilik bitişi; boşsa açık dönem.",
        "monthly_price": "Abonelik veya paket için aylık recurring fiyat.",
        "status": "Kaydın yaşam döngüsü durumu.",
    }
    if field.name in descriptions:
        return descriptions[field.name], "inferred"
    return "doğrulanamadı", "unresolved"


def relation_type(field: models.Field) -> str:
    if isinstance(field, models.OneToOneField):
        return "one_to_one"
    if isinstance(field, models.ForeignKey):
        return "foreign_key"
    if isinstance(field, models.ManyToManyField):
        return "many_to_many"
    return ""


def related_model_name(field: models.Field) -> str:
    remote = getattr(field, "remote_field", None)
    if not remote or isinstance(remote.model, str):
        return ""
    return remote.model._meta.label


def related_field_name(field: models.Field) -> str:
    remote = getattr(field, "remote_field", None)
    if not remote or isinstance(remote.model, str):
        return ""
    return remote.model._meta.pk.name


def on_delete_name(field: models.Field) -> str:
    remote = getattr(field, "remote_field", None)
    if not remote or not getattr(remote, "on_delete", None):
        return ""
    return getattr(remote.on_delete, "__name__", str(remote.on_delete))


def cardinality(field: models.Field) -> str:
    if isinstance(field, models.OneToOneField):
        return "1:1"
    if isinstance(field, models.ForeignKey):
        return "N:1"
    return ""


def parent_tables(model: type[Model]) -> str:
    return "|".join(
        field.remote_field.model._meta.db_table
        for field in concrete_fields(model)
        if field.is_relation
        and getattr(field, "remote_field", None)
        and not isinstance(field.remote_field.model, str)
    )


def child_tables(model: type[Model]) -> str:
    children = []
    for spec in MODEL_SPECS:
        for field in concrete_fields(spec.model):
            if (
                field.is_relation
                and getattr(field, "remote_field", None)
                and field.remote_field.model is model
            ):
                children.append(spec.model._meta.db_table)
    return "|".join(sorted(set(children)))


def relationship_meaning(model: type[Model], field: models.Field) -> str:
    return (
        f"{model._meta.verbose_name} kaydı {field.verbose_name} üzerinden "
        "hedef kayıtla ilişkilidir."
    )


def serialize_choices(field: models.Field) -> str:
    if not getattr(field, "choices", None):
        return ""
    return "|".join(f"{code}:{label}" for code, label in field.choices)


def infer_unit(field_name: str) -> str:
    if field_name.endswith("_seconds"):
        return "seconds"
    if field_name.endswith("_minutes"):
        return "minutes"
    if field_name.endswith("_percent"):
        return "percent"
    if field_name.endswith("_ms"):
        return "milliseconds"
    if "amount" in field_name or "price" in field_name:
        return "TRY"
    if field_name.endswith("_mbps"):
        return "Mbps"
    return ""


def infer_format(field: models.Field) -> str:
    if isinstance(field, models.DateTimeField):
        return "ISO 8601 timezone-aware datetime"
    if isinstance(field, models.DateField):
        return "ISO 8601 date"
    if isinstance(field, models.JSONField):
        return "JSON"
    if isinstance(field, models.DecimalField):
        return f"Decimal({field.max_digits},{field.decimal_places})"
    return ""


def synthetic_generation_rule(spec: ModelSpec, field: models.Field) -> str:
    if spec.model in {AlarmType, Rule, RuleVersion, ServicePackage, SLAProfile, Campaign}:
        return "config-driven synthetic catalog"
    if spec.snapshot_scoped:
        return "seed_multicity_realism deterministic generator"
    return "shared reference data"


def validation_rule_summary(model: type[Model], field_name: str) -> str:
    constraints = []
    for constraint in model._meta.constraints:
        text = str(constraint)
        if field_name in text:
            constraints.append(getattr(constraint, "name", text))
    if constraints:
        return "|".join(constraints)
    if hasattr(model, "clean"):
        return "model.clean may validate this field"
    return ""


def contains_personal_data_hint(field_name: str) -> str:
    if field_name in {"display_name", "customer_number"}:
        return "synthetic_personal_like"
    return "no"


def enum_category(field_name: str) -> str:
    return field_name


def enum_turkish_description(field_name: str, code: str, label: str) -> str:
    translations = {
        "device_type": "Ağ cihazı türü.",
        "inventory_status": "Envanter veya port durumu.",
        "access_role": "Access node cihazının erişim rolü.",
        "technology": "Fiziksel erişim teknolojisi.",
        "connection_role": "Abonelik bağlantısının primary veya backup rolü.",
        "segment": "Müşteri segmenti.",
        "priority_level": "Müşteri öncelik etiketi.",
        "suspension_reason": "Askıya alma gerekçesi.",
        "service_type": "Paketin hizmet tipi.",
        "severity": "Alarm veya incident operasyonel ciddiyeti.",
        "service_impact_class": "Müşteri hizmet etkisi sınıfı.",
        "incident_type": "Incident türü.",
        "outage_type": "Kesinti türü.",
        "decision_status": "Telafi karar sonucu.",
        "settlement_status": "Telafi ödeme/mahsup durumu.",
        "action_type": "Kural aksiyon tipi.",
        "price_basis": "Telafi tutarında kullanılan fiyat kaynağı.",
    }
    return translations.get(field_name, f"{label} enum değeri.")


def model_source_file(model: type[Model]) -> str:
    return f"backend/{model.__module__.replace('.', '/')}.py"


def expected_counts_by_model() -> dict[str, int]:
    return {
        "City": 4,
        "District": 12,
        "Neighborhood": 59,
        "NetworkDevice": 235,
        "NetworkLink": 245,
        "Customer": 14400,
        "Subscription": 16200,
        "SubscriptionConnection": 16235,
        "ServicePackage": 27,
        "SLAProfile": 5,
        "Campaign": 10,
        "ServicePackagePriceVersion": 72,
        "PaymentRecord": 59600,
        "CampaignEnrollment": 4050,
        "CompensationHistory": 1100,
        "AlarmType": 30,
        "Alarm": 2100,
        "Incident": 210,
        "Outage": 78,
        "MaintenanceWindow": 30,
        "OperationalEvent": 900,
        "QualityMeasurement": 12000,
        "RuleSet": 1,
        "Rule": 25,
        "RuleVersion": 25,
        "GroundTruthCase": 30,
    }


def turkish_alarm_description(item: dict[str, Any]) -> str:
    code = item.get("code", "")
    explicit = {
        "BNG_UNREACHABLE": "BNG cihazına ağ üzerinden erişilemediğini gösterir.",
        "OPTICAL_SIGNAL_LOSS": "Fiber hatta optik sinyalin tamamen kaybolduğunu gösterir.",
        "BACKUP_LINK_UNAVAILABLE": (
            "Ana hizmet çalışsa da yedek bağlantının kullanılamadığını gösterir."
        ),
        "LINK_FLAPPING": "Ağ bağlantısının kısa aralıklarla gidip geldiğini gösterir.",
        "PRIMARY_PATH_DOWN": (
            "Aboneliğin primary fiziksel erişim yolunun kullanılamadığını gösterir."
        ),
        "FAILOVER_UNSUCCESSFUL": "Yedek yola geçişin başarısız olduğunu gösterir.",
    }
    if code in explicit:
        return explicit[code]
    name = item.get("name", code).replace("_", " ").title()
    return f"{name} durumunu temsil eden sentetik alarm tipidir."


def scenario_lookup_by_alarm() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for scenario in alarm_config.SCENARIO_TEMPLATES:
        for code in scenario.get("alarm_codes", []):
            lookup.setdefault(code, scenario["code"])
    return lookup


def find_example_alarm_source(alarm_type: AlarmType) -> str:
    alarm = Alarm.objects.filter(
        data_snapshot=alarm_type.data_snapshot, alarm_type=alarm_type
    ).first()
    if not alarm:
        return ""
    return alarm.source_label


def summarize_conditions(condition: dict[str, Any], *, include: str) -> str:
    if not condition:
        return ""
    text = json.dumps(condition, ensure_ascii=False, sort_keys=True)
    if include == "negative":
        markers = ["not", "exclude", "ineligible", "manual_review"]
        return text if any(marker in text for marker in markers) else ""
    return text


def summarize_action(action_type: str, action: dict[str, Any]) -> str:
    if action_type == "tiered_percentage":
        return "Fiyat bazına süre veya ihlal tier oranı uygular."
    if action_type == "prorated":
        return "Gerçek dönem süresi ve etki oranıyla oransal tutar hesaplar."
    if action_type == "sla_matrix":
        return "SLA threshold aşım oranına göre sentetik kredi oranı seçer."
    if action_type == "manual_review":
        return "Otomatik parasal karar üretmez; manuel inceleme gerekçesi döndürür."
    if action_type == "ineligible":
        return "Otomatik telafi dışı bırakır."
    if action_type == "evidence_only":
        return "Parasal karar üretmeden kanıt kaydı sağlar."
    return json.dumps(action, ensure_ascii=False, sort_keys=True)


def summarize_tiers(action: dict[str, Any]) -> str:
    for key in ["tiers", "matrix", "availability_tiers"]:
        if key in action:
            return json.dumps(action[key], ensure_ascii=False, sort_keys=True)
    return ""


def summarize_modifiers(action: dict[str, Any]) -> str:
    return json.dumps(
        action.get("modifiers", action.get("modifier", "")), ensure_ascii=False, sort_keys=True
    )


def summarize_cap_floor(action: dict[str, Any]) -> str:
    keys = ["floor_amount", "minimum_credit", "incident_cap_rate", "monthly_cap_rate", "cap_amount"]
    return "; ".join(f"{key}={action[key]}" for key in keys if key in action)


def summarize_manual_review(rule_code: str, action: dict[str, Any]) -> str:
    if "MR-" in rule_code or action.get("status") == "manual_review":
        return json.dumps(
            action.get("manual_review_reasons", action), ensure_ascii=False, sort_keys=True
        )
    return ""


def example_rule_result(rule_code: str) -> str:
    examples = {
        "BB-FULL-OUTAGE-TIERED": "399.90 TRY, 40 dakika -> floor sonrası 10.00 TRY",
        "ME-LATENCY-BREACH": "SLA threshold aşımı matrix oranıyla hesaplanır.",
        "ME-FAILED-FAILOVER": "Backup başarısızsa Metro full outage tier uygulanır.",
        "MR-UNKNOWN-MISSING-EVIDENCE": "Eksik/unknown kanıt -> manual_review, 0 TRY",
    }
    return examples.get(rule_code, "")


def collect_path_diversity_summary(snapshot: DataSnapshot) -> dict[str, int]:
    counter: Counter[str] = Counter()
    backups = SubscriptionConnection.objects.filter(
        data_snapshot=snapshot,
        connection_role=SubscriptionConnectionRole.BACKUP,
    ).select_related("subscription", "line_connection")
    for backup in backups:
        primary = SubscriptionConnection.objects.get(
            data_snapshot=snapshot,
            subscription=backup.subscription,
            connection_role=SubscriptionConnectionRole.PRIMARY,
        )
        result = PathDiversityService().evaluate(
            primary_line=primary.line_connection,
            backup_line=backup.line_connection,
            snapshot=snapshot,
        )
        counter[result.classification] += 1
    return dict(sorted(counter.items()))


def collect_db_row_count_fingerprint(
    snapshot: DataSnapshot,
    maltepe_snapshot: DataSnapshot | None,
) -> dict[str, int]:
    fingerprint = {}
    for prefix, current_snapshot in [("multi", snapshot), ("maltepe", maltepe_snapshot)]:
        if current_snapshot is None:
            continue
        for spec in MODEL_SPECS:
            fingerprint[f"{prefix}:{spec.model._meta.label}"] = scoped_count(
                spec.model,
                current_snapshot,
            )
    return fingerprint


def create_zip(source_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file() and not is_ignored_export_artifact(path):
                archive.write(path, path.relative_to(source_dir.parent))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def file_category(relative_path: str) -> str:
    if relative_path.endswith(".md"):
        return "documentation"
    if relative_path.startswith("diagrams/"):
        return "diagram"
    if relative_path.endswith(".xlsx"):
        return "feedback_workbook"
    return "support"


def is_ignored_export_artifact(path: Path) -> bool:
    return path.name == ".DS_Store" or any(part.startswith("__MACOSX") for part in path.parts)


def file_row_count(path: Path) -> int | str:
    if path.suffix.lower() == ".md" or path.suffix.lower() == ".mmd":
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    return ""


def current_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
        ).strip()
    except Exception:
        return "unknown"
