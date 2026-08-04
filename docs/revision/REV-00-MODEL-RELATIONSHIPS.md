# REV-00 Model Relationships

Bu diyagramlar `ca225f3` commit'indeki Django modelleri ve servis çağrıları okunarak hazırlanmıştır. Oklar veri yönünü değil, ilişki/çağrı yönünü gösterir. Çoğu domain tablosu `DataSnapshot` ile izole edilir; coğrafya tabloları ve global RAG dokümanları istisnadır.

## 1. Müşteriden şebeke cihazına erişim

```mermaid
flowchart LR
  C[Customer] -->|1-N| S[Subscription]
  S -->|1-N, primary/backup| SC[SubscriptionConnection]
  SC -->|N-1| LC[LineConnection]
  LC -->|terminating_port| NP[NetworkPort]
  NP -->|device| ND[NetworkDevice]
  S --> SP[ServicePackage]
  S --> SLA[SLAProfile]
  LC --> AS[AccessSegment]
```

`SubscriptionConnection` zaman aralığı ve `connection_role` ile aboneliğin primary/backup hattını temsil eder. `LineConnection` erişim teknolojisi ve fiziksel/logical sonlandırma portunu taşır.

## 2. Şebeke hiyerarşisi

```mermaid
flowchart TB
  U[upstream NetworkDevice] -->|source_device| L[NetworkLink]
  L -->|target_device| D[downstream NetworkDevice]
  U --> UP[NetworkPort]
  D --> DP[NetworkPort]
  FD[FailureDomain] --> DM[DeviceFailureDomainMembership] --> U
  FD --> LM[NetworkLinkFailureDomainMembership] --> L
  FD --> LCM[LineConnectionFailureDomainMembership] --> LC[LineConnection]
```

Topology traversal `NetworkLink` yönünü kullanır. Mevcut veride line failure-domain üyelikleri doludur; device/link üyelik tabloları boştur.

## 3. Alarm, incident ve outage

```mermaid
flowchart LR
  AT[AlarmType] --> A[Alarm]
  A --> IA[IncidentAlarm]
  I[Incident] --> IA
  I --> O[Outage]
  I --> OE[OperationalEvent]
  I --> QM[QualityMeasurement]
  MW[MaintenanceWindow] --> MWD[MaintenanceWindowDevice] --> ND[NetworkDevice]
  MW --> MWL[MaintenanceWindowNetworkLink] --> NL[NetworkLink]
  A --> ND
  I --> ND
  O --> ND
```

`IncidentAlarm.role` alarmın primary/supporting ilişkisini, `Outage` doğrulanmış/hesaplanmış kesinti kaydını temsil eder. Mevcut multi-city generator'da Incident→Outage nedensel olarak aynı senaryodan gelir; Alarm→Incident bağı ayrı alarm döngüsünden seçilen kayıtların sonradan bağlanmasıdır.

## 4. Müşteri etkisi, kural ve telafi

```mermaid
flowchart LR
  I[Incident] --> O[Outage]
  O --> IMP[CustomerImpactService sonucu]
  SC[SubscriptionConnection] --> IMP
  IMP --> RE[RuleEvaluationService]
  RS[RuleSet] --> R[Rule] --> RV[RuleVersion]
  RV --> RE
  RE --> CE[CompensationEvaluation]
  CE --> DE[DecisionEvidence]
  RS --> DE
  RV --> DE
  CE --> CH[CompensationHistory / persist yolu]
```

Customer impact kalıcı ayrı bir model değildir; topology ve zaman filtrelerinden deterministik servis sonucu olarak hesaplanır. `DecisionEvidence`, seçilen rule/version ile hesaplama izini kalıcı ve hash'li biçimde saklar.

## 5. RAG kaynak zinciri

```mermaid
flowchart LR
  DS[DataSnapshot veya NULL/global] --> SD[SourceDocument]
  SD -->|1-N| DC[DocumentChunk]
  DC -->|1-N| DCE[DocumentChunkEmbedding]
  DC -. legacy read-only .-> LV[DocumentChunk.embedding]
  IR[IndexRun] -->|çalışma özeti| DS
```

Bir chunk aynı anda Gemini, aktif Qwen3 4B ve tarihsel lokal model embedding kayıtlarına sahip olabilir. Search yalnız aktif provider descriptor ile tam eşleşen `DocumentChunkEmbedding` setini kullanır.

## 6. MCP → API → servis → model

```mermaid
flowchart TB
  NM[Network MCP / 9 tool] --> BC[Shared BackendClient]
  CM[Customer MCP / 7 tool] --> BC
  RM[Rule MCP / 8 tool] --> BC
  PM[Compensation MCP / 6 tool] --> BC
  BC --> API[Authenticated /api/internal/v1]

  API --> TS[TopologyService] --> NMOD[NetworkDevice, NetworkLink, NetworkPort]
  API --> IS[CustomerImpactService] --> CMOD[Customer, Subscription, SubscriptionConnection]
  API --> ACS[AlarmCorrelationService] --> OMOD[Alarm, IncidentAlarm, Incident]
  API --> RCS[RootCauseService] --> OMOD
  API --> RES[RuleEvaluationService] --> RMOD[RuleSet, Rule, RuleVersion]
  API --> CPS[CompensationService] --> PMOD[CompensationEvaluation, DecisionEvidence]
  API --> RAGS[RAG search] --> RAGMOD[SourceDocument, DocumentChunk, DocumentChunkEmbedding]
```

MCP process'leri Django ORM import etmez. Bearer service token, correlation ID, timeout ve güvenli hata eşleme ortak `BackendClient` sözleşmesindedir. Rule MCP'nin `search_rule_documents` aracı RAG'a erişir; Network MCP'de doküman arama aracı yoktur.

## Snapshot sınırı

```mermaid
flowchart LR
  DV[DatasetVersion] --> DS[DataSnapshot]
  DS --> N[Network]
  DS --> C[Customers]
  DS --> O[Operations]
  DS --> R[Rules]
  DS --> P[Compensation]
  DS --> GT[GroundTruthCase]
  DS --> SD[Snapshot SourceDocument]
  G[Global SourceDocument] -. data_snapshot=NULL .-> SD
```

Servis ve internal API'ler snapshot'ı exact `snapshot_key`, bazı sözleşmelerde yalnız tekil dataset slug ile çözer; aktif snapshot'a sessiz fallback yapılmaz.
