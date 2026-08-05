# REV-01 Uygulama Planı

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
