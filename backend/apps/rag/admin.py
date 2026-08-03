from django.contrib import admin

from apps.rag.models import DocumentChunk, IndexRun, SourceDocument


@admin.register(SourceDocument)
class SourceDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "document_code",
        "version",
        "document_type",
        "source_kind",
        "status",
        "is_synthetic",
        "data_snapshot",
    )
    list_filter = ("document_type", "source_kind", "status", "is_synthetic")
    search_fields = ("document_code", "title", "content", "content_hash")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot",)
    list_select_related = ("data_snapshot",)


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = (
        "source_document",
        "sequence",
        "heading",
        "rule_code",
        "embedding_dimensions",
    )
    list_filter = ("embedding_dimensions",)
    search_fields = ("source_document__document_code", "heading", "text", "rule_code")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source_document",)
    list_select_related = ("source_document",)


@admin.register(IndexRun)
class IndexRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "data_snapshot",
        "source_count",
        "chunk_count",
        "embedding_count",
        "started_at",
        "completed_at",
    )
    list_filter = ("status",)
    search_fields = ("source_digest", "embedding_provider", "embedding_model")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot",)
    list_select_related = ("data_snapshot",)
