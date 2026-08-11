from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.accounts.models import UserRole
from apps.core.internal_api import resolve_correlation_id
from apps.orchestration.facade import OrchestrationFacade


def get_orchestration_facade() -> OrchestrationFacade:
    return OrchestrationFacade()


@require_POST
def execute_authenticated_query(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": {"code": "authentication_required", "message": "Authentication required."}},
            status=401,
        )
    if request.user.role not in {UserRole.ANALYST, UserRole.ADMIN}:
        return JsonResponse(
            {"error": {"code": "permission_denied", "message": "Analysis access is not allowed."}},
            status=403,
        )

    correlation_id = resolve_correlation_id(request)
    if isinstance(correlation_id, JsonResponse):
        return correlation_id
    request.correlation_id = correlation_id
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse(
            {
                "status": "failed",
                "error": {"code": "validation_error", "message": "Request body is invalid."},
            },
            status=400,
        )
    outcome = get_orchestration_facade().execute(payload, request_id=correlation_id)
    return JsonResponse(outcome.envelope.to_payload(), status=outcome.http_status)
