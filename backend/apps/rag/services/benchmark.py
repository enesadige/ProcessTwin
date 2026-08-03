from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from django.conf import settings

from apps.rag.benchmark_manifest import (
    BENCHMARK_VERSION,
    SEMANTIC_PROFILE,
    BenchmarkCase,
)
from apps.rag.corpus_manifest import CORPUS_KEY
from apps.rag.models import DocumentChunk
from apps.rag.providers.base import (
    DOCUMENT_MODEL,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_VERSION,
    PROMPT_VERSION,
)
from apps.rag.services.search import SearchRequest, search

CANONICAL_CHUNK_COUNT = 74
SEMANTIC_PROVIDER = "gemini"
MARKDOWN_HEADING_PREFIX = re.compile(r"^\s{0,3}#{1,6}\s*")


class BenchmarkPrerequisiteError(Exception):
    """Safe benchmark prerequisite failure."""


@dataclass(frozen=True)
class BenchmarkCaseResult:
    case_code: str
    category: str
    profile: str
    passed: bool
    expected_document_code: str
    actual_top_document_code: str | None
    expected_rank_limit: int
    actual_rank: int | None
    requested_mode: str
    effective_mode: str | None
    expected_document_version: int
    actual_document_version: int | None
    expected_rule_version: int | None
    actual_rule_version: int | None
    heading: str | None
    chunk_id: int | None
    content_hash: str | None
    semantic_score: float | None
    full_text_score: float | None
    hybrid_score: float | None
    warnings: tuple[dict[str, Any], ...]
    failure_reasons: tuple[str, ...]

    def to_dict(self):
        value = asdict(self)
        value["warnings"] = list(self.warnings)
        value["failure_reasons"] = list(self.failure_reasons)
        return value


def _safe_failure(exc: Exception) -> str:
    if isinstance(exc, (BenchmarkPrerequisiteError, LookupError, ValueError)):
        return str(exc)[:240]
    return "benchmark_case_failed"


def normalize_heading(value: str | None) -> str:
    normalized = unicodedata.normalize("NFC", value or "").strip()
    normalized = MARKDOWN_HEADING_PREFIX.sub("", normalized)
    return " ".join(normalized.split()).casefold()


def validate_semantic_prerequisites() -> dict[str, Any]:
    if getattr(settings, "RAG_EMBEDDING_PROVIDER", "mock") != SEMANTIC_PROVIDER:
        raise BenchmarkPrerequisiteError(
            "Semantic profile requires RAG_EMBEDDING_PROVIDER=gemini and canonical Gemini "
            "embeddings. Run generate_rag_embeddings --provider gemini --force first."
        )
    chunks = DocumentChunk.objects.filter(
        source_document__status="active",
        source_document__metadata__corpus_key=CORPUS_KEY,
    )
    if chunks.count() != CANONICAL_CHUNK_COUNT:
        raise BenchmarkPrerequisiteError(
            f"Semantic profile requires exactly {CANONICAL_CHUNK_COUNT} canonical chunks."
        )
    incompatible = chunks.exclude(
        embedding__isnull=False,
        embedding_provider=SEMANTIC_PROVIDER,
        embedding_model=DOCUMENT_MODEL,
        embedding_version=EMBEDDING_VERSION,
        embedding_dimensions=EMBEDDING_DIMENSIONS,
        metadata__prompt_version=PROMPT_VERSION,
    ).exists()
    if incompatible:
        raise BenchmarkPrerequisiteError(
            "Canonical chunk embeddings do not match gemini-embedding-2/768/"
            "asymmetric-retrieval-v1. Run generate_rag_embeddings --provider gemini --force."
        )
    return {
        "provider": SEMANTIC_PROVIDER,
        "model": DOCUMENT_MODEL,
        "dimensions": EMBEDDING_DIMENSIONS,
        "embedding_version": EMBEDDING_VERSION,
        "prompt_version": PROMPT_VERSION,
        "chunk_count": CANONICAL_CHUNK_COUNT,
    }


def evaluate_case(case: BenchmarkCase) -> BenchmarkCaseResult:
    try:
        response = search(
            SearchRequest(
                query=case.query,
                snapshot_identifier=case.snapshot_identifier,
                search_mode=case.search_mode,
                top_k=case.top_k,
                evaluation_time=case.evaluation_time,
                document_type=case.document_type,
                language=case.language,
                source_kind=case.source_kind,
                rule_code=case.rule_code,
                rule_version=case.rule_version,
                include_scores=True,
            )
        )
    except Exception as exc:
        return BenchmarkCaseResult(
            case_code=case.case_code,
            category=case.category,
            profile=case.profile,
            passed=False,
            expected_document_code=case.expected_document_code,
            actual_top_document_code=None,
            expected_rank_limit=case.max_accepted_rank,
            actual_rank=None,
            requested_mode=case.search_mode,
            effective_mode=None,
            expected_document_version=case.expected_document_version,
            actual_document_version=None,
            expected_rule_version=case.expected_rule_version,
            actual_rule_version=None,
            heading=None,
            chunk_id=None,
            content_hash=None,
            semantic_score=None,
            full_text_score=None,
            hybrid_score=None,
            warnings=(),
            failure_reasons=(_safe_failure(exc),),
        )

    results = response.get("results", [])
    expected_result = next(
        (item for item in results if item.get("document_code") == case.expected_document_code),
        None,
    )
    actual_rank = results.index(expected_result) + 1 if expected_result else None
    failures = []
    if expected_result is None:
        failures.append("expected_document_not_found")
    elif actual_rank > case.max_accepted_rank:
        failures.append("expected_document_rank_exceeded")
    forbidden = {
        item.get("document_code")
        for item in results
        if item.get("document_code") in case.forbidden_document_codes
    }
    if forbidden:
        failures.append("forbidden_document_present:" + ",".join(sorted(forbidden)))
    effective_mode = response.get("effective_mode")
    if effective_mode != case.search_mode:
        failures.append("effective_mode_mismatch")
    if expected_result:
        if expected_result.get("document_version") != case.expected_document_version:
            failures.append("document_version_mismatch")
        if (
            case.expected_rule_version is not None
            and expected_result.get("rule_version") != case.expected_rule_version
        ):
            failures.append("rule_version_mismatch")
        if (
            case.require_heading_match
            and normalize_heading(case.expected_heading_contains)
            not in normalize_heading(expected_result.get("heading"))
        ):
            failures.append("heading_mismatch")
        if case.category == "exact_code" and not expected_result.get("exact_code_match"):
            failures.append("exact_code_match_false")
    warnings = tuple(response.get("warnings") or ())
    if case.profile == SEMANTIC_PROFILE and warnings:
        failures.append("semantic_warning_present")
    return BenchmarkCaseResult(
        case_code=case.case_code,
        category=case.category,
        profile=case.profile,
        passed=not failures,
        expected_document_code=case.expected_document_code,
        actual_top_document_code=results[0].get("document_code") if results else None,
        expected_rank_limit=case.max_accepted_rank,
        actual_rank=actual_rank,
        requested_mode=case.search_mode,
        effective_mode=effective_mode,
        expected_document_version=case.expected_document_version,
        actual_document_version=(
            expected_result.get("document_version") if expected_result else None
        ),
        expected_rule_version=case.expected_rule_version,
        actual_rule_version=expected_result.get("rule_version") if expected_result else None,
        heading=expected_result.get("heading") if expected_result else None,
        chunk_id=expected_result.get("chunk_id") if expected_result else None,
        content_hash=expected_result.get("content_hash") if expected_result else None,
        semantic_score=expected_result.get("semantic_score") if expected_result else None,
        full_text_score=expected_result.get("full_text_score") if expected_result else None,
        hybrid_score=expected_result.get("hybrid_score") if expected_result else None,
        warnings=warnings,
        failure_reasons=tuple(failures),
    )


def _metrics(results: Iterable[BenchmarkCaseResult], *, blocked_count=0):
    values = list(results)
    total = len(values) + blocked_count
    ranks = [result.actual_rank for result in values]
    passed = sum(result.passed for result in values)
    metrics = {
        "total": total,
        "evaluated": len(values),
        "blocked": blocked_count,
        "passed": passed,
        "failed": total - passed,
        "hit_at_1": sum(rank == 1 for rank in ranks) / total if total else 0.0,
        "hit_at_3": sum(rank is not None and rank <= 3 for rank in ranks) / total if total else 0.0,
        "mean_reciprocal_rank": (
            sum(1 / rank for rank in ranks if rank is not None) / total if total else 0.0
        ),
        "forbidden_document_violations": sum(
            any(
                reason.startswith("forbidden_document_present")
                for reason in result.failure_reasons
            )
            for result in values
        ),
        "fallback_count": sum(result.effective_mode == "full_text_fallback" for result in values),
    }
    return {
        key: round(value, 6) if isinstance(value, float) and math.isfinite(value) else value
        for key, value in metrics.items()
    }


def run_benchmark(cases: Iterable[BenchmarkCase]) -> dict[str, Any]:
    selected = tuple(cases)
    semantic_cases = tuple(case for case in selected if case.profile == SEMANTIC_PROFILE)
    deterministic_cases = tuple(case for case in selected if case.profile != SEMANTIC_PROFILE)
    results = [evaluate_case(case) for case in deterministic_cases]
    profile_errors = []
    semantic_metadata = None
    blocked = 0
    if semantic_cases:
        try:
            semantic_metadata = validate_semantic_prerequisites()
        except BenchmarkPrerequisiteError as exc:
            blocked = len(semantic_cases)
            profile_errors.append(
                {
                    "profile": SEMANTIC_PROFILE,
                    "code": "prerequisite_error",
                    "message": str(exc),
                    "blocked_case_codes": [case.case_code for case in semantic_cases],
                }
            )
        else:
            results.extend(evaluate_case(case) for case in semantic_cases)
    category_metrics = {}
    for category in sorted({case.category for case in selected}):
        category_results = [result for result in results if result.category == category]
        category_blocked = (
            sum(
                case.category == category and case.profile == SEMANTIC_PROFILE
                for case in semantic_cases
            )
            if blocked
            else 0
        )
        category_metrics[category] = _metrics(category_results, blocked_count=category_blocked)
    metrics = _metrics(results, blocked_count=blocked)
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "success": metrics["failed"] == 0 and not profile_errors,
        "selected_case_count": len(selected),
        "profiles": sorted({case.profile for case in selected}),
        "semantic_prerequisites": semantic_metadata,
        "metrics": metrics,
        "category_metrics": category_metrics,
        "profile_errors": profile_errors,
        "cases": [result.to_dict() for result in results],
    }
