"""Closed-world natural-language intake for the internal orchestration API."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from apps.customers.models import Subscription
from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDevice
from apps.operations.models import Alarm, CausalEvent, Outage
from apps.orchestration.providers.base import LLMProvider, LLMProviderError
from apps.orchestration.providers.ollama import OllamaLLMProvider, OllamaLLMProviderError
from apps.orchestration.structured_query import (
    AnalyticsSpecification,
    ClarificationReason,
    RequestedOutput,
    SemanticDimension,
    StructuredQuery,
    StructuredQueryIntent,
)

STRUCTURED_QUERY_PARSER_PROMPT_VERSION = "structured-query-parser-tr-v1"
DETERMINISTIC_STRUCTURED_QUERY_PARSER_VERSION = "deterministic-structured-query-tr-v1"
SEMANTIC_DECOMPOSITION_PROMPT_VERSION = "semantic-decomposition-tr-v1"
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_TURKISH_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)\s+(\d{4})\b",
    re.IGNORECASE,
)
_TURKISH_MONTHS = {
    "ocak": 1,
    "şubat": 2,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "agustos": 8,
    "eylül": 9,
    "eylul": 9,
    "ekim": 10,
    "kasım": 11,
    "kasim": 11,
    "aralık": 12,
    "aralik": 12,
}
_CAUSAL_CODE_RE = re.compile(r"\bCE-[A-Z0-9][A-Z0-9-]*\b", re.IGNORECASE)
_ALARM_CODE_RE = re.compile(r"\bALM-[A-Z0-9][A-Z0-9-]*\b", re.IGNORECASE)
_OUTAGE_CODE_RE = re.compile(r"\bOUT-[A-Z0-9][A-Z0-9-]*\b", re.IGNORECASE)
_SUBSCRIPTION_RE = re.compile(r"\bSUB-[A-Z0-9][A-Z0-9-]*\b", re.IGNORECASE)
_CUSTOMER_IMPACT_REQUEST_TERMS = (
    "kaç müşteri",
    "kac musteri",
    "kaç abonelik",
    "kac abonelik",
    "müşteri etkisi",
    "musteri etkisi",
    "abonelik etkisi",
    "müşteri sayısı",
    "musteri sayisi",
    "abonelik sayısı",
    "abonelik sayisi",
    "müşteriler gerçekten etkilendi",
    "musteriler gercekten etkilendi",
    "customer impact",
    "subscription impact",
)


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


@dataclass(frozen=True)
class SemanticDecompositionResult:
    structured_query: StructuredQuery
    accepted: bool
    failure_code: str | None = None


class LLMSemanticDecomposer:
    """Select allowlisted answer dimensions without extracting trusted anchors."""

    _DIMENSION_OUTPUTS: dict[SemanticDimension, tuple[RequestedOutput, ...]] = {
        SemanticDimension.ALARM_CORRELATION: (RequestedOutput.CORRELATION,),
        SemanticDimension.SUMMARY: (RequestedOutput.SUMMARY,),
        SemanticDimension.OUTAGE_CLASSIFICATION: (RequestedOutput.DETAILS,),
        SemanticDimension.VERIFIED_CUSTOMER_IMPACT: (RequestedOutput.IMPACT,),
        SemanticDimension.VERIFIED_SUBSCRIPTION_IMPACT: (RequestedOutput.IMPACT,),
        SemanticDimension.POTENTIAL_SCOPE: (RequestedOutput.IMPACT,),
        SemanticDimension.FAILOVER_STATUS: (RequestedOutput.DETAILS, RequestedOutput.IMPACT),
        SemanticDimension.FAILOVER_PROTECTION: (RequestedOutput.IMPACT,),
        SemanticDimension.ROOT_RESOURCE: (RequestedOutput.ROOT_CAUSE,),
        SemanticDimension.PHYSICAL_ROOT_CAUSE: (RequestedOutput.ROOT_CAUSE,),
        # Impact evidence gaps are answered by the customer-impact contract;
        # they must not make a location aggregate require rule-document evidence.
        SemanticDimension.EVIDENCE_GAP: (RequestedOutput.IMPACT,),
        SemanticDimension.COMPENSATION_RESULT: (RequestedOutput.ELIGIBILITY,),
        SemanticDimension.COMPENSATION_REASON: (RequestedOutput.EVIDENCE,),
        SemanticDimension.RULE_VERSION: (RequestedOutput.EVIDENCE,),
        SemanticDimension.DECISION_EVIDENCE: (RequestedOutput.EVIDENCE,),
        SemanticDimension.RAG_EVIDENCE: (RequestedOutput.EVIDENCE,),
        SemanticDimension.SOURCE_VERSION_SECTION: (RequestedOutput.EVIDENCE,),
        SemanticDimension.MANUAL_REVIEW_REASON: (RequestedOutput.EVIDENCE,),
    }

    def __init__(self, provider: LLMProvider):
        self._provider = provider

    def merge(
        self, *, original_query: str, deterministic_query: StructuredQuery
    ) -> SemanticDecompositionResult:
        if deterministic_query.intent == StructuredQueryIntent.OPERATIONAL_ANALYTICS:
            # The typed analytics contract already owns metric, filters, grouping,
            # comparison and ranking. The current allowlist cannot add a trusted
            # analytics output, so a Phase 2 model call is pure latency.
            return SemanticDecompositionResult(deterministic_query, accepted=False)
        try:
            response = self._provider.generate(
                request={
                    "contents": self._prompt(original_query, deterministic_query),
                    "format_schema": self._schema(),
                }
            )
            if (
                not isinstance(response, Mapping)
                or response.get("provider") != self._provider.provider_name
                or response.get("model") != self._provider.model_name
                or not isinstance(response.get("content"), str)
            ):
                raise ValueError("provider_response_invalid")
            candidate = _SemanticDecomposition.model_validate(json.loads(response["content"]))
            dimensions = sorted(set(candidate.dimensions), key=lambda value: value.value)
            requested = set(deterministic_query.requested_outputs)
            allowed_outputs = self._allowed_outputs(deterministic_query)
            dimensions = [
                dimension
                for dimension in dimensions
                if set(self._DIMENSION_OUTPUTS[dimension]) & allowed_outputs
            ]
            for dimension in dimensions:
                requested.update(
                    output
                    for output in self._DIMENSION_OUTPUTS[dimension]
                    if output in allowed_outputs
                )
            merged = deterministic_query.model_copy(
                update={
                    "requested_outputs": sorted(requested, key=lambda value: value.value),
                    "semantic_dimensions": dimensions,
                    "semantic_decomposition_status": "accepted",
                    "semantic_decomposition_failure": None,
                }
            )
            return SemanticDecompositionResult(merged, accepted=True)
        except Exception as exc:
            code = self._failure_code(exc)
            fallback = deterministic_query.model_copy(
                update={
                    "semantic_decomposition_status": "fallback",
                    "semantic_decomposition_failure": code,
                }
            )
            return SemanticDecompositionResult(fallback, accepted=False, failure_code=code)

    @staticmethod
    def _allowed_outputs(query: StructuredQuery) -> frozenset[RequestedOutput]:
        """Keep probabilistic dimensions inside the deterministic intent contract."""
        if query.intent == StructuredQueryIntent.OPERATIONAL_ANALYTICS:
            # The typed analytics specification, not LLM dimensions, fixes scope.
            return frozenset(query.requested_outputs)
        if query.intent == StructuredQueryIntent.ALARM_CORRELATION:
            return frozenset(
                {
                    RequestedOutput.SUMMARY,
                    RequestedOutput.CORRELATION,
                    RequestedOutput.EVIDENCE,
                }
            )
        if query.intent == StructuredQueryIntent.NETWORK_INVESTIGATION:
            return frozenset(
                {
                    RequestedOutput.SUMMARY,
                    RequestedOutput.DETAILS,
                    RequestedOutput.IMPACT,
                    RequestedOutput.ROOT_CAUSE,
                    RequestedOutput.EVIDENCE,
                }
            )
        if query.intent == StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL:
            return frozenset(
                {
                    RequestedOutput.SUMMARY,
                    RequestedOutput.DETAILS,
                    RequestedOutput.EVIDENCE,
                }
            )
        if query.intent == StructuredQueryIntent.COMPENSATION_EVALUATION:
            return frozenset(
                {
                    RequestedOutput.SUMMARY,
                    RequestedOutput.ELIGIBILITY,
                    RequestedOutput.EVIDENCE,
                }
            )
        return frozenset(RequestedOutput)

    @staticmethod
    def _failure_code(exc: Exception) -> str:
        if isinstance(exc, LLMProviderError):
            return f"provider_call_failed_{exc.code}"
        if isinstance(exc, json.JSONDecodeError):
            return "malformed_schema"
        if isinstance(exc, ValidationError):
            return "invalid_dimension"
        return str(exc) if str(exc) in {"provider_response_invalid"} else "provider_unavailable"

    @staticmethod
    def _schema() -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "dimensions": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [item.value for item in SemanticDimension],
                    },
                    "uniqueItems": True,
                    "minItems": 1,
                }
            },
            "required": ["dimensions"],
            "additionalProperties": False,
        }

    @staticmethod
    def _prompt(original_query: str, deterministic_query: StructuredQuery) -> str:
        return (
            "Yalnız kullanıcının istediği allowlist answer dimension değerlerini seç. "
            "Tool, MCP, SQL, ID, tarih, konum, RuleVersion veya DecisionEvidence üretme. "
            "Deterministik requested_outputs zaten güvenilirdir; yalnız açıkça veya "
            "anlamca istenen ek boyutları ekle. Native schema dışında metin üretme.\n"
            f"PROMPT_VERSION={SEMANTIC_DECOMPOSITION_PROMPT_VERSION}\n"
            "DETERMINISTIC_OUTPUTS="
            f"{json.dumps([item.value for item in deterministic_query.requested_outputs])}\n"
            f"USER_QUERY={original_query}"
        )


class _SemanticDecomposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: list[SemanticDimension] = Field(min_length=1, max_length=17)

    @field_validator("dimensions")
    @classmethod
    def normalize_dimensions(cls, value: list[SemanticDimension]) -> list[SemanticDimension]:
        return sorted(set(value), key=lambda item: item.value)


def _fold(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


def query_requests_customer_impact(folded_query: str) -> bool:
    """Detect explicit customer/subscription impact intent, independent of LLM labels."""
    return any(term in folded_query for term in _CUSTOMER_IMPACT_REQUEST_TERMS)


class DeterministicStructuredQueryParser:
    """Provider-free extraction of safe scope fields from a Turkish user query."""

    def parse(self, *, original_query: str, snapshot: DataSnapshot) -> ParsedStructuredQuery:
        if not isinstance(original_query, str) or not original_query.strip():
            raise NaturalLanguageQueryParseError("invalid_structured_query")
        text = original_query.strip()
        folded = _fold(text)
        analytics_specs = self._analytics_specs(folded, snapshot)
        analytics = analytics_specs[0] if analytics_specs else None
        causal_event_codes = self._extract_codes(_CAUSAL_CODE_RE, text)
        if not causal_event_codes:
            causal_event_codes = self._causal_events_for_alarm_codes(
                snapshot=snapshot,
                alarm_codes=self._extract_codes(_ALARM_CODE_RE, text),
            )
        causal_event_code = causal_event_codes[0] if causal_event_codes else None
        comparison_causal_event_code = (
            causal_event_codes[1] if len(causal_event_codes) > 1 else None
        )
        outage_code = self._extract_code(_OUTAGE_CODE_RE, text)
        subscription_reference = self._extract_code(_SUBSCRIPTION_RE, text)
        device_code = self._extract_device_code(snapshot, text)
        if (
            analytics is not None
            and analytics.metric == "compensation_amount"
            and analytics.group_by is None
            and (causal_event_code or outage_code)
            and not any(
                term in folded
                for term in (
                    "sırala",
                    "sirala",
                    "en çok",
                    "en cok",
                    "en yüksek",
                    "en yuksek",
                    "ortalama",
                    "trend",
                    "karşılaştır",
                    "karsilastir",
                    "aylara göre",
                    "aylara gore",
                )
            )
        ):
            # An exact outage/event compensation request asks for that decision,
            # even when the natural wording includes "toplam tutar". Dataset-wide
            # aggregation requires an explicit grouping/ranking/trend signal.
            analytics = None
            analytics_specs = []
        self._validate_references(
            snapshot,
            causal_event_code,
            comparison_causal_event_code,
            outage_code,
            subscription_reference,
            device_code,
        )
        dates = self._extract_dates(text)
        if device_code and causal_event_code is None and outage_code is None:
            outage_code = self._outage_for_device(snapshot, device_code, dates=dates)
        location, ambiguous_location = self._resolve_location(snapshot, folded)
        analytics_locations = (
            self._resolve_analytics_locations(snapshot, folded) if analytics else []
        )
        intent, requested_outputs = self._intent_and_outputs(folded)
        if comparison_causal_event_code and any(
            term in folded
            for term in (
                "korelasyon",
                "ilişki",
                "ilisk",
                "nedensel",
                "neden-sonuç",
                "neden sonuc",
                "causal",
                "zincirin yönü",
                "zincirin yonu",
            )
        ):
            intent = StructuredQueryIntent.ALARM_CORRELATION
            requested_outputs = [
                RequestedOutput.SUMMARY,
                RequestedOutput.CORRELATION,
                RequestedOutput.EVIDENCE,
            ]
        if (
            intent == StructuredQueryIntent.ALARM_CORRELATION
            and causal_event_code
            and comparison_causal_event_code is None
            and any(
                term in folded
                for term in ("içindeki alarm", "icindeki alarm", "aynı olay", "ayni olay")
            )
        ):
            # A single event's own alarm roles are causal evidence, not a
            # cross-incident correlation search.
            intent = StructuredQueryIntent.NETWORK_INVESTIGATION
            requested_outputs = [
                RequestedOutput.SUMMARY,
                RequestedOutput.DETAILS,
                RequestedOutput.ROOT_CAUSE,
                RequestedOutput.EVIDENCE,
            ]
        if analytics:
            intent, requested_outputs = (
                StructuredQueryIntent.OPERATIONAL_ANALYTICS,
                [RequestedOutput.SUMMARY, RequestedOutput.ANALYTICS],
            )
        correlation_window_minutes, correlation_direction = self._correlation_window(folded)
        correlation_other_region_only = any(
            term in folded
            for term in ("başka bölge", "baska bolge", "farklı bölge", "farkli bolge")
        )
        if intent != StructuredQueryIntent.ALARM_CORRELATION:
            comparison_causal_event_code = None
            correlation_window_minutes = None
            correlation_direction = "both"
            correlation_other_region_only = False
        if (
            causal_event_code
            and not outage_code
            and intent
            in {
                StructuredQueryIntent.OUTAGE_IMPACT,
                StructuredQueryIntent.COMPENSATION_EVALUATION,
            }
        ):
            outage_code = self._outage_for_event(snapshot, causal_event_code, dates=dates)
            if outage_code:
                causal_event_code = None
        decision_type = self._decision_type(folded)
        analytics_time_window = (
            self._analytics_time_window(text, dates, snapshot=snapshot) if analytics else None
        )
        unresolved_location = (
            analytics and self._location_requested(folded) and not analytics_locations
        )
        missing = (
            [MissingField.SCOPE_FILTER]
            if analytics and self._analytics_comparison_requires_period(
                folded, analytics, analytics_time_window
            )
            else []
            if analytics
            else self._missing_fields(
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
        )
        if unresolved_location:
            missing = [*missing, MissingField.SCOPE_FILTER]
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
                "analytics": analytics.model_dump() if analytics else None,
                "analytics_specs": [item.model_dump() for item in analytics_specs],
                "analytics_locations": analytics_locations,
                "customer_impact_requested": query_requests_customer_impact(folded),
                "snapshot_identifier": snapshot.snapshot_key,
                "causal_event_code": causal_event_code,
                "comparison_causal_event_code": comparison_causal_event_code,
                "correlation_window_minutes": correlation_window_minutes,
                "correlation_direction": correlation_direction,
                "correlation_other_region_only": correlation_other_region_only,
                "outage_code": outage_code,
                "device_code": device_code,
                "subscription_reference": subscription_reference,
                "decision_type": decision_type,
                "location": location,
                "time_window": analytics_time_window if analytics else self._time_window(dates),
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

    @classmethod
    def clarification_candidates(
        cls, *, original_query: str, snapshot: DataSnapshot
    ) -> tuple[str, ...]:
        """Return public device candidates for a genuinely broad location query."""
        folded = _fold(original_query)
        city_names = {
            device.city.name
            for device in NetworkDevice.objects.filter(data_snapshot=snapshot).select_related(
                "city"
            )
            if _fold(device.city.name) in folded
        }
        candidates: set[str] = set()
        for device in NetworkDevice.objects.filter(
            data_snapshot=snapshot, city__name__in=city_names
        ).order_by("code"):
            if cls._outage_for_device(snapshot, device.code, dates=[]):
                candidates.add(device.code)
        return tuple(sorted(candidates))

    @staticmethod
    def _extract_code(pattern: re.Pattern[str], text: str) -> str | None:
        match = pattern.search(text)
        return match.group(0).upper() if match else None

    @staticmethod
    def _extract_codes(pattern: re.Pattern[str], text: str) -> list[str]:
        return list(dict.fromkeys(match.group(0).upper() for match in pattern.finditer(text)))

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
    def _outage_for_device(
        snapshot: DataSnapshot, device_code: str, *, dates: list[str]
    ) -> str | None:
        """Resolve a unique operational outage through the resource graph.

        Direct source/root relations outrank supporting resource relations and
        topology metadata. When a device has repeated equally direct historical
        outages, choose the uniquely most recent record instead of depending on
        insertion order; an explicit date still narrows the candidate set first.
        """
        from django.db.models import Q

        from apps.operations.models import Outage

        direct = (
            Q(source_device__code=device_code)
            | Q(incident__primary_device__code=device_code)
            | Q(causal_event__root_device__code=device_code)
        )
        resource_graph = (
            Q(causal_event__root_network_port__device__code=device_code)
            | Q(causal_event__root_line_connection__port__device__code=device_code)
            | Q(causal_event__root_access_segment__serving_device__code=device_code)
            | Q(causal_event__root_failure_domain__device_memberships__device__code=device_code)
        )
        topology_metadata = Q(causal_event__metadata__topology_scope__device=device_code)
        outages_query = Outage.objects.filter(data_snapshot=snapshot).filter(
            direct | resource_graph | topology_metadata
        )
        if dates:
            outage_dates = [date.fromisoformat(item) for item in dates]
            outages_query = outages_query.filter(
                started_at__date__gte=min(outage_dates), started_at__date__lte=max(outage_dates)
            )
        candidates = list(
            outages_query.distinct().values(
                "outage_code",
                "source_device__code",
                "incident__primary_device__code",
                "causal_event__root_device__code",
                "causal_event__root_network_port__device__code",
                "causal_event__root_line_connection__port__device__code",
                "causal_event__root_access_segment__serving_device__code",
                "causal_event__metadata",
                "metadata",
                "started_at",
            )
        )
        ranked: list[tuple[int, object, str]] = []
        for candidate in candidates:
            if candidate["metadata"].get("ground_truth_reconciled"):
                score = 120
            elif any(
                candidate[field] == device_code
                for field in (
                    "source_device__code",
                    "incident__primary_device__code",
                    "causal_event__root_device__code",
                )
            ):
                score = 100
            elif any(
                candidate[field] == device_code
                for field in (
                    "causal_event__root_network_port__device__code",
                    "causal_event__root_line_connection__port__device__code",
                    "causal_event__root_access_segment__serving_device__code",
                )
            ):
                score = 80
            else:
                score = 70
            ranked.append((score, candidate["started_at"], candidate["outage_code"]))
        if not ranked:
            return None
        highest = max(score for score, _started_at, _code in ranked)
        candidates = [
            (started_at, code) for score, started_at, code in ranked if score == highest
        ]
        latest = max(started_at for started_at, _code in candidates)
        winners = sorted(code for started_at, code in candidates if started_at == latest)
        return winners[0] if len(winners) == 1 else None

    @staticmethod
    def _outage_for_event(
        snapshot: DataSnapshot, causal_event_code: str, *, dates: list[str]
    ) -> str | None:
        queryset = Outage.objects.filter(
            data_snapshot=snapshot, causal_event__event_code=causal_event_code
        )
        if dates:
            parsed = [date.fromisoformat(item) for item in dates]
            queryset = queryset.filter(
                started_at__date__gte=min(parsed), started_at__date__lte=max(parsed)
            )
        codes = list(queryset.order_by("outage_code").values_list("outage_code", flat=True))
        return codes[0] if len(codes) == 1 else None

    @staticmethod
    def _extract_dates(text: str) -> list[str]:
        dates = list(_DATE_RE.findall(text))
        for day, month, year in _TURKISH_DATE_RE.findall(text):
            try:
                dates.append(
                    date(int(year), _TURKISH_MONTHS[month.casefold()], int(day)).isoformat()
                )
            except (KeyError, ValueError):
                raise NaturalLanguageQueryParseError("invalid_structured_query") from None
        return sorted(set(dates))

    @staticmethod
    def _causal_events_for_alarm_codes(
        *, snapshot: DataSnapshot, alarm_codes: list[str]
    ) -> list[str]:
        """Resolve explicit alarm references through their persisted causal events."""
        if not alarm_codes:
            return []
        alarms = {
            alarm.alarm_id.upper(): alarm
            for alarm in Alarm.objects.filter(
                data_snapshot=snapshot,
                alarm_id__in=alarm_codes,
                causal_event__isnull=False,
            ).select_related("causal_event")
        }
        if len(alarms) != len(alarm_codes):
            raise NaturalLanguageQueryParseError("reference_not_found")
        return [alarms[alarm_code].causal_event.event_code for alarm_code in alarm_codes]

    @staticmethod
    def _validate_references(
        snapshot: DataSnapshot,
        causal_event_code: str | None,
        comparison_causal_event_code: str | None,
        outage_code: str | None,
        subscription_reference: str | None,
        device_code: str | None,
    ) -> None:
        for event_code in (causal_event_code, comparison_causal_event_code):
            if (
                event_code
                and not CausalEvent.objects.filter(
                    data_snapshot=snapshot, event_code=event_code
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
        district_matches = {
            value for (_city, district), value in pairs.items() if district in folded
        }
        if len(district_matches) > 1:
            return None, True
        if len(district_matches) == 1:
            city, district = district_matches.pop()
            return {"city": city, "district": district}, False
        city_matches = {
            value[0] for (city, _district), value in pairs.items() if city in folded
        }
        if len(city_matches) > 1:
            return None, True
        if len(city_matches) == 1:
            return {"city": city_matches.pop()}, False
        return None, False

    @staticmethod
    def _intent_and_outputs(folded: str) -> tuple[StructuredQueryIntent, list[RequestedOutput]]:
        if any(
            term in folded
            for term in (
                "korelasyon",
                "ilişkili mi",
                "iliskili mi",
                "ilişki var mı",
                "iliski var mi",
                "iliski var mı",
                "alarm ilişkisi",
                "alarm iliskisi",
                "karşılaştır",
                "karsilastir",
                "başka bölgede başlayan alarm",
                "baska bolgede baslayan alarm",
            )
        ):
            return StructuredQueryIntent.ALARM_CORRELATION, [
                RequestedOutput.SUMMARY,
                RequestedOutput.CORRELATION,
                RequestedOutput.EVIDENCE,
            ]
        if any(
            term in folded
            for term in (
                "hangi kural",
                "hangi kaynak",
                "dokümana göre",
                "dokumana gore",
                "kaynak ve bölüm",
                "kaynak ve bolum",
                "source",
                "section",
                "citation",
            )
        ):
            return StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL, [
                RequestedOutput.SUMMARY,
                RequestedOutput.DETAILS,
                RequestedOutput.EVIDENCE,
            ]
        impact_requested = any(
            term in folded
            for term in (
                "kaç müşteri",
                "kaç abonelik",
                "kac musteri",
                "kac abonelik",
                "musteri etkisi",
                "abonelik etkisi",
                "müşteri etkisi",
                "abonelik",
                "etkilendi",
                "etkiyi",
                "dogrulanmis etki",
                "potansiyel kapsam",
                "tam kesinti",
                "kısmi kesinti",
                "failover",
                "yedek",
                "ana bağlantı",
            )
        )
        compensation_requested = any(term in folded for term in ("tazminat", "telafi", "uygunluk"))
        eligibility_requested = any(
            term in folded
            for term in (
                "uygun",
                "uygunluk",
                "sonucu",
                "karar",
                "hesaplanan",
            )
        )
        root_requested = any(
            term in folded
            for term in (
                "kok neden",
                "ana sebep",
                "neden",
                "dying gasp",
                "device not active",
                "belirti mi",
                "shared-risk",
                "shared risk",
                "manuel inceleme",
            )
        )
        if impact_requested:
            outputs = [RequestedOutput.SUMMARY, RequestedOutput.DETAILS, RequestedOutput.IMPACT]
            if root_requested:
                outputs.append(RequestedOutput.ROOT_CAUSE)
            if compensation_requested or eligibility_requested:
                outputs.append(RequestedOutput.EVIDENCE)
                if eligibility_requested:
                    outputs.append(RequestedOutput.ELIGIBILITY)
            return StructuredQueryIntent.OUTAGE_IMPACT, sorted(
                set(outputs), key=lambda item: item.value
            )
        if compensation_requested:
            return StructuredQueryIntent.COMPENSATION_EVALUATION, [
                RequestedOutput.SUMMARY,
                RequestedOutput.ELIGIBILITY,
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
        if root_requested:
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
    def _analytics_spec(folded: str, snapshot: DataSnapshot) -> AnalyticsSpecification | None:
        analytic_terms = (
            "sırala",
            "sirala",
            "en çok",
            "en cok",
            "en fazla",
            "en az",
            "en yüksek",
            "en yuksek",
            "en düşük",
            "en dusuk",
            "toplam",
            "ortalama",
            "trend",
            "artmış",
            "artmis",
            "azalmış",
            "azalmis",
            "aylara göre",
            "haftalara göre",
            "karşılaştır",
            "karsilastir",
            "karsılastır",
            "göster",
            "goster",
            "ilk ",
            "son ",
            "kaç kesinti",
            "kac kesinti",
            "kaç olay",
            "kac olay",
            "kaç alarm",
            "kac alarm",
        )
        if not any(term in folded for term in analytic_terms):
            return None
        metric_terms = (
            (
                "potential_subscriptions",
                ("potansiyel kapsam", "potansiyel abonelik", "potansiyel abone"),
            ),
            ("affected_customers", ("müşteri", "musteri")),
            ("affected_subscriptions", ("abonelik", "abone")),
            ("compensation_amount", ("tazminat", "telafi tutarı", "telafi tutari")),
            (
                "failed_failover_count",
                ("failed failover", "başarısız failover", "basarisiz failover"),
            ),
            ("full_outage_count", ("tam hizmet kesintisi", "full outage", "tam kesinti")),
            (
                "alarm_count",
                (
                    "alarm sayısı", "alarm sayisi", "alarm sayılarını", "alarm sayilarini",
                    "kac alarm", "alarm olustu", "alarm oluştu",
                ),
            ),
            (
                "outage_count",
                (
                    "kesinti sayısı",
                    "kesinti sayisi",
                    "kesinti sayılarını",
                    "kesinti sayilarini",
                    "kaç kesinti",
                    "kac kesinti",
                ),
            ),
            (
                "event_count",
                (
                    "olay sayısı",
                    "olay sayisi",
                    "olay sayılarını",
                    "olay sayilarini",
                    "kaç olay",
                    "kac olay",
                ),
            ),
        )
        metric = next(
            (key for key, terms in metric_terms if any(term in folded for term in terms)), None
        )
        if metric is None:
            return None
        count_only_metrics = {
            "outage_count",
            "event_count",
            "alarm_count",
            "failed_failover_count",
            "full_outage_count",
        }
        aggregation = (
            "sum"
            if metric
            in {
                "affected_customers",
                "affected_subscriptions",
                "potential_subscriptions",
                "compensation_amount",
            }
            else "count"
        )
        if "ortalama" in folded:
            aggregation = "average"
        if "maksimum" in folded:
            aggregation = "max"
        if "minimum" in folded:
            aggregation = "min"
        # "En yüksek/düşük" expresses ranking direction for event counts;
        # it must not turn a count-only metric into an invalid max/min request.
        if metric in count_only_metrics:
            aggregation = "count"
        group_by = None
        # A location mention narrows the result; it becomes a grouping only
        # when the user explicitly requests a breakdown or ranking by it.
        groups = (
            (
                "root_alarm_type",
                (
                    "alarm tipi",
                    "alarm tiplerine",
                    "alarm türü",
                    "alarm türlerine",
                    "alarm turu",
                    "alarm turlerine",
                    "alarm tipine göre",
                    "alarm türüne göre",
                ),
            ),
            (
                "city",
                (
                    "şehirleri",
                    "sehirleri",
                    "şehri sırala",
                    "sehri sırala",
                    "sehri sirala",
                    "şehirlere göre",
                    "sehirlere gore",
                    "şehir bazında",
                    "sehir bazinda",
                    "her şehir",
                    "her sehir",
                    "hangi şehir",
                    "hangi sehir",
                    "şehir hangisi",
                    "sehir hangisi",
                ),
            ),
            (
                "district",
                (
                    "ilçeleri",
                    "ilceleri",
                    "ilçelere göre",
                    "ilcelere gore",
                    "ilçe bazında",
                    "ilce bazinda",
                    "her ilçe",
                    "her ilce",
                    "hangi ilçe",
                    "hangi ilce",
                ),
            ),
            ("event", ("listele", "listesi")),
            (
                "time_bucket",
                (
                    "aylara göre",
                    "aylarına göre",
                    "aylarina göre",
                    "haftalara göre",
                    "günlere göre",
                    "gunlere göre",
                ),
            ),
        )
        group_by = next(
            (key for key, terms in groups if any(term in folded for term in terms)), None
        )
        if group_by is None and "aylar" in folded and "gore" in folded:
            group_by = "time_bucket"
        explicit_event_group = any(
            term in folded
            for term in (
                "olayları sırala",
                "olaylari sirala",
                "olaylara göre",
                "olaylara gore",
                "olay bazında",
                "olay bazinda",
                "her olay",
            )
        ) or bool(re.search(r"\b(?:ilk|top|son)\s+\d{1,3}\b[^.?!]*\bolay", folded))
        if group_by == "event" and "toplam" in folded and not explicit_event_group:
            group_by = None
        month_mentions = re.findall(
            r"\b(" + "|".join(_TURKISH_MONTHS) + r")\s+\d{4}\b", folded
        )
        named_months = re.findall(r"\b(" + "|".join(_TURKISH_MONTHS) + r")\b", folded)
        comparison = (
            (len(month_mentions) > 1 or len(set(named_months)) > 1)
            and any(
                term in folded
                for term in (
                    "karşılaştır",
                    "karsilastir",
                    "karsılastır",
                    "degisim",
                    "değişim",
                    "degisen",
                    "değişen",
                )
            )
        )
        if comparison and group_by == "event" and not explicit_event_group:
            group_by = None
        if comparison and group_by is None:
            group_by = "time_bucket"
        grain = (
            "month"
            if "aylara göre" in folded or len(month_mentions) > 1 or len(set(named_months)) > 1
            else "week"
            if "haftalara göre" in folded
            else "day"
            if group_by == "time_bucket"
            else None
        )
        limit_match = re.search(r"\b(?:ilk|top|en çok|en cok)\s*(\d{1,3})\b", folded)
        exhaustive_ranking = any(
            term in folded
            for term in (
                "sırala",
                "sirala",
                "her şehir",
                "her sehir",
                "tüm şehir",
                "tum sehir",
                "şehir bazında",
                "sehir bazinda",
                "en yüksekten en düşüğe",
                "en yuksekten en dusuge",
            )
        )
        limit = (
            int(limit_match.group(1))
            if limit_match
            else (
                1
                if not exhaustive_ranking
                and any(
                    term in folded
                    for term in (
                        "en çok",
                        "en cok",
                        "en fazla",
                        "en az",
                        "en düşük",
                        "en dusuk",
                        "en yüksek",
                        "en yuksek",
                    )
                )
                else None
            )
        )
        return AnalyticsSpecification(
            metric=metric,
            aggregation=aggregation,
            group_by=group_by,
            time_grain=grain,
            comparison=comparison,
            limit=limit,
            direction="asc"
            if any(term in folded for term in ("en az", "en düşük", "en dusuk"))
            else "desc",
            failed_failover=True
            if "failover" in folded
            and any(term in folded for term in ("başarısız", "basarisiz", "failed"))
            else None,
            full_outage=True
            if "tam hizmet kesintisi" in folded or "full outage" in folded
            else None,
            root_alarm_type=DeterministicStructuredQueryParser._exact_snapshot_value(
                folded,
                Alarm.objects.filter(data_snapshot=snapshot).values_list(
                    "alarm_type__code", flat=True
                ),
            ),
            event_type=DeterministicStructuredQueryParser._exact_snapshot_value(
                folded,
                CausalEvent.objects.filter(data_snapshot=snapshot).values_list(
                    "event_type", flat=True
                ),
            ),
            device_type=DeterministicStructuredQueryParser._exact_snapshot_value(
                folded,
                NetworkDevice.objects.filter(data_snapshot=snapshot).values_list(
                    "device_type", flat=True
                ),
            ),
        )

    @staticmethod
    def _analytics_specs(folded: str, snapshot: DataSnapshot) -> list[AnalyticsSpecification]:
        """Preserve every requested metric while sharing one parsed scope."""
        primary = DeterministicStructuredQueryParser._analytics_spec(folded, snapshot)
        if primary is None:
            return []
        metric_terms = (
            ("outage_count", ("kesinti say", "kac kesinti")),
            ("alarm_count", ("alarm say", "kac alarm", "alarm olustu")),
            ("affected_customers", ("musteri",)),
            ("affected_subscriptions", ("abonelik", "abone")),
            ("full_outage_count", ("tam hizmet kesintisi say", "tam kesinti say")),
        )
        metrics = [
            metric for metric, terms in metric_terms if any(term in folded for term in terms)
        ]
        if not metrics:
            metrics = [primary.metric]
        if primary.metric == "potential_subscriptions":
            metrics = [primary.metric]
        specs: list[AnalyticsSpecification] = []
        for metric in metrics:
            # "tam hizmet kesintisi sayısı" is a metric, not a filter on all
            # other requested metrics in the same sentence.
            full_outage = (
                primary.full_outage
                if metric not in {"full_outage_count", "outage_count", "alarm_count"}
                else None
            )
            specs.append(
                primary.model_copy(
                    update={
                        "metric": metric,
                        "aggregation": (
                            "sum"
                            if metric in {"affected_customers", "affected_subscriptions"}
                            else "count"
                        ),
                        "full_outage": full_outage,
                    }
                )
            )
        return specs

    @staticmethod
    def _resolve_analytics_locations(snapshot: DataSnapshot, folded: str) -> list[dict[str, str]]:
        """Return all explicit known cities/districts, never silently widen scope."""
        pairs = {
            (_fold(device.city.name), _fold(device.district.name)): (
                device.city.name,
                device.district.name,
            )
            for device in NetworkDevice.objects.filter(
                data_snapshot=snapshot, city__isnull=False, district__isnull=False
            ).select_related("city", "district")
        }
        found: list[dict[str, str]] = []
        for city, district in sorted(set(pairs.values())):
            if _fold(district) in folded:
                found.append({"city": city, "district": district})
        for city in sorted({city for city, _district in pairs.values()}):
            if _fold(city) in folded and not any(item["city"] == city for item in found):
                found.append({"city": city})
        return found

    @staticmethod
    def _location_requested(folded: str) -> bool:
        return any(term in folded for term in ("ilcesinde", "ilçesinde", "sehrinde", "şehrinde"))

    @staticmethod
    def _exact_snapshot_value(folded: str, values) -> str | None:
        """Resolve only an exact current-snapshot analytic filter, never a model guess."""
        matches = sorted(
            {
                str(value)
                for value in values
                if value
                and re.search(
                    rf"(?<![a-z0-9_-]){re.escape(_fold(str(value)))}(?![a-z0-9_-])", folded
                )
            }
        )
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _analytics_time_window(
        text: str,
        dates: list[str],
        *,
        snapshot: DataSnapshot,
    ) -> dict[str, str] | None:
        window = DeterministicStructuredQueryParser._time_window(dates)
        if window:
            return window
        matches = re.findall(r"\b(" + "|".join(_TURKISH_MONTHS) + r")\s+(\d{4})\b", _fold(text))
        # Turkish commonly supplies one year after a pair: "Haziran ve Temmuz
        # 2026". Apply that explicit year to each named month.
        named_with_shared_year = re.search(
            r"\b(" + "|".join(_TURKISH_MONTHS) + r")\s*(?:ve|ile|-)\s*("
            + "|".join(_TURKISH_MONTHS) + r")\s+(\d{4})\b",
            _fold(text),
        )
        if named_with_shared_year:
            matches = [
                (named_with_shared_year.group(1), named_with_shared_year.group(3)),
                (named_with_shared_year.group(2), named_with_shared_year.group(3)),
            ]
        if matches:
            months = sorted((int(year), _TURKISH_MONTHS[month]) for month, year in matches)
        else:
            mentioned = sorted(
                {
                    _TURKISH_MONTHS[month]
                    for month in re.findall(
                        r"\b(" + "|".join(_TURKISH_MONTHS) + r")\b", _fold(text)
                    )
                }
            )
            years = sorted(
                {
                    value
                    for value in CausalEvent.objects.filter(data_snapshot=snapshot).values_list(
                        "started_at__year", flat=True
                    )
                    if value is not None
                }
            )
            if not mentioned or len(years) != 1:
                return None
            months = [(years[0], month) for month in mentioned]
        first_year, first_month = months[0]
        last_year, last_month = months[-1]
        start = date(first_year, first_month, 1)
        next_month = date(
            last_year + (last_month == 12), 1 if last_month == 12 else last_month + 1, 1
        )
        end = next_month - timedelta(days=1)
        return {
            "from_time": f"{start.isoformat()}T00:00:00+00:00",
            "to_time": f"{end.isoformat()}T23:59:59+00:00",
        }

    @staticmethod
    def _analytics_comparison_requires_period(
        folded: str,
        analytics: AnalyticsSpecification,
        time_window: dict[str, str] | None,
    ) -> bool:
        """Comparison without a grouping or period has no deterministic baseline."""
        comparison_requested = any(
            term in folded for term in ("karşılaştır", "karsilastir", "karsılastır")
        )
        return comparison_requested and analytics.group_by is None and time_window is None

    @staticmethod
    def _decision_type(folded: str) -> str | None:
        if any(term in folded for term in ("tazminat", "telafi", "compensation")):
            return "compensation"
        if any(term in folded for term in ("manuel inceleme", "hangi kararı")):
            return "compensation"
        if any(term in folded for term in ("uygunluk", "eligibility")):
            return "eligibility"
        return None

    @staticmethod
    def _missing_fields(**values: object) -> list[MissingField]:
        intent = values["intent"]
        anchors = bool(values["causal_event_code"] or values["outage_code"])
        if intent == StructuredQueryIntent.ALARM_CORRELATION:
            return [] if values["causal_event_code"] else [MissingField.OPERATIONAL_REFERENCE]
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
        if intent == StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL:
            return []
        if intent == StructuredQueryIntent.COMPENSATION_EVALUATION:
            missing = []
            if not (values["causal_event_code"] or values["outage_code"] or values["device_code"]):
                missing.append(MissingField.COMPENSATION_ANCHOR)
            return missing
        if values["device_code"] and anchors:
            return []
        return [MissingField.SCOPE_FILTER] if values["ambiguous_location"] or not anchors else []

    @staticmethod
    def _time_window(dates: list[str]) -> dict[str, str] | None:
        if not dates:
            return None
        return {"from_time": f"{dates[0]}T00:00:00+00:00", "to_time": f"{dates[-1]}T23:59:59+00:00"}

    @staticmethod
    def _correlation_window(folded: str) -> tuple[int, str]:
        match = re.search(r"\b(\d{1,2})\s*saat\b", folded)
        if "bir saat" in folded:
            minutes = 60
        elif match:
            minutes = min(int(match.group(1)) * 60, 24 * 60)
        else:
            minutes = 60
        if "önce" in folded or "once" in folded:
            return minutes, "before"
        if "sonra" in folded:
            return minutes, "after"
        return minutes, "both"


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
