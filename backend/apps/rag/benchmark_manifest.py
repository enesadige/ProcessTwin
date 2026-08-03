from dataclasses import dataclass
from datetime import datetime

from apps.rag.corpus_manifest import MALTEPE_SNAPSHOT_KEY, MULTICITY_SNAPSHOT_KEY

BENCHMARK_VERSION = "rag-benchmark-v1"
DETERMINISTIC_PROFILE = "deterministic"
SEMANTIC_PROFILE = "semantic"


@dataclass(frozen=True)
class BenchmarkCase:
    case_code: str
    category: str
    profile: str
    description: str
    query: str
    snapshot_identifier: str
    search_mode: str
    top_k: int
    evaluation_time: datetime | None
    document_type: str | None
    language: str | None
    source_kind: str | None
    rule_code: str | None
    rule_version: int | None
    expected_document_code: str
    expected_document_version: int
    expected_rule_version: int | None
    expected_heading_contains: str | None
    max_accepted_rank: int
    forbidden_document_codes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


def _case(
    case_code,
    category,
    profile,
    description,
    query,
    snapshot_identifier,
    expected_document_code,
    *,
    search_mode="full_text",
    top_k=5,
    evaluation_time=None,
    document_type=None,
    language="tr",
    source_kind="synthetic",
    rule_code=None,
    rule_version=None,
    expected_document_version=1,
    expected_rule_version=None,
    expected_heading_contains=None,
    max_accepted_rank=1,
    forbidden_document_codes=(),
    tags=(),
):
    return BenchmarkCase(
        case_code=case_code,
        category=category,
        profile=profile,
        description=description,
        query=query,
        snapshot_identifier=snapshot_identifier,
        search_mode=search_mode,
        top_k=top_k,
        evaluation_time=evaluation_time,
        document_type=document_type,
        language=language,
        source_kind=source_kind,
        rule_code=rule_code,
        rule_version=rule_version,
        expected_document_code=expected_document_code,
        expected_document_version=expected_document_version,
        expected_rule_version=expected_rule_version,
        expected_heading_contains=expected_heading_contains,
        max_accepted_rank=max_accepted_rank,
        forbidden_document_codes=tuple(forbidden_document_codes),
        tags=tuple(tags),
    )


BENCHMARK_CASES = (
    _case(
        "RAG-EXACT-DOC-BROADBAND",
        "exact_code",
        DETERMINISTIC_PROFILE,
        "SourceDocument koduyla broadband politika kaynağını bulur.",
        "SYN-COMP-2026-BROADBAND",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-COMP-2026-BROADBAND",
        expected_heading_contains="Broadband Telafi",
        tags=("document_code",),
    ),
    _case(
        "RAG-EXACT-RULE-FULL-OUTAGE",
        "exact_code",
        DETERMINISTIC_PROFILE,
        "Tam kesinti rule code değerini doğru politika bölümüne bağlar.",
        "BB-FULL-OUTAGE-TIERED",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-COMP-2026-BROADBAND",
        expected_heading_contains="Full Outage",
        tags=("rule_code",),
    ),
    _case(
        "RAG-EXACT-ALARM-BNG",
        "exact_code",
        DETERMINISTIC_PROFILE,
        "BNG alarm kodunu sentetik alarm kataloğunda bulur.",
        "BNG_UNREACHABLE",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-ALARM-CATALOG-2026",
        expected_heading_contains="Katalog",
        tags=("alarm_code",),
    ),
    _case(
        "RAG-EXACT-RULE-MANUAL-REVIEW",
        "exact_code",
        DETERMINISTIC_PROFILE,
        "Manual review rule code değerini sınır ve inceleme kaynağında bulur.",
        "MR-UNKNOWN-MISSING-EVIDENCE",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-COMP-2026-REVIEW-CAPS",
        expected_heading_contains="Manual Review",
        tags=("rule_code", "manual_review"),
    ),
    _case(
        "RAG-HISTORY-REFUND-V1",
        "historical_version",
        DETERMINISTIC_PROFILE,
        "REFUND-001 için v1 geçerlilik dönemindeki kaynak sürümünü seçer.",
        "REFUND-001",
        MALTEPE_SNAPSHOT_KEY,
        "REFUND-001-V1-SOURCE",
        evaluation_time=datetime.fromisoformat("2026-07-10T12:00:00+03:00"),
        expected_rule_version=1,
        expected_heading_contains="v1 Sentetik Kaynak",
        forbidden_document_codes=("REFUND-001-V2-SOURCE",),
        tags=("historical", "refund"),
    ),
    _case(
        "RAG-HISTORY-REFUND-V2",
        "historical_version",
        DETERMINISTIC_PROFILE,
        "REFUND-001 için v2 geçerlilik dönemindeki kaynak sürümünü seçer.",
        "REFUND-001",
        MALTEPE_SNAPSHOT_KEY,
        "REFUND-001-V2-SOURCE",
        evaluation_time=datetime.fromisoformat("2026-07-20T12:00:00+03:00"),
        expected_document_version=2,
        expected_rule_version=2,
        expected_heading_contains="v2 Sentetik Kaynak",
        forbidden_document_codes=("REFUND-001-V1-SOURCE",),
        tags=("historical", "refund"),
    ),
    _case(
        "RAG-SCOPE-MULTICITY-GLOBAL-LIFECYCLE",
        "scope_and_filter",
        DETERMINISTIC_PROFILE,
        "Multi-city kapsamından global operasyon prosedürüne erişir.",
        "SYN-OPERATIONS-LIFECYCLE-2026",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-OPERATIONS-LIFECYCLE-2026",
        document_type="procedure",
        expected_heading_contains="Operasyon Olay Yaşam",
        forbidden_document_codes=("REFUND-001-V1-SOURCE", "REFUND-001-V2-SOURCE"),
        tags=("global", "snapshot_scope"),
    ),
    _case(
        "RAG-SCOPE-MALTEPE-GLOBAL-FAILOVER",
        "scope_and_filter",
        DETERMINISTIC_PROFILE,
        "Maltepe kapsamından global failover ve bakım prosedürüne erişir.",
        "SYN-FAILOVER-MAINTENANCE-2026",
        MALTEPE_SNAPSHOT_KEY,
        "SYN-FAILOVER-MAINTENANCE-2026",
        document_type="procedure",
        expected_heading_contains="Failover ve Planlı Bakım",
        forbidden_document_codes=("SYN-COMP-2026-METRO-SLA",),
        tags=("global", "snapshot_scope"),
    ),
    _case(
        "RAG-SCOPE-MULTICITY-POLICY",
        "scope_and_filter",
        DETERMINISTIC_PROFILE,
        "Multi-city politika kaynağını bulurken Maltepe kaynaklarını dışarıda tutar.",
        "SYN-COMP-2026-OVERVIEW",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-COMP-2026-OVERVIEW",
        document_type="rule_policy",
        expected_heading_contains="Sentetik Telafi Politikası",
        forbidden_document_codes=("REFUND-001-V1-SOURCE", "REFUND-001-V2-SOURCE"),
        tags=("snapshot_isolation", "document_type"),
    ),
    _case(
        "RAG-FILTER-DEGRADATION-RULE",
        "scope_and_filter",
        DETERMINISTIC_PROFILE,
        "Rule code filtresiyle degradation bölümünü sınırlar.",
        "BB-DEGRADATION-QUALITY",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-COMP-2026-BROADBAND",
        document_type="rule_policy",
        rule_code="BB-DEGRADATION-QUALITY",
        expected_heading_contains="Degradation",
        forbidden_document_codes=("REFUND-001-V1-SOURCE", "REFUND-001-V2-SOURCE"),
        tags=("rule_filter", "document_type"),
    ),
    _case(
        "RAG-SEM-FAILED-FAILOVER",
        "turkish_semantic",
        SEMANTIC_PROFILE,
        "Başarısız yedek yol geçişini doğal Türkçe ifadeyle bulur.",
        "Ana yol kesilince yedek bağlantı trafiği üstlenemiyorsa hangi kaynak açıklıyor?",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-FAILOVER-MAINTENANCE-2026",
        search_mode="semantic",
        expected_heading_contains="Failover",
        max_accepted_rank=3,
        forbidden_document_codes=("REFUND-001-V1-SOURCE", "REFUND-001-V2-SOURCE"),
        tags=("paraphrase", "failover"),
    ),
    _case(
        "RAG-SEM-PACKET-LOSS-SLA",
        "turkish_semantic",
        SEMANTIC_PROFILE,
        "Paket kaybı SLA ihlalini düşük kelime örtüşmesiyle bulur.",
        (
            "Aktarım sırasında verilerin bir bölümü hedefe ulaşmıyorsa hizmet seviyesi "
            "nasıl ele alınır?"
        ),
        MULTICITY_SNAPSHOT_KEY,
        "SYN-COMP-2026-METRO-SLA",
        search_mode="hybrid",
        expected_heading_contains="SLA İhlalleri",
        max_accepted_rank=3,
        tags=("paraphrase", "sla"),
    ),
    _case(
        "RAG-SEM-BROADBAND-FULL-OUTAGE",
        "turkish_semantic",
        SEMANTIC_PROFILE,
        "Broadband tam kesinti politikasını doğal dil ifadesiyle bulur.",
        "Abonenin sabit internet erişimi bütünüyle koptuğunda uygulanacak politika nedir?",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-COMP-2026-BROADBAND",
        search_mode="semantic",
        expected_heading_contains="Full Outage",
        max_accepted_rank=3,
        tags=("paraphrase", "broadband"),
    ),
    _case(
        "RAG-SEM-DEGRADATION",
        "turkish_semantic",
        SEMANTIC_PROFILE,
        "Hizmet sürerken kalite düşüşü politikasını bulur.",
        "Bağlantı kopmadı ama hız ve hizmet kalitesi belirgin şekilde bozuldu.",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-COMP-2026-BROADBAND",
        search_mode="hybrid",
        expected_heading_contains="Degradation",
        max_accepted_rank=3,
        tags=("paraphrase", "quality"),
    ),
    _case(
        "RAG-SEM-MAINTENANCE-OVERRUN",
        "turkish_semantic",
        SEMANTIC_PROFILE,
        "Bildirilen pencereyi aşan bakım prosedürünü bulur.",
        "Önceden duyurulan çalışma söz verilen bitiş saatinde tamamlanmadı.",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-FAILOVER-MAINTENANCE-2026",
        search_mode="semantic",
        expected_heading_contains="Planlı Bakım",
        max_accepted_rank=3,
        tags=("paraphrase", "maintenance"),
    ),
    _case(
        "RAG-SEM-MANUAL-REVIEW",
        "turkish_semantic",
        SEMANTIC_PROFILE,
        "Otomatik karar üretilemeyen telafi inceleme kaynağını bulur.",
        "Kanıtlar eksikken sistemin insan değerlendirmesine bırakması gereken durum nedir?",
        MULTICITY_SNAPSHOT_KEY,
        "SYN-COMP-2026-REVIEW-CAPS",
        search_mode="hybrid",
        expected_heading_contains="Manual Review",
        max_accepted_rank=3,
        tags=("paraphrase", "manual_review"),
    ),
)
