# REV-00 Current System Report

Baseline commit: `ca225f32ea571a76a7a41499fb94a3e96f1209a0` (`main`). Bu rapor 4 Ağustos 2026 tarihinde repository kodu, read-only Django ORM sorguları ve mevcut PostgreSQL veritabanı üzerinden üretildi. Davranış veya veri değiştirilmedi.

## Repository ve migration durumu

- Başlangıç branch: `main`; başlangıç working tree temizdi.
- README: repository root `README.md`.
- Görev planı: repository parent dizininde `processtwin_gorev_plani.md`.
- Son 15 commit (yeniden eskiye):
  - `ca225f3 feat: support validated local RAG embeddings`
  - `d67ebcf fix: improve section-level RAG retrieval`
  - `fde61c7 test: define RAG benchmark heading policy`
  - `5fab23e test: isolate RAG provider configuration`
  - `1238993 test: add RAG benchmark mini set`
  - `d903a14 feat: add Rule MCP RAG search tool`
  - `3d60ae9 feat: add RAG embeddings and hybrid search`
  - `bcf1684 feat: add RAG ingestion and chunking`
  - `7ccd64a feat: add synthetic RAG source corpus`
  - `5026a7b feat: add RAG document models`
  - `d2db454 test: add MCP contract test suite`
  - `6b781ba feat: add MCP health and registry`
  - `4c73a7d feat: implement compensation MCP server`
  - `fd244a2 feat: implement rule MCP server`
  - `babc567 feat: implement customer MCP server`
- Django migration graphında 53 migration applied, pending migration yoktur. Son RAG migration `rag.0002_document_chunk_embedding` uygulanmıştır.
- Baseline başlangıcında tracked/untracked değişiklik yoktu. REV-00 sırasında yalnız bu rapor seti ve read-only audit scripti oluşturuldu.

## A. Genel mimari

- **Runtime:** Python 3.12.5, Django 5.2.16, Django REST Framework, Pydantic tabanlı MCP input modelleri.
- **Veritabanı:** PostgreSQL 14.18; pgvector 0.8.5. Local settings PostgreSQL'i desteklenen native veri tabanı olarak kullanır.
- **Django app'leri:** `accounts`, `core`, `datasets`, `geography`, `network`, `customers`, `operations`, `rules`, `compensation`, `rag`.
- **Katmanlar:** Django modelleri → domain servisleri → authenticated internal DRF function views → shared HTTP `BackendClient` → stdio MCP server/tool adapter'ları.
- **Public API:** yalnız `/api/health/`. Domain API'leri `/api/internal/v1/` altında bearer service token ve correlation ID ile korunur.
- **MCP:** Network, Customer, Rule ve Compensation olmak üzere dört bağımsız stdio server. MCP process'leri ORM kullanmaz; backend internal API'yi çağırır.
- **RAG:** sürümlü sentetik Markdown corpus → `SourceDocument` → heading-char chunking → çoklu `DocumentChunkEmbedding` → PostgreSQL full-text expression + pgvector cosine + section-aware hybrid retrieval.
- **Provider'lar:** Gemini `gemini-embedding-2` ve lokal Ollama `qwen3-embedding:4b` aktiftir. Nomic ve Qwen 0.6B kayıtları tarihsel karşılaştırma setidir; mock yalnız test içindir.
- **LLM/orchestrator:** Henüz implementation yoktur. Planlanan lokal LLM `gemma4:12b-it-qat`, thinking daima kapalı; MCP/RAG sonuçlarını birleştiren orchestrator sonraki görevlerdedir.
- **Generator:** Maltepe fixed-seed regression ve multi-city realism command'leri; ayrıca RAG corpus seed, chunk index ve embedding command'leri vardır.

## B. Model sahipliği ve kullanım haritası

Tüm modellerin alan, ilişki, constraint ve mevcut satır sayısı [Ek 1](#ek-1-tam-model-kataloğu) içindedir. Aşağıdaki tablo model başına amaç, servis, MCP ve producer sahipliğini verir.

| Modeller | Amaç / tarih-snapshot | Servis ve API | MCP | Producer |
|---|---|---|---|---|
| `accounts.User` | Django kullanıcısı ve rolü; snapshot dışı | admin/auth | yok | admin/manual |
| `DatasetVersion`, `DataSnapshot` | Generator sürümü, seed, config, snapshot aktivasyon/doğrulama sınırı | bütün snapshot resolver'ları | dört MCP dolaylı | iki dataset seed command'i |
| `GroundTruthCase` | Outage/root-cause/impact/rule/tutar beklenen sonucu; snapshot FK | validators/regression | dolaylı | Maltepe ve multi-city ground-truth adımı |
| `City`, `District`, `Neighborhood` | Coğrafya hiyerarşisi; snapshot dışı ortak katalog | location/customer/network filtreleri | Customer, Network | geography adımı/get-or-create |
| `NetworkDevice`, `NetworkLink`, `NetworkPort` | Yönlü topoloji, cihaz ve port envanteri; snapshot FK | topology, path diversity, root cause | Network | network topology seed |
| `AccessSegment`, `LineConnection` | erişim alanı ve abone hattının port/teknoloji bağlantısı | topology, customer impact | Network, Customer | network + subscription/line seed |
| `FailureDomain`, `DeviceFailureDomainMembership`, `NetworkLinkFailureDomainMembership`, `LineConnectionFailureDomainMembership` | shared-risk/path diversity; snapshot FK | path diversity, correlation | Network | multi-city network seed |
| `Customer`, `Subscription`, `SubscriptionConnection` | müşteri/abonelik ve tarihsel primary/backup hat eşlemesi | customer profile, impact, eligibility | Customer, Network, Compensation | customer/subscription seed |
| `ServicePackage`, `ServicePackageAllowedSegment`, `ServicePackagePriceVersion` | ürün, segment uygunluğu ve tarihsel fiyat | pricing/compensation inputs | Customer, Compensation | package catalog seed |
| `SLAProfile` | availability/latency/jitter/loss/restoration ve backup şartları | rule/compensation context | Customer, Rule, Compensation | SLA catalog seed |
| `Campaign`, allowed-segment/service/technology tabloları, `CampaignEnrollment` | kampanya katalog ve abonelik katılımı | campaign eligibility/ranking | Compensation, Customer | campaign + enrollment seed |
| `PaymentRecord`, `CompensationHistory` | fatura/ödeme durumu ve geçmiş telafi; snapshot/tarih | customer history, preconditions | Customer, Compensation | payment/history seed; persist yolu |
| `AlarmType`, allowed-source-kind ve supported-device-type tabloları | normalize alarm katalog sözleşmesi | validation/correlation | Network | alarm catalog seed |
| `Alarm` | cihaz/link/port kaynaklı alarm instance'ı, lifecycle ve metadata | alarm search/correlation/root cause | Network | operations/timeline seed |
| `Incident`, `IncidentAlarm` | operasyon olayı ve alarmların primary/supporting bağı | correlation/root cause/outage | Network | operations/timeline seed |
| `Outage` | kaynak cihaz/incident üzerinde kesinti aralığı ve durumu | outage duration/search, impact, compensation | Network, Customer, Compensation | operations/timeline seed |
| `OperationalEvent`, `QualityMeasurement` | incident yaşam döngüsü ve ölçüm serisi | operasyon analizi; henüz ayrı MCP tool yok | dolaylı | timeline seed |
| `MaintenanceWindow` ve device/link ara tabloları | planlı bakım kapsamı ve zamanı | rule/outage istisnaları | Network/Rule dolaylı | timeline seed |
| `RuleSet`, `Rule`, `RuleVersion` | versioned condition/action policy; snapshot ve zaman aralığı | selection/evaluation/conflict | Rule, Compensation | rule catalog seed |
| `RuleChangeSet`, `RuleTestCase` | gelecekte rule değişiklik paketi/test örneği; şu an boş | henüz aktif servis yok | yok | producer yok |
| `CompensationEvaluation`, `DecisionEvidence` | deterministik değerlendirme sonucu, tutar ve hash'li açıklanabilirlik | compensation/evidence services | Compensation, Rule evidence | multi-city seed ve persist option |
| `SourceDocument`, `DocumentChunk` | global/snapshot kaynak ve kaynak içi birebir text slice | chunking/search | Rule `search_rule_documents` | corpus seed/index command |
| `DocumentChunkEmbedding` | chunk başına provider/model/version/prompt/hash kimlikli vector | embedding/search/benchmark | Rule RAG dolaylı | embedding command + Gemini migration backfill |
| `IndexRun` | chunk/embedding çalışma lifecycle ve sayaçları | indexing/embedding | yok | index ve embedding command'leri |

## C. İlişki özeti

Detaylı Mermaid diyagramları: [`REV-00-MODEL-RELATIONSHIPS.md`](REV-00-MODEL-RELATIONSHIPS.md).

- Müşteri hattı: Customer → Subscription → SubscriptionConnection → LineConnection → NetworkPort → NetworkDevice.
- Operasyon: AlarmType → Alarm ↔ IncidentAlarm ↔ Incident → Outage.
- Karar: Outage + hesaplanan müşteri etkisi + RuleVersion → CompensationEvaluation → DecisionEvidence.
- RAG: SourceDocument → DocumentChunk → birden fazla DocumentChunkEmbedding.

## D. Veri üretim akışı

### Maltepe regression

- **Command:** `backend/apps/datasets/management/commands/seed_maltepe_mvp.py`.
- **Sıra:** geography → dataset/snapshot → `seed_network_topology` → `seed_customer_subscriptions` → `seed_operations` → `seed_rules` → `seed_ground_truth` → `validate_maltepe_mvp_snapshot`.
- **Davranış:** `transaction.atomic`, fixed identifiers/seed, tekrar çalıştırılabilir get/update/create politikası.
- **Nedensellik:** Maltepe operasyon helper'ı alarm, incident, IncidentAlarm ve outage'ı aynı senaryo çağrısında üretir; regression akışı sıkı bağlıdır.

### Multi-city realism

- **Command:** `backend/apps/datasets/management/commands/seed_multicity_realism.py`; ana orchestration `data_generator/seeders/multicity_realism.py::seed_multicity_realism_dataset`.
- **Sıra:** geography → SLA → packages → campaigns → SYN-COMP rules → network → customers → subscriptions/lines → alarm types → timeline → payments → enrollments → compensation history/evidence → row counts/validation.
- **Girdi:** versioned config katalogları, dataset seed ve deterministic random üreticiler.
- **Nedensellik bulgusu:** Incident'lar scenario template/impact plan'dan üretilir; uygun Incident'lardan aynı zaman, cihaz ve scenario metadata'sıyla Outage üretilir. Alarm'lar ise ayrı 2.100 öğelik döngüde periyodik zaman ve dönen source seçimiyle üretilir; ardından incident başına uygun iki Alarm pozisyonel slice ile `IncidentAlarm` olarak bağlanır. Dolayısıyla Incident→Outage nedensel, Alarm→Incident bağı tam nedensel event instance üretimi değildir.
- **OperationalEvent:** incident akışını takip eder. **QualityMeasurement:** ayrı deterministik seri olarak üretilir.

### Katalog ve ticari üretim

- Coğrafya `geography` yardımcılarıyla ortak katalog olarak get/create edilir.
- Network topology; device → port → link/access segment → line/failure-domain üyelikleri sırasını izler.
- Customer → subscription → line/connection üretimi topology ve package/SLA kataloglarına bağlıdır.
- Payment, campaign enrollment ve compensation history subscription'lardan sonra üretilir.
- Rule catalog compensation/evidence üretiminden önce oluşturulur.
- Ground-truth, üretilen gerçek kod/hash/count/tutar değerlerine sabit kabul sözleşmesi ekler.

### Generator/seed adım matrisi

| Adım | Dosya ve ana giriş | Girdi / determinism | Ürettiği tablolar | Sonraki bağımlılık |
|---|---|---|---|---|
| Maltepe geography/snapshot | `seed_maltepe_mvp.py::handle` | fixed version/seed/reference time | DatasetVersion, DataSnapshot, City/District/Neighborhood | bütün Maltepe adımları |
| Maltepe topology | `data_generator/seeders/network.py::seed_network_topology` | snapshot, Maltepe location, fixed codes | Device, Port, Link, AccessSegment, Line | customer/subscription |
| Maltepe customers | `data_generator/seeders/customers.py::seed_customer_subscriptions` | snapshot, topology, fixed counts | Customer, Subscription, SubscriptionConnection, package/SLA | operations/impact |
| Maltepe operations | `data_generator/seeders/operations.py::seed_operations` | snapshot, reference datetime | AlarmType, Alarm, Incident, IncidentAlarm, Outage, OperationalEvent | rule/GT regression |
| Maltepe rules | `data_generator/seeders/rules.py::seed_rules` | snapshot | REFUND-001 Rule/versions | ground truth/compensation |
| Maltepe GT | `data_generator/seeders/ground_truth.py::seed_ground_truth` | existing outage/customer/rule codes | 3 GroundTruthCase | validator |
| Multi-city geography | `multicity_realism.py::seed_multicity_realism_dataset` geography phase | config catalog + fixed seed | shared geography | network/customer |
| SLA/package/campaign | aynı orchestrator, catalog helpers | versioned config constants | SLA, package/price/allowed, campaign/allowed | subscriptions/enrollments/rules |
| SYN-COMP rule catalog | aynı orchestrator, policy catalog helper | fixed 25-rule catalog | RuleSet, Rule, RuleVersion | compensation/evidence/GT |
| Network topology | aynı orchestrator network phase | city/district targets + seeded RNG | Device/Port/Link/Segment/Line/FailureDomain | subscriptions/timeline |
| Customer/subscription | aynı orchestrator customer/subscription phases | commercial profile + seeded RNG | Customer, Subscription, Connection | payments/impact/timeline |
| Alarm catalog | aynı orchestrator alarm-type phase | fixed 30-type catalog | AlarmType ve allowlist tabloları | timeline |
| Timeline | `data_generator/seeders/multicity_realism.py::seed_timeline` | scenario templates, reference times, seeded RNG | Incident, Outage, Alarm, IncidentAlarm, OperationalEvent, Maintenance, QualityMeasurement | compensation/GT |
| Payments | aynı orchestrator payment phase | subscription/package price history | PaymentRecord | rule preconditions |
| Enrollments | aynı orchestrator enrollment phase | subscription/campaign eligibility | CampaignEnrollment | options/ranking |
| Compensation/evidence | aynı orchestrator compensation phase | outages, subscriptions, rules, prices | CompensationHistory, Evaluation, DecisionEvidence | regression/GT |
| Multi-city GT | `backend/apps/datasets/management/commands/validate_multicity_ground_truth.py` → `data_generator/seeders/multicity_ground_truth.py::seed_multicity_ground_truth` | canonical scenario outputs; command önce 30 case'i yeniden seed eder, sonra doğrular | 30 GroundTruthCase | 30/30 gate |
| RAG corpus | `backend/apps/rag/management/commands/seed_rag_corpus.py` | immutable manifest + Markdown | 10 SourceDocument | chunk index |
| RAG chunks | `backend/apps/rag/management/commands/index_rag_documents.py` | SourceDocument.content/hash | 74 DocumentChunk, IndexRun | embeddings/search |
| RAG embeddings | `backend/apps/rag/management/commands/generate_rag_embeddings.py` | chunks + allowlisted descriptor | DocumentChunkEmbedding, IndexRun | semantic/hybrid/benchmark |

### RAG üretimi

1. `seed_rag_corpus`: 10 canonical Markdown içeriğini `SourceDocument` olarak seed eder.
2. `index_rag_documents`: aktif kaynakları `heading-char-v1` ile chunk'lar, `IndexRun` kaydeder.
3. `generate_rag_embeddings`: allowlist descriptor için 74 chunk embedding setini atomik üretir.
4. `benchmark_rag`: read-only 10 deterministic + 6 semantic vakayı değerlendirir.

## E. Servis akışı

| Servis | Dosya / public giriş | Girdi → çıktı | Model bağımlılığı | Çağıranlar |
|---|---|---|---|---|
| Topology traversal | `network/services/topology.py`; `get_children`, `get_ancestors`, `get_subgraph` | snapshot/device/time/depth → yönlü node/link graph | Device, Link | Network internal API/MCP, tests |
| Path diversity | `network/services/path_diversity.py`; `evaluate` | primary/backup line → shared device/link/failure-domain sonucu | Line, Link, Device, memberships | impact/rule context, tests |
| Customer impact | `customers/services/impact.py`; `calculate_impact` | outage/device/time → etkilenen customer/subscription ve failover warnings | SubscriptionConnection, Line, topology | Network/Customer internal API, Compensation |
| Alarm correlation | `operations/services/alarm_correlation.py`; `find_correlations`, `score_pair` | anchor alarm/window → scored related alarms | Alarm, type, topology/failure-domain | Network correlation endpoint/tool |
| Root cause | `operations/services/root_cause.py`; `analyze` | outage/window → ranked candidate devices/evidence gaps | Alarm, Incident, Outage, topology | Network root-cause endpoint/tool |
| Outage | `operations/services/outages.py`; `calculate_duration`, `is_ongoing` | outage/time → normalized duration/status | Outage | Network, Customer, Compensation |
| Rule evaluation | `rules/services/evaluation.py`; `evaluate`, `evaluate_for_outage`, `evaluate_rule_set` | context/rule set/time → matched/excluded/actions/trace | RuleSet, Rule, RuleVersion | Rule API, CompensationService |
| Rule version/conflict | `rules/services/version_selection.py` ve query helpers | code/snapshot/time → active history/conflicts | Rule/Version | Rule API/MCP |
| Compensation | `compensation/services.py`; eligibility/amount/options/evidence | outage+subscription+rule context → deterministic decision/tutar/evidence | customer, outage, rules, evaluation/evidence | Compensation internal API/MCP |
| RAG chunking | `rag/services/chunking.py` | SourceDocument.content → offset-preserving chunk specs | SourceDocument/Chunk | index command/tests |
| RAG indexing | `rag/services/indexing.py` | active docs/filter → idempotent chunk replacement + IndexRun | SourceDocument/Chunk/IndexRun | management command |
| Embeddings | `rag/services/embeddings.py` | selected chunks+descriptor → atomic embedding records | Chunk/Embedding/IndexRun | generation command |
| Search | `rag/services/search.py`; `search` | validated request → full_text/semantic/hybrid ranked evidence | docs/chunks/embeddings | RAG internal API, Rule MCP |
| Benchmark | `rag/services/benchmark.py` | immutable manifest/profile → per-case ranks/metrics | read-only RAG | benchmark command/tests |

## F. API envanteri

Tüm internal endpoint'ler `internal_service_required` ile bearer service token doğrular, correlation ID'yi kabul/üretir ve JSON error envelope kullanır.

| Method ve path | View / ana servis | Girdi ve çıktı özeti |
|---|---|---|
| `GET /api/health/` | `core.views.health` | public readiness JSON |
| `GET /api/internal/v1/health/` | `core.internal_views.internal_health` | authenticated backend health |
| `GET /api/internal/v1/mcp/registry/` | core registry | server descriptor ve expected tool count |
| `GET /api/internal/v1/mcp/health/` | live stdio probe | initialize/list_tools sonucu |
| `GET .../customer/customers/{number}/profile/` | customer view | snapshot + masked profile |
| `GET .../customer/subscriptions/` | customer view | snapshot/customer/subscription filtreleri → subscriptions |
| `GET .../customer/payments/` | customer view | subscription/period → payment status |
| `GET .../customer/outages/history/` | outage + impact | customer/subscription/time → outage history |
| `GET .../customer/compensation/history/` | customer query | customer/subscription → compensation history |
| `GET .../customer/customers/by-device/{code}/` | topology + impact | snapshot/device/time → customers |
| `GET .../customer/customers/by-location/` | customer query | city/district/neighborhood → customers |
| `GET .../network/devices/{code}/` | device query | snapshot/device → details |
| `GET .../network/devices/{code}/topology/` | topology | depth/direction/time → graph |
| `GET .../network/alarms/` | alarm query | code/type/severity/status/time → alarms |
| `GET .../network/alarms/{id}/correlations/` | correlation | window/threshold → ranked alarms |
| `GET .../network/outages/` | outage query | snapshot/device/status/time → outages |
| `GET .../network/outages/longest/` | outage duration | filter → longest outage |
| `GET .../network/outages/{code}/` | outage service | detail/duration |
| `GET .../network/outages/{code}/customer-impact/` | impact service | impact and warnings |
| `GET .../network/outages/{code}/root-cause-candidates/` | root cause | ranked candidates/evidence |
| `GET .../rules/` | rule query | text/family/status/snapshot → rules |
| `GET .../rules/effective-at/` | version selection | evaluation_time → effective versions |
| `GET .../rules/related/` | relation query | rule code → related rules |
| `GET .../rules/conflicts/` | conflict service | rule set/time → conflicts |
| `GET .../rules/evidence/` | evidence query | evaluation/outage identifiers → evidence |
| `GET .../rules/{code}/` | rule query | rule detail/current version |
| `GET .../rules/{code}/versions/` | version query | ordered history |
| `POST .../compensation/eligibility/` | rule + compensation | outage/subscription/time → eligible/reasons |
| `POST .../compensation/amount/` | compensation amount | selected rule/context; optional persist → amount/evidence |
| `POST .../compensation/options/` | option evaluation | eligible alternatives |
| `POST .../compensation/campaigns/check/` | campaign checks | subscription/campaign/time |
| `POST .../compensation/options/rank/` | deterministic ranking | options → ordered list |
| `GET .../compensation/evidence/` | evidence query | evaluation/id → DecisionEvidence |
| `POST .../rag/search/` | RAG search | query/snapshot/mode/filters/top_k → source chunks and scores |

Serializer validation ilgili `internal_serializers.py` dosyalarındadır. Internal API serbest SQL/field/provider/model kabul etmez.

## G. MCP envanteri

Ortak çıktı `MCPToolResponse`; input'lar Pydantic modelleridir. Shared `BackendClient` auth, timeout, correlation ID ve `validation_error/not_found/authentication_error/provider_error/timeout/internal_error` eşlemelerini uygular. Contract testleri `mcp_servers/shared/tests/` ve `backend/apps/core/tests/test_mcp_shared_contracts.py` içindedir.

| Server | Tool'lar | Davranış |
|---|---|---|
| Network (9) | `get_device_details`, `get_device_topology`, `search_alarms`, `search_outages`, `get_outage_details`, `calculate_customer_impact`, `correlate_alarms`, `rank_root_cause_candidates`, `get_longest_outage` | read-only backend GET; topology/operations servisleri |
| Customer (7) | `get_customer_profile`, `get_customer_subscription`, `get_customer_payment_status`, `get_customer_outage_history`, `get_customer_compensation_history`, `list_customers_by_device`, `list_customers_by_location` | read-only GET; masking backend'de korunur |
| Rule (8) | `search_rules`, `get_rule`, `get_rules_effective_at`, `get_rule_version_history`, `find_related_rules`, `detect_rule_conflicts`, `get_rule_evidence`, `search_rule_documents` | read-only GET ve RAG POST; karar/tutar üretmez |
| Compensation (6) | `evaluate_refund_eligibility`, `calculate_refund_amount`, `evaluate_compensation_options`, `check_campaign_eligibility`, `rank_compensation_options`, `get_compensation_evidence` | POST değerlendirmeleri; input destekliyorsa `persist=false` dry-run, `persist=true` kontrollü evaluation/evidence yazımı |

Gerçek SDK `list_tools` sayıları registry beklentisiyle aynıdır: `9 / 7 / 8 / 6`. Bir MCP başka MCP process'ini çağırmaz.

### Tool input/output sözleşmeleri

Tüm tool'lar `request_id` kabul edebilir ve `MCPToolResponse {success, request_id, correlation_id, data, error}` döndürür. `data`, yeniden hesaplanmadan ilgili backend endpoint'inin kontrollü payload'ıdır; pagination kullanan sonuçlarda `items/limit/next_cursor`, tekil sonuçlarda entity/detail, RAG'da `results` ve skor metadata'sı bulunur.

| Server / tool | Zorunlu input | Diğer kontrollü input | HTTP | Çıktı/model ailesi |
|---|---|---|---|---|
| Network / `get_device_details` | snapshot, device code | request id | GET | device/port/link detail; NetworkDevice/Port/Link |
| Network / `get_device_topology` | snapshot, device code | time, mode, depth, links, limit | GET | graph nodes/links; topology service |
| Network / `search_alarms` | snapshot | alarm/type/severity/status/source/device/link/incident/time/page | GET | alarm items; Alarm/AlarmType |
| Network / `search_outages` | snapshot | type/status/device/incident/location/time/page | GET | outage items; Outage/Incident |
| Network / `get_outage_details` | snapshot, outage code | evaluation time | GET | outage duration/detail |
| Network / `calculate_customer_impact` | snapshot, outage code | evaluation time | GET | affected customer/subscription counts, warnings |
| Network / `correlate_alarms` | snapshot, anchor alarm id | limit | GET | ranked correlations/reasons |
| Network / `rank_root_cause_candidates` | snapshot, outage code | time, limit | GET | ranked devices/evidence gaps |
| Network / `get_longest_outage` | snapshot | time window/location/device/technology/status/limit | GET | longest outage/detail |
| Customer / `get_customer_profile` | snapshot, customer number | include subscriptions/display name | GET | masked customer profile |
| Customer / `get_customer_subscription` | snapshot | customer/subscription, connections/campaigns/page | GET | subscriptions and relations |
| Customer / `get_customer_payment_status` | snapshot | customer/subscription/period/status/page | GET | PaymentRecord items/summary |
| Customer / `get_customer_outage_history` | snapshot | customer/subscription/time/impact/page | GET | outage history + calculated impact |
| Customer / `get_customer_compensation_history` | snapshot | customer/subscription/decision/settlement/time/page | GET | CompensationHistory items |
| Customer / `list_customers_by_device` | snapshot, device code | time/segment/priority/status/page/display name | GET | masked customer items |
| Customer / `list_customers_by_location` | snapshot | location/segment/priority/status/page/display name | GET | masked customer items |
| Rule / `search_rules` | snapshot | set/code/family/type/status/action/price/conflict/time/page | GET | Rule/RuleVersion summaries |
| Rule / `get_rule` | snapshot, rule code | version/effective time/raw config/schema summary | GET | rule and selected version |
| Rule / `get_rules_effective_at` | snapshot | time/family/type/code/set/conflict/page | GET | effective RuleVersion items |
| Rule / `get_rule_version_history` | snapshot, rule code | raw config/page | GET | ordered versions |
| Rule / `find_related_rules` | snapshot | code/set/family/conflict/action/price/page | GET | related rules |
| Rule / `detect_rule_conflicts` | snapshot | time/set/code/conflict/page | GET | conflict groups/candidates |
| Rule / `get_rule_evidence` | snapshot | evidence/evaluation/rule/set/outage/subscription/decision/page | GET | DecisionEvidence summaries |
| Rule / `search_rule_documents` | snapshot, query | time/mode/top_k/document/language/source/rule filters/scores | POST | RAG source/chunk/version/heading/text/scores; no vector |
| Compensation / `evaluate_refund_eligibility` | snapshot, outage, subscription | rule/set/time | POST | eligibility/reasons/rule trace |
| Compensation / `calculate_refund_amount` | snapshot, outage, subscription | rule/set/time/`persist` | POST | amount/calculation/evidence; optional persist |
| Compensation / `evaluate_compensation_options` | snapshot, outage, subscription, rule set | time/include ineligible | POST | deterministic options |
| Compensation / `check_campaign_eligibility` | snapshot, subscription | campaign/time | POST | eligible campaigns/reasons |
| Compensation / `rank_compensation_options` | snapshot, outage, subscription, rule set | time/limit | POST | ranked option list |
| Compensation / `get_compensation_evidence` | snapshot | evaluation/hash/outage/subscription/rule/decision/page | GET | DecisionEvidence records |

Validation, not-found, auth, timeout ve internal provider hataları ortak güvenli error envelope'a çevrilir; traceback, SQL, token, path ve raw embedding çıkmaz.

## H. RAG durumu

- Corpus: Türkçe, tamamen sentetik 10 Markdown SourceDocument; dağılım 2 global, 6 multi-city, 2 Maltepe.
- Chunking: `heading-char-v1`, H1/H2/H3, `max_chars=1800`, son çare `overlap_chars=200`; 74 birebir source slice.
- Physical embedding records: 296. Gemini 74; Nomic 74; Qwen3 0.6B 74; Qwen3 4B 74.
- Aktif semantic setler: Gemini 74 ve Ollama Qwen3 4B 74. Provider/model/version/prompt/content_hash tam kimliği zorunlu; farklı uzaylar karıştırılmaz.
- Full-text: PostgreSQL `simple` configuration, expression based; modelde SearchVectorField/GIN yok.
- Semantic: pgvector cosine distance, section-aware deterministic reranking `semantic-section-v3`.
- Hybrid: RRF + section-aware ranking `hybrid-section-v3`; runtime provider erişilemezse açık `full_text_fallback`, eksik/partial set varsa fallback yoktur.
- Benchmark: `rag-benchmark-v1`, 10 deterministic + 6 semantic vaka. Mevcut lokal Qwen3 4B: 6/6; deterministic: 10/10.
- MCP: yalnız Rule MCP `search_rule_documents`; Network MCP'de operasyon/alarm dokümanı arama aracı yoktur.
- Lokal bellek: Qwen query vector üretir, Ollama `/api/embed` `keep_alive=0` ile unload edilir; pgvector aramasından sonra ileride Gemma yüklenir. Bulk generation batch boyunca modeli tutup sonunda çıkarır.
- LLM: Gemma chat adapter henüz yoktur. `think=false` kararı plan/dokümantasyonda gelecek adapter kabul kriteridir; mevcut kodda chat çağrısı yoktur.

## I. Test envanteri

`pytest --collect-only -q` repository root'tan 612 test topladı.

| Kategori | Collected | Dosyalar / koruduğu davranış |
|---|---:|---|
| RAG | 112 | `backend/apps/rag/tests/test_rag_*.py`; model, migration, corpus, chunk, provider, generation, search, benchmark, internal API |
| MCP server unit | 75 | `mcp_servers/{network,customer,rules,compensation}/tests`; tool schema/adapter/error mapping |
| MCP shared contract/security | 41 | `mcp_servers/shared/tests`; BackendClient, SDK contract, no ORM/cross-MCP/security |
| Dataset/generator/ground truth | 49 | `backend/apps/datasets/tests`; Maltepe, multi-city, export, validation |
| Customer | 87 | model, technology compatibility, commercial config, impact, internal API |
| Operations | 50 | model, outage, alarm correlation, root cause, catalog config |
| Network | 46 | model, topology, path diversity, internal API |
| Compensation | 44 | model, service, formula/policy, internal API |
| Rules | 39 | model, evaluation, policy config, internal API |
| Core/accounts/geography | 69 | auth, health, registry/live health, shared contract, helpers, base models |

Toplam parametrized test item sayısı dosya içindeki function sayısından yüksektir. Native PostgreSQL/pgvector entegrasyonu model/migration/search testleri ve command smoke'larıyla korunur.

## J. Mevcut veri sayıları

### Genel ve snapshot

| Varlık | Toplam | Maltepe | Multi-city | Not |
|---|---:|---:|---:|---|
| DatasetVersion / DataSnapshot | 2 / 2 | 1 | 1 | iki snapshot validated; Maltepe active |
| City / District / Neighborhood | 4 / 12 / 59 | ortak | ortak | snapshot dışı katalog |
| Customer / Subscription | 14.625 / 16.440 | 225 / 240 | 14.400 / 16.200 | tüm customer status active |
| SubscriptionConnection / LineConnection | 16.475 / 16.475 | 240 / 240 | 16.235 / 16.235 | 16.267 primary, 208 backup |
| Device / Link / Port / AccessSegment | 249 / 257 / 13.841 / 323 | 14 / 12 / 177 / 17 | 235 / 245 / 13.664 / 306 | - |
| FailureDomain / line membership | 2.997 / 1.236 | 0 / 0 | 2.997 / 1.236 | device/link memberships 0 |
| AlarmType / Alarm | 33 / 2.104 | 3 / 4 | 30 / 2.100 | multi-city katalog tipleri çoğunlukla tam 70'er alarm |
| Incident / IncidentAlarm / Outage | 213 / 424 / 81 | 3 / 4 / 3 | 210 / 420 / 78 | - |
| OperationalEvent / QualityMeasurement | 912 / 12.000 | 12 / 0 | 900 / 12.000 | - |
| MaintenanceWindow | 30 | 0 | 30 | device/link membership 30'ar |
| SLA / Package / PriceVersion | 6 / 35 / 80 | 1 / 8 / 8 | 5 / 27 / 72 | - |
| Campaign / Enrollment | 10 / 4.050 | 0 / 0 | 10 / 4.050 | - |
| Payment / CompensationHistory | 59.600 / 1.100 | 0 / 0 | 59.600 / 1.100 | - |
| RuleSet / Rule / RuleVersion | 1 / 26 / 27 | 0 / 1 / 2 | 1 / 25 / 25 | REFUND legacy + SYN-COMP |
| CompensationEvaluation / Evidence | 227 / 227 | 0 / 0 | 227 / 227 | one-to-one evidence |
| GroundTruthCase | 33 | 3 | 30 | stored multi-city `row_counts` içinde 0 yazmasına rağmen gerçek tablo 30: metadata drift |
| SourceDocument / Chunk | 10 / 74 | 2 docs | 6 docs | ayrıca 2 global doc |
| Embedding records | 296 | scope'a göre chunk | scope'a göre chunk | 148 aktif + 148 tarihsel lokal aday |

### Dağılımlar

- Customer segment: individual 9.378, SME 3.278, enterprise 1.532, public 437.
- Subscription status: active 15.496, suspended 465, cancelled 306, pending 173.
- Line technology: GPON 7.677, VDSL 5.984, fiber 2.280, ADSL 534.
- Device type: DSLAM 100, access node 86, OLT 37, metro aggregation 16, BNG 10.
- Package technology: fiber 23, VDSL 9, ADSL 3; GPON hatları package compatibility katmanında fiber ürünle eşleşir.
- Alarm severity: major 1.193, critical 351, minor 280, warning 280.
- Alarm status: cleared 1.684, open 210, suppressed 210.
- Incident type: network outage 90, service degradation 64, planned maintenance 31, protection event 26, intermittent 1, unknown 1.
- Rule family: eligibility 2, exclusion 5, broadband 3, failover 3, metro SLA 4, modifier 4, SLA evidence 2, manual review 1, final policy 1, legacy 1.

## K. Baseline bulguları

1. Multi-city alarm sayılarındaki 70'lik düzen gerçek veritabanında doğrulandı; bu doğal frekans değil generator katalog döngüsüdür.
2. Mevcut müşteri etkisi kalıcı doğrulanmış session kanıtına sahip değildir; topology/line/time üzerinden servisçe hesaplanır.
3. Session başlangıç/devam/bitiş modeli yoktur.
4. `GroundTruthCase` gerçek 30 multi-city kayda sahipken snapshot `row_counts` metadata'sı 0 gösterir.
5. Network MCP'de RAG aracı yoktur; alarm/operasyon doküman retrieval entegrasyonu sonraki görevdir.
6. Rule/compensation sonuçları deterministiktir; LLM hesaplama akışında yoktur.

## Ek 1. Tam model kataloğu

Bu bölüm read-only `scripts/audit/revision_baseline_audit.py` çıktısından mekanik olarak üretilmiştir. “Constraints: none” yalnız model `Meta.constraints` listesini ifade eder; Django field-level unique/validator davranışları ayrıca field tanımında bulunabilir.

### `accounts.User`
- Table: `accounts_user`; source: `backend/apps/accounts/models.py`; rows: 1.
- Fields: `id` (BigAutoField), `password` (CharField), `last_login` (DateTimeField), `is_superuser` (BooleanField), `username` (CharField), `first_name` (CharField), `last_name` (CharField), `email` (CharField), `is_staff` (BooleanField), `is_active` (BooleanField), `date_joined` (DateTimeField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `role` (CharField), `groups` (ManyToManyField -> auth.Group), `user_permissions` (ManyToManyField -> auth.Permission).
- Constraints: none declared in model Meta.

### `compensation.CompensationEvaluation`
- Table: `compensation_evaluation`; source: `backend/apps/compensation/models.py`; rows: 227.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `evaluation_code` (CharField), `outage` (ForeignKey -> operations.Outage), `customer` (ForeignKey -> customers.Customer), `subscription` (ForeignKey -> customers.Subscription), `rule_version` (ForeignKey -> rules.RuleVersion), `result_type` (CharField), `status` (CharField), `proposed_amount` (DecimalField), `currency` (CharField), `explanation` (TextField), `calculation_trace` (JSONField), `metadata` (JSONField).
- Constraints: `unique_compensation_evaluation_code_per_snapshot` (UniqueConstraint), `unique_compensation_evaluation_per_outage_subscription_rule` (UniqueConstraint), `compensation_proposed_amount_non_negative` (CheckConstraint).

### `compensation.DecisionEvidence`
- Table: `compensation_decision_evidence`; source: `backend/apps/compensation/models.py`; rows: 227.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `compensation_evaluation` (OneToOneField -> compensation.CompensationEvaluation), `rule_set` (ForeignKey -> rules.RuleSet), `selected_rule_version` (ForeignKey -> rules.RuleVersion), `price_basis` (CharField), `selected_price` (DecimalField), `unrounded_amount` (DecimalField), `final_amount` (DecimalField), `currency` (CharField), `decision` (CharField), `evidence_schema_version` (PositiveIntegerField), `evidence_hash` (CharField), `matched_conditions` (JSONField), `failed_conditions` (JSONField), `excluded_rules` (JSONField), `candidate_base_rules` (JSONField), `applied_modifiers` (JSONField), `formula_inputs` (JSONField), `cap_floor_trace` (JSONField), `manual_review_reasons` (JSONField), `context_snapshot` (JSONField), `finalized` (BooleanField).
- Constraints: `unique_decision_evidence_hash_per_snapshot` (UniqueConstraint), `decision_evidence_final_amount_non_negative` (CheckConstraint).

### `customers.Campaign`
- Table: `customers_campaign`; source: `backend/apps/customers/models.py`; rows: 10.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `code` (CharField), `name` (CharField), `discount_type` (CharField), `discount_value` (DecimalField), `duration_months` (PositiveIntegerField), `valid_from` (DateTimeField), `valid_to` (DateTimeField), `stackable` (BooleanField), `status` (CharField), `metadata` (JSONField).
- Constraints: `unique_campaign_code_per_snapshot` (UniqueConstraint), `campaign_valid_range` (CheckConstraint), `campaign_discount_value_non_negative` (CheckConstraint).

### `customers.CampaignAllowedSegment`
- Table: `customers_campaign_allowed_segment`; source: `backend/apps/customers/models.py`; rows: 20.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `campaign` (ForeignKey -> customers.Campaign), `segment` (CharField).
- Constraints: `unique_campaign_allowed_segment` (UniqueConstraint).

### `customers.CampaignAllowedServiceType`
- Table: `customers_campaign_allowed_service_type`; source: `backend/apps/customers/models.py`; rows: 12.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `campaign` (ForeignKey -> customers.Campaign), `service_type` (CharField).
- Constraints: `unique_campaign_allowed_service_type` (UniqueConstraint).

### `customers.CampaignAllowedTechnology`
- Table: `customers_campaign_allowed_technology`; source: `backend/apps/customers/models.py`; rows: 21.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `campaign` (ForeignKey -> customers.Campaign), `technology` (CharField).
- Constraints: `unique_campaign_allowed_technology` (UniqueConstraint).

### `customers.CampaignEnrollment`
- Table: `customers_campaign_enrollment`; source: `backend/apps/customers/models.py`; rows: 4050.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `subscription` (ForeignKey -> customers.Subscription), `campaign` (ForeignKey -> customers.Campaign), `campaign_code` (CharField), `name` (CharField), `status` (CharField), `valid_from` (DateTimeField), `valid_to` (DateTimeField), `metadata` (JSONField).
- Constraints: none declared in model Meta.

### `customers.CompensationHistory`
- Table: `customers_compensation_history`; source: `backend/apps/customers/models.py`; rows: 1100.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `subscription` (ForeignKey -> customers.Subscription), `customer` (ForeignKey -> customers.Customer), `incident` (ForeignKey -> operations.Incident), `outage` (ForeignKey -> operations.Outage), `rule_version` (ForeignKey -> rules.RuleVersion), `compensation_conflict_group` (CharField), `reference_code` (CharField), `amount` (DecimalField), `decision_status` (CharField), `settlement_status` (CharField), `currency` (CharField), `reason` (CharField), `decided_at` (DateTimeField), `settled_at` (DateTimeField), `idempotency_key` (CharField), `metadata` (JSONField).
- Constraints: `unique_compensation_reference_per_snapshot` (UniqueConstraint), `unique_final_compensation_per_sub_incident_rule` (UniqueConstraint), `unique_final_compensation_per_sub_incident_group` (UniqueConstraint), `unique_compensation_history_idempotency_key` (UniqueConstraint).

### `customers.Customer`
- Table: `customers_customer`; source: `backend/apps/customers/models.py`; rows: 14625.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `customer_number` (CharField), `display_name` (CharField), `segment` (CharField), `status` (CharField), `priority_level` (CharField), `city` (ForeignKey -> geography.City), `district` (ForeignKey -> geography.District), `neighborhood` (ForeignKey -> geography.Neighborhood), `metadata` (JSONField).
- Constraints: `unique_customer_number_per_snapshot` (UniqueConstraint).

### `customers.PaymentRecord`
- Table: `customers_payment_record`; source: `backend/apps/customers/models.py`; rows: 59600.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `subscription` (ForeignKey -> customers.Subscription), `period` (CharField), `amount` (DecimalField), `billing_period_start` (DateField), `billing_period_end` (DateField), `due_date` (DateField), `recurring_amount` (DecimalField), `one_time_amount` (DecimalField), `discount_amount` (DecimalField), `billed_amount` (DecimalField), `paid_amount` (DecimalField), `outstanding_amount` (DecimalField), `currency` (CharField), `status` (CharField), `paid_at` (DateTimeField), `metadata` (JSONField).
- Constraints: `unique_payment_record_period_per_subscription` (UniqueConstraint).

### `customers.SLAProfile`
- Table: `customers_sla_profile`; source: `backend/apps/customers/models.py`; rows: 6.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `code` (CharField), `name` (CharField), `availability_target_percent` (DecimalField), `support_window` (CharField), `response_target_minutes` (PositiveIntegerField), `restoration_target_minutes` (PositiveIntegerField), `latency_threshold_ms` (PositiveIntegerField), `jitter_threshold_ms` (PositiveIntegerField), `packet_loss_threshold_percent` (DecimalField), `backup_requirement` (CharField), `required_path_diversity` (CharField), `monitoring_level` (CharField), `is_contractual` (BooleanField), `active` (BooleanField), `metadata` (JSONField).
- Constraints: `unique_sla_profile_code_per_snapshot` (UniqueConstraint), `sla_availability_target_percent_range` (CheckConstraint), `sla_packet_loss_threshold_percent_range` (CheckConstraint).

### `customers.ServicePackage`
- Table: `customers_service_package`; source: `backend/apps/customers/models.py`; rows: 35.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `package_code` (CharField), `name` (CharField), `technology` (CharField), `service_type` (CharField), `status` (CharField), `default_sla_profile` (ForeignKey -> customers.SLAProfile), `download_mbps` (PositiveIntegerField), `upload_mbps` (PositiveIntegerField), `symmetric` (BooleanField), `monthly_price` (DecimalField), `commitment_months` (PositiveIntegerField), `backup_eligible` (BooleanField), `valid_from` (DateTimeField), `valid_to` (DateTimeField), `metadata` (JSONField).
- Constraints: `unique_service_package_code_per_snapshot` (UniqueConstraint).

### `customers.ServicePackageAllowedSegment`
- Table: `customers_service_package_allowed_segment`; source: `backend/apps/customers/models.py`; rows: 66.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `service_package` (ForeignKey -> customers.ServicePackage), `segment` (CharField).
- Constraints: `unique_service_package_allowed_segment` (UniqueConstraint).

### `customers.ServicePackagePriceVersion`
- Table: `customers_service_package_price_version`; source: `backend/apps/customers/models.py`; rows: 80.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `service_package` (ForeignKey -> customers.ServicePackage), `amount` (DecimalField), `currency` (CharField), `valid_from` (DateTimeField), `valid_to` (DateTimeField), `version_number` (PositiveIntegerField), `active` (BooleanField), `metadata` (JSONField).
- Constraints: `unique_service_package_price_version_number` (UniqueConstraint), `service_package_price_version_valid_range` (CheckConstraint), `service_package_price_version_non_negative` (CheckConstraint).

### `customers.Subscription`
- Table: `customers_subscription`; source: `backend/apps/customers/models.py`; rows: 16440.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `subscription_number` (CharField), `customer` (ForeignKey -> customers.Customer), `service_package` (ForeignKey -> customers.ServicePackage), `sla_profile` (ForeignKey -> customers.SLAProfile), `status` (CharField), `suspension_reason` (CharField), `valid_from` (DateTimeField), `valid_to` (DateTimeField), `is_active` (BooleanField), `monthly_price` (DecimalField), `metadata` (JSONField).
- Constraints: `unique_subscription_number_per_snapshot` (UniqueConstraint), `subscription_valid_range` (CheckConstraint).

### `customers.SubscriptionConnection`
- Table: `customers_subscription_connection`; source: `backend/apps/customers/models.py`; rows: 16475.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `subscription` (ForeignKey -> customers.Subscription), `line_connection` (ForeignKey -> network.LineConnection), `valid_from` (DateTimeField), `valid_to` (DateTimeField), `is_active` (BooleanField), `connection_role` (CharField), `port_identifier` (CharField), `metadata` (JSONField).
- Constraints: `subscription_connection_valid_range` (CheckConstraint), `unique_open_active_connection_per_subscription_role` (UniqueConstraint), `unique_open_active_connection_per_line` (UniqueConstraint).

### `datasets.DataSnapshot`
- Table: `datasets_snapshot`; source: `backend/apps/datasets/models.py`; rows: 2.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `dataset_version` (ForeignKey -> datasets.DatasetVersion), `name` (CharField), `snapshot_key` (SlugField), `status` (CharField), `is_active` (BooleanField), `row_counts` (JSONField), `validation_status` (CharField), `validation_result` (JSONField), `source_started_at` (DateTimeField), `source_finished_at` (DateTimeField), `activated_at` (DateTimeField).
- Constraints: `one_active_data_snapshot` (UniqueConstraint).

### `datasets.DatasetVersion`
- Table: `datasets_version`; source: `backend/apps/datasets/models.py`; rows: 2.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `name` (CharField), `slug` (SlugField), `kind` (CharField), `generator_version` (CharField), `seed` (CharField), `config` (JSONField), `description` (TextField), `created_by` (ForeignKey -> accounts.User).
- Constraints: none declared in model Meta.

### `datasets.GroundTruthCase`
- Table: `datasets_ground_truth_case`; source: `backend/apps/datasets/models.py`; rows: 33.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `case_code` (CharField), `outage_code` (CharField), `expected_source_device_code` (CharField), `expected_incident_code` (CharField), `expected_alarm_type_codes` (JSONField), `expected_duration_minutes` (PositiveIntegerField), `expected_rule_code` (CharField), `expected_rule_version` (PositiveIntegerField), `affected_subscription_codes` (JSONField), `affected_subscription_hash` (CharField), `affected_subscription_count` (PositiveIntegerField), `affected_customer_codes` (JSONField), `affected_customer_hash` (CharField), `affected_customer_count` (PositiveIntegerField), `unaffected_subscription_count` (PositiveIntegerField), `unaffected_customer_count` (PositiveIntegerField), `affected_segment_counts` (JSONField), `affected_priority_counts` (JSONField), `expected_eligibility` (CharField), `expected_reason_code` (CharField), `expected_total_refund_amount` (DecimalField), `currency` (CharField), `metadata` (JSONField).
- Constraints: `unique_ground_truth_case_code_per_snapshot` (UniqueConstraint), `unique_ground_truth_case_outage_per_snapshot` (UniqueConstraint), `ground_truth_subscriptions_not_less_than_customers` (CheckConstraint), `ground_truth_refund_amount_non_negative` (CheckConstraint).

### `geography.City`
- Table: `geography_city`; source: `backend/apps/geography/models.py`; rows: 4.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `name` (CharField), `slug` (SlugField), `country_code` (CharField), `plate_code` (CharField), `metadata` (JSONField).
- Constraints: none declared in model Meta.

### `geography.District`
- Table: `geography_district`; source: `backend/apps/geography/models.py`; rows: 12.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `city` (ForeignKey -> geography.City), `name` (CharField), `slug` (SlugField), `profile_type` (CharField), `metadata` (JSONField).
- Constraints: `unique_district_slug_per_city` (UniqueConstraint), `unique_district_name_per_city` (UniqueConstraint).

### `geography.Neighborhood`
- Table: `geography_neighborhood`; source: `backend/apps/geography/models.py`; rows: 59.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `district` (ForeignKey -> geography.District), `name` (CharField), `slug` (SlugField), `profile_type` (CharField), `external_code` (CharField), `metadata` (JSONField).
- Constraints: `unique_neighborhood_slug_per_district` (UniqueConstraint), `unique_neighborhood_name_per_district` (UniqueConstraint).

### `network.AccessSegment`
- Table: `network_access_segment`; source: `backend/apps/network/models.py`; rows: 323.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `segment_code` (CharField), `name` (CharField), `slug` (SlugField), `technology` (CharField), `serving_device` (ForeignKey -> network.NetworkDevice), `city` (ForeignKey -> geography.City), `district` (ForeignKey -> geography.District), `neighborhood` (ForeignKey -> geography.Neighborhood), `estimated_customer_count` (PositiveIntegerField), `metadata` (JSONField).
- Constraints: `unique_access_segment_code_per_snapshot` (UniqueConstraint).

### `network.DeviceFailureDomainMembership`
- Table: `network_device_failure_domain_membership`; source: `backend/apps/network/models.py`; rows: 0.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `device` (ForeignKey -> network.NetworkDevice), `failure_domain` (ForeignKey -> network.FailureDomain).
- Constraints: `unique_device_failure_domain_membership` (UniqueConstraint).

### `network.FailureDomain`
- Table: `network_failure_domain`; source: `backend/apps/network/models.py`; rows: 2997.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `code` (CharField), `name` (CharField), `domain_type` (CharField), `description` (TextField).
- Constraints: `unique_failure_domain_code_per_snapshot` (UniqueConstraint).

### `network.LineConnection`
- Table: `network_line_connection`; source: `backend/apps/network/models.py`; rows: 16475.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `line_code` (CharField), `port` (ForeignKey -> network.NetworkPort), `access_segment` (ForeignKey -> network.AccessSegment), `technology` (CharField), `status` (CharField), `valid_from` (DateTimeField), `valid_to` (DateTimeField), `is_active` (BooleanField), `metadata` (JSONField).
- Constraints: `unique_line_connection_code_per_snapshot` (UniqueConstraint), `line_connection_valid_range` (CheckConstraint).

### `network.LineConnectionFailureDomainMembership`
- Table: `network_line_connection_failure_domain_membership`; source: `backend/apps/network/models.py`; rows: 1236.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `line_connection` (ForeignKey -> network.LineConnection), `failure_domain` (ForeignKey -> network.FailureDomain).
- Constraints: `unique_line_connection_failure_domain_membership` (UniqueConstraint).

### `network.NetworkDevice`
- Table: `network_device`; source: `backend/apps/network/models.py`; rows: 249.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `code` (CharField), `name` (CharField), `device_type` (CharField), `inventory_status` (CharField), `access_role` (CharField), `vendor` (CharField), `model_name` (CharField), `software_version` (CharField), `management_ip` (GenericIPAddressField), `city` (ForeignKey -> geography.City), `district` (ForeignKey -> geography.District), `neighborhood` (ForeignKey -> geography.Neighborhood), `metadata` (JSONField).
- Constraints: `unique_network_device_code_per_snapshot` (UniqueConstraint), `network_device_access_role_matches_type` (CheckConstraint).

### `network.NetworkLink`
- Table: `network_link`; source: `backend/apps/network/models.py`; rows: 257.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `link_code` (CharField), `source_device` (ForeignKey -> network.NetworkDevice), `target_device` (ForeignKey -> network.NetworkDevice), `status` (CharField), `capacity_mbps` (PositiveIntegerField), `metadata` (JSONField).
- Constraints: `unique_network_link_code_per_snapshot` (UniqueConstraint), `network_link_source_target_differ` (CheckConstraint).

### `network.NetworkLinkFailureDomainMembership`
- Table: `network_link_failure_domain_membership`; source: `backend/apps/network/models.py`; rows: 0.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `network_link` (ForeignKey -> network.NetworkLink), `failure_domain` (ForeignKey -> network.FailureDomain).
- Constraints: `unique_network_link_failure_domain_membership` (UniqueConstraint).

### `network.NetworkPort`
- Table: `network_port`; source: `backend/apps/network/models.py`; rows: 13841.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `device` (ForeignKey -> network.NetworkDevice), `port_code` (CharField), `port_type` (CharField), `inventory_status` (CharField), `capacity_mbps` (PositiveIntegerField), `metadata` (JSONField).
- Constraints: `unique_network_port_code_per_device_snapshot` (UniqueConstraint).

### `operations.Alarm`
- Table: `operations_alarm`; source: `backend/apps/operations/models.py`; rows: 2104.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `alarm_id` (CharField), `alarm_type` (ForeignKey -> operations.AlarmType), `device` (ForeignKey -> network.NetworkDevice), `network_link` (ForeignKey -> network.NetworkLink), `network_port` (ForeignKey -> network.NetworkPort), `line_connection` (ForeignKey -> network.LineConnection), `failure_domain` (ForeignKey -> network.FailureDomain), `subscription_connection` (ForeignKey -> customers.SubscriptionConnection), `severity` (CharField), `status` (CharField), `detected_at` (DateTimeField), `received_at` (DateTimeField), `acknowledged_at` (DateTimeField), `cleared_at` (DateTimeField), `last_seen_at` (DateTimeField), `occurrence_count` (PositiveIntegerField), `deduplication_key` (CharField), `suppression_reason` (CharField), `recurrence_group_key` (CharField), `raw_payload` (JSONField), `metadata` (JSONField).
- Constraints: `unique_alarm_id_per_snapshot` (UniqueConstraint), `unique_open_alarm_per_deduplication_key` (UniqueConstraint), `alarm_clear_time_after_detected_time` (CheckConstraint), `alarm_has_exactly_one_source` (CheckConstraint), `cleared_alarm_requires_cleared_at` (CheckConstraint).

### `operations.AlarmType`
- Table: `operations_alarm_type`; source: `backend/apps/operations/models.py`; rows: 33.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `code` (CharField), `name` (CharField), `severity` (CharField), `category` (CharField), `probable_cause_family` (CharField), `service_impact_class` (CharField), `auto_clear_policy` (CharField), `deduplication_window_seconds` (PositiveIntegerField), `correlation_family` (CharField), `default_incident_type` (CharField), `is_root_candidate` (BooleanField), `description` (TextField), `metadata` (JSONField).
- Constraints: `unique_alarm_type_code_per_snapshot` (UniqueConstraint).

### `operations.AlarmTypeAllowedSourceKind`
- Table: `operations_alarm_type_allowed_source_kind`; source: `backend/apps/operations/models.py`; rows: 35.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `alarm_type` (ForeignKey -> operations.AlarmType), `source_kind` (CharField).
- Constraints: `unique_alarm_type_allowed_source_kind` (UniqueConstraint).

### `operations.AlarmTypeSupportedDeviceType`
- Table: `operations_alarm_type_supported_device_type`; source: `backend/apps/operations/models.py`; rows: 17.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `alarm_type` (ForeignKey -> operations.AlarmType), `device_type` (CharField).
- Constraints: `unique_alarm_type_supported_device_type` (UniqueConstraint).

### `operations.Incident`
- Table: `operations_incident`; source: `backend/apps/operations/models.py`; rows: 213.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `incident_number` (CharField), `title` (CharField), `status` (CharField), `severity` (CharField), `incident_type` (CharField), `service_impact_class` (CharField), `correlation_method` (CharField), `failover_result` (CharField), `transition_duration_seconds` (PositiveIntegerField), `primary_device` (ForeignKey -> network.NetworkDevice), `root_cause_category` (CharField), `root_cause_summary` (CharField), `detected_at` (DateTimeField), `started_at` (DateTimeField), `resolved_at` (DateTimeField), `restored_at` (DateTimeField), `closed_at` (DateTimeField), `metadata` (JSONField).
- Constraints: `unique_incident_number_per_snapshot` (UniqueConstraint), `incident_resolved_after_started` (CheckConstraint), `incident_closed_after_started` (CheckConstraint).

### `operations.IncidentAlarm`
- Table: `operations_incident_alarm`; source: `backend/apps/operations/models.py`; rows: 424.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `incident` (ForeignKey -> operations.Incident), `alarm` (ForeignKey -> operations.Alarm), `role` (CharField), `metadata` (JSONField).
- Constraints: `unique_alarm_per_incident` (UniqueConstraint).

### `operations.MaintenanceWindow`
- Table: `operations_maintenance_window`; source: `backend/apps/operations/models.py`; rows: 30.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `reference_code` (CharField), `status` (CharField), `planned_start_at` (DateTimeField), `planned_end_at` (DateTimeField), `actual_start_at` (DateTimeField), `actual_end_at` (DateTimeField), `expected_impact_class` (CharField), `actual_impact_class` (CharField), `overrun_minutes` (PositiveIntegerField), `description` (TextField), `linked_incident` (ForeignKey -> operations.Incident).
- Constraints: `unique_maintenance_window_reference_per_snapshot` (UniqueConstraint), `maintenance_planned_end_after_start` (CheckConstraint), `maintenance_actual_end_requires_start` (CheckConstraint).

### `operations.MaintenanceWindowDevice`
- Table: `operations_maintenance_window_device`; source: `backend/apps/operations/models.py`; rows: 30.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `maintenance_window` (ForeignKey -> operations.MaintenanceWindow), `device` (ForeignKey -> network.NetworkDevice).
- Constraints: `unique_maintenance_window_device` (UniqueConstraint).

### `operations.MaintenanceWindowNetworkLink`
- Table: `operations_maintenance_window_network_link`; source: `backend/apps/operations/models.py`; rows: 30.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `maintenance_window` (ForeignKey -> operations.MaintenanceWindow), `network_link` (ForeignKey -> network.NetworkLink).
- Constraints: `unique_maintenance_window_network_link` (UniqueConstraint).

### `operations.OperationalEvent`
- Table: `operations_operational_event`; source: `backend/apps/operations/models.py`; rows: 912.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `event_code` (CharField), `event_type` (CharField), `occurred_at` (DateTimeField), `device` (ForeignKey -> network.NetworkDevice), `incident` (ForeignKey -> operations.Incident), `source` (CharField), `summary` (CharField), `metadata` (JSONField).
- Constraints: `unique_operational_event_code_per_snapshot` (UniqueConstraint).

### `operations.Outage`
- Table: `operations_outage`; source: `backend/apps/operations/models.py`; rows: 81.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `outage_code` (CharField), `incident` (ForeignKey -> operations.Incident), `source_device` (ForeignKey -> network.NetworkDevice), `outage_type` (CharField), `impact_type` (CharField), `status` (CharField), `root_cause_category` (CharField), `root_cause_summary` (CharField), `detected_at` (DateTimeField), `started_at` (DateTimeField), `ended_at` (DateTimeField), `resolved_at` (DateTimeField), `restored_at` (DateTimeField), `transition_duration_seconds` (PositiveIntegerField), `impact_scope` (JSONField), `metadata` (JSONField).
- Constraints: `unique_outage_code_per_snapshot` (UniqueConstraint), `outage_end_after_start` (CheckConstraint), `outage_resolved_at_or_after_start` (CheckConstraint).

### `operations.QualityMeasurement`
- Table: `operations_quality_measurement`; source: `backend/apps/operations/models.py`; rows: 12000.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `device` (ForeignKey -> network.NetworkDevice), `network_link` (ForeignKey -> network.NetworkLink), `line_connection` (ForeignKey -> network.LineConnection), `subscription_connection` (ForeignKey -> customers.SubscriptionConnection), `metric_type` (CharField), `measured_at` (DateTimeField), `value` (DecimalField), `unit` (CharField), `metadata` (JSONField).
- Constraints: `unique_quality_measurement_per_metric_time` (UniqueConstraint), `unique_quality_measurement_per_link_metric_time` (UniqueConstraint), `unique_quality_measurement_per_line_metric_time` (UniqueConstraint), `unique_quality_measurement_per_sub_conn_metric_time` (UniqueConstraint), `quality_measurement_has_exactly_one_source` (CheckConstraint).

### `rag.DocumentChunk`
- Table: `rag_document_chunk`; source: `backend/apps/rag/models.py`; rows: 74.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `source_document` (ForeignKey -> rag.SourceDocument), `sequence` (PositiveIntegerField), `heading` (CharField), `section_path` (JSONField), `text` (TextField), `content_hash` (CharField), `char_start` (PositiveIntegerField), `char_end` (PositiveIntegerField), `token_start` (PositiveIntegerField), `token_end` (PositiveIntegerField), `valid_from` (DateTimeField), `valid_to` (DateTimeField), `rule_code` (CharField), `rule_version` (PositiveIntegerField), `embedding` (VectorField), `embedding_provider` (CharField), `embedding_model` (CharField), `embedding_version` (CharField), `embedding_dimensions` (PositiveIntegerField), `metadata` (JSONField).
- Constraints: `rag_chunk_document_sequence_uniq` (UniqueConstraint), `rag_chunk_char_bounds_pair` (CheckConstraint), `rag_chunk_token_bounds_pair` (CheckConstraint), `rag_chunk_valid_range` (CheckConstraint).

### `rag.DocumentChunkEmbedding`
- Table: `rag_document_chunk_embedding`; source: `backend/apps/rag/models.py`; rows: 296.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `document_chunk` (ForeignKey -> rag.DocumentChunk), `provider` (CharField), `model` (CharField), `dimensions` (PositiveIntegerField), `embedding_version` (CharField), `prompt_version` (CharField), `content_hash` (CharField), `embedding` (VectorField).
- Constraints: `rag_chunk_embedding_identity_uniq` (UniqueConstraint), `rag_chunk_embedding_dimensions_768` (CheckConstraint).

### `rag.IndexRun`
- Table: `rag_index_run`; source: `backend/apps/rag/models.py`; rows: 15.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `status` (CharField), `started_at` (DateTimeField), `completed_at` (DateTimeField), `source_count` (PositiveIntegerField), `chunk_count` (PositiveIntegerField), `embedding_count` (PositiveIntegerField), `embedding_provider` (CharField), `embedding_model` (CharField), `embedding_dimensions` (PositiveIntegerField), `source_digest` (CharField), `error_summary` (TextField), `metadata` (JSONField).
- Constraints: none declared in model Meta.

### `rag.SourceDocument`
- Table: `rag_source_document`; source: `backend/apps/rag/models.py`; rows: 10.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `document_code` (CharField), `title` (CharField), `document_type` (CharField), `source_kind` (CharField), `version` (PositiveIntegerField), `language` (CharField), `content` (TextField), `content_hash` (CharField), `is_synthetic` (BooleanField), `status` (CharField), `valid_from` (DateTimeField), `valid_to` (DateTimeField), `metadata` (JSONField).
- Constraints: `rag_doc_snapshot_code_version_uniq` (UniqueConstraint), `rag_doc_global_code_version_uniq` (UniqueConstraint), `rag_doc_valid_range` (CheckConstraint).

### `rules.Rule`
- Table: `rules_rule`; source: `backend/apps/rules/models.py`; rows: 26.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `rule_set` (ForeignKey -> rules.RuleSet), `code` (CharField), `name` (CharField), `rule_type` (CharField), `family` (CharField), `conflict_group` (CharField), `status` (CharField), `description` (TextField), `metadata` (JSONField).
- Constraints: `unique_rule_code_per_snapshot` (UniqueConstraint).

### `rules.RuleChangeSet`
- Table: `rules_change_set`; source: `backend/apps/rules/models.py`; rows: 0.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `change_set_code` (CharField), `title` (CharField), `status` (CharField), `reason` (TextField), `requested_by` (ForeignKey -> accounts.User), `approved_by` (ForeignKey -> accounts.User), `approved_at` (DateTimeField), `metadata` (JSONField).
- Constraints: `unique_rule_change_set_code_per_snapshot` (UniqueConstraint).

### `rules.RuleSet`
- Table: `rules_rule_set`; source: `backend/apps/rules/models.py`; rows: 1.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `code` (CharField), `version` (PositiveIntegerField), `name` (CharField), `effective_from` (DateTimeField), `effective_to` (DateTimeField), `active` (BooleanField), `change_reason` (TextField), `metadata` (JSONField).
- Constraints: `unique_rule_set_code_version_per_snapshot` (UniqueConstraint), `rule_set_effective_range` (CheckConstraint).

### `rules.RuleTestCase`
- Table: `rules_test_case`; source: `backend/apps/rules/models.py`; rows: 0.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `rule` (ForeignKey -> rules.Rule), `rule_version` (ForeignKey -> rules.RuleVersion), `name` (CharField), `status` (CharField), `input_payload` (JSONField), `expected_output` (JSONField), `metadata` (JSONField).
- Constraints: `unique_rule_test_case_name` (UniqueConstraint).

### `rules.RuleVersion`
- Table: `rules_rule_version`; source: `backend/apps/rules/models.py`; rows: 27.
- Fields: `id` (BigAutoField), `created_at` (DateTimeField), `updated_at` (DateTimeField), `data_snapshot` (ForeignKey -> datasets.DataSnapshot), `rule` (ForeignKey -> rules.Rule), `version` (PositiveIntegerField), `status` (CharField), `priority` (PositiveIntegerField), `action_type` (CharField), `price_basis` (CharField), `stackable` (BooleanField), `active` (BooleanField), `valid_from` (DateTimeField), `valid_to` (DateTimeField), `condition_tree` (JSONField), `action_config` (JSONField), `change_note` (TextField), `change_set` (ForeignKey -> rules.RuleChangeSet), `created_by` (ForeignKey -> accounts.User), `metadata` (JSONField).
- Constraints: `unique_rule_version_number` (UniqueConstraint), `rule_version_valid_range` (CheckConstraint).
