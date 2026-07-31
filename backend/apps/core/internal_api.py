import secrets
from functools import wraps
from uuid import uuid4

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from apps.core.correlation import is_valid_correlation_id

AUTHORIZATION_HEADER = "HTTP_AUTHORIZATION"
BEARER_PREFIX = "Bearer "
CORRELATION_ID_HEADER = "HTTP_X_CORRELATION_ID"
CORRELATION_ID_RESPONSE_HEADER = "X-Correlation-ID"


def internal_service_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        correlation_id_or_response = resolve_correlation_id(request)
        if isinstance(correlation_id_or_response, JsonResponse):
            return correlation_id_or_response
        correlation_id = correlation_id_or_response
        request.correlation_id = correlation_id

        if not is_authorized_internal_request(request):
            response = JsonResponse(
                {
                    "error": {
                        "code": "authentication_failed",
                        "message": "Internal service authentication failed.",
                        "details": {},
                    }
                },
                status=401,
            )
            response[CORRELATION_ID_RESPONSE_HEADER] = correlation_id
            return response

        response = view_func(request, *args, **kwargs)
        response[CORRELATION_ID_RESPONSE_HEADER] = correlation_id
        return response

    return csrf_exempt(wrapped)


def resolve_correlation_id(request):
    raw_correlation_id = request.META.get(CORRELATION_ID_HEADER)
    if raw_correlation_id is None or raw_correlation_id == "":
        return str(uuid4())
    if not is_valid_correlation_id(raw_correlation_id):
        return JsonResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Invalid correlation id.",
                    "details": {"header": "X-Correlation-ID"},
                }
            },
            status=400,
        )
    return raw_correlation_id


def is_authorized_internal_request(request) -> bool:
    expected_token = getattr(settings, "INTERNAL_API_SERVICE_TOKEN", "")
    if not expected_token:
        return False
    authorization = request.META.get(AUTHORIZATION_HEADER, "")
    if not authorization.startswith(BEARER_PREFIX):
        return False
    provided_token = authorization.removeprefix(BEARER_PREFIX)
    if not provided_token:
        return False
    return secrets.compare_digest(provided_token, expected_token)
