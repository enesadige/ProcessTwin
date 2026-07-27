from __future__ import annotations

from typing import Any

from rest_framework import status as http_status
from rest_framework.response import Response

from apps.core.choices import ResultStatus
from apps.core.exceptions import ProcessTwinError


def build_api_payload(
    data: Any = None,
    *,
    result_status: ResultStatus = ResultStatus.EXACT,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": result_status,
        "data": data,
        "meta": meta or {},
    }


def api_response(
    data: Any = None,
    *,
    result_status: ResultStatus = ResultStatus.EXACT,
    meta: dict[str, Any] | None = None,
    status_code: int = http_status.HTTP_200_OK,
) -> Response:
    return Response(
        build_api_payload(data=data, result_status=result_status, meta=meta),
        status=status_code,
    )


def error_response(
    error: ProcessTwinError,
    *,
    status_code: int = http_status.HTTP_400_BAD_REQUEST,
) -> Response:
    return Response(error.to_response_payload(), status=status_code)
