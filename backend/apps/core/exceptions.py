from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.core.choices import ResultStatus


@dataclass
class ProcessTwinError(Exception):
    message: str
    code: str = "processtwin_error"
    status: ResultStatus = ResultStatus.FAILED
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    def to_response_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


class DomainValidationError(ProcessTwinError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            code="domain_validation_error",
            status=ResultStatus.FAILED,
            details=details or {},
        )


class InsufficientDataError(ProcessTwinError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            code="insufficient_data",
            status=ResultStatus.INSUFFICIENT_DATA,
            details=details or {},
        )


class ExternalServiceError(ProcessTwinError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            code="external_service_error",
            status=ResultStatus.FAILED,
            details=details or {},
        )
