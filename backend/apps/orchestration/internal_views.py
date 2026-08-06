"""Authenticated internal endpoint for synchronous query orchestration."""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.core.internal_api import internal_service_required
from apps.orchestration.facade import OrchestrationFacade


def get_orchestration_facade() -> OrchestrationFacade:
    return OrchestrationFacade()


@require_POST
@internal_service_required
def execute_query(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse(
            {
                "status": "failed",
                "replayed": False,
                "error": {"code": "validation_error", "message": "Request body is invalid."},
            },
            status=400,
        )
    outcome = get_orchestration_facade().execute(payload, request_id=request.correlation_id)
    return JsonResponse(outcome.envelope.to_payload(), status=outcome.http_status)
