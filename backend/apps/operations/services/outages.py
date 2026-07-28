from dataclasses import dataclass

from django.utils import timezone

from apps.operations.models import Outage


class OutageServiceError(Exception):
    """Base error for deterministic outage calculations."""


class OutageServiceInputError(OutageServiceError):
    """Raised when outage or evaluation time inputs are invalid."""


@dataclass(frozen=True)
class OutageDuration:
    seconds: int
    minutes: int
    is_ongoing: bool


class OutageService:
    def calculate_duration(
        self,
        *,
        outage: Outage,
        evaluation_time=None,
    ) -> OutageDuration:
        if outage is None:
            raise OutageServiceInputError("An Outage must be provided.")
        if not outage.pk:
            raise OutageServiceInputError("Outage must be a persisted Outage.")

        if outage.ended_at is None:
            if evaluation_time is None:
                raise OutageServiceInputError(
                    "evaluation_time is required for ongoing outages."
                )
            self._validate_evaluation_time(evaluation_time)
            if evaluation_time < outage.started_at:
                raise OutageServiceInputError(
                    "evaluation_time cannot be earlier than outage started_at."
                )
            return self._build_duration(
                seconds=int((evaluation_time - outage.started_at).total_seconds()),
                is_ongoing=True,
            )

        if outage.ended_at <= outage.started_at:
            raise OutageServiceInputError("outage ended_at must be later than started_at.")
        return self._build_duration(seconds=outage.duration_seconds, is_ongoing=False)

    def is_ongoing(self, outage: Outage) -> bool:
        if outage is None:
            raise OutageServiceInputError("An Outage must be provided.")
        return outage.ended_at is None

    def _validate_evaluation_time(self, evaluation_time) -> None:
        if timezone.is_naive(evaluation_time):
            raise OutageServiceInputError("evaluation_time must be timezone-aware.")

    def _build_duration(self, *, seconds: int, is_ongoing: bool) -> OutageDuration:
        if seconds < 0:
            raise OutageServiceInputError("Outage duration cannot be negative.")
        return OutageDuration(
            seconds=seconds,
            minutes=seconds // 60,
            is_ongoing=is_ongoing,
        )
