import json

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.rag.models import DocumentType, SourceKind
from apps.rag.services.search import MAX_TOP_K, SEARCH_MODES, SearchRequest


def parse_search_request(payload: dict) -> SearchRequest:
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    query = payload.get("query")
    snapshot_identifier = payload.get("snapshot_identifier")
    if not isinstance(query, str) or not isinstance(snapshot_identifier, str):
        raise ValidationError("query and snapshot_identifier are required strings.")
    mode = payload.get("search_mode", "hybrid")
    if mode not in SEARCH_MODES:
        raise ValidationError("search_mode is invalid.")
    top_k = payload.get("top_k", 5)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= MAX_TOP_K:
        raise ValidationError(f"top_k must be between 1 and {MAX_TOP_K}.")
    evaluation_time = payload.get("evaluation_time")
    parsed_time = None
    if evaluation_time not in (None, ""):
        if not isinstance(evaluation_time, str):
            raise ValidationError("evaluation_time must be an ISO 8601 datetime.")
        parsed_time = parse_datetime(evaluation_time)
        if parsed_time is None or timezone.is_naive(parsed_time):
            raise ValidationError("evaluation_time must be timezone-aware.")
    document_type = payload.get("document_type")
    if document_type and document_type not in DocumentType.values:
        raise ValidationError("document_type is invalid.")
    source_kind = payload.get("source_kind")
    if source_kind and source_kind not in SourceKind.values:
        raise ValidationError("source_kind is invalid.")
    language = payload.get("language")
    if language is not None and (not isinstance(language, str) or not language.strip()):
        raise ValidationError("language is invalid.")
    rule_code = payload.get("rule_code")
    rule_version = payload.get("rule_version")
    if rule_version is not None and (not isinstance(rule_version, int) or rule_version < 1):
        raise ValidationError("rule_version is invalid.")
    include_scores = payload.get("include_scores", True)
    if not isinstance(include_scores, bool):
        raise ValidationError("include_scores must be boolean.")
    embedding_provider = payload.get("embedding_provider")
    if embedding_provider is not None and embedding_provider not in {"ollama", "gemini"}:
        raise ValidationError("embedding_provider is invalid.")
    return SearchRequest(
        query=query,
        snapshot_identifier=snapshot_identifier,
        search_mode=mode,
        top_k=top_k,
        evaluation_time=parsed_time,
        document_type=document_type,
        language=language,
        source_kind=source_kind,
        rule_code=rule_code,
        rule_version=rule_version,
        include_scores=include_scores,
        embedding_provider=embedding_provider,
    )


def parse_json_body(request) -> dict:
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError) as exc:
        raise ValidationError("Request body must contain valid JSON.") from exc
    return payload
