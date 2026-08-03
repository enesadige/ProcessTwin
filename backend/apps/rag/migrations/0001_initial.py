import django.db.models.deletion
import pgvector.django.vector
from django.db import migrations, models
from pgvector.django import VectorExtension

import apps.rag.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("datasets", "0003_groundtruthcase"),
    ]

    operations = [
        VectorExtension(),
        migrations.CreateModel(
            name="SourceDocument",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("document_code", models.CharField(max_length=120)),
                ("title", models.CharField(max_length=240)),
                (
                    "document_type",
                    models.CharField(
                        choices=[
                            ("rule_policy", "Rule policy"),
                            ("procedure", "Procedure"),
                            ("sla", "SLA"),
                            ("campaign", "Campaign"),
                            ("technical_guide", "Technical guide"),
                            ("operational_runbook", "Operational runbook"),
                            ("other", "Other"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "source_kind",
                    models.CharField(
                        choices=[
                            ("synthetic", "Synthetic"),
                            ("internal", "Internal"),
                            ("imported", "Imported"),
                            ("manual", "Manual"),
                        ],
                        max_length=24,
                    ),
                ),
                ("version", models.PositiveIntegerField()),
                ("language", models.CharField(default="tr", max_length=16)),
                ("content", models.TextField()),
                (
                    "content_hash",
                    models.CharField(max_length=64, validators=[apps.rag.models.validate_sha256]),
                ),
                ("is_synthetic", models.BooleanField(default=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("active", "Active"),
                            ("archived", "Archived"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("valid_from", models.DateTimeField(blank=True, null=True)),
                ("valid_to", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "data_snapshot",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="source_documents",
                        to="datasets.datasnapshot",
                    ),
                ),
            ],
            options={
                "db_table": "rag_source_document",
                "ordering": ["document_code", "version"],
            },
        ),
        migrations.CreateModel(
            name="DocumentChunk",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sequence", models.PositiveIntegerField()),
                ("heading", models.CharField(blank=True, max_length=240)),
                ("section_path", models.JSONField(blank=True, default=list)),
                ("text", models.TextField()),
                (
                    "content_hash",
                    models.CharField(max_length=64, validators=[apps.rag.models.validate_sha256]),
                ),
                ("char_start", models.PositiveIntegerField(blank=True, null=True)),
                ("char_end", models.PositiveIntegerField(blank=True, null=True)),
                ("token_start", models.PositiveIntegerField(blank=True, null=True)),
                ("token_end", models.PositiveIntegerField(blank=True, null=True)),
                ("valid_from", models.DateTimeField(blank=True, null=True)),
                ("valid_to", models.DateTimeField(blank=True, null=True)),
                ("rule_code", models.CharField(blank=True, max_length=80, null=True)),
                ("rule_version", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "embedding",
                    pgvector.django.vector.VectorField(blank=True, dimensions=768, null=True),
                ),
                ("embedding_provider", models.CharField(blank=True, max_length=80, null=True)),
                ("embedding_model", models.CharField(blank=True, max_length=160, null=True)),
                ("embedding_version", models.CharField(blank=True, max_length=80, null=True)),
                ("embedding_dimensions", models.PositiveIntegerField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "source_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="rag.sourcedocument",
                    ),
                ),
            ],
            options={
                "db_table": "rag_document_chunk",
                "ordering": ["source_document", "sequence"],
            },
        ),
        migrations.CreateModel(
            name="IndexRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("source_count", models.PositiveIntegerField(default=0)),
                ("chunk_count", models.PositiveIntegerField(default=0)),
                ("embedding_count", models.PositiveIntegerField(default=0)),
                ("embedding_provider", models.CharField(blank=True, max_length=80, null=True)),
                ("embedding_model", models.CharField(blank=True, max_length=160, null=True)),
                ("embedding_dimensions", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "source_digest",
                    models.CharField(
                        blank=True,
                        max_length=64,
                        null=True,
                        validators=[apps.rag.models.validate_sha256],
                    ),
                ),
                ("error_summary", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "data_snapshot",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rag_index_runs",
                        to="datasets.datasnapshot",
                    ),
                ),
            ],
            options={
                "db_table": "rag_index_run",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["status"], name="rag_index_status_idx"),
                    models.Index(
                        fields=["data_snapshot", "status"], name="rag_index_snap_status_idx"
                    ),
                    models.Index(fields=["created_at"], name="rag_index_created_idx"),
                ],
            },
        ),
        migrations.AddIndex(
            model_name="sourcedocument",
            index=models.Index(fields=["document_code"], name="rag_doc_code_idx"),
        ),
        migrations.AddIndex(
            model_name="sourcedocument",
            index=models.Index(fields=["content_hash"], name="rag_doc_hash_idx"),
        ),
        migrations.AddIndex(
            model_name="sourcedocument",
            index=models.Index(fields=["status"], name="rag_doc_status_idx"),
        ),
        migrations.AddIndex(
            model_name="sourcedocument",
            index=models.Index(
                fields=["data_snapshot", "document_code"], name="rag_doc_snap_code_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="sourcedocument",
            index=models.Index(fields=["valid_from", "valid_to"], name="rag_doc_valid_idx"),
        ),
        migrations.AddConstraint(
            model_name="sourcedocument",
            constraint=models.UniqueConstraint(
                condition=models.Q(("data_snapshot__isnull", False)),
                fields=("data_snapshot", "document_code", "version"),
                name="rag_doc_snapshot_code_version_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="sourcedocument",
            constraint=models.UniqueConstraint(
                condition=models.Q(("data_snapshot__isnull", True)),
                fields=("document_code", "version"),
                name="rag_doc_global_code_version_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="sourcedocument",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("valid_to__isnull", True),
                    ("valid_from__isnull", True),
                    ("valid_to__gte", models.F("valid_from")),
                    _connector="OR",
                ),
                name="rag_doc_valid_range",
            ),
        ),
        migrations.AddIndex(
            model_name="documentchunk",
            index=models.Index(
                fields=["source_document", "sequence"], name="rag_chunk_doc_seq_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="documentchunk",
            index=models.Index(fields=["content_hash"], name="rag_chunk_hash_idx"),
        ),
        migrations.AddIndex(
            model_name="documentchunk",
            index=models.Index(fields=["rule_code"], name="rag_chunk_rule_idx"),
        ),
        migrations.AddIndex(
            model_name="documentchunk",
            index=models.Index(fields=["rule_code", "rule_version"], name="rag_chunk_rule_ver_idx"),
        ),
        migrations.AddIndex(
            model_name="documentchunk",
            index=models.Index(fields=["valid_from", "valid_to"], name="rag_chunk_valid_idx"),
        ),
        migrations.AddConstraint(
            model_name="documentchunk",
            constraint=models.UniqueConstraint(
                fields=("source_document", "sequence"), name="rag_chunk_document_sequence_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="documentchunk",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("char_end__isnull", True), ("char_start__isnull", True)),
                    models.Q(("char_end__isnull", False), ("char_start__isnull", False)),
                    _connector="OR",
                ),
                name="rag_chunk_char_bounds_pair",
            ),
        ),
        migrations.AddConstraint(
            model_name="documentchunk",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("token_end__isnull", True), ("token_start__isnull", True)),
                    models.Q(("token_end__isnull", False), ("token_start__isnull", False)),
                    _connector="OR",
                ),
                name="rag_chunk_token_bounds_pair",
            ),
        ),
        migrations.AddConstraint(
            model_name="documentchunk",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("valid_to__isnull", True),
                    ("valid_from__isnull", True),
                    ("valid_to__gte", models.F("valid_from")),
                    _connector="OR",
                ),
                name="rag_chunk_valid_range",
            ),
        ),
    ]
