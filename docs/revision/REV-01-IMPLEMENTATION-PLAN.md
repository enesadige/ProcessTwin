# REV-01 Uygulama Planı

> **Güncel durum notu:** Bu doküman REV serisinin tarihsel uygulama planıdır.
> REV-00–REV-12, orchestration, frontend shell/auth/AI Analysis ve sonraki
> grounded narrative/correlation güvenlik işleri tamamlanmıştır. Güncel görev
> sırası `docs/CODEX_HANDOFF.md` içindeki **Kilitli Sonraki Öncelik** bölümüdür:
> kalibrasyondan önce dataset inventory / audit, sonra kalan `MAIN-066`+
> frontend işleri ve final polish. `MAIN-061` veya PRE-061 blocker'ı güncel
> değildir.

> **2026-08-13 analytics checkpoint:** `1b8b0af` ile mevcut
> sentetik/erişilebilir veri setinde deterministic operational
> trend/ranking/aggregate analytics tamamlandı. Hesaplama `CausalEvent`
> granülünde yapılır; semptom alarmlar customer impact'i çoğaltmaz ve unknown
> impact sıfıra çevrilmez. Typed metric/aggregation/group/filter/ranking/time
> sözleşmesi backend tarafından doğrulanır; provider yalnız verified sonucu
> anlatır. Sonraki iş `MAIN-066` ve kalan frontend tamamlamalarıdır.

> **2026-08-13 cloud LLM provider checkpoint:** NVIDIA GLM-5.2
> (`nvidia` / `z-ai/glm-5.2`) ve Groq GPT-OSS 120B
> (`groq` / `openai/gpt-oss-120b`) mevcut LLM registry ve ortak
> OpenAI-compatible chat adapter ile eklendi. Her iki adapter mevcut
> Phase 2 ve Phase 1B sözleşmesini kullanır; deterministic AnswerPlan,
> grounding, embedding seçimi ve domain hesapları değişmedi. API anahtarları
> yalnız `NVIDIA_API_KEY`/`GROQ_API_KEY` ortam değişkenlerindedir. Canlı
> ön-kontrol ve AGG-ANK-002 kabulü iki provider ile de geçti; Groq Phase 2
> `json_object` transportuyla uyumlu hale getirildi (`ef436ea`). NVIDIA'nın
> sonraki analytics narrative çağrısındaki dış rate-limit nedeniyle genel
> kabul `PARTIAL_PROVIDER_LIMIT` olarak kaydedildi. Sonraki iş kalibrasyondan
> önce dataset inventory / audit'tir. Provider kod commit'i: `c66ef23`.

Bu plan hedef tasarımdır; REV-01 kapsamında implementation yapılmaz. Sıra, schema ve nedensel generator olmadan service/API/MCP davranışının değiştirilmemesi için düzenlenmiştir.

## İlerleme

- `REV-02` tamamlandı: `apps.operations.contracts` içindeki modelden bağımsız
  enum, dataclass, validation ve privacy serialization sözleşmeleri
  `REV-02-DOMAIN-CONTRACTS.md` ile tanımlandı. Django modeli, migration, API ve
  MCP yüzeyi değiştirilmedi.
- `REV-03` tamamlandı: `operations.0004` migration'ı `CausalEvent`,
  `SessionEvent` ve `CustomerImpactAssessment` modellerini ekledi; mevcut
  operasyon kayıtlarına nullable causal relation eklendi. Legacy kayıtlar
  `causal_event=NULL` kalır, sahte causal backfill yapılmaz.
- `REV-04` tamamlandı: GPON/DSL/Metro alarm kaynak uyumluluğu için merkezi
  topology validator eklendi; katalog 31. tip olarak
  `DISTRIBUTION_CABLE_DOWN` ile genişletildi. Mevcut alarm kayıtları ve
  generator event üretimi değiştirilmedi.

| Sıra / görev adı | Amaç | Ana değişiklikler | Ana katmanlar | Testler | Kabul kriteri | Commit mesajı |
|---|---|---|---|---|---|---|
| REV-02 — Operasyon sözleşmeleri ve enumlar | **Tamamlandı.** Causal event, impact verification ve session kanıtının kesin backend sözleşmesini tanımlamak | Enum/field isimleri, status transitions, privacy/redaction ve API additive-field contract tasarımı | `operations`, `customers`, `core` doküman/test fixture'ları | schema/contract tasarım testleri | Açık enum, state machine ve legacy mapping kabul edildi | `feat: define causal operations contracts` |
| REV-03 — Nedensel operasyon modelleri | **Tamamlandı.** Sorgulanabilir ortak olay kökünü ve impact/session kayıtlarını eklemek | `CausalEvent`, `CustomerImpactAssessment`, `SessionEvent`; mevcut operasyon modellerine nullable causal FK; `ground_truth_cases` row-count sync migration'ı | Django models, migrations, admin | model constraints, migration/backfill, PII-safe validation | Legacy kayıtlar korunur; snapshot isolation ve unique constraints çalışır | `feat: add causal operations models` |
| REV-04 — GPON topology ve alarm katalog tutarlılığı | **Tamamlandı.** OLT/PON/segment/failure-domain kaynak doğruluğunu kurmak | Merkezi compatibility validator; PON/DSL/Metro kaynak kuralları; idempotent catalog seed; `DISTRIBUTION_CABLE_DOWN` | `operations`, data configs | topology, source compatibility, PON/DSL/Metro validators | PON alarmı yalnız OLT/PON portunda; DSL/Metro uyumluluğu doğrulanır | `feat: enforce GPON alarm topology catalog` |
| REV-05 — Nedensel GPON generator | **Tamamlandı.** Ayrı döngüler yerine aynı scenario zincirinden operasyon verisi üretmek | 7 GPON scenario, relative timeline, causal IDs, alarm roles, clear/recovery, no-impact/hitless cases | `data_generator`, datasets commands | deterministic seed, causal-chain, no-outage/no-impact, row-count tests | Alarm/incident/outage/event aynı scenario zincirine bağlı; sabit 70 loop kaldırıldı | `feat: generate causal GPON operations data` |
| REV-05A — Anonim alarm kalibrasyonu | **Tamamlandı.** Alan örneğini runtime bağımlılığı yapmadan normalizasyon ve symptom fanout sinyali olarak kullanmak | Typed raw-title mapping, source-context conditional alias, raw severity precedence, bounded Dying-Gasp fanout | `operations`, `data_generator`, docs | normalization ve causal fanout hedefli testleri | CSV import edilmez; 7 scenario ve REV-04 validator korunur | `feat: calibrate alarm normalization from field sample` |
| REV-06 — Correlation ve root-cause revizyonu | **Tamamlandı.** CausalEvent sınırı, zaman/topoloji/failure-domain kanıtı ve role tabanlı root ranking | delayed propagation, root/child/symptom/supporting/unrelated/noise sonuçları, legacy conservative fallback, privacy-safe explainability | `operations/services` | causal boundary, delayed propagation, symptom/supporting ve root-resource regression | 08.00 upstream kök ile gecikmeli downstream semptom açıklanabilir; farklı event'ler karışmaz | `feat: revise causal alarm correlation` |
| REV-07 — Session doğrulama ve impact assessment | **Tamamlandı.** Potential topology scope'u connection-level session kanıtıyla verified/no-impact/insufficient olarak ayırmak | idempotent assessment persistence, session lifecycle, backup/failover ve privacy-safe aggregate summary | `operations/services` | stop/restart, active session, incomplete evidence, failover ve idempotency | Verified impact potential setin alt kümesidir; session yoksa verified denmez | `feat: verify customer impact from sessions` |
| REV-08 — Outage, rule, compensation ve evidence | **Tamamlandı.** Verified connection impact'i mevcut deterministic compensation ve immutable evidence zincirine bağlamak | verified-only scope adapter, privacy-safe impact aggregate/provenance, idempotent evidence | `compensation/services` | verified/non-verified scope ve evidence idempotency regressions | No-impact/insufficient compensation üretmez; mevcut REFUND regression korunur | `feat: bind verified impact to compensation evidence` |
| REV-09 — Backend internal API uyarlaması | **Tamamlandı.** Read-only CausalEvent analysis özeti | internal operations endpoint, auth/404/pending-safe response | `operations/internal_*` | auth ve response contract | Legacy consumer alanları korunur | `feat: expose causal analysis through internal api` |
| REV-10 — Dört MCP uyarlaması | **Tamamlandı.** Causal analysis kanıtlarını mevcut MCP araçlarına additive yansıtmak | Network/Customer/Rule/Compensation causal public-code mapping ve koşullu legacy validation | `mcp_servers` | tool unit, API ve shared contracts | Tool sayıları 9/7/8/6 korunur; raw/PII sızmaz | `fix: complete causal mcp contracts` |
| REV-11 — RAG corpus ve benchmark yenilemesi | **Tamamlandı.** Causal analysis terminolojisini immutable source sürümleriyle aratılabilir yapmak | 3 causal source/version, 9 benchmark vakası, iki aktif embedding seti | `rag`, `documents` | corpus/hash/chunk/search/benchmark ve Rule MCP retrieval | Eski source version korunur; canlı index sayıları DB erişimi yokken iddia edilmez | `feat: refresh rag corpus for causal analysis` |
| REV-12 — Final consistency ve regresyon | **Tamamlandı.** Yeni veri zincirini uçtan uca kapatmak | full suite, MCP/API/RAG contracts ve native non-destructive gates | tüm backend/MCP/datasets | 667 passed, Ruff, Django check | Native mevcut snapshot precondition mismatch'i açık blocker olarak kaldı | `chore: close causal revision integration gate` |

PRE-052 — **Tamamlandı.** Eski snapshot ve PROTECT bağlı RAG kayıtları
silinmeden, güncel causal generator'dan versioned native snapshot üretildi.
Görev 052 snapshot identifier'ı
`multi-city-realism-v2-causal-r1-multi-city-realism-snapshot-v1-multi-city-realism-v2-causal-r1`;
native realism gate PASS, katalog 31, CausalEvent 198, SessionEvent 496 ve
GroundTruthCase 30'dur. Corpus idempotent seed edildi; yeni causal kaynakların
chunk index'i doğrulandı. Commit: `feat: create versioned causal dataset snapshot`.

Görev 052 — **Tamamlandı.** `apps.orchestration` içindeki `QueryRun`, explicit
`DataSnapshot`/`PROTECT`, global unique idempotency key, terminal run'a bağlı
retry, privacy-safe JSON audit alanları ve `pending -> planned -> executing ->
completed|failed` yaşam döngüsünü ekledi. Planner, MCP executor, RAG retrieval
çağrısı ve LLM final cevabı bu görevde uygulanmadı; sıradaki Görev 053
provider interface/registry çalışmasına bırakıldı.

Görev 053 — **Tamamlandı.** `apps.orchestration.providers` içinde immutable
allowlist registry, LLM provider interface'i ve Gemini/Ollama descriptor'ları
eklendi. Gemma `gemma4:12b-it-qat` için thinking policy zorunlu olarak kapalı;
onaylı Gemini model adı olmadığı için Gemini descriptor'ı provider-level'dır.
Gerçek provider adapter'ı veya network çağrısı yoktur. LLM provider seçimi RAG
embedding registry'sinden bağımsız kalır. Sıradaki görev Görev 053A mock LLM
provider'dır.

Görev 053A — **Tamamlandı.** `MockLLMProvider` canonicalized privacy-safe
mapping input ile deterministic success/empty response ve controlled failure
senaryoları üretir; gerçek network/model çağrısı yapmaz. `mock` descriptor'ı
yalnız `LLM_ALLOW_MOCK_PROVIDER=true` test/development izniyle factory üzerinden
oluşturulur; production varsayılanı kapalıdır. QueryRun entegrasyonu, gerçek
Gemini/Ollama adapter'ı ve orchestration bu görevde uygulanmadı. Sıradaki görev
Görev 053B Gemini LLM adapter'ıdır.

Görev 053B — **Tamamlandı.** `GeminiLLMProvider`, sabit
`gemini-3.5-flash` descriptor/factory ile lazy `google-genai` client kullanır.
Girdi yalnız normalized `contents` alanıdır; response ortak content/finish
reason/provider/model/usage contract'ına dönüştürülür. Timeout, en fazla üç
denemelik transient retry ve redakte stabil hata kodları vardır. Gerçek API
çağrısı, QueryRun integration, planner, MCP/RAG execution ve final cevap bu
görevde uygulanmadı. Sıradaki görev Görev 053C Ollama LLM adapter'ıdır.

Görev 053C — **Tamamlandı.** `OllamaLLMProvider`, sabit
`gemma4:12b-it-qat` modelini lazy `httpx` istemcisiyle `/api/chat` üzerinden
çağırır. Normalized girdi yalnız `contents` alanıdır; her request top-level
`think: false` ve `stream: false` taşır. Timeout, en fazla üç transient retry,
normalize usage/finish response'u ve redakte stabil hata sözleşmesi vardır.
Gerçek Ollama smoke, Qwen/Gemma bellek sıralama orchestration'ı, QueryRun
entegrasyonu, planner, MCP/RAG execution ve final cevap uygulanmadı; Qwen
embedding `keep_alive=0` politikası değişmedi. Sıradaki görev Görev 054
StructuredQuery schema'dır.

Görev 054 — **Tamamlandı.** `StructuredQuery` Pydantic sözleşmesi strict
intent/requested-output/technology/clarification allowlist'leri, public event
reference önceliği, nested location ve timezone-aware time-window validation'ı
sağlar. Extra/raw/PK/tool alanları reddedilir. `QueryRunService`, yalnız geçerli
normalize şemayı eşleşen snapshot'taki pending kayda idempotent biçimde yazıp
planned durumuna geçirir;
LLM ile doğal dilden üretim, tool planı, MCP/RAG execution ve final cevap bu
görevde uygulanmadı. Sıradaki görev Görev 055 tool-plan schema'dır.

Görev 055 — **Tamamlandı.** `ToolPlan`/`ToolCall` Pydantic sözleşmeleri dört
mevcut MCP tool registry'sinden allowlist server/tool/input modelini çözer.
Her çağrının arguments alanı ilgili MCP Pydantic input modeliyle doğrulanır;
snapshot/context eşleşmesi, privacy, duplicate, dependency ve parallel-group
invariant'ları korunur. Yalnız valid plan planned `QueryRun.planned_tools`
alanına idempotent yazılır ve run planned kalır. LLM planner, MCP/RAG execution
ve final cevap bu görevde uygulanmadı. Sıradaki görev Görev 056 planner'dır.

Görev 056 — **Tamamlandı.** `DeterministicToolPlanner`, valid
`StructuredQuery` için allowlisted MCP araçlarıyla kural tabanlı `ToolPlan`
üretir ve yalnız successful planı `save_tool_plan` ile planned QueryRun'a yazar.
Causal event code önceliklidir; clarification/unplannable sonuçları değişiklik
yapmaz. Kişisel identity üretilmez; compensation yalnız causal/outage public
evidence yolu varsa planlanır. LLM, MCP/RAG execution, result merge ve final
cevap uygulanmadı. Sıradaki görev Görev 057 MCP executor'dır.

052-056 Orchestration Integration Gate — **Tamamlandi.** Explicit snapshot ile
QueryRun -> StructuredQuery -> deterministic ToolPlan zinciri tek offline smoke
ile idempotent olarak dogrulandi. Hedefli provider/schema/MCP contract seti 236
passed, full suite 807 passed; gercek LLM, MCP, RAG veya model cagrisi yapilmadi.
MCP tool sayilari 9/7/8/6 kaldi. Siradaki gorev: Gorev 057 - MCP executor.

Gorev 057 — **Tamamlandi.** `ToolExecutor`, persisted ToolPlan'i mevcut MCP
tool siniflarina sirali ve deterministic olarak yonlendirir. Dependency failure
bagli call'i skip eder, bagimsiz call'lar devam eder; yalniz explicit read-only
allowlist retry edilir. QueryRun `executing` kalir ve ham response yerine
privacy-safe call audit ozetleri saklanir. Result merge, validation ve terminal
karar Gorev 058'e birakildi.

Gorev 058 — **Tamamlandi.** `ResultMergerValidator`, fresh runtime MCP
sonuclarini yalniz explicit server/tool response normalizer'lariyla typed,
privacy-safe `ValidatedExecutionResult`a donusturur. Required evidence
policy'si StructuredQuery intent/requested-output degerlerinden turetilir;
optional retrieval/supporting failure partial warning olarak kalabilir, fakat
required failure, snapshot/reference conflict veya impact/compensation
invariant ihlali QueryRun'i `failed` yapar. Valid sonuc `executing ->
completed` gecisiyle normalize `final_result`a yazilir. Persisted audit
ozetlerinde raw runtime response olmadigindan audit-only resume
`runtime_result_unavailable` ile guvenli bicimde durur. Dogal dil response
builder siradaki Gorev 059'a birakildi.

Gorev 059 — **Tamamlandi.** `ValidatedResponseBuilder`, yalniz completed ve
valid `QueryRun.final_result` uzerinden canonical Turkce fact bloklari render
eder; QueryRun ve persisted final_result degistirilmez. LLM-assisted mod yalniz
privacy-safe fact sheet ile kisa anlatim ekleyebilir. Yeni sayi, public
reference veya karar terimi tespitinde ya da provider hatasinda deterministic
fallback kullanilir. Retrieval sonuclari citation olarak kalir; endpoint ve
E2E orchestration Gorev 060'a birakildi.

Gorev 060 — **Tamamlandi.** Internal service-token authentication kullanan
senkron endpoint, explicit snapshot ile `QueryRun -> StructuredQuery ->
deterministic planner -> ToolExecutor -> ResultMergerValidator ->
ValidatedResponseBuilder` zincirini ince facade uzerinden baglar. Completed
idempotency replayi MCP execution'i tekrar etmez; clarification/unplannable
run planned kalir, executing run 202, conflict 409 ve terminal failure yeni
idempotency key gerektirir. Endpoint yalniz privacy-safe typed response veya
stable hata doner; gercek network/model cagrilari testlerde kullanilmadi.

**Görev takip notu:** Ana plandaki 052–060, causal revizyon serisi
`REV-00–REV-12`, frontend `MAIN-061`–`MAIN-065` ve sonraki grounded narrative,
cross-incident correlation ve unanswerable/partial-answer güvenlik işleri
tamamlanmıştır. Genel trend/ranking/aggregate analytics de tamamlandı. Güncel
sıra: kalibrasyondan önce dataset inventory / audit; kalan `MAIN-066`+
frontend işleri; final polish, geniş regresyon ve demo hazırlığı.

## Zorunlu domain consistency validator'ları

- Alarm type kaynak teknoloji ve source level ile uyumludur.
- PON alarmı OLT/PON portunda; DSL alarmı DSLAM/xDSL port/line'ında oluşur.
- Incident zamanı bağlı alarm zinciriyle tutarlıdır; root alarm child alarmdan sonra başlayamaz.
- Primary device, bağlı root/source alarmıyla topolojik olarak ilişkilidir.
- `creates_outage=false` scenario Outage oluşturmaz.
- Hitless failover Outage ve verified impact oluşturmaz.
- Verified impact, potential impact kümesinin dışına çıkmaz.
- Clear/recovery sırası causality ve session recovery ile tutarlıdır.
- Session kanıtı olmayan sonuç verified diye işaretlenmez.
- Snapshot `row_counts`, gerçek model sayılarıyla eşleşir.

## Uygulama öncesi açık karar kapıları

1. Session kaynak alan eşlemesi, pseudonymization ve retention politikası.
2. CausalEvent state/role enumlarının REV-02’de kesinleştirilmesi.
3. Outage verification state'in additive alan mı, ayrı assessment mi olacağı; hedef öneri additive verification alanı + assessment'tır.
4. GPON scenario weight'leri ve kaynak eşiklerinin örnek CSV/log geldikten sonra kalibrasyonu.
5. Ticari policy, özellikle 24 saat ifadesi, bağımsız rule governance ile teyit edilmeden değişmeyecektir.

## 2026-08-14 — V3 final acceptance ve güvenli activation

- Validated V3 repair snapshot `74`, immutable V2 rollback snapshot `54` ve
  original V3 candidate `73` korunarak AI Analysis varsayılanına alındı.
  Authoritative seçim `is_active` değil, frontend'in backend'e gönderdiği exact
  snapshot anahtarıdır.
- Base-world fingerprint, failed/hitless failover, compensation persistence,
  correlation, RAG/Local Qwen retrieval ve generic analytics kabulü doğrulandı.
  Unknown impact sıfırlaştırılmaz; exhaustive ranking ve explicit top-N semantics korunur.
- V3: 91 schedule + 3 helper event, 420 alarm, 77.125 SessionEvent, 49.996
  assessment, 10.658 CompensationEvaluation, 10.716 DecisionEvidence.
  Activation/integration commit: `60fa4fa`.
- Rollback: frontend exact snapshot anahtarını snapshot 54'e geri çevir; eski
  QueryRun replay'leri değişmez. Sonraki görev `MAIN-066`; bu görevde başlatılmadı.

## 2026-08-14 — V3 trend/grouping regression fix

- `1986ac2` generic comparison contract'ını grouping ile compose edecek şekilde
  düzeltti. City ve root alarm type comparison sonuçları dönem bazlı değer,
  signed fark, yön ve unknown-exclusion metadata'sını taşır; explicit top-N
  korunur.
- Canonical analytics `included_event_count` AnswerPlan'a eklendi. Snapshot 74,
  RAG, provider ve activation mekanizması değiştirilmedi.

## 2026-08-14 — V3 / AI Analysis final acceptance

- Active snapshot `74` ile trend/ranking, specific operational investigation,
  alarm correlation, evidence-limit ve unknown-exclusion kabulü tamamlandı.
- Forecast ve remediation/command/field-procedure talepleri generic deterministic
  unsupported contract'a alındı; desteklenen event/impact/correlation yolları
  korunur. Son commit: `9d7dbca`.
- Sonraki görev `MAIN-066`: BNG'den alt cihazlara ve müşteri etkisine uzanan
  topoloji özet görünümü; bu kayıtta başlatılmadı.

## 2026-08-14 — AI Analysis general reliability hardening

- `be6cb7c` analytics sorgularında filter/grouping ayrımını, persisted
  outage/alarm count toplamını ve empty-scope sonucunun zero sayılmaması
  sözleşmesini düzeltti.
- Predictive probability intentleri unsupported kapsamına alındı; supported
  event/impact/correlation/analytics yolları korunur.
- Snapshot 74 üzerinde gerçek backend/MCP ile 15 representative case çalıştı:
  12 completed, 3 unsupported deterministic early exit. Sonraki görev MAIN-066.

## 2026-08-14 — MAIN-066 topology summary

- `f2a4e48` AI Analysis'e full graph olmayan, read-only ve snapshot-local bir
  topology summary ekledi. Doğrulanmış device root için upstream/kök/sınırlı
  downstream erişim zinciri, mevcut connection role metadata'sı ve persisted
  scope gösterilir.
- Snapshot 74 değişmedi; yeni customer impact/failover hesabı yapılmadı.
  Snapshot smoke ve focused backend/frontend kontrolleri PASS. Sonraki görev
  `MAIN-067`dir.

## 2026-08-14 — MAIN-067 rule ve RAG provenance görünümü

- AI Analysis sonucu, mevcut validated execution provenance'ından seçilmiş
  RuleVersion, DecisionEvidence ve RAG document code/version/heading/section
  bilgisini kullanıcıya görünür taşır.
- Retrieval skoru yeni arama çalıştırılmadan mevcut sonuçtan alınır: öncelik
  `hybrid_score`, ardından `semantic_score`, sonra `full_text_score`dur.
  RAG yalnız citation/retrieval kaynağıdır; karar ve operasyonel sayı hesaplamaz.
- Boş kaynakta sahte kart yoktur; topology summary ile bağımsız bölümler birlikte
  çalışır. Sonraki görev `MAIN-068`dir.

## 2026-08-14 — MAIN-068 DecisionEvidence linki

- AI Analysis provenance kartındaki gerçek DecisionEvidence referansı,
  snapshot identifier ve evidence hash ile `/evidence` detay görünümüne bağlandı.
- Browser yalnız authenticated public read endpointini kullanır. Endpoint mevcut
  immutable evidence serializer'ını reuse eder ve `snapshot + evidence_hash`
  dışında fallback yapmaz; missing/mismatch güvenli not-found döner.
- Detail ekranı selected RuleVersion, decision/finalized, evaluation/outage,
  tutar ve mevcut koşul/inceleme kanıtlarını gösterir. Sonraki görev `MAIN-069`dur.

## 2026-08-14 — MAIN-069 Frontend Hata ve Boş Durumları

- AI Analysis'te mevcut backend response ayrımları korunarak clarification,
  unsupported, retryable failure, access ve not-found durumları görünür ve
  erişilebilir hale getirildi. Stale sonuç/progress temizlenir; retry yalnız
  geçici hatalarda kullanılabilir.
- Evidence detail ekranı eksik parametre, snapshot mismatch/not-found, erişim
  ve geçici hata için ayrı durumlar sunar. Topology summary veri yok/yükleme
  hatasında sessizce kaybolmaz.
- Snapshot 74, analytics, RAG, provider ve backend hata semantiği değişmedi.
  Sonraki görev `MAIN-070`; başlatılmayacak.

## 2026-08-14 — MAIN-070 Genel Evidence Veri Modeli

- `EvidenceRecord`, `EvidenceToolCall`, `EvidenceRuleReference`,
  `EvidenceCalculation` ve `EvidenceRAGReference` additive olarak eklendi.
  EvidenceRecord exact snapshot ve QueryRun bağlamına bağlıdır.
- Child kayıtlar aynı snapshot'taki explicit RuleVersion ve RAG kaynağına
  bağlanır; cross-snapshot referansları reddedilir. Finalized parent/child
  kayıtları immutable'dır.
- Mevcut compensation DecisionEvidence, snapshot 74, AI Analysis ve evidence
  detail davranışı korunur. Evidence üretimi/API/UI sonraki MAIN-071/072/073
  görevleridir; sonraki görev `MAIN-071`dir.

## 2026-08-14 — MAIN-071 QueryRun Evidence Materialization

- QueryRun `executing` durumunda snapshot-local draft `EvidenceRecord` oluşturur;
  `completed` veya `failed` olduğunda mevcut kalıcı canonical/audit verisinden
  tool, explicit RuleVersion, deterministic summary ve RAG provenance child
  kayıtları yazılarak immutable biçimde finalize edilir.
- Yeni tool, retrieval, hesaplama veya RuleVersion seçimi yapılmaz. Raw payload,
  token ve gizli alanlar saklanmaz; compensation `DecisionEvidence` otoriter
  kaydı değişmeden kalır.
- Replay finalized record'u yeniden kullanır; retry yeni QueryRun'a ayrı record
  açar. Focused lifecycle/evidence testleri geçti. Sonraki görev: `MAIN-072`.

## 2026-08-14 — MAIN-072 General Evidence Detail API

- Authenticated read-only `GET /api/orchestration/evidence-records/detail/`
  endpointi, yalnız exact `snapshot_identifier + evidence_code` ile eşleşen
  finalized ve terminal QueryRun'a bağlı genel EvidenceRecord'u döner.
- Response, safe tool timeline, calculation, explicit RuleVersion, RAG
  document/chunk/score, snapshot/query-run provenance ve warnings içerir.
  Serializer persisted JSON'u da yeniden sanitize eder; raw payload/secret
  açılmaz. Draft, missing ve cross-snapshot kayıtlar not-found döner.
- Mevcut compensation `DecisionEvidence` endpointi değişmeden kaldı. Sonraki
  görev: `MAIN-073`.

## 2026-08-14 — MAIN-073 General Evidence Detail UI

- `/evidence`, parametre türüne göre snapshot-local iki ayrı kanıt yüzeyi
  sunar: `evidence_hash` compensation `DecisionEvidence`; `evidence_code`
  finalized genel QueryRun `EvidenceRecord` içindir. Eksik veya çelişkili
  parametreler güvenli not-found olur; kanıt türleri birbirine fallback yapmaz.
- Genel detayda safe tool timeline, deterministic calculation, explicit
  RuleVersion, RAG retrieval provenance ve persisted warnings render edilir.
  Raw payload, secret, token ve debug dump kullanıcıya açılmaz.
- AI Analysis contract'ında genel evidence code bulunmadığından tahmini link
  üretilmedi; mevcut compensation evidence yolu korundu. Sonraki görev:
  `MAIN-074`.

## 2026-08-14 — AI Analysis Scope ve Telafi Execution Düzeltmesi

- Açık ama snapshot içinde çözülemeyen şehirler, `Çorum'da` gibi locative
  yazımlarda da clarification'a gider; analytics filtresi sessizce global
  scope'a genişlemez.
- Telafi/uygunluk talepleri mevcut compensation evidence yoluna önceliklidir.
  Retrieval result'ındaki liste section path değeri presentation için güvenli
  biçimde normalize edilir; mevcut Rule/RAG verisi değiştirilmez.
- Persisted karar yoksa pending/evidence yok sonucu korunur; sahte RuleVersion
  veya DecisionEvidence gösterilmez.
