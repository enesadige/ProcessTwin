from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.core.internal_api import internal_service_required
from apps.rag.internal_serializers import parse_json_body, parse_search_request
from apps.rag.providers import EmbeddingProviderError
from apps.rag.services.search import (
    EmbeddingIntegrityError,
    EmbeddingPrerequisiteError,
    search,
)


def _error(code, message, status, details=None):
    return JsonResponse(
        {"error": {"code": code, "message": message, "details": details or {}}},
        status=status,
    )


def _ok(request, data):
    return JsonResponse(
        {
            "data": data,
            "warnings": data.pop("warnings", []),
            "evidence": [],
            "metadata": {"correlation_id": getattr(request, "correlation_id", None)},
        }
    )


@require_POST
@internal_service_required
def search_documents(request):
    try:
        search_request = parse_search_request(parse_json_body(request))
        data = search(search_request)
    except ValidationError as exc:
        return _error("validation_error", str(exc), 400)
    except EmbeddingProviderError as exc:
        return _error("provider_unavailable", str(exc), 503)
    except EmbeddingPrerequisiteError:
        return _error(
            "embedding_prerequisite_error",
            "The selected embedding set is incomplete for this scope.",
            409,
        )
    except EmbeddingIntegrityError:
        return _error(
            "embedding_integrity_error",
            "The selected embedding set failed integrity validation.",
            409,
        )
    except LookupError as exc:
        return _error("not_found", str(exc), 404)
    except Exception:
        return _error("internal_error", "RAG search failed.", 500)
    return _ok(request, data)
