"""Deterministic answerability classification before provider-backed orchestration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from apps.customers.models import Subscription
from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice
from apps.operations.models import Alarm, CausalEvent


class AnswerabilityStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DATA_UNAVAILABLE = "data_unavailable"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNKNOWN_IDENTIFIER = "unknown_identifier"


@dataclass(frozen=True)
class PreflightAnswerability:
    status: AnswerabilityStatus
    response_text: str
    identifiers: tuple[str, ...] = ()


_PUBLIC_IDENTIFIER_RE = re.compile(r"\b(?:CE|ALM|AGG|SUB)-[\w-]+\b", re.I)
_FORECAST_TERMS = (
    "tahmin",
    "öngörü",
    "ongoru",
    "gelecek ay",
    "gelecek hafta",
    "next month",
    "forecast",
    "prediction",
)
_REMEDIATION_TERMS = (
    "hangi komut",
    "komutları çalıştır",
    "komutlari calistir",
    "cli komut",
    "runbook",
    "remediation",
    "arızasını düzelt",
    "arizasini duzelt",
    "nasıl düzelt",
    "nasil duzelt",
    "hangi parça",
    "hangi parca",
    "parçanın değiştiril",
    "parcanin degistiril",
    "teknisyen",
    "saha müdahale",
    "saha mudahale",
    "müdahale prosedür",
    "mudahale prosedur",
    "tam prosedür",
    "tam prosedur",
)


def classify_unsupported_capability(query: str) -> PreflightAnswerability | None:
    """Classify requests outside deterministic operational-analysis capabilities."""
    folded = query.casefold()
    probability_forecast = (
        any(term in folded for term in ("olasılı", "olasil", "probability"))
        and any(
            term in folded
            for term in (
                "yüzde",
                "yuzde",
                "%",
                "hesapla",
                "tekrar",
                "önümüzdeki",
                "onumuzdeki",
                "olacak",
            )
        )
    )
    if (
        any(term in folded for term in (*_FORECAST_TERMS, *_REMEDIATION_TERMS))
        or probability_forecast
    ):
        return PreflightAnswerability(
            status=AnswerabilityStatus.UNSUPPORTED_CAPABILITY,
            response_text="Bu sorgu mevcut analiz kapsamı tarafından desteklenmiyor.",
        )
    return None


def unknown_identifier_answer(query: str) -> PreflightAnswerability:
    identifiers = tuple(
        dict.fromkeys(match.group(0).upper() for match in _PUBLIC_IDENTIFIER_RE.finditer(query))
    )
    if len(identifiers) == 1:
        response_text = f"{identifiers[0]} için doğrulanmış bir kayıt bulunamadı."
    elif identifiers:
        response_text = (
            "Belirtilen referanslar için doğrulanmış kayıt bulunamadı: "
            + ", ".join(identifiers)
            + "."
        )
    else:
        response_text = "Bu istek için doğrulanmış bir operasyon kaydı bulunamadı."
    return PreflightAnswerability(
        status=AnswerabilityStatus.UNKNOWN_IDENTIFIER,
        response_text=response_text,
        identifiers=identifiers,
    )


def unresolved_identifiers(*, query: str, snapshot: DataSnapshot) -> tuple[str, ...]:
    """Return only explicit public identifiers absent from this snapshot.

    The query text is never treated as evidence.  This check exists solely to
    prevent a missing exact reference from falling through to a nearby record.
    """
    identifiers = tuple(
        dict.fromkeys(match.group(0).upper() for match in _PUBLIC_IDENTIFIER_RE.finditer(query))
    )
    unresolved: list[str] = []
    for identifier in identifiers:
        prefix = identifier.split("-", 1)[0]
        exists = {
            "CE": CausalEvent.objects.filter(
                data_snapshot=snapshot, event_code=identifier
            ).exists(),
            "ALM": Alarm.objects.filter(data_snapshot=snapshot, alarm_id=identifier).exists(),
            "AGG": NetworkDevice.objects.filter(data_snapshot=snapshot, code=identifier).exists(),
            "SUB": Subscription.objects.filter(
                data_snapshot=snapshot, subscription_number=identifier
            ).exists(),
        }[prefix]
        if not exists:
            unresolved.append(identifier)
    return tuple(unresolved)


def unresolved_identifier_answer(identifiers: tuple[str, ...]) -> PreflightAnswerability:
    if len(identifiers) == 1:
        response_text = f"{identifiers[0]} için doğrulanmış bir kayıt bulunamadı."
    else:
        response_text = (
            "Belirtilen referanslar için doğrulanmış kayıt bulunamadı: "
            + ", ".join(identifiers)
            + "."
        )
    return PreflightAnswerability(
        status=AnswerabilityStatus.UNKNOWN_IDENTIFIER,
        response_text=response_text,
        identifiers=identifiers,
    )


def classify_completed_answerability(
    *, final_result: dict[str, object] | None, requested_outputs: list[str]
) -> dict[str, object]:
    """Summarize existing deterministic evidence without changing it."""
    result = final_result or {}
    missing_outputs: list[str] = []
    causal = result.get("causal_summary")
    if isinstance(causal, dict) and "root_cause" in requested_outputs:
        if "root_cause_unverified" in causal.get("root_cause_reason_codes", []):
            missing_outputs.append("physical_root_cause")
    impact = result.get("impact_summary")
    if isinstance(impact, dict) and "impact" in requested_outputs:
        if impact.get("missing_evidence_categories"):
            missing_outputs.append("customer_impact")
    compensation = result.get("compensation_summary")
    if isinstance(compensation, dict) and "compensation_amount" in requested_outputs:
        if compensation.get("total_amount") is None:
            missing_outputs.append("compensation_amount")
    correlation = result.get("cross_incident_correlation_summary")
    if isinstance(correlation, dict) and "correlation" in requested_outputs:
        if correlation.get("correlation_status") == "insufficient_evidence":
            missing_outputs.append("correlation")
    if missing_outputs:
        return {
            "status": AnswerabilityStatus.PARTIALLY_VERIFIED.value,
            "missing_unverified_outputs": missing_outputs,
            "verified_outputs": [item for item in requested_outputs if item not in missing_outputs],
        }
    return {
        "status": AnswerabilityStatus.VERIFIED.value,
        "missing_unverified_outputs": [],
        "verified_outputs": requested_outputs,
    }
