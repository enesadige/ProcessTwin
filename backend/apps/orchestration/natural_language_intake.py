"""Closed-world natural-language intake for the internal orchestration API."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from apps.customers.models import Subscription
from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice
from apps.operations.models import CausalEvent, Outage
from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.ollama import OllamaLLMProvider, OllamaLLMProviderError
from apps.orchestration.structured_query import (
    ClarificationReason,
    RequestedOutput,
    StructuredQuery,
    StructuredQueryIntent,
)

STRUCTURED_QUERY_PARSER_PROMPT_VERSION = "structured-query-parser-tr-v1"
DETERMINISTIC_STRUCTURED_QUERY_PARSER_VERSION = "deterministic-structured-query-tr-v1"
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_CAUSAL_CODE_RE = re.compile(r"\bCE-[A-Z0-9][A-Z0-9-]*\b", re.IGNORECASE)
_OUTAGE_CODE_RE = re.compile(r"\bOUT-[A-Z0-9][A-Z0-9-]*\b", re.IGNORECASE)
_SUBSCRIPTION_RE = re.compile(r"\bSUB-[A-Z0-9][A-Z0-9-]*\b", re.IGNORECASE)


class NaturalLanguageQueryParseError(Exception):
    """Safe parser failure that must not fall through to execution."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MissingField(StrEnum):
    OPERATIONAL_REFERENCE = "operational_reference"
    SCOPE_FILTER = "scope_filter"
    REQUESTED_OUTPUT = "requested_output"
    COMPENSATION_ANCHOR = "compensation_anchor"


class _ParserOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: StructuredQueryIntent
    requested_outputs: list[RequestedOutput] = Field(default_factory=list)
    causal_event_code: str | None = None
    outage_code: str | None = None
    subscription_reference: str | None = None
    decision_type: str | None = None
    location_city: str | None = None
    location_district: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    retrieval_query: str | None = None
    missing_fields: list[MissingField] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("date_start", "date_end")
    @classmethod
    def validate_calendar_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise ValueError("date must be YYYY-MM-DD") from exc


@dataclass(frozen=True)
class ParsedStructuredQuery:
    structured_query: StructuredQuery
    missing_fields: tuple[MissingField, ...]
    prompt_version: str = STRUCTURED_QUERY_PARSER_PROMPT_VERSION


def _fold(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


class DeterministicStructuredQueryParser:
    """Provider-free extraction of safe scope fields from a Turkish user query."""

    def parse(self, *, original_query: str, snapshot: DataSnapshot) -> ParsedStructuredQuery:
        if not isinstance(original_query, str) or not original_query.strip():
            raise NaturalLanguageQueryParseError("invalid_structured_query")
        text = original_query.strip()
        folded = _fold(text)
        causal_event_code = self._extract_code(_CAUSAL_CODE_RE, text)
        outage_code = self._extract_code(_OUTAGE_CODE_RE, text)
        subscription_reference = self._extract_code(_SUBSCRIPTION_RE, text)
        device_code = self._extract_device_code(snapshot, text)
        self._validate_references(
            snapshot,
            causal_event_code,
            outage_code,
            subscription_reference,
            device_code,
        )
        if device_code and causal_event_code is None and outage_code is None:
            causal_event_code = self._causal_event_for_device(snapshot, device_code)
        location, ambiguous_location = self._resolve_location(snapshot, folded)
        dates = _DATE_RE.findall(text)
        intent, requested_outputs = self._intent_and_outputs(folded)
        decision_type = self._decision_type(folded)
        missing = self._missing_fields(
            intent=intent,
            causal_event_code=causal_event_code,
            outage_code=outage_code,
            subscription_reference=subscription_reference,
            device_code=device_code,
            location=location,
            dates=dates,
            ambiguous_location=ambiguous_location,
            requested_outputs=requested_outputs,
        )
        reasons = {
            MissingField.OPERATIONAL_REFERENCE: ClarificationReason.MISSING_OPERATIONAL_ANCHOR,
            MissingField.SCOPE_FILTER: ClarificationReason.MISSING_SCOPE_FILTER,
            MissingField.REQUESTED_OUTPUT: ClarificationReason.MISSING_REQUESTED_OUTPUT,
            MissingField.COMPENSATION_ANCHOR: ClarificationReason.COMPENSATION_ANCHOR_REQUIRED,
        }
        query = StructuredQuery.model_validate(
            {
                "intent": intent,
                "requested_outputs": requested_outputs,
                "snapshot_identifier": snapshot.snapshot_key,
                "causal_event_code": causal_event_code,
                "outage_code": outage_code,
                "device_code": device_code,
                "subscription_reference": subscription_reference,
                "decision_type": decision_type,
                "location": location,
                "time_window": self._time_window(dates),
                "retrieval_query": text
                if intent == StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL
                else None,
                "clarification_required": bool(missing),
                "clarification_reasons": [reasons[item] for item in missing],
            }
        )
        return ParsedStructuredQuery(
            structured_query=query,
            missing_fields=tuple(missing),
            prompt_version=DETERMINISTIC_STRUCTURED_QUERY_PARSER_VERSION,
        )

    @staticmethod
    def _extract_code(pattern: re.Pattern[str], text: str) -> str | None:
        match = pattern.search(text)
        return match.group(0).upper() if match else None

    @staticmethod
    def _extract_device_code(snapshot: DataSnapshot, text: str) -> str | None:
        """Return one exact, canonical snapshot device code mentioned by the user."""
        from apps.network.models import NetworkDevice

        matches = [
            code
            for code in NetworkDevice.objects.filter(data_snapshot=snapshot)
            .order_by("code")
            .values_list("code", flat=True)
            if re.search(
                rf"(?<![A-Z0-9_-]){re.escape(code)}(?![A-Z0-9_-])",
                text,
                flags=re.IGNORECASE,
            )
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _causal_event_for_device(snapshot: DataSnapshot, device_code: str) -> str | None:
        """Resolve an unambiguous device-rooted event without inventing scope."""
        from apps.operations.models import CausalEvent, Outage

        events = list(
            CausalEvent.objects.filter(data_snapshot=snapshot, root_device__code=device_code)
            .order_by("event_code")
            .values_list("event_code", flat=True)[:2]
        )
        if len(events) == 1:
            return events[0]
        outages = list(
            Outage.objects.filter(
                data_snapshot=snapshot,
                source_device__code=device_code,
                causal_event__isnull=False,
            )
            .order_by("outage_code")
            .values_list("causal_event__event_code", flat=True)[:2]
        )
        return outages[0] if len(outages) == 1 else None

    @staticmethod
    def _validate_references(
        snapshot: DataSnapshot,
        causal_event_code: str | None,
        outage_code: str | None,
        subscription_reference: str | None,
        device_code: str | None,
    ) -> None:
        if (
            causal_event_code
            and not CausalEvent.objects.filter(
                data_snapshot=snapshot, event_code=causal_event_code
            ).exists()
        ):
            raise NaturalLanguageQueryParseError("reference_not_found")
        if (
            device_code
            and not NetworkDevice.objects.filter(data_snapshot=snapshot, code=device_code).exists()
        ):
            raise NaturalLanguageQueryParseError("reference_not_found")
        if (
            outage_code
            and not Outage.objects.filter(data_snapshot=snapshot, outage_code=outage_code).exists()
        ):
            raise NaturalLanguageQueryParseError("reference_not_found")
        if (
            subscription_reference
            and not Subscription.objects.filter(
                data_snapshot=snapshot, subscription_number=subscription_reference
            ).exists()
        ):
            raise NaturalLanguageQueryParseError("reference_not_found")

    @staticmethod
    def _resolve_location(
        snapshot: DataSnapshot, folded: str
    ) -> tuple[dict[str, str] | None, bool]:
        pairs = {
            (_fold(device.city.name), _fold(device.district.name)): (
                device.city.name,
                device.district.name,
            )
            for device in NetworkDevice.objects.filter(
                data_snapshot=snapshot, city__isnull=False, district__isnull=False
            ).select_related("city", "district")
        }
        district_matches = [
            value for (city, district), value in pairs.items() if district in folded
        ]
        city_matches = [value for (city, _district), value in pairs.items() if city in folded]
        matches = {(city, district) for city, district in district_matches + city_matches}
        if len(matches) > 1:
            return None, True
        if len(matches) == 1:
            city, district = matches.pop()
            return {"city": city, "district": district}, False
        return None, False

    @staticmethod
    def _intent_and_outputs(folded: str) -> tuple[StructuredQueryIntent, list[RequestedOutput]]:
        if any(term in folded for term in ("tazminat", "telafi", "uygunluk")):
            return StructuredQueryIntent.COMPENSATION_EVALUATION, [
                RequestedOutput.SUMMARY,
                RequestedOutput.ELIGIBILITY,
                RequestedOutput.EVIDENCE,
            ]
        if any(
            term in folded
            for term in ("hangi kural", "hangi kaynak", "source", "section", "citation")
        ):
            return StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL, [
                RequestedOutput.SUMMARY,
                RequestedOutput.DETAILS,
                RequestedOutput.EVIDENCE,
            ]
        if any(
            term in folded
            for term in ("yedek baglanti", "backup", "failover", "tam hizmet kesintisi")
        ):
            return StructuredQueryIntent.OUTAGE_IMPACT, [
                RequestedOutput.SUMMARY,
                RequestedOutput.DETAILS,
                RequestedOutput.IMPACT,
            ]
        if any(
            term in folded
            for term in ("kok neden", "ana sebep", "dying gasp", "device not active", "belirti mi")
        ):
            return StructuredQueryIntent.NETWORK_INVESTIGATION, [
                RequestedOutput.SUMMARY,
                RequestedOutput.ROOT_CAUSE,
                RequestedOutput.EVIDENCE,
            ]
        if any(
            term in folded
            for term in ("kesin olarak dogrulanmis", "kanit yetersiz", "gercekten etkilendi")
        ):
            return StructuredQueryIntent.OUTAGE_IMPACT, [
                RequestedOutput.SUMMARY,
                RequestedOutput.IMPACT,
                RequestedOutput.EVIDENCE,
            ]
        return StructuredQueryIntent.OUTAGE_IMPACT, [
            RequestedOutput.SUMMARY,
            RequestedOutput.DETAILS,
            RequestedOutput.IMPACT,
        ]

    @staticmethod
    def _decision_type(folded: str) -> str | None:
        if any(term in folded for term in ("tazminat", "telafi", "compensation")):
            return "compensation"
        if any(term in folded for term in ("uygunluk", "eligibility")):
            return "eligibility"
        return None

    @staticmethod
    def _missing_fields(**values: object) -> list[MissingField]:
        intent = values["intent"]
        anchors = bool(
            values["causal_event_code"] or values["outage_code"] or values["device_code"]
        )
        if (
            intent == StructuredQueryIntent.OUTAGE_IMPACT
            and values["location"] is not None
            and values["dates"]
        ):
            return []
        if intent == StructuredQueryIntent.OUTAGE_IMPACT and anchors:
            return []
        if intent == StructuredQueryIntent.NETWORK_INVESTIGATION and anchors:
            return []
        if intent == StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL and values["causal_event_code"]:
            return []
        if intent == StructuredQueryIntent.COMPENSATION_EVALUATION:
            missing = []
            if not values["causal_event_code"]:
                missing.append(MissingField.COMPENSATION_ANCHOR)
            if not values["subscription_reference"]:
                missing.append(MissingField.SCOPE_FILTER)
            return missing
        return [MissingField.SCOPE_FILTER] if values["ambiguous_location"] or not anchors else []

    @staticmethod
    def _time_window(dates: list[str]) -> dict[str, str] | None:
        if not dates:
            return None
        return {"from_time": f"{dates[0]}T00:00:00+00:00", "to_time": f"{dates[-1]}T23:59:59+00:00"}


class NaturalLanguageStructuredQueryParser:
    """Parse scope only; all facts remain in deterministic backend services."""

    def __init__(self, *, provider: LLMProvider | None = None) -> None:
        self._provider = provider or OllamaLLMProvider()

    def parse(self, *, original_query: str, snapshot: DataSnapshot) -> ParsedStructuredQuery:
        if not isinstance(original_query, str) or not original_query.strip():
            raise NaturalLanguageQueryParseError("invalid_structured_query")
        response = self._generate(original_query)
        candidate = self._parse_response(response)
        self._validate_not_invented(original_query, candidate)
        self._validate_snapshot_references(snapshot, candidate)
        try:
            query = self._to_structured_query(candidate, snapshot.snapshot_key)
        except ValidationError as exc:
            raise NaturalLanguageQueryParseError("invalid_structured_query") from exc
        return ParsedStructuredQuery(
            structured_query=query,
            missing_fields=tuple(
                sorted(set(candidate.missing_fields), key=lambda item: item.value)
            ),
        )

    def _generate(self, original_query: str) -> Mapping[str, object]:
        try:
            response = self._provider.generate(
                request={
                    "contents": self._prompt(original_query),
                    "format_schema": self._schema(),
                }
            )
        except OllamaLLMProviderError as exc:
            raise NaturalLanguageQueryParseError("query_parse_unavailable") from exc
        except Exception as exc:
            raise NaturalLanguageQueryParseError("query_parse_unavailable") from exc
        if (
            not isinstance(response, Mapping)
            or response.get("provider") != self._provider.provider_name
        ):
            raise NaturalLanguageQueryParseError("query_parse_unavailable")
        if response.get("model") != self._provider.model_name or not isinstance(
            response.get("content"), str
        ):
            raise NaturalLanguageQueryParseError("query_parse_unavailable")
        return response

    @staticmethod
    def _parse_response(response: Mapping[str, object]) -> _ParserOutput:
        try:
            return _ParserOutput.model_validate(json.loads(str(response["content"])))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            raise NaturalLanguageQueryParseError("invalid_structured_query") from exc

    @staticmethod
    def _prompt(original_query: str) -> str:
        return (
            "Turkce kullanici sorgusundan yalniz kapsam alanlarini cikar. Yeni olay, tarih, "
            "konum, abonelik veya karar uydurma. Belirsiz alanlari missing_fields'a koy. "
            "assumptions bos liste olmali. Tarihleri sadece kullanicinin yazdigi YYYY-MM-DD "
            "biçiminde ver. Intent eslemesi: kok neden=network_investigation; kesinti veya "
            "etki/failover=outage_impact; tazminat=compensation_evaluation; kural, kanit veya "
            "kaynak=rule_document_retrieval. requested_outputs yalniz kullanicinin istedigi "
            "sonuclari icermeli. Yalniz native schema nesnesini uret.\n"
            f"PROMPT_VERSION={STRUCTURED_QUERY_PARSER_PROMPT_VERSION}\n"
            f"USER_QUERY={original_query}"
        )

    @staticmethod
    def _schema() -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [item.value for item in StructuredQueryIntent],
                },
                "requested_outputs": {
                    "type": "array",
                    "items": {"type": "string", "enum": [item.value for item in RequestedOutput]},
                    "uniqueItems": True,
                },
                "causal_event_code": {"type": ["string", "null"]},
                "outage_code": {"type": ["string", "null"]},
                "subscription_reference": {"type": ["string", "null"]},
                "decision_type": {
                    "type": ["string", "null"],
                    "enum": ["eligibility", "compensation", None],
                },
                "location_city": {"type": ["string", "null"]},
                "location_district": {"type": ["string", "null"]},
                "date_start": {"type": ["string", "null"]},
                "date_end": {"type": ["string", "null"]},
                "retrieval_query": {"type": ["string", "null"]},
                "missing_fields": {
                    "type": "array",
                    "items": {"type": "string", "enum": [item.value for item in MissingField]},
                    "uniqueItems": True,
                },
                "assumptions": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            },
            "required": [
                "intent",
                "requested_outputs",
                "causal_event_code",
                "outage_code",
                "subscription_reference",
                "decision_type",
                "location_city",
                "location_district",
                "date_start",
                "date_end",
                "retrieval_query",
                "missing_fields",
                "assumptions",
            ],
            "additionalProperties": False,
        }

    @staticmethod
    def _validate_not_invented(original_query: str, candidate: _ParserOutput) -> None:
        folded = original_query.casefold()
        for value in (
            candidate.causal_event_code,
            candidate.outage_code,
            candidate.subscription_reference,
        ):
            if value and value.casefold() not in folded:
                raise NaturalLanguageQueryParseError("invalid_structured_query")
        for value in (candidate.location_city, candidate.location_district):
            if value and value.casefold() not in folded:
                raise NaturalLanguageQueryParseError("invalid_structured_query")
        supplied_dates = set(_DATE_RE.findall(original_query))
        if any(
            value and value not in supplied_dates
            for value in (candidate.date_start, candidate.date_end)
        ):
            raise NaturalLanguageQueryParseError("invalid_structured_query")
        if candidate.assumptions:
            raise NaturalLanguageQueryParseError("invalid_structured_query")

    @staticmethod
    def _validate_snapshot_references(snapshot: DataSnapshot, candidate: _ParserOutput) -> None:
        if (
            candidate.causal_event_code
            and not CausalEvent.objects.filter(
                data_snapshot=snapshot, event_code=candidate.causal_event_code
            ).exists()
        ):
            raise NaturalLanguageQueryParseError("reference_not_found")
        if (
            candidate.outage_code
            and not Outage.objects.filter(
                data_snapshot=snapshot, outage_code=candidate.outage_code
            ).exists()
        ):
            raise NaturalLanguageQueryParseError("reference_not_found")
        if (
            candidate.subscription_reference
            and not Subscription.objects.filter(
                data_snapshot=snapshot, subscription_number=candidate.subscription_reference
            ).exists()
        ):
            raise NaturalLanguageQueryParseError("reference_not_found")

    @staticmethod
    def _to_structured_query(candidate: _ParserOutput, snapshot_identifier: str) -> StructuredQuery:
        reasons = {
            MissingField.OPERATIONAL_REFERENCE: ClarificationReason.MISSING_OPERATIONAL_ANCHOR,
            MissingField.SCOPE_FILTER: ClarificationReason.MISSING_SCOPE_FILTER,
            MissingField.REQUESTED_OUTPUT: ClarificationReason.MISSING_REQUESTED_OUTPUT,
            MissingField.COMPENSATION_ANCHOR: ClarificationReason.COMPENSATION_ANCHOR_REQUIRED,
        }
        clarification_reasons = [reasons[field] for field in candidate.missing_fields]
        location = None
        if candidate.location_city or candidate.location_district:
            location = {"city": candidate.location_city, "district": candidate.location_district}
        time_window = None
        if candidate.date_start or candidate.date_end:
            time_window = {
                "from_time": (
                    datetime.fromisoformat(candidate.date_start).replace(tzinfo=UTC).isoformat()
                    if candidate.date_start
                    else None
                ),
                "to_time": (
                    datetime.fromisoformat(candidate.date_end).replace(tzinfo=UTC).isoformat()
                    if candidate.date_end
                    else None
                ),
            }
        return StructuredQuery.model_validate(
            {
                "intent": candidate.intent,
                "requested_outputs": candidate.requested_outputs,
                "snapshot_identifier": snapshot_identifier,
                "causal_event_code": candidate.causal_event_code,
                "outage_code": candidate.outage_code,
                "subscription_reference": candidate.subscription_reference,
                "decision_type": candidate.decision_type,
                "location": location,
                "time_window": time_window,
                "retrieval_query": candidate.retrieval_query,
                "clarification_required": bool(clarification_reasons),
                "clarification_reasons": clarification_reasons,
            }
        )
