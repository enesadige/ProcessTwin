from django.http import JsonResponse

from apps.core.internal_api import internal_service_required
from apps.core.mcp_health import ProbeError, probe_descriptor, validate_timeout
from apps.core.mcp_registry import descriptor_payload, get_descriptor, get_descriptors


@internal_service_required
def internal_health(_request):
    return JsonResponse(
        {
            "status": "ok",
            "service": "internal-api",
        }
    )


@internal_service_required
def mcp_registry(_request):
    return JsonResponse(
        {
            "status": "ok",
            "services": [descriptor_payload(descriptor) for descriptor in get_descriptors()],
        }
    )


@internal_service_required
def mcp_health(request):
    service_key = request.GET.get("service")
    if service_key:
        descriptor = get_descriptor(service_key)
        if descriptor is None:
            return JsonResponse(
                {
                    "error": {
                        "code": "validation_error",
                        "message": "Unknown MCP service.",
                        "details": {"service": service_key},
                    }
                },
                status=400,
            )
        descriptors = (descriptor,)
    else:
        descriptors = get_descriptors()

    try:
        timeout_seconds = validate_timeout(request.GET.get("timeout_seconds"))
    except ProbeError as exc:
        return JsonResponse(
            {"error": {"code": exc.code, "message": exc.message, "details": {}}},
            status=400,
        )

    backend_base_url = f"{request.scheme}://{request.get_host()}"
    services = [
        probe_descriptor(
            descriptor,
            timeout_seconds,
            backend_base_url=backend_base_url,
        )
        for descriptor in descriptors
    ]
    return JsonResponse(
        {
            "status": "ok",
            "timeout_seconds": timeout_seconds,
            "services": services,
        }
    )
