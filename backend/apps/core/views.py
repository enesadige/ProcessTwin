from django.http import JsonResponse

from apps.core.choices import ResultStatus


def health(_request):
    return JsonResponse(
        {
            "status": ResultStatus.EXACT,
            "service": "backend",
        }
    )
