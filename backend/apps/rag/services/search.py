import math
import re
from dataclasses import dataclass
from functools import reduce
from operator import or_
from typing import Any

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import F, Q
from pgvector.django import CosineDistance

from apps.rag.models import DocumentChunk
from apps.rag.providers import EmbeddingProviderError
from apps.rag.providers.base import query_embedding_input
from apps.rag.services.embeddings import get_provider
from apps.rag.services.indexing import resolve_snapshot_identifier

SEARCH_MODES = {"semantic", "full_text", "hybrid"}
RANKING_VERSION = "hybrid-rrf-v1"
RRF_K = 60
SEMANTIC_WEIGHT = 0.5
FULL_TEXT_WEIGHT = 0.5
MAX_QUERY_LENGTH = 500
MAX_TOP_K = 20
CODE_RE = re.compile(r"[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+")


def expanded_search_terms(query: str) -> list[str]:
    """Add only deterministic vocabulary aliases used by the synthetic corpus."""
    normalized = " ".join(query.lower().split())
    terms = query.split()
    aliases = {
        "paket kaybı": ["packet_loss"],
        "başarısız yedek hat geçişi": ["failed", "failover"],
        "başarılı yedek hat geçişi": ["successful", "failover"],
        "kesinti süresi": ["minimum", "etki", "duration"],
    }
    for phrase, replacements in aliases.items():
        if phrase in normalized:
            terms.extend(replacements)
    return list(dict.fromkeys(term for term in terms if term.strip()))


@dataclass(frozen=True)
class SearchRequest:
    query: str
    snapshot_identifier: str
    search_mode: str = "hybrid"
    top_k: int = 5
    evaluation_time: Any = None
    document_type: str | None = None
    language: str | None = None
    source_kind: str | None = None
    rule_code: str | None = None
    rule_version: int | None = None
    include_scores: bool = True


def validate_request(request: SearchRequest):
    query = request.query.strip()
    if len(query) < 2:
        raise ValidationError("query must contain at least 2 characters.")
    if len(query) > MAX_QUERY_LENGTH:
        raise ValidationError("query exceeds the maximum length.")
    if request.snapshot_identifier.strip() == "":
        raise ValidationError("snapshot_identifier is required.")
    if request.search_mode not in SEARCH_MODES:
        raise ValidationError("search_mode is invalid.")
    if request.top_k < 1 or request.top_k > MAX_TOP_K:
        raise ValidationError(f"top_k must be between 1 and {MAX_TOP_K}.")
    if request.evaluation_time is not None:
        if not hasattr(request.evaluation_time, "tzinfo") or request.evaluation_time.tzinfo is None:
            raise ValidationError("evaluation_time must be timezone-aware.")


def base_queryset(request: SearchRequest):
    try:
        snapshot = resolve_snapshot_identifier(request.snapshot_identifier)
    except ValidationError as exc:
        if "was not found" in str(exc):
            raise LookupError("snapshot_identifier was not found.") from exc
        raise
    queryset = DocumentChunk.objects.filter(source_document__status="active").filter(
        Q(source_document__data_snapshot=snapshot) | Q(source_document__data_snapshot__isnull=True)
    )
    if request.document_type:
        queryset = queryset.filter(source_document__document_type=request.document_type)
    if request.language:
        queryset = queryset.filter(source_document__language=request.language)
    if request.source_kind:
        queryset = queryset.filter(source_document__source_kind=request.source_kind)
    if request.rule_code:
        queryset = queryset.filter(rule_code=request.rule_code)
    if request.rule_version is not None:
        queryset = queryset.filter(rule_version=request.rule_version)
    if request.evaluation_time is not None:
        point = request.evaluation_time
        queryset = queryset.filter(
            Q(source_document__valid_from__isnull=True) | Q(source_document__valid_from__lte=point),
            Q(source_document__valid_to__isnull=True) | Q(source_document__valid_to__gte=point),
            Q(valid_from__isnull=True) | Q(valid_from__lte=point),
            Q(valid_to__isnull=True) | Q(valid_to__gte=point),
        )
    return queryset.select_related("source_document").order_by(
        "source_document__document_code", "-source_document__version", "sequence", "pk"
    ), snapshot


def exact_code_match(query: str, chunk: DocumentChunk) -> bool:
    query_upper = query.strip().upper()
    codes = [chunk.source_document.document_code, chunk.rule_code or ""]
    codes.extend(CODE_RE.findall(chunk.text))
    return any(
        query_upper == code.upper()
        or query_upper in {part.upper() for part in re.split(r"[-_]", code) if part}
        or query_upper in code.upper()
        for code in codes
    )


def full_text_results(queryset, request: SearchRequest, limit: int) -> list[dict[str, Any]]:
    if connection.vendor == "postgresql":
        vector = (
            SearchVector("source_document__document_code", weight="A", config="simple")
            + SearchVector("rule_code", weight="A", config="simple")
            + SearchVector("source_document__title", weight="B", config="simple")
            + SearchVector("heading", weight="B", config="simple")
            + SearchVector("text", weight="C", config="simple")
        )
        search_queries = [
            SearchQuery(term, config="simple", search_type="plain")
            for term in expanded_search_terms(request.query)
        ]
        search_query = reduce(or_, search_queries)
        rows = (
            queryset.annotate(search_vector=vector)
            .filter(search_vector=search_query)
            .annotate(full_text_score=SearchRank(F("search_vector"), search_query))[:limit]
        )
    else:
        terms = [term.lower() for term in expanded_search_terms(request.query)]
        rows = []
        for chunk in queryset:
            haystack = " ".join(
                [
                    chunk.source_document.document_code,
                    chunk.rule_code or "",
                    chunk.source_document.title,
                    chunk.heading,
                    chunk.text,
                ]
            ).lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                chunk.full_text_score = float(score)
                rows.append(chunk)
        rows = rows[:limit]
    results = []
    for chunk in rows:
        score = float(getattr(chunk, "full_text_score", 0.0))
        exact = exact_code_match(request.query, chunk)
        if exact:
            score += 1.0
        results.append({"chunk": chunk, "score": score, "exact_code_match": exact})
    results.sort(
        key=lambda item: (
            -item["score"],
            item["chunk"].source_document.document_code,
            -item["chunk"].source_document.version,
            item["chunk"].sequence,
            item["chunk"].pk,
        )
    )
    for rank, item in enumerate(results, start=1):
        item["rank"] = rank
    return results


def semantic_results(
    queryset, request: SearchRequest, provider, limit: int
) -> list[dict[str, Any]]:
    vector = provider.embed(query_embedding_input(request.query), is_query=True)
    eligible = queryset.filter(
        embedding__isnull=False,
        embedding_dimensions=provider.dimensions,
        embedding_provider=provider.provider_name,
        embedding_model=provider.model_name,
        embedding_version=provider.embedding_version,
        metadata__prompt_version=provider.prompt_version,
    )
    if connection.vendor == "postgresql":
        rows = eligible.annotate(distance=CosineDistance("embedding", vector)).order_by(
            "distance",
            "source_document__document_code",
            "-source_document__version",
            "sequence",
            "pk",
        )[:limit]
        results = [
            {
                "chunk": row,
                "score": max(0.0, 1.0 - float(row.distance)),
                "exact_code_match": exact_code_match(request.query, row),
            }
            for row in rows
        ]
    else:
        results = []
        for chunk in eligible:
            values = list(chunk.embedding) if chunk.embedding is not None else []
            denominator = math.sqrt(sum(value * value for value in values))
            query_norm = math.sqrt(sum(value * value for value in vector))
            score = sum(left * right for left, right in zip(values, vector, strict=True)) / (
                denominator * query_norm
            )
            results.append(
                {
                    "chunk": chunk,
                    "score": score,
                    "exact_code_match": exact_code_match(request.query, chunk),
                }
            )
        results.sort(
            key=lambda item: (
                -item["score"],
                item["chunk"].source_document.document_code,
                -item["chunk"].source_document.version,
                item["chunk"].sequence,
                item["chunk"].pk,
            )
        )
        results = results[:limit]
    for rank, item in enumerate(results, start=1):
        item["rank"] = rank
    return results


def result_payload(
    item, *, semantic=None, full_text=None, hybrid=None, exact=False, include_scores=True
):
    chunk = item["chunk"]
    document = chunk.source_document
    payload = {
        "document_code": document.document_code,
        "title": document.title,
        "document_version": document.version,
        "document_type": document.document_type,
        "source_kind": document.source_kind,
        "language": document.language,
        "snapshot_key": document.data_snapshot.snapshot_key if document.data_snapshot_id else None,
        "chunk_id": chunk.pk,
        "sequence": chunk.sequence,
        "heading": chunk.heading,
        "section_path": chunk.section_path,
        "text": chunk.text,
        "rule_code": chunk.rule_code,
        "rule_version": chunk.rule_version,
        "valid_from": chunk.valid_from.isoformat() if chunk.valid_from else None,
        "valid_to": chunk.valid_to.isoformat() if chunk.valid_to else None,
        "content_hash": chunk.content_hash,
        "semantic_score": semantic["score"] if include_scores and semantic else None,
        "semantic_rank": semantic["rank"] if semantic else None,
        "full_text_score": full_text["score"] if include_scores and full_text else None,
        "full_text_rank": full_text["rank"] if full_text else None,
        "hybrid_score": hybrid if include_scores else None,
        "exact_code_match": exact,
        "evidence": {"source_content_hash": (chunk.metadata or {}).get("source_content_hash")},
    }
    return payload


def search(request: SearchRequest) -> dict[str, Any]:
    validate_request(request)
    queryset, snapshot = base_queryset(request)
    provider = None
    warnings = []
    candidate_limit = min(max(request.top_k * 4, 20), 100)
    full = (
        full_text_results(queryset, request, candidate_limit)
        if request.search_mode in {"full_text", "hybrid"}
        else []
    )
    semantic = []
    effective_mode = request.search_mode
    if request.search_mode in {"semantic", "hybrid"}:
        provider = get_provider()
        try:
            semantic = semantic_results(queryset, request, provider, candidate_limit)
        except EmbeddingProviderError:
            if request.search_mode == "semantic":
                raise
            effective_mode = "full_text_fallback"
            warnings.append(
                {
                    "code": "provider_unavailable",
                    "message": "Semantic provider unavailable; full-text results returned.",
                }
            )
    by_id = {}
    semantic_by_id = {item["chunk"].pk: item for item in semantic}
    full_by_id = {item["chunk"].pk: item for item in full}
    if effective_mode == "full_text_fallback":
        results = [
            result_payload(
                item,
                full_text=item,
                exact=item["exact_code_match"],
                include_scores=request.include_scores,
            )
            for item in full[: request.top_k]
        ]
    elif request.search_mode == "full_text":
        results = [
            result_payload(
                item,
                full_text=item,
                exact=item["exact_code_match"],
                include_scores=request.include_scores,
            )
            for item in full[: request.top_k]
        ]
    elif request.search_mode == "semantic":
        results = [
            result_payload(
                item,
                semantic=item,
                exact=item["exact_code_match"],
                include_scores=request.include_scores,
            )
            for item in semantic[: request.top_k]
        ]
    else:
        for _rank, item in enumerate(semantic, start=1):
            by_id[item["chunk"].pk] = item["chunk"]
        for _rank, item in enumerate(full, start=1):
            by_id[item["chunk"].pk] = item["chunk"]
        ranked = []
        for chunk_id, _chunk in by_id.items():
            sem = semantic_by_id.get(chunk_id)
            fts = full_by_id.get(chunk_id)
            exact = (sem or fts)["exact_code_match"]
            score = ((SEMANTIC_WEIGHT / (RRF_K + sem["rank"])) if sem else 0.0) + (
                (FULL_TEXT_WEIGHT / (RRF_K + fts["rank"])) if fts else 0.0
            )
            ranked.append((score, exact, sem, fts))
        ranked.sort(
            key=lambda row: (
                -row[0],
                -int(row[1]),
                row[2]["rank"] if row[2] else 10**9,
                row[3]["rank"] if row[3] else 10**9,
                row[2]["chunk"].source_document.document_code
                if row[2]
                else row[3]["chunk"].source_document.document_code,
                -(row[2] or row[3])["chunk"].source_document.version,
                (row[2] or row[3])["chunk"].sequence,
                (row[2] or row[3])["chunk"].pk,
            )
        )
        results = [
            result_payload(
                row[2] or row[3],
                semantic=row[2],
                full_text=row[3],
                hybrid=row[0],
                exact=row[1],
                include_scores=request.include_scores,
            )
            for row in ranked[: request.top_k]
        ]
    return {
        "query": request.query.strip(),
        "requested_mode": request.search_mode,
        "effective_mode": effective_mode,
        "top_k": request.top_k,
        "result_count": len(results),
        "snapshot": {
            "dataset_slug": snapshot.dataset_version.slug,
            "snapshot_key": snapshot.snapshot_key,
            "snapshot_name": snapshot.name,
            "snapshot_status": snapshot.status,
            "is_active": snapshot.is_active,
        },
        "embedding": provider.metadata() if provider else None,
        "ranking_version": RANKING_VERSION
        if request.search_mode == "hybrid" and effective_mode == "hybrid"
        else None,
        "warnings": warnings,
        "results": results,
    }
