import json
from collections import Counter
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.rag.benchmark_manifest import (
    BENCHMARK_CASES,
    BENCHMARK_VERSION,
    DETERMINISTIC_PROFILE,
    SEMANTIC_PROFILE,
    BenchmarkCase,
)
from apps.rag.corpus_manifest import MULTICITY_ALARMS, MULTICITY_RULES
from apps.rag.models import IndexRun
from apps.rag.services import benchmark as benchmark_service
from apps.rag.services.benchmark import (
    BenchmarkPrerequisiteError,
    evaluate_case,
    normalize_heading,
    run_benchmark,
    validate_semantic_prerequisites,
)


def _case(**overrides):
    values = {
        "case_code": "RAG-TEST-001",
        "category": "exact_code",
        "profile": DETERMINISTIC_PROFILE,
        "description": "Test case",
        "query": "DOC-001",
        "snapshot_identifier": "snapshot-1",
        "search_mode": "full_text",
        "top_k": 5,
        "evaluation_time": None,
        "document_type": None,
        "language": "tr",
        "source_kind": "synthetic",
        "rule_code": None,
        "rule_version": None,
        "expected_document_code": "DOC-001",
        "expected_document_version": 1,
        "expected_rule_version": None,
        "expected_heading_contains": "Koşullar",
        "require_heading_match": True,
        "max_accepted_rank": 1,
        "forbidden_document_codes": (),
        "tags": (),
    }
    values.update(overrides)
    return BenchmarkCase(**values)


def _search_response(*, expected_rank=1, effective_mode="full_text", warnings=None):
    results = [
        {
            "document_code": "OTHER-DOC",
            "document_version": 1,
            "rule_version": None,
            "heading": "Diğer",
            "chunk_id": 9,
            "content_hash": "a" * 64,
            "semantic_score": None,
            "full_text_score": 0.2,
            "hybrid_score": None,
            "exact_code_match": False,
        }
        for _ in range(expected_rank - 1)
    ]
    results.append(
        {
            "document_code": "DOC-001",
            "document_version": 1,
            "rule_version": None,
            "heading": "Koşullar ve İstisnalar",
            "chunk_id": 10,
            "content_hash": "b" * 64,
            "semantic_score": 0.8,
            "full_text_score": 0.7,
            "hybrid_score": 0.016,
            "exact_code_match": True,
        }
    )
    return {"effective_mode": effective_mode, "warnings": warnings or [], "results": results}


def test_manifest_has_versioned_immutable_sixteen_case_catalog():
    assert BENCHMARK_VERSION == "rag-benchmark-v1"
    assert isinstance(BENCHMARK_CASES, tuple)
    assert len(BENCHMARK_CASES) == 16
    assert len({case.case_code for case in BENCHMARK_CASES}) == 16
    assert Counter(case.category for case in BENCHMARK_CASES) == {
        "exact_code": 4,
        "historical_version": 2,
        "scope_and_filter": 4,
        "turkish_semantic": 6,
    }
    assert Counter(case.profile for case in BENCHMARK_CASES) == {
        DETERMINISTIC_PROFILE: 10,
        SEMANTIC_PROFILE: 6,
    }


def test_manifest_contract_and_canonical_codes_are_valid():
    exact_queries = {case.query for case in BENCHMARK_CASES if case.category == "exact_code"}
    assert "BB-FULL-OUTAGE-TIERED" in exact_queries & set(MULTICITY_RULES)
    assert "MR-UNKNOWN-MISSING-EVIDENCE" in exact_queries & set(MULTICITY_RULES)
    assert "BNG_UNREACHABLE" in exact_queries & set(MULTICITY_ALARMS)
    for case in BENCHMARK_CASES:
        assert case.snapshot_identifier
        assert case.expected_document_code
        assert 1 <= case.top_k <= 20
        assert 1 <= case.max_accepted_rank <= case.top_k
        assert case.search_mode in {"semantic", "full_text", "hybrid"}
        if case.evaluation_time:
            assert case.evaluation_time.utcoffset() is not None
        assert isinstance(case.require_heading_match, bool)
    assert all(
        case.search_mode == "full_text"
        for case in BENCHMARK_CASES
        if case.profile == DETERMINISTIC_PROFILE
    )
    assert Counter(
        case.search_mode for case in BENCHMARK_CASES if case.profile == SEMANTIC_PROFILE
    ) == {"semantic": 3, "hybrid": 3}


def test_evaluator_passes_expected_rank_and_exposes_no_chunk_text(monkeypatch):
    monkeypatch.setattr(benchmark_service, "search", lambda request: _search_response())
    result = evaluate_case(_case())

    assert result.passed is True
    assert result.actual_rank == 1
    assert result.heading == "Koşullar ve İstisnalar"
    assert "text" not in result.to_dict()


def test_optional_heading_policy_passes_correct_document_with_different_heading(monkeypatch):
    monkeypatch.setattr(benchmark_service, "search", lambda request: _search_response())

    result = evaluate_case(
        _case(expected_heading_contains="Başka Bölüm", require_heading_match=False)
    )

    assert result.passed is True


def test_required_heading_policy_rejects_different_heading(monkeypatch):
    monkeypatch.setattr(benchmark_service, "search", lambda request: _search_response())

    result = evaluate_case(
        _case(expected_heading_contains="Başka Bölüm", require_heading_match=True)
    )

    assert result.passed is False
    assert "heading_mismatch" in result.failure_reasons


def test_required_heading_policy_uses_normalized_substring(monkeypatch):
    response = _search_response()
    response["results"][-1]["heading"] = "  ## KOŞULLAR   ve İstisnalar  "
    monkeypatch.setattr(benchmark_service, "search", lambda request: response)

    result = evaluate_case(
        _case(expected_heading_contains="koşullar ve", require_heading_match=True)
    )

    assert result.passed is True


def test_required_heading_policy_selects_matching_section_rank(monkeypatch):
    response = _search_response()
    matching_section = {
        **response["results"][-1],
        "heading": "Koşullar",
        "chunk_id": 11,
        "semantic_score": 0.7,
    }
    response["results"][-1]["heading"] = "Genel Bakış"
    response["results"].append(matching_section)
    monkeypatch.setattr(benchmark_service, "search", lambda request: response)

    result = evaluate_case(_case(max_accepted_rank=2))

    assert result.passed is True
    assert result.actual_rank == 2
    assert result.heading == "Koşullar"
    assert result.chunk_id == 11


def test_required_heading_policy_enforces_matching_section_rank_limit(monkeypatch):
    response = _search_response()
    response["results"][-1]["heading"] = "Genel Bakış"
    response["results"].append(
        {
            **response["results"][-1],
            "heading": "Koşullar",
            "chunk_id": 11,
        }
    )
    monkeypatch.setattr(benchmark_service, "search", lambda request: response)

    result = evaluate_case(_case(max_accepted_rank=1))

    assert result.passed is False
    assert result.actual_rank == 2
    assert result.heading == "Koşullar"
    assert "expected_document_rank_exceeded" in result.failure_reasons


def test_matching_heading_on_wrong_document_does_not_pass(monkeypatch):
    response = _search_response()
    response["results"] = [
        {
            **response["results"][-1],
            "document_code": "OTHER-DOC",
            "heading": "Koşullar",
        }
    ]
    monkeypatch.setattr(benchmark_service, "search", lambda request: response)

    result = evaluate_case(_case())

    assert result.passed is False
    assert "expected_document_not_found" in result.failure_reasons


def test_heading_normalization_handles_unicode_whitespace_case_and_markdown():
    decomposed = "Bas\u0327lık   İhlalleri"

    assert normalize_heading("  ## Başlık İhlalleri  ") == normalize_heading(decomposed)
    assert normalize_heading("## RULE   POLICY") == normalize_heading("rule policy")
    assert normalize_heading("ÇĞİÖŞÜ") != "cgiOSu".casefold()


def test_three_native_heading_mismatches_remain_quality_gate_cases():
    cases = {
        case.case_code: case
        for case in BENCHMARK_CASES
        if "chunk_selection_quality_issue" in case.tags
    }

    assert set(cases) == {
        "RAG-SEM-FAILED-FAILOVER",
        "RAG-SEM-PACKET-LOSS-SLA",
        "RAG-SEM-DEGRADATION",
    }
    assert all(case.require_heading_match for case in cases.values())


@pytest.mark.parametrize(
    ("case", "response", "reason"),
    [
        (_case(), {"effective_mode": "full_text", "results": []}, "expected_document_not_found"),
        (
            _case(max_accepted_rank=1),
            _search_response(expected_rank=2),
            "expected_document_rank_exceeded",
        ),
        (
            _case(forbidden_document_codes=("OTHER-DOC",)),
            _search_response(expected_rank=2),
            "forbidden_document_present:OTHER-DOC",
        ),
        (
            _case(expected_document_version=2),
            _search_response(),
            "document_version_mismatch",
        ),
        (
            _case(expected_heading_contains="Bulunmayan"),
            _search_response(),
            "heading_mismatch",
        ),
        (
            _case(),
            _search_response(effective_mode="full_text_fallback"),
            "effective_mode_mismatch",
        ),
    ],
)
def test_evaluator_detects_contract_failures(monkeypatch, case, response, reason):
    monkeypatch.setattr(benchmark_service, "search", lambda request: response)
    result = evaluate_case(case)

    assert result.passed is False
    assert reason in result.failure_reasons


def test_evaluator_continues_after_case_exception_and_metrics_are_correct(monkeypatch):
    calls = 0

    def fake_search(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("/private/path token=secret SELECT *")
        return _search_response()

    monkeypatch.setattr(benchmark_service, "search", fake_search)
    report = run_benchmark((_case(case_code="FAIL"), _case(case_code="PASS")))

    assert report["success"] is False
    assert report["metrics"]["total"] == 2
    assert report["metrics"]["passed"] == 1
    assert report["metrics"]["hit_at_1"] == 0.5
    assert report["metrics"]["hit_at_3"] == 0.5
    assert report["metrics"]["mean_reciprocal_rank"] == 0.5
    serialized = json.dumps(report)
    assert "private/path" not in serialized
    assert "SELECT *" not in serialized
    assert "token=secret" not in serialized


def test_semantic_warning_and_fallback_fail_case(monkeypatch):
    warning = {"code": "provider_unavailable", "message": "fallback"}
    monkeypatch.setattr(
        benchmark_service,
        "search",
        lambda request: _search_response(
            effective_mode="full_text_fallback",
            warnings=[warning],
        ),
    )
    result = evaluate_case(
        _case(profile=SEMANTIC_PROFILE, search_mode="hybrid", max_accepted_rank=3)
    )

    assert result.passed is False
    assert "effective_mode_mismatch" in result.failure_reasons
    assert "semantic_warning_present" in result.failure_reasons


def test_semantic_prerequisite_rejects_mock_provider(settings):
    settings.RAG_EMBEDDING_PROVIDER = "mock"
    with pytest.raises(BenchmarkPrerequisiteError, match="production provider"):
        validate_semantic_prerequisites()


def test_semantic_prerequisite_accepts_canonical_gemini_metadata(settings, monkeypatch):
    class FakeChunks:
        def count(self):
            return 74

    class FakeRecords:
        def count(self):
            return 74

    settings.RAG_EMBEDDING_PROVIDER = "gemini"
    monkeypatch.setattr(
        benchmark_service.DocumentChunk.objects,
        "filter",
        lambda **kwargs: FakeChunks(),
    )
    monkeypatch.setattr(
        benchmark_service.DocumentChunkEmbedding.objects,
        "filter",
        lambda **kwargs: FakeRecords(),
    )

    metadata = validate_semantic_prerequisites()

    assert metadata["provider"] == "gemini"
    assert metadata["dimensions"] == 768
    assert metadata["chunk_count"] == 74


def test_semantic_prerequisite_is_reported_once_for_six_blocked_cases(monkeypatch):
    cases = tuple(
        _case(
            case_code=f"SEM-{index}",
            profile=SEMANTIC_PROFILE,
            category="turkish_semantic",
            search_mode="semantic",
        )
        for index in range(6)
    )
    monkeypatch.setattr(
        benchmark_service,
        "validate_semantic_prerequisites",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            BenchmarkPrerequisiteError("embedding prerequisite")
        ),
    )
    report = run_benchmark(cases)

    assert report["metrics"]["total"] == 6
    assert report["metrics"]["blocked"] == 6
    assert report["metrics"]["failed"] == 6
    assert len(report["profile_errors"]) == 1
    assert len(report["profile_errors"][0]["blocked_case_codes"]) == 6
    assert report["cases"] == []


def _successful_command_report():
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "success": True,
        "selected_case_count": 10,
        "profiles": [DETERMINISTIC_PROFILE],
        "semantic_prerequisites": None,
        "metrics": {
            "total": 10,
            "evaluated": 10,
            "blocked": 0,
            "passed": 10,
            "failed": 0,
            "hit_at_1": 1.0,
            "hit_at_3": 1.0,
            "mean_reciprocal_rank": 1.0,
            "forbidden_document_violations": 0,
            "fallback_count": 0,
        },
        "category_metrics": {},
        "profile_errors": [],
        "cases": [],
    }


def test_command_defaults_to_deterministic_and_outputs_json(monkeypatch):
    captured = {}

    def fake_run(cases):
        captured["cases"] = tuple(cases)
        return _successful_command_report()

    monkeypatch.setattr("apps.rag.management.commands.benchmark_rag.run_benchmark", fake_run)
    stdout = StringIO()
    call_command("benchmark_rag", "--format", "json", stdout=stdout)
    payload = json.loads(stdout.getvalue())

    assert payload["success"] is True
    assert len(captured["cases"]) == 10
    assert {case.profile for case in captured["cases"]} == {DETERMINISTIC_PROFILE}


def test_command_supports_case_and_category_filters(monkeypatch):
    captured = {}

    def fake_run(cases):
        captured["cases"] = tuple(cases)
        return _successful_command_report()

    monkeypatch.setattr("apps.rag.management.commands.benchmark_rag.run_benchmark", fake_run)
    case = BENCHMARK_CASES[0]
    call_command(
        "benchmark_rag",
        "--case-code",
        case.case_code,
        "--category",
        case.category,
        stdout=StringIO(),
    )
    assert [item.case_code for item in captured["cases"]] == [case.case_code]


def test_command_passes_controlled_embedding_provider(monkeypatch):
    captured = {}

    def fake_run(cases, *, embedding_provider=None):
        captured["provider"] = embedding_provider
        return _successful_command_report()

    monkeypatch.setattr("apps.rag.management.commands.benchmark_rag.run_benchmark", fake_run)
    call_command(
        "benchmark_rag",
        "--embedding-provider",
        "ollama",
        stdout=StringIO(),
    )

    assert captured["provider"] == "ollama"


def test_command_passes_allowlisted_embedding_profile(monkeypatch):
    captured = {}

    def fake_run(cases, *, embedding_provider=None):
        captured["provider"] = embedding_provider
        return _successful_command_report()

    monkeypatch.setattr("apps.rag.management.commands.benchmark_rag.run_benchmark", fake_run)
    call_command(
        "benchmark_rag",
        "--embedding-profile",
        "ollama-qwen3-0.6b",
        stdout=StringIO(),
    )

    assert captured["provider"] == "ollama-qwen3-0.6b"


@pytest.mark.parametrize(
    "arguments",
    [
        ("--profile", "unknown"),
        ("--format", "xml"),
        ("--case-code", "UNKNOWN"),
        ("--category", "unknown"),
    ],
)
def test_command_rejects_unknown_filters(arguments):
    with pytest.raises(CommandError):
        call_command("benchmark_rag", *arguments, stdout=StringIO())


def test_command_returns_nonzero_after_rendering_failed_report(monkeypatch):
    report = _successful_command_report()
    report["success"] = False
    report["metrics"]["passed"] = 9
    report["metrics"]["failed"] = 1
    monkeypatch.setattr(
        "apps.rag.management.commands.benchmark_rag.run_benchmark",
        lambda cases: report,
    )
    stdout = StringIO()
    with pytest.raises(CommandError, match="RAG benchmark failed"):
        call_command("benchmark_rag", "--format", "json", stdout=stdout)
    assert json.loads(stdout.getvalue())["success"] is False


@pytest.mark.django_db
def test_command_does_not_create_index_run(monkeypatch):
    monkeypatch.setattr(
        "apps.rag.management.commands.benchmark_rag.run_benchmark",
        lambda cases: _successful_command_report(),
    )
    before = IndexRun.objects.count()

    call_command("benchmark_rag", stdout=StringIO())

    assert IndexRun.objects.count() == before


@pytest.mark.django_db
def test_semantic_command_rejects_mock_provider_without_writes(settings):
    settings.RAG_EMBEDDING_PROVIDER = "mock"
    before = IndexRun.objects.count()
    stdout = StringIO()

    with pytest.raises(CommandError, match="RAG benchmark failed"):
        call_command("benchmark_rag", "--profile", "semantic", "--format", "json", stdout=stdout)

    payload = json.loads(stdout.getvalue())
    assert payload["success"] is False
    assert payload["metrics"]["blocked"] == 6
    assert len(payload["profile_errors"]) == 1
    assert IndexRun.objects.count() == before
