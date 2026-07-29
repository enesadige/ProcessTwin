from django.http import JsonResponse

from apps.core.internal_api import internal_service_required


@internal_service_required
def internal_health(_request):
    return JsonResponse(
        {
            "status": "ok",
            "service": "internal-api",
        }
    )
