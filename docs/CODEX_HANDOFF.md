# ProcessTwin Codex Handoff

## Güncel Otoriter Durum

Bu bölüm, aşağıdaki tarihsel PRE-061 ve eski MAIN checkpoint notlarının yerini
alır. Güncel kaynak; `feat: add nvidia and groq llm providers` commit'indeki
repository durumudur. Çalışma ağacı bu checkpoint'te temiz olmalıdır.

- Frontend uygulama kabuğu, rol tabanlı oturum kimlik doğrulaması, AI Analysis
  workspace'i, sorgu ilerleme görünümü ve doğrulanmış sonuç kartları
  tamamlandı. Frontend, analyst/admin yetkisiyle public orchestration
  endpoint'ine bağlıdır.
- Yerel profil `gemma4:12b-it-qat` + `qwen3-embedding:4b`; Gemini,
  NVIDIA `z-ai/glm-5.2` ve Groq `openai/gpt-oss-120b` LLM profilleri de
  desteklenir. NVIDIA/Groq OpenAI-compatible chat adapter üzerinden yalnız
  Phase 2 semantic decomposition ve Phase 1B narrative üretir. Embedding
  seçicisi bağımsızdır; yeni LLM'ler embedding sağlayıcısı değildir.
  Provider yalnız doğal dil anlayışı ve anlatımı yapar; güvenli fallback
  provider veya grounding hatasında kullanılmaya devam eder.
- Güncel analiz hattı şudur: doğal dil sorgusu -> deterministic exact anchor
  extraction -> LLM semantic decomposition -> deterministic validation/merge
  -> deterministic planner -> MCP/domain services ve gerektiğinde RAG ->
  verified machine facts -> canonical statements/relationships -> deterministic
  AnswerPlan -> provider natural-language synthesis -> backend grounding
  validation -> kullanıcı yanıtı ve structured verified-data presentation.
- LLM; müşteri/abonelik sayısı, kesinti süresi, tazminat değeri, RuleVersion,
  DecisionEvidence, topoloji, korelasyon, fiziksel RCA veya aggregate/ranking
  hesabının otoritesi değildir. Bu doğrular backend'in deterministic
  sorumluluğundadır.
- Cross-incident/cross-region correlation tamamlandı. Explicit pair ve bounded
  time-window discovery desteklenir; `verified_relation`,
  `insufficient_evidence` ve `no_relation` sonuçları zaman, kaynak/topoloji ve
  mevcut event kanıtından deterministik türetilir. Zaman yakınlığı tek başına
  korelasyon veya fiziksel kök neden kanıtı değildir. Kök/belirti yönü açık
  deterministic kanıt yoksa doğrulanmamış kalır. Correlation kartı doğal Türkçe
  kanıt alanlarını gösterir.
- Unanswerable ve partial davranışı tamamlandı: bilinmeyen exact
  `CE-*`/`ALM-*`/`AGG-*`/`SUB-*` kimlikleri fuzzy substitution yapmadan not-found
  döner; desteklenmeyen capability ayrı sınıflanır ve gereksiz LLM/MCP çalışmaz;
  partial doğrulanmış yanıtlar korunur; eksik kanıt unknown/unverified olarak
  kalır ve sıfıra dönüştürülmez. Gerekli clarification bilgisi korunur.
- Deterministic operational analytics tamamlandı. Mevcut veri setinde olay
  granülünde affected customer/subscription, potential scope, event/outage/alarm
  count, full-outage/failed-failover count ve authoritative compensation amount
  için typed count/sum/average/min/max hesapları yapılır. Event, root alarm,
  konum, cihaz/event tipi, outage/failover ve zaman bucket'larıyla grouping;
  tarih, konum ve durum filtreleri; kullanıcıdan alınan generic top/bottom N ve
  dönem değişimi desteklenir. Unknown impact event'leri sıfır sayılmaz,
  hesap dışı bırakılır ve excluded count olarak görünür.
- Bu proje mevcut sentetik/erişilebilir veri seti üzerinde çalışır; canlı,
  ülke çapında Turkcell üretim analizi olarak tanımlanmaz.

## Düşük Öncelikli Son Parlatmalar

- Local Gemma bazen fiziksel nedensellik kanıtından biraz daha güçlü ifade
  kullanabilir.
- Provider anlatımı, structured verified-data kartında görünen bazı doğrulanmış
  ayrıntıları atlayabilir.
- Prompt/prose kalitesi final polish aşamasında tekrar ele alınabilir; bunlar
  mevcut iş akışının veya grounding güvenliğinin bloklayıcısı değildir.

## Kilitli Sonraki Öncelik

1. Kalibrasyondan önce dataset inventory / audit.
2. Kalan frontend MAIN işleri, `MAIN-066` ve sonrası.
3. Final polish, daha geniş regresyon ve demo hazırlığı.

## Cloud LLM Provider Genişletmesi

- NVIDIA GLM-5.2 (`nvidia` / `z-ai/glm-5.2`) ve Groq GPT-OSS 120B
  (`groq` / `openai/gpt-oss-120b`) AI Analysis LLM seçicisine eklendi.
  Sabit registry provider/model eşlerini zorunlu kılar; yanlış eşler kabul
  edilmez. Her ikisi aynı deterministic AnswerPlan ve backend grounding
  doğrulamasından geçer; operasyonel gerçek veya hesaplama yetkisi taşımaz.
- Anahtarlar yalnız ortam değişkenlerinden okunur: `NVIDIA_API_KEY` ve
  `GROQ_API_KEY`. Anahtarlar audit, hata, Git veya dokümantasyona yazılmaz.
  Canlı ön-kontroller ve AGG-ANK-002 ProcessTwin kabulü iki provider ile de
  `llm_assisted`, uyarısız ve grounding valid geçti. NVIDIA'nın sonraki
  analytics narrative çağrısı dış `rate_limited` yanıtı verdi; deterministic
  analytics fallback doğru kaldı. Kod commitleri: `c66ef23`, `ef436ea`.

## Latest MAIN-065 Checkpoint

- Public orchestration response now includes only backend-validated
  `structured_result` summaries for causal, impact, rule, compensation and
  compact retrieval references. Raw MCP/provider payloads, prompts and
  provenance call records are not exposed.
- AI Analysis renders dynamic Impact, Outage/Network, Root cause,
  Compensation/decision and technical evidence-reference groups. Missing
  values stay absent; verified zero values remain visible.
- Management and Technical views use the same verified facts; Technical adds
  available root-cause and retrieval-reference detail without changing
  calculations. MAIN-066 was not started.
- Focused response-builder tests: 13 passed. Frontend lint/build, Django
  check, migration check and diff check are clean. One local HTTP smoke
  reached the real orchestration tools but did not complete within the bounded
  smoke window; no result card was accepted from incomplete data.

## Latest MAIN-062 Checkpoint

- `aa8b74f` üzerindeki MAIN-061 shell korunarak session tabanlı login, logout
  ve current-user endpoint'leri eklendi (`/api/auth/csrf/`, `/login/`,
  `/logout/`, `/me/`). Django'nun mevcut `User` modeli ve CSRF/session
  middleware'i kullanılıyor.
- Frontend auth provider oturumu geri yüklüyor; protected routes, güvenli
  login yönlendirmesi, logout ve viewer/analyst/engineer/admin route görünürlüğü
  uygulanıyor. Yetkisiz rol için 403 görünümü var.
- Yerel geliştirme kullanıcıları için kaynakta parola tutmayan
  `seed_demo_users --password ...` komutu eklendi. MAIN-063 başlatılmadı.

## Latest MAIN-063 Checkpoint

- AI Analysis workspace doğal dil textarea'sı, gerçek provider seçimleri,
  Yönetim/Teknik görünüm tercihi, idempotent submit ve success/clarification/
  failure durumlarıyla bağlandı.
- Session + CSRF + analyst/admin rol kontrollü
  `/api/orchestration/queries/execute/` endpoint'i mevcut
  `OrchestrationFacade`'ı kullanıyor; internal service-token endpoint'i
  değiştirilmedi.
- Tek gerçek local smoke HTTP 200, completed QueryRun ve
  `ollama/gemma4:12b-it-qat` provenance'ı ile tamamlandı. Gemma güvenli
  deterministic fallback döndürdü; sahte sonuç veya backend semantiği
  değişikliği yoktur. MAIN-064 başlatılmadı.

## Latest MAIN-064 Checkpoint

- Session-auth public orchestration runs now persist an optional QueryRun owner
  and expose a read-only `/api/orchestration/queries/status/` endpoint scoped
  to that owner and analyst/admin roles.
- Status payload yalnız persisted QueryRun status, safe tool counts/names,
  error code ve elapsed timestamps içerir. Frontend, synchronous POST ile
  birlikte idempotency key üzerinden bu endpoint'i poll eder; timer yalnız
  elapsed süreyi gösterir, backend fazlarını taklit etmez.
- Truthful states `request_received`, `plan_prepared`, `tools_executing`,
  `completed` ve `failed` ile sınırlıdır. MAIN-065 başlatılmadı.

## Latest MAIN-061 Checkpoint

- `feature/llm-role-expansion` üzerinde `acece2a` tabanından frontend uygulama
  kabuğu tamamlandı.
- Persistent sidebar navigation, auth-shell sınırı, operations/process views,
  prepared routes (`AI Analysis`, `Network`, `Customers`, `Rules`, `Decision
  Evidence`, `Settings`), loading fallback ve route error state eklendi.
- Frontend backend/orchestration semantiğine dokunmadı; MAIN-062 başlatılmadı.
- `frontend` lint/typecheck, production build, route HTTP kontrolü ve diff
  kontrolü temizdir. MAIN-061 commit'i bu değişikliklerle oluşturulmuştur.

## 1. Mevcut Checkpoint

- Aktif branch ve HEAD her oturum başında `git status --short` ve
  `git rev-parse HEAD` ile doğrulanır; bu belge sabit bir branch adı veya eski
  test toplamını otoriter kaynak kabul etmez.
- Güncel ürün checkpoint'i `1b8b0af` ve üstteki **Güncel Otoriter Durum**
  bölümüdür. Tarihsel REV/PRE günlükleri karar ve kanıt izi olarak korunur.
- Kod/test değişikliği sonunda working tree temiz bırakılır. Sadece ilgili
  focused testler çalıştırılır; full suite yalnız ayrı bir kabul kapısı veya
  açık istek olduğunda çalıştırılır.

## Görev Takip Durumu

> Bu başlığın altındaki eski PRE-061 kronolojisi tarihsel kayıttır. Güncel
> görev sırası üstteki **Kilitli Sonraki Öncelik** bölümüdür; `MAIN-061`
> frontend blocker'ı ve PRE-061 provider-quota blocker'ı güncel durum değildir.

- **PRE-061 — Final status: PASS.** Retrieval acceptance **PASS**
  (8 source, 54 chunk, 54 real Qwen embeddings; top-3 %93.33, top-5 %100,
  citation mismatch/leakage 0). Real Gemini provider/smoke is **PASS**. Gemma
  native-schema statement selection is **PASS** at `3c364e3` (capability 3/3;
  clean 12/12). Deterministic original-query intake passed 6/6 without LLM
  calls; the Gemma+Qwen baseline passed 6/6 and the real provider matrix passed
  4/4 combinations (8/8 cases). Qwen and Gemini canonical corpora each cover
  54/54 chunks with zero contamination. Overall PRE-061 is **PASS**;
  `MAIN-061` may start. A later semantic-completeness rerun also passed:
  baseline 6/6 and provider matrix 8/8 each required user-visible canonical
  fields, not merely HTTP completion. The final text is still assembled only
  from backend statement IDs; no free model facts are rendered.

- **PRE-061 final Gemini/LIVE-07 follow-up:** Aynı ephemeral key ile gerçek
  Gemini 3.6 interactions, 3.5 interactions ve 2.5 generate-content
  diagnosticleri başarılı oldu. Canonical production seçimi
  `gemini-3.6-flash` + `interactions`; dört gerçek fact-sheet smoke guard
  fallback'iyle güvenli kaldı. LIVE-07 planner/required-evidence dar
  düzeltmesi kod/test düzeyinde tamamlandı. Post-fix canlı sonuç ayrı
  `live_live_07.json` artefact'ına yazılmış, fakat aggregate rapora
  uzlaştırılmamıştı.

- **PRE-061 final-gap completion:** LIVE-07 post-fix canlı kanıtı HTTP 200,
  completed QueryRun, gerçek `rule.search_rule_documents`, citation support ve
  sıfır critical mismatch/leakage/privacy ihlali ile kabul edildi. Üç eksik
  gerçek Gemma çağrısı (`GEMMA-10-RAG-CITATION`, `GEMMA-11-IMPACT`,
  `GEMMA-12-COMPENSATION`) tamamlandı ve model unload edildi. İlk dokuz
  provenance kaydı kurtarılamadığı için aynı koşullarda birer kez yeniden
  çalıştırıldı. Toplam 12/12; narrative acceptance %25, güvenli fallback %100,
  final user-visible unsupported fact 0'dır. Ancak yedi gerçek fact-guard
  reddi, model unsupported-fact/contradiction oranı için %58.33 alt sınırını
  verir ve %10 eşiğini aşar. PRE-061 **FAIL**, `MAIN-061` bloklu kalır.

- **PRE-061 closed-world narrative remediation:** `closed-world-structured-
  narrative-tr-v2` per-case JSON allowlist ve structured validator ile dokuz
  eski Gemma reddini birer kez çalıştırdı; üç eski PASS korundu. Dokuz çağrının
  dördü provider error, beşi parse edilemeyen JSON döndürdü. Unsupported
  number/reference/decision ve potential/failover contradiction 0, fallback
  %100, user-visible unsupported fact 0; fakat doğrudan narrative acceptance
  %25 ve contradiction 9/12 olduğundan gate **FAIL**. Gemma unload edildi;
  `MAIN-061` ve altı kullanıcı promptu black-box turu başlamaz.

- **PRE-061 native schema statement selection:** `format` alanı olmayan v2
  prompt-only JSON sözleşmesi kaldırıldı. v3, native Ollama JSON Schema ile
  yalnız backend'in canonical statement ID'lerini seçtirir; final metin model
  serbest metni değildir. 3/3 capability gate ve temiz 12/12 benchmark PASS:
  provider/schema parse 12/12, timeout/unknown ID/semantic/potential/failover
  hata 0, fallback gerekmeyen supported final output 12/12. Gemma unload
  edildi. Sıradaki kabul işi altı gerçek kullanıcı promptunun black-box
  testidir; MAIN-061 hâlâ başlamaz.

- **PRE-061 natural-language intake capability:** `original_query`-only yol,
  sabit Gemma/native-schema parser ve invented-field/snapshot-reference guard
  ile eklendi; hazır `structured_query` replay yolu korunur. Tek gerçek altı
  vaka gate'i **FAIL** oldu: 1/6 provider/schema/StructuredQuery başarısı,
  0/6 kapsam eşleşmesi; beş vaka iki 60 saniyelik denemeden sonra
  `query_parse_unavailable` döndü. Endpoint/MCP/RAG black-box zinciri
  başlatılmadı, Gemma unload edildi. PRE-061 ve `MAIN-061` bloklu kalır.

- **MAIN-xxx — Ana kümülatif görev planı:** Ek orchestration serisinden önce
  son tamamlanan ana plan maddesi `MAIN-051.5 — Çoklu embedding seti ve lokal
  provider`dır. Dosyadaki ilk tamamlanmamış ana plan maddesi
  `MAIN-061 — Frontend uygulama kabuğunu tasarla`dır.
- **REV-00–REV-12 — Causal revizyon serisi:** Tamamlandı; PRE-052 native
  snapshot refresh ve causal integration gate de tamamlandı.
- **ORCH-052–ORCH-060 — Ek orchestration serisi:** Tamamlandı. QueryRun,
  provider registry/adapters, StructuredQuery, ToolPlan, deterministic planner,
  MCP executor, result validation, response builder ve authenticated endpoint
  bu ayrı serinin parçalarıdır. Bu seri ana kümülatif plan numaralandırmasını
  veya MAIN görev imlecini değiştirmez.
- Görev 052 tamamlandı: `apps.orchestration.QueryRun` explicit snapshot,
  unique idempotency key, retry zinciri, privacy-safe JSON audit alanları ve
  `pending -> planned -> executing -> completed|failed` yaşam döngüsünü
  taşır. Planner, MCP executor, RAG çağrısı ve LLM yanıt üretimi henüz
  başlamadı.
- Görev 053 tamamlandı: `apps.orchestration.providers` sabit Gemini ve Ollama
  allowlist descriptor'larını taşır. Ollama modeli `gemma4:12b-it-qat` ve
  `thinking_enabled=false` olarak sabittir; LLM ve embedding provider seçimleri
  bağımsızdır.
- Görev 053A tamamlandı: `MockLLMProvider` yalnız açık test/development izniyle
  seçilir, ağ/model çağrısı yapmaz ve canonicalized güvenli input'tan
  deterministic response veya kontrollü hata üretir. QueryRun entegrasyonu ve
  gerçek Gemini/Ollama adapter'ları henüz yoktur. Sıradaki görev Görev 053B
  Gemini LLM adapter'ıdır.
- Görev 053B tamamlandı: `GeminiLLMProvider`, allowlisted
  `gemini-3.5-flash` modeliyle lazy `google-genai` client oluşturur; timeout,
  sınırlı transient retry, normalize response ve redakte stabil hata kodları
  taşır. Testlerde yalnız fake SDK/client kullanıldı; gerçek API çağrısı ve
  QueryRun entegrasyonu yapılmadı. Sıradaki görev Görev 053C Ollama LLM
  adapter'ıdır.
- Görev 053C tamamlandı: `OllamaLLMProvider`, allowlisted
  `gemma4:12b-it-qat` modeline lazy `httpx` istemcisiyle `/api/chat` çağrısı
  yapar. Her çağrıda `think: false` ve `stream: false` zorunludur; timeout,
  en fazla üç denemelik transient retry, normalize response ve redakte stabil
  hata kodları vardır. Testlerde fake HTTP client kullanıldı; gerçek Ollama
  smoke, Qwen/Gemma residency orchestration ve QueryRun entegrasyonu yapılmadı.
  Qwen `/api/embed` `keep_alive=0` politikası değişmedi. Sıradaki görev Görev
  054 StructuredQuery schema'dır.
- Görev 054 tamamlandı: `StructuredQuery`, nested location/time-window
  modelleri ve strict allowlist ile Pydantic sözleşmesidir. LLM ile doğal dil
  dönüşümü yapmaz; yalnız validasyon sonrası privacy-safe normalize JSON'u
  bağlı snapshot identifier'ıyla eşleşen pending `QueryRun` kaydına idempotent
  biçimde yazıp `planned` durumuna geçirir.
  Tool planı, MCP/RAG execution ve final yanıt henüz yoktur. Sıradaki görev
  Görev 055 tool-plan schema'dır.
- Görev 055 tamamlandı: `ToolPlan` ve `ToolCall`, dört mevcut MCP registry'sinden
  çözülen allowlist tool/input sözleşmelerini kullanır. Snapshot ve
  StructuredQuery context'i eşleşir; çağrı grafiğinde duplicate, geçersiz
  dependency ve parallel-group çelişkileri reddedilir. Yalnız valid plan
  planned `QueryRun.planned_tools` alanına idempotent yazılır; planner, MCP
  execution, RAG ve final yanıt yoktur. Sıradaki görev Görev 056 planner'dır.
- Görev 056 tamamlandı: `DeterministicToolPlanner`, valid StructuredQuery'yi
  kural tabanlı ToolPlan'a dönüştürür ve yalnız başarıda `save_tool_plan`
  üzerinden QueryRun'a kaydeder. Clarification/unplannable sonuçlar kaydı
  değiştirmez. Causal reference önceliklidir; compensation için PII üretmeden
  yalnız causal/outage evidence yolu kullanılabilir. Gerçek MCP execution, LLM,
  RAG ve final yanıt yoktur. Sıradaki görev Görev 057 MCP executor'dır.
- 052-056 orchestration integration gate tamamlandı: explicit snapshot ile
  QueryRun -> StructuredQuery -> ToolPlan zinciri offline ve idempotent olarak
  doğrulandı. Hedefli regresyon seti 236 passed, full suite 807 passed;
  gerçek LLM, MCP, RAG veya model çağrısı yapılmadı. Sıradaki görev Görev 057
  MCP executor'dır.
- Görev 057 tamamlandı: `ToolExecutor`, persisted ve validated `ToolPlan`
  çağrılarını mevcut dört MCP tool sınıfına sıralı olarak yönlendirir. Plan
  bağımlılıkları, bounded read-only retry ve partial failure korunur; her call
  için yalnız privacy-safe audit özeti `QueryRun.executed_tools` alanına yazılır.
  Run execution sonunda `executing` kalır; result merge ve terminal karar
  uygulanmadı. Testlerde yalnız fake transport kullanıldı. Sıradaki görev
  Görev 058 result merge/validation'dır.
- Görev 058 tamamlandı: `ResultMergerValidator`, fresh runtime
  `ExecutorResult` verisini yalnız allowlisted MCP response sözleşmelerinden
  privacy-safe `ValidatedExecutionResult` biçimine normalleştirir. Required
  evidence intent/requested-output'tan türetilir; optional tool failure
  warning ile partial tamamlanabilir, required evidence/contract/invariant
  hatası `QueryRun`ı `failed` yapar. Valid sonuç `executing -> completed`
  geçişiyle yalnız normalize `final_result` kaydeder. Persisted audit özeti
  ham runtime response taşımadığından audit-only resume güvenli biçimde
  `runtime_result_unavailable` olur. Doğal dil response builder henüz yoktur;
  sıradaki görev Görev 059'dur.
- Görev 059 tamamlandı: `ValidatedResponseBuilder`, yalnız completed ve valid
  `QueryRun.final_result` üzerinden Türkçe kullanıcı cevabı üretir; QueryRun
  veya final_result değiştirilmez. Deterministik fact blokları source of truth
  kalır. LLM-assisted mod yalnız privacy-safe fact sheet'ten kısa anlatı
  üretebilir; yeni sayı/reference/karar tespiti veya provider hatasında
  deterministik fallback kullanılır. Endpoint ve E2E entegrasyonu Görev 060'a
  bırakıldı.
- Görev 060 tamamlandı: internal service-token ile korunan endpoint ve ince
  orchestration facade, explicit snapshot-bound `QueryRun -> StructuredQuery
  -> ToolPlan -> executor -> merge -> validated response` zincirini senkron
  bağlar. İdempotent completed replay araçları yeniden çalıştırmaz; executing,
  clarification, failed ve payload/snapshot conflict durumları stable ve
  privacy-safe HTTP sonuçları verir. LLM-assisted provider hatası mevcut
  deterministic fallback ile başarılı sunum olarak kalır. Ham query, MCP,
  provider veya kişisel veri endpoint/audit sonucuna taşınmaz. Hedefli E2E seti
  164 passed, full suite 836 passed in 396.28s; gerçek MCP/LLM/RAG network
  çağrısı testlerde yapılmadı.
- REV-00–REV-12, PRE-052 ve Görev 052 tamamlandı. QueryRun kayıtları
  explicit `multi-city-realism-v2-causal-r1-multi-city-realism-snapshot-v1-multi-city-realism-v2-causal-r1`
  snapshot'ını native kullanımda explicit almalıdır; model herhangi bir
  snapshot'ı hard-code etmez. Eski snapshot ve bağlı RAG kayıtları korunur;
  `SourceDocument.data_snapshot=PROTECT` blocker'ı destructive çözüm olmadan
  açık teknik takip maddesidir.

Belge çelişkilerinde öncelik sırası: güncel git/kod durumu, REV-01, REV-00, güncel ilerleme günlüğü, sonra eski plan ve karar belgeleri. Örneğin README eski ürün vizyonunda simülasyondan söz eder; güncel REV-01 kararı canlı simülasyon, Simulation MCP ve Analytics MCP'nin mevcut zorunlu revizyonun parçası olmadığıdır. Bu, simülasyonu silme kararı değil; revizyon tamamlanmadan başlatmama kararıdır.

## 2. Projenin Amacı

ProcessTwin, tamamen sentetik fakat bir Turkcell/Superonline sabit genişbant operasyonuna benzeyen telekom operasyon veri seti üzerinde ağ, müşteri etkisi, kural ve telafi analizleri yapan Django tabanlı bir sistemdir. Veri seti Türkiye sabit genişbant pazarını temsil etmez. Sistem, baseline–candidate iş kuralı karşılaştırmasıyla eşik değişimlerinin müşteri kapsamını ve telafi maliyetini ölçmeyi de hedefler.

Mevcut ürün; deterministik backend servisleri, dört MCP sunucusu, kaynak
retrieval için RAG ve doğal dil orchestration katmanı içerir. LLM semantic
decomposition ve grounded anlatım sağlar; deterministic hesaplama, kök neden,
uygunluk, telafi tutarı, topology ve correlation kararı LLM'e bırakılmaz.

## 3. Mevcut Teknik Mimari

Backend Python 3.12.5, Django 5.2.16 ve DRF kullanır; PostgreSQL 14.18 üzerinde pgvector 0.8.5 aktiftir. Ana uygulamalar datasets/geography/network/customers/operations/rules/compensation/rag ile core ve accounts katmanlarıdır. İç API'ler service-token kimlik doğrulaması ve correlation ID sözleşmesiyle korunur; dışa açık yüzey bu aşamada sınırlıdır.

Temel veri zinciri müşteri etkisi için `Customer -> Subscription -> SubscriptionConnection -> LineConnection -> NetworkPort -> NetworkDevice` biçimindedir. Operasyon zinciri `AlarmType -> Alarm -> IncidentAlarm -> Incident -> Outage`; kural ve telafi zinciri rule versioning üzerinden `CompensationEvaluation -> immutable DecisionEvidence`; RAG zinciri `SourceDocument -> DocumentChunk -> DocumentChunkEmbedding` şeklindedir. Mevcut müşteri etkisi servisleri topoloji ve sağlıklı yedek yol bilgisine göre potansiyel etki çıkarır; session kanıtına dayalı kalıcı verified impact henüz yoktur.

Dört MCP sunucusu yalnız authenticated backend internal API'lerini çağırır,
MCP süreçlerinde Django ORM kullanılmaz: Network 11 tool, Customer 7 tool,
Rule 8 tool, Compensation 6 tool. Registry, health ve shared contract testleri
bu envanteri korur.

RAG tarafında 10 canonical kaynak doküman, 74 chunk bulunur. Arama full-text, semantic ve hybrid modlarını destekler; Rule MCP'nin `search_rule_documents` aracı yalnız retrieval yapar, karar üretmez. Çoklu embedding kayıtları provider/model/version/prompt/content hash kimliğiyle ayrılır; farklı vektör uzayları asla birlikte aranmaz. Geçmiş model kayıtları silinmeden saklanır, aktif descriptor hangi setin kullanılacağını belirler.

## 4. Tamamlanan Önemli İşler

Network, Customer, Rule ve Compensation MCP'leri; shared BackendClient, contract/registry/health korumalarıyla tamamlandı. RAG model/corpus/ingestion/chunking, embedding generation, full-text/semantic/hybrid search ve Rule MCP retrieval entegrasyonu tamamlandı. Sabit 16 vakalık benchmark deterministic profile'da 10/10, aktif Gemini ve yerel Qwen profile'larında semantic 6/6 kalite kapısını geçmiştir.

Yerel/online embedding çalışması sonrası aktif embedding setleri iki ayrı 74'lük koleksiyondur: Gemini için `gemini-embedding-2`, Qwen için `qwen3-embedding:4b`. Nomic ve Qwen 0.6B kayıtları benchmark geçmişi olarak kalır fakat runtime'ın aktif yerel seti değildir. REV-00 mevcut sistemi, gerçek generator davranışını ve riskleri belgeledi; REV-01 ise uygulamaya geçmeden hedef operasyon modelini, alarm matrisi ve revizyon planını kesinleştirdi.

## 5. Değişmez Teknik Politikalar

LLM provider ile RAG embedding provider bağımsızdır. Online profil `LLM_PROVIDER=gemini` ve `RAG_EMBEDDING_PROVIDER=gemini`; online embedding modeli 768 boyutlu `gemini-embedding-2`dir. Yerel profil `LLM_PROVIDER=ollama` ve `RAG_EMBEDDING_PROVIDER=ollama`; yerel LLM `gemma4:12b-it-qat`, yerel embedding modeli 768 boyutlu `qwen3-embedding:4b`dir. Gemini LLM + Qwen embedding ve Gemma/Ollama LLM + Gemini embedding kombinasyonları da desteklenir. Bir ayar diğerini sessizce değiştiremez.

M1 16 GB birleşik bellek politikası önemlidir: normal kullanıcı sorgusunda yalnız query vector üretilir; 74 doküman tekrar embed edilmez. Qwen query embedding tamamlanınca Ollama `/api/embed` için doğrulanmış `keep_alive=0` politikasıyla unload edilir, ardından Gemma yüklenebilir. İki model sürekli resident tutulmaz. Bulk embedding işlemi boyunca model batch'ler arasında tutulabilir, işlem sonunda unload edilir.

Gemma'nın gelecekteki her `/api/chat` isteği top-level `think: false` taşımalıdır; CLI smoke biçimi `--think=false`dir. Thinking kullanıcı veya environment ile açılamaz; response, log, veritabanı ve DecisionEvidence'a yazılamaz. Bu karar LLM adapter görevinin kabul kriteridir; bu checkpoint'te Gemma chat adapter'ı henüz yazılmamıştır.

## 6. Domain ve Kapsam Kararları

Proje BNG, aggregation, OLT/GPON, DSLAM/xDSL, Metro Ethernet, primary/backup ve failover yapılarını içerir. Bunların bugünkü dağılımları dondurulmuş değildir; topoloji, senaryo ve davranış gerçekçiliğe göre revize edilecektir. GPON ilk eksiksiz, ayrıntılı altyapıdır; kapsam daraltması değildir. Diğer teknolojiler ortak operasyon modeline bağlanacak, veri ve zaman yeterliliğine göre aynı derinlikte geliştirilecektir.

BTK notları yalnız teknoloji/hız/kullanım değerlerinin gerçeklik kontrolü içindir; oranlar doğrudan seed dağılımı değildir. Turkcell/KAP, fiber ağırlıklı operatör profilini destekleyen yardımcı bağlamdır; gerçek topoloji, alarm sıklığı veya iş kuralı kaynağı değildir. OpenConfig alarm id/resource/severity/zaman/clear/component-interface normalizasyonu için referanstır; kurum içi alarm kataloğu değildir. Yusuf/Sercan örnekleri geldiğinde mapping ve dağılımlar kalibre edilir. “24 saatten kısa kesintide iade yok” ifadesi müşteri/hizmet/outage koşulları doğrulanmadığı için açık sorudur; kural olarak uygulanmamalıdır.

## 7. Yusuf Geri Bildiriminin Teknik Sonucu

Alarm gerçek müşteri kesintisini tek başına kanıtlamaz. Hedef sistem, topolojik **potential impact** ile session/IP kanıtlı **verified impact** ayrımını yapmalıdır. Saat 09.00'daki müşteri etkisinin kökü saat 08.00'de üst cihazda başlayan anomaly veya arıza olabilir; korelasyon event sırası, cihaz hiyerarşisi, upstream/uplink, shared failure domain, alarm yayılımı, session durumu, clear ve recovery sırasını birlikte değerlendirmelidir.

Her olayda root, child/symptom, supporting ve unrelated/noise alarm sınıfları açıklanabilir olmalıdır. GPON/OLT/PON port, distribution cable, optical signal, yüksek sıcaklık anomaly'si, uplink ve alarm olduğu halde session düşmeyen no-impact vakaları önceliklidir. Yusuf, bu olay-hiyerarşi korelasyonu ve rule baseline–candidate etkisini ProcessTwin'in güçlü tarafı olarak değerlendirdi.

## 8. Doğrulanmış Sorunlar

Maltepe generator bütünleşik/nedensel olay üretirken multi-city generator alarmları ayrı döngüde üretir ve IncidentAlarm ilişkilerini pozisyonel kurar. Çoğu multi-city alarm tipi sabit 70 kayıt üretir. Bu nedenle alarm–incident–outage ilişkisi teknik olarak stabil olsa da gerçekçi bir neden zincirini kanıtlamaz. Alarm/topoloji/senaryo/zaman tutarsızlıkları oluşabilir.

Session başlangıç/devam/bitiş modeli, kalıcı verified impact ve bu kanıtların DecisionEvidence bağlantısı yoktur. Ground-truth testlerinin PASS olması domain gerçekçiliğinin kanıtı değildir. Ayrıca multi-city snapshot metadata'sı ground-truth sayısını 0 gösterirken tabloda 30 kayıt vardır; row count parity düzeltilecektir.

## 9. REV-01 Hedef Tasarımı

Hedef akış şöyledir: raw source event/alarm -> normalized Alarm -> temporal/topological correlation -> `CausalEvent` -> root-cause candidate ranking -> Incident -> potential impact -> `SessionEvent` ile doğrulama -> `CustomerImpactAssessment` -> verified/no-impact/insufficient-evidence -> outage/degradation -> rule/compensation -> DecisionEvidence.

`CausalEvent`, `SessionEvent` ve `CustomerImpactAssessment` henüz implementasyon değildir; REV-01 tasarım kararıdır. `CausalEvent`, mevcut metadata içine serbest id koymaya veya Incident'i zorla ortak kimlik yapmaya tercih edilir: snapshot, zaman penceresi, root/correlation sınıfı, confidence ve metadata için sorgulanabilir küçük bir omurga sağlar. Operasyon modellerine gelecekte nullable causal relation eklenmelidir.

SessionEvent minimum olarak snapshot, bağlantı referansı, pseudonymized subscriber referansı, start/continue/stop/unknown türü, event/received zamanları, isteğe bağlı NAS/service/activity alanları, raw payload ve metadata taşımalıdır. Ayrı SessionState ilk adımda gerekli değildir; state sıralı eventlerden hesaplanır. Olay öncesinden offline müşteri `pre_existing_offline`; sağlıklı failover ile session düşmeyen müşteri `protected_no_session_loss`; geç/eksik session ise `insufficient_evidence` olur.

CustomerImpactAssessment, CausalEvent ve SubscriptionConnection için potential/verified/no-impact/insufficient-evidence durumlarını, neden kodlarını, zaman penceresini ve session kanıtlarını kalıcı saklamalıdır. Verified kümesi potential kümesinin dışına çıkamaz. Mevcut Outage operasyonel interruption anlamını korur; eski kayıtlar additive doğrulama alanları gelene kadar `legacy_unverified` olarak ele alınır.

## 10. Korunacak Güçlü Temeller

Customer/Subscription ayrımı; bağlantıdan port ve cihaza uzanan topology traversal; Alarm/Incident/Outage ayrımı; primary/backup/failover yaklaşımı; rule versioning; CompensationEvaluation ve immutable DecisionEvidence; dört MCP; çoklu-provider RAG; ve Maltepe'nin nedensel regression yaklaşımı korunacak temel yapılardır. “Korunacak” bunların hiç değişmeyeceği değil, revizyonun bunların üstünde additive ve tutarlı kurulacağı anlamına gelir.

## 11. Sıradaki Görev Sırası

Bu bölümdeki aşağıdaki REV/PRE kayıtları tarihsel tamamlanma izidir. Güncel
uygulama sırası şöyledir:

1. Kalibrasyondan önce dataset inventory / audit.
2. Kalan frontend MAIN işleri, `MAIN-066` ve sonrası.
3. Final polish, daha geniş regresyon ve demo hazırlığı.

Cross-incident correlation, unsupported/unknown-ID/partial-answer davranışı ve
genel trend/ranking/aggregate analytics tamamlandı; sonraki görev olarak tekrar
açılmaz.

- **REV-02 — Operations contracts and enums:** Tamamlandı; modelden bağımsız enum, immutable dataclass, validation ve privacy serialization sözleşmeleri `apps.operations.contracts` içinde tanımlandı.
- **REV-03 — Causal operations models:** Tamamlandı; CausalEvent, SessionEvent, CustomerImpactAssessment modelleri, nullable ilişkiler ve snapshot row-count düzeltme migration'ı eklendi.
- **REV-04 — GPON topology and alarm catalog:** Tamamlandı; merkezi source/device/technology compatibility validator, idempotent catalog seed ve `DISTRIBUTION_CABLE_DOWN` kararı eklendi. Mevcut operasyon kayıtları yeniden üretilmedi.
- **REV-05 — Causal GPON generator:** Tamamlandı; yedi GPON senaryosundan zaman çizelgeli alarm, incident, outage, session ve recovery üretir; ayrı alarm döngüsü/sabit-70 dağılımını kaldırır.
- **REV-05A — Alarm calibration:** Tamamlandı; anonim alan örneği repository/runtime bağımlılığı yapılmadan merkezi title normalization, raw-severity precedence ve sınırlı optical symptom fanout için kullanıldı. RAG reset `PROTECT` blocker'ı ayrı kaldı.
- **REV-06 — Correlation and root cause:** Tamamlandı; CausalEvent-bound olaylar farklı event'lerle karışmadan temporal/topological/failure-domain kanıtıyla açıklanabilir root, child, symptom, supporting, unrelated ve noise sonuçlarına dönüştürülür. Legacy kayıtlar konservatif fallback'te kalır.
- **REV-07 — Session verification and impact:** Tamamlandı; CausalEvent topology scope'u connection-level SessionEvent lifecycle, failover ve idempotent assessment ile potential/verified/no-impact/insufficient sonuçlarına ayrılır.
- **REV-08 — Compensation and evidence:** Tamamlandı; yalnız verified connection impact mevcut deterministic rule/compensation zincirine aday olur ve privacy-safe immutable evidence aggregate'i taşır.
- **REV-09 — Backend/API**, **REV-10 — dört MCP**, **REV-11 — RAG
  corpus/benchmark** ve **REV-12 — final integration gate** tamamlandı.
  REV-12 full suite sonucu 667 passed; MCP tool sayıları 9/7/8/6, RAG manifest
  13 ve benchmark 25'tir. Native multi-city/RAG gates eski snapshot data
  precondition'larında güvenli biçimde durdu; yeni canlı sayı iddia edilmedi.
  Ana plan takibinde 052–060 tamamlanmıştır. `PRE-061 — Live RAG + MCP + LLM
  Core Acceptance Gate` gerçek yerel smoke yolunu doğruladı. Genişletilmiş 15
  vakalık gerçek Qwen retrieval benchmarkında post-index top-5 expected-source
  hit oranı %100, top-3 oranı %93.33 ve kritik citation mismatch sayısı 0
  çıktığı için retrieval aşaması **PASS** durumundadır. PRE-061'in Gemma/Gemini
  acceptance aşaması sıradadır; frontend henüz başlatılmaz.
  Native-schema Gemma acceptance is now PASS, but normal Turkish query black-box
  E2E has not run because an `original_query -> StructuredQuery` intake/parser
  does not exist. PRE-061 is **NOT COMPLETE** and `MAIN-061 — Frontend uygulama
  kabuğunu tasarla` başlatılmamalıdır.

## 12. Açık Sorular

Session identity mapping, masking ve retention; stop/restart/continue semantiği; geç veya eksik kayıtlar; alarm source mapping ve clear semantics; GPON senaryo ağırlıkları; ticari iade koşulları; Yusuf/Sercan'dan gelecek örnek kayıtların alan eşlemesi açık konulardır. Kaynağı olmayan kurum içi bilgi uydurulmaz.

## 13. Yeni Codex Oturumu İçin Kurallar

İşe `git status --short`, `git rev-parse HEAD` ve son commit ile başla. Tamamlanmış görevleri yeniden uygulama, kullanıcı değişikliklerini silme, görevin dışına refactor taşıma. Her görevde tüm repo kataloglanmaz; önce bu handoff ve ilgili REV-01/REV-00 dokümanları okunur. Uygulama görevinde yalnız ilgili testler, önemli entegrasyon kapısında veya finalde full suite çalıştırılır. Her tamamlanan görev ayrı commit alır. 24 saat kuralı doğrulanmadan kodlanmaz; canlı simülasyon veya yeni MCP kendiliğinden başlatılmaz. Görev seçerken `Görev Takip Durumu` bölümündeki MAIN/REV/ORCH ayrımını kullan.

Her **major completed task** sonrasında mevcut takip yüzeyleri birlikte
güncellenir: `docs/CODEX_HANDOFF.md`,
`docs/revision/REV-01-IMPLEMENTATION-PLAN.md`, üst proje klasöründeki
`proje_ilerleme_gunlugu.txt` ve tarihsel olarak kullanılan görev/roadmap dosyası.
Tek satırlık küçük bug fix'ler, proje durumunu değiştirmiyorsa ayrı günlük
girdisi gerektirmez.

## Tarihsel Provider Selection Audit (Superseded)

Bu bölümdeki rate-limit ve Phase 1A statement-selection notları, güncel
deterministic AnswerPlan mimarisinden öncedir; güncel durum için üstteki
**Güncel Otoriter Durum** bölümüne bakılır.

One representative real Gemini case now passes non-fallback statement
selection. The full 18-case run still has 1/10 original and 0/8 unseen
provider-selection passes; 17/18 use safe fallback because Gemini rate limits
remain. Diagnostics are persisted as bounded warning categories, without raw
provider payloads. PRE-061 remains **NOT COMPLETE**.

## Tarihsel Provider Resilience Status (Superseded)

Gemini now uses bounded two-attempt retry with provider-supplied retry timing
or capped exponential backoff plus jitter. Acceptance pacing is sequential and
configurable at 0.5 seconds by default. One post-fix representative case
passed `llm_assisted`; a three-case burst was 0/3 provider selection and 3/3
safe fallback with `provider_call_failed_rate_limited`. The code path is
complete, but acceptance is provider-quota-limited. MAIN-061 remains blocked.

## Tarihsel Local Provider Baseline (Superseded)

The same canonical semantic acceptance was run without Gemini: resolved LLM
`ollama/gemma4:12b-it-qat`, resolved embedding `ollama/qwen3-embedding:4b`
(Qwen profile), with native Ollama `think:false` and `stream:false`. The
representative case, four-case burst, original 10 and existing unseen 8 all
completed through real HTTP. Local Gemma statement selection was `llm_assisted`
for 18/18 with no safe fallback or provider failure. Latency was 19.114 s min,
30.368 s median, 52.036 s max and 33.848 s average. Qwen RAG citations were
supported and security/evidence counters were zero. Full details are in
`artifacts/pre061/local_ollama_qwen_acceptance.json`.

This does not erase the Gemini quota-limited result. The local provider baseline
is complete, while overall PRE-061 and MAIN-061 remain blocked until the Gemini
acceptance criterion is satisfied.

## Tarihsel Semantic Audit (Superseded)

The old semantic-completeness PASS text is historical and is superseded by
`artifacts/pre061/semantic_generalization_acceptance.json`. The latest run
completed 10 original and 8 unseen real HTTP cases, but Gemini statement
selection fell back to deterministic rendering in all recorded cases.
Provider-success evidence is therefore incomplete. PRE-061 is **NOT COMPLETE**;
do not start MAIN-061.

## 14. Yeni Oturuma Yapıştırılacak Başlangıç Promptu

```text
docs/CODEX_HANDOFF.md dosyasını tamamen oku. Handoff'ın yönlendirdiği güncel
REV-01 ve REV-00 belgelerini oku. git status, HEAD ve son commit'i doğrula.
Belgeyle kod çelişirse güncel kod/git durumunu kaynak kabul et. Henüz
implementasyon yapmadan checkpoint'i en fazla 10 maddede özetle. Sonraki
görev promptunu kullanıcıdan bekle.
```
## Tarihsel Gemini Final Baseline (Superseded)

The existing original 10 and unseen 8 questions were run once with real HTTP,
Gemini `gemini-3.6-flash`, Gemini Embedding `gemini-embedding-2` and 10-second
sequential pacing. All 18 QueryRuns completed with HTTP 200. Semantic results
remained 10/10 and 8/8. Gemini selection passed 15/18: original 10/10 and
unseen 5/8. `unseen-04`, `unseen-07` and `unseen-08` hit bounded retry
exhaustion with `provider_call_failed_rate_limited` and safely fell back.
Provider failures were 0; security and citation counters were zero. Details:
`artifacts/pre061/gemini_acceptance_baseline.json`.

Overall status is **PARTIAL_PROVIDER_LIMIT**. No production code changed;
PRE-061 is not promoted to complete and MAIN-061 remains blocked.

## V3 Dataset Activation (2026-08-14)

- AI Analysis varsayılanı validated V3 repair snapshot `74` anahtarıdır:
  `multi-city-realism-v3-repair-r1-multi-city-realism-snapshot-v3-repair-r1`.
  V2 rollback snapshot `54` ve original V3 candidate `73` korunur.
- Snapshot 74 base world fingerprint'i snapshot 54 ile eşittir: 14.400 müşteri,
  16.200 abonelik, 238 cihaz ve external-ID/topology dünyası değişmedi. V3
  operational veri 94 event (91+3), 420 alarm, 77.125 SessionEvent, 49.996
  impact assessment, 10.658 CompensationEvaluation ve 10.716 DecisionEvidence içerir.
- Failed failover `CE-MCR-0052`: potential 1.441, impacted 1.009, customer 924;
  hitless `CE-MCR-0041/0044/0084`: impacted 0, protected/no-impact 1. Unknown
  değerler sıfır sayılmaz. `OUT-MCR-0052` telafisi 984 evaluation ve
  `58.850,16 TRY` aggregate'iyle snapshot-local evidence üzerinden sunulur.
- RAG canonical corpus Local Qwen ile snapshot-74 metadata altında indekslendi;
  retrieval operasyonel sayı hesaplamaz. Trend analytics internal MCP read
  timeout'ı bounded stdio tool süresiyle 15 saniyede hizalandı.
- Activation/integration commit: `60fa4fa`. Rollback: yalnız
  `frontend/src/pages/AIAnalysisPage.tsx` snapshot anahtarını snapshot 54
  anahtarına çevir; eski QueryRun replay'leri kendi snapshot provenance'ını korur.
- Sonraki görev: `MAIN-066`. Başlatılmayacak.

## V3 Trend/Comparison Contract Fix (2026-08-14)

- Commit `1986ac2` comparison ile grouping boyutunun birlikte taşınmasını sağladı:
  global comparison zaman kovalarını, city/alarm-type comparison ise her grup için
  dönem değerleri, fark ve yön bilgisini döndürür. Explicit top-N korunur;
  "şehirleri sırala" exhaustive kalır.
- Analytics AnswerPlan artık `included_event_count` değerini de first-class
  verified fact olarak sunar. Unknown exclusion tekrar edilmez ve unknown `0`
  olarak yorumlanmaz.
- Snapshot 74 verisi, RAG, provider konfigürasyonu ve activation seçimi bu
  düzeltmede değiştirilmedi. Sonraki görev hâlâ `MAIN-066`dır.

## V3 / AI Analysis Final Acceptance (2026-08-14)

- Snapshot `74` aktif production candidate; snapshot `54` rollback ve `73`
  original candidate olarak korunur.
- Trend/ranking, specific operational investigation ve same-event alarm
  correlation kabulü geçti. Evidence-limit ve `unknown != 0` sözleşmesi korunur.
- Forecast, remediation, cihaz komutu, saha prosedürü ve parça değişimi gibi
  desteklenmeyen istekler provider/tool çağrısı olmadan deterministic
  unsupported sonucu verir; supported event/impact/correlation sorguları bu
  filtreden etkilenmez. Unsupported ekranda mevcut "Soruyu düzenle" aksiyonu
  gösterilir.
- Son güvenlik commitleri: `460eac9` ve `9d7dbca`. Küçük provider anlatım üslubu
  kusurları blocker değildir. Sonraki görev `MAIN-066`: topoloji özet görünümü.

## AI Analysis General Reliability Hardening (2026-08-14)

- Commit `be6cb7c` generic analytics sözleşmesini güçlendirdi: location filtresi
  grouping değildir; outage/alarm count event sayısına çökmeden persisted count
  üzerinden toplanır; boş scoped sonuç doğrulanmış sıfır olarak yorumlanmaz.
- Olasılık yüzdesi isteyen predictive sorgular da remediation/forecast ile aynı
  early unsupported contract'a girer. Boş scoped analytics sonucu LLM'e
  yorumlatılmaz; deterministic kayıt-yok cevabı kullanılır.
- Snapshot `74`, V3 verisi, RAG ve provider registry değişmedi. Gerçek backend/MCP
  acceptance matrisi: 12 supported QueryRun completed, 3 unsupported intent
  doğru erken reddedildi. Bilinen blocker yoktur. Sonraki görev `MAIN-066`dır.

## MAIN-066 Topoloji Özet Görünümü (2026-08-14)

- Commit `f2a4e48` AI Analysis sonuçlarında, doğrulanmış cihaz kökü varsa
  snapshot-local topology summary gösterir: upstream, seçili root ve sınırlı
  downstream access zinciri.
- Payload yalnız mevcut NetworkDevice/NetworkLink ilişkilerini, aktif
  primary/backup connection role sayılarını ve persisted assessment scope'unu
  okur. Yeni impact hesabı veya failover sonucu türetmez.
- Snapshot 74 smoke: `AGG-ANK-002` upstream `BNG-ANK-001`, 15 downstream
  cihaz, potential 572, verified connection/subscription 429 ve customer 393.
- Focused testler (3), Ruff, Django check, migration dry-run ve frontend
  typecheck geçti. Sonraki görev: `MAIN-067`.

## MAIN-067 Kural ve Kaynak Kanıtları (2026-08-14)

- AI Analysis doğrulanmış sonuç kartlarına, mevcut deterministic provenance'tan
  beslenen `Kural ve kaynak kanıtları` bölümü eklendi. Seçilmiş RuleVersion,
  DecisionEvidence ve mevcut RAG doküman kodu/sürümü/başlığı/bölümü gösterilir.
- RAG arama tekrar çalıştırılmaz: sonuçtan gelen mevcut `hybrid_score`, yoksa
  `semantic_score`, yoksa `full_text_score` aynı kaynak kaydıyla taşınır.
  RAG kaynakları karar veya operasyonel sayı hesabının kaynağı olarak sunulmaz.
- Boş provenance için kart üretilmez. MAIN-066 topology summary bağımsız kalır.
- Sonraki görev: `MAIN-068`. Başlatılmayacak.

## MAIN-068 DecisionEvidence Detayı (2026-08-14)

- AI Analysis içindeki gerçek DecisionEvidence referansları artık exact snapshot
  identifier ve evidence hash taşıyan `/evidence` bağlantılarıdır.
- Yeni authenticated read-only public endpoint aynı immutable serializer'ı
  kullanır; lookup yalnız `snapshot_key + evidence_hash` eşleşmesiyle yapılır.
  Cross-snapshot ve missing kayıtlar `not_found` döner; latest-rule fallback,
  yeni evidence veya hesaplama yoktur.
- Evidence ekranı karar/finalized durumu, selected RuleVersion, evaluation/outage
  referansı, tutar ve koşul/modifier/manual-review kanıtlarını gösterir.
  Topology summary ve RAG provenance bağımsız kalır.
- Sonraki görev: `MAIN-069`. Başlatılmayacak.

## MAIN-069 Frontend Hata ve Boş Durumları (2026-08-14)

- AI Analysis mevcut backend hata semantiğini koruyarak clarification,
  unsupported, retry edilebilir hata, erişim ve not-found durumlarını ayrı
  yüzeylerde gösterir. Yeni sorgu önceki progress/sonuç/hata durumunu temizler;
  yalnız geçici hatalar aynı sorguyla tekrar denenebilir.
- Evidence detail eksik parametre, snapshot-local not-found/mismatch, erişim ve
  retry edilebilir hata durumlarını ayrıştırır. Topology summary yüklenemezse
  sessizce kaybolmak yerine güvenli bir durum bilgisi gösterir.
- Yeni backend endpointi veya veri semantiği eklenmedi; Snapshot 74, topology,
  Rule/RAG provenance ve mevcut safe fallback davranışı korundu.
- Sonraki görev: `MAIN-070`. Başlatılmayacak.

## MAIN-070 Genel Evidence Veri Modeli (2026-08-14)

- `orchestration` altında QueryRun ve exact snapshot'a bağlı, additive
  `EvidenceRecord` omurgası eklendi. Tool call, explicit RuleVersion,
  deterministic calculation ve RAG document/chunk/score provenance'i ayrı
  child kayıtları olarak saklanır.
- Snapshot uyuşmazlığı model validation ile reddedilir. Finalization sonrası
  parent ve child kanıt kayıtları değiştirilemez veya genişletilemez.
  Mevcut compensation `DecisionEvidence` ve `/evidence` akışı değiştirilmedi.
- MAIN-070 otomatik evidence üretimi, API veya UI eklemez; bunlar sırasıyla
  MAIN-071/072/073 kapsamındadır. Sonraki görev: `MAIN-071`.

## MAIN-071 QueryRun Evidence Materialization (2026-08-14)

- QueryRun `executing` durumunda snapshot-local draft `EvidenceRecord` oluşturur;
  `completed` veya `failed` olduğunda mevcut kalıcı canonical/audit verisinden
  tool, explicit RuleVersion, deterministic summary ve RAG provenance child
  kayıtları yazılarak immutable biçimde finalize edilir.
- Yeni tool, retrieval, hesaplama veya RuleVersion seçimi yapılmaz. Raw payload,
  token ve gizli alanlar saklanmaz; compensation `DecisionEvidence` otoriter
  kaydı değişmeden kalır.
- Replay finalized record'u yeniden kullanır; retry yeni QueryRun'a ayrı record
  açar. Focused lifecycle/evidence testleri geçti. Sonraki görev: `MAIN-072`.

## MAIN-072 General Evidence Detail API (2026-08-14)

- Authenticated read-only `GET /api/orchestration/evidence-records/detail/`
  endpointi, yalnız exact `snapshot_identifier + evidence_code` ile eşleşen
  finalized ve terminal QueryRun'a bağlı genel EvidenceRecord'u döner.
- Response, safe tool timeline, calculation, explicit RuleVersion, RAG
  document/chunk/score, snapshot/query-run provenance ve warnings içerir.
  Serializer persisted JSON'u da yeniden sanitize eder; raw payload/secret
  açılmaz. Draft, missing ve cross-snapshot kayıtlar not-found döner.
- Mevcut compensation `DecisionEvidence` endpointi değişmeden kaldı. Sonraki
  görev: `MAIN-073`.

## MAIN-073 General Evidence Detail UI (2026-08-14)

- `/evidence` parametreleri kesin ayrılır: yalnız exact
  `evidence_hash + snapshot_identifier` mevcut compensation `DecisionEvidence`
  detayını; yalnız exact `evidence_code + snapshot_identifier` finalized genel
  QueryRun `EvidenceRecord` detayını açar. Eksik veya çelişkili parametreler
  hiçbir kanıt türüne fallback yapmadan güvenli not-found yüzeyine gider.
- Genel ekran safe tool timeline, deterministic calculation, explicit
  RuleVersion, RAG retrieval provenance ve persisted warnings alanlarını
  gösterir; raw payload, secret, token ve debug dump render edilmez. Mobil
  yerleşim ve erişilebilir loading/error durumları eklendi.
- AI Analysis response sözleşmesi henüz güvenilir `evidence_code` taşımadığı
  için genel evidence linki uydurulmadı; mevcut compensation evidence linki
  korunur. Sonraki görev: `MAIN-074`.

## MAIN-074 Evidence/Governance Acceptance (2026-08-14)

- Completed QueryRun -> finalized `EvidenceRecord` -> exact snapshot-local API
  detail zinciri focused integration testiyle doğrulandı. Tool sırası/denemesi/
  süresi, deterministic calculation, explicit RuleVersion, RAG provenance ve
  warnings persisted kayıttan gelir; replay child kayıtları çoğaltmaz.
- Failure/answerability, draft/missing/cross-snapshot, finalized immutability
  ve compensation `DecisionEvidence` endpoint ayrımı ilgili focused testlerle
  geçti. Genel `evidence_code` ve compensation `evidence_hash` rotaları
  birbirine fallback yapmaz.
- Genel evidence code henüz AI Analysis response contract'ında taşınmadığı
  için doğrudan sonuçtan genel evidence linki yoktur; bu non-blocking ürün
  bağlantısı ayrı ele alınmalıdır. Evidence/governance paketi kapanmıştır.
  Sonraki görev: `MAIN-075`.

## AI Analysis Scope ve Telafi Execution Düzeltmesi (2026-08-14)

- Çözülemeyen açık şehir ifadeleri, Türkçe locative yazımı (`Çorum'da`) dahil,
  global analytics'e düşmez ve güvenli clarification üretir. Bilinen şehir
  scope davranışı korunur.
- Exact event telafi/uygunluk sorguları doküman niyetine kaymak yerine mevcut
  compensation evidence yolunu kullanır. RAG kaynak sözleşmesindeki liste
  biçimli section path, read-only sunum metnine normalize edilir; merge hatası
  üretmez.
- CE-MCR-0010 için persisted compensation değerlendirmesi olmadığı doğrulandı:
  sistem bunu pending/evidence yok olarak gösterecek, RuleVersion veya
  DecisionEvidence uydurmayacaktır.

## Decision Evidence Index Completion (2026-08-15)

- Parametresiz `/evidence` artık not-found yerine son finalized, terminal
  QueryRun EvidenceRecord kayıtlarının kısa read-only listesini gösterir.
- Her satır exact snapshot anahtarıyla kendi genel evidence detayına gider;
  draft/non-terminal kayıtlar listelenmez. Compensation `evidence_hash`
  detay akışı değişmeden kalır. Sonraki ana görev: `MAIN-075`.

## MAIN-075 ProcessTwin Simulation Veri Omurgası (2026-08-17)

- Yeni `simulation` Django uygulaması snapshot-local `SimulationScenario`,
  `SimulationRun` ve sıralı `SimulationRunEvent` modellerini ekler. Run; exact
  source snapshot, deterministic seed, virtual clock, yalnız `1x`/`10x`/`60x`
  hızları, lifecycle durumu, baseline/candidate bağı ve replay kimliğini taşır.
- Candidate yalnız aynı snapshot, scenario, seed ve virtual clock kullanan bir
  baseline'a bağlanabilir; replay aynı source/seed/scenario ve replay kimliğini
  korur. Event'ler yalnız kendi run'ına bağlı, benzersiz sequence/code ile
  zaman sıralı tutulur.
- Bu yalnız veri omurgasıdır: SimulationService, override/execution, metric,
  API, frontend, rule/compensation uygulaması veya operasyon tablolarına yazım
  yoktur. Focused isolation testi CausalEvent, Alarm, Outage,
  CustomerImpactAssessment ve CompensationEvaluation sayılarının değişmediğini
  doğruladı. Sonraki görev: `MAIN-076`.

## MAIN-076 Deterministik Simulation Runtime (2026-08-17)

- `SimulationService`, scenario defaults ile run-local override'ları derin kopya
  ve kararlı merge ile effective input'a dönüştürür; baseline ve candidate
  parametreleri birbirini veya scenario varsayılanlarını değiştirmez.
- Start/pause/resume/stop, reset ve replay yalnız simulation-local lifecycle
  durumunu değiştirir. Virtual clock, gerçek zamandan bağımsız olarak çağrının
  verdiği adım x `1x`/`10x`/`60x` ile ilerler; replay kaynak bağlamını yeni,
  izlenebilir bir run'a taşır.
- Runtime event'leri deterministik sequence ve hash tabanlı kod ile sıralanır.
  Terminal run resetlenmez; geçmiş korunur ve replay gerekir. Focused testler
  lifecycle, pause, hızlar, replay determinismi, input/snapshot izolasyonu,
  sıralama ve ana operasyon tablolarına sıfır yazımı doğruladı.
- Bu görev gerçek BNG senaryosu, alarm/outage/impact/compensation, API, UI veya
  evidence entegrasyonu eklemez. Sonraki görev: `MAIN-077`.

## MAIN-077 Canonical BNG Baseline/Candidate (2026-08-17)

- `apps.simulation.services.CanonicalBNGSimulationService`, simulation-local
  BNG failure → alarm → incident → outage/degradation → impact → compensation
  timeline'ını yalnız `SimulationRun`/`SimulationRunEvent` üzerinde üretir.
- Historical ve hypothetical impact ayrıdır: production `evaluate_read_only()`
  persisted SessionEvent olmadan verified etki üretmez; ProcessTwin ise
  snapshot topology, aktif connection ve full-diverse backup kanıtıyla açıkça
  `projection` alanında projected affected/protected/unknown sonucu üretir.
- Baseline ile candidate aynı snapshot/scenario/seed/başlangıç clock'tan
  başlar; candidate yalnız deep-merged explicit override kullanır. Canonical
  result, virtual-time strict RuleVersion, projection basis/assumptions,
  projected impact/protection/unknown sayıları, compensation cost ve SLA
  bilgisini taşıyıp deterministic delta üretir.
- MAIN-078 API/event-stream, MAIN-079 UI ve MAIN-080 evidence entegrasyonu
  kapsam dışıdır. Focused tests passed; sonraki görev: `MAIN-078`.

## MAIN-077 Snapshot 74 Live Acceptance (2026-08-17)

- Development PostgreSQL'e yalnız `simulation.0001_initial` uygulandı; mevcut
  operasyon tablolarına migration DDL'i uygulanmadı. Gerçek Snapshot 74 için
  `BNG-İZM-002` anchor'ı seçildi: 26 downstream cihaz, 2.930 valid
  subscription connection/subscription ve 2.539 müşteri scope'u.
- Canonical service `source_device_code` anchor'ını mevcut topology/validity
  resolver'ıyla kullanır. Persisted SessionEvent yokluğu historical sonucu
  unknown bırakır; hypothetical ProcessTwin sonucu ise bunu verified diye
  sunmadan topology projection üretir.
- R2 live baseline (600 sn), candidate (1.200 sn) ve candidate replayi
  completed oldu. Her iki koşul: 2.930 potential subscription / 2.539
  potential customer / 2.882 projected affected subscription / 2.491
  projected affected customer / 48 projected protected-no-impact / 0 projected
  unknown üretti. Koruma yalnız BNG subgraph dışındaki aktif ve fully-diverse
  backup path'lerden gelir; 15 subscription'ın primary path'i zaten BNG scope
  dışında kalır. Delta yalnız +600 sn duration'dır.
- Strict `BB-FULL-OUTAGE-TIERED:v1` seçildi; mevcut rule evaluation bu virtual
  contextte manual-review/not-eligible ile 0.00 TRY döndürdü, fall-back rule
  seçilmedi. Replay payloadı run kimliği hariç aynıdır. Ölçümlü replay:
  baseline 2.322 sn / 719 SQL, candidate 2.251 sn / 725 SQL; subscription
  başına sorgu yoktur, path-diversity sorguları gerçek backup path çiftleriyle
  sınırlıdır.
- PostgreSQL lock yolundaki nullable `baseline_run` outer-join hatası düzeltildi:
  runtime yalnız mutable SimulationRun satırını locklar. CausalEvent (94), Alarm
  (420), Incident (87), Outage (58), CustomerImpactAssessment (49,996) ve
  CompensationEvaluation (10,658) before/after aynıdır. Sonraki görev:
  `MAIN-078`.

## MAIN-077 Generic ProcessTwin Core Expansion (2026-08-17)

- Canonical failure contract artık `anchor_type + anchor_code + failure_type`
  ile çalışır. `BNG`, `OLT`, metro aggregation ve access-node cihazları ortak
  `network_device` yolu üzerinden; yönlü `network_link` ve exact
  `line_connection` anchor'ları ayrı, snapshot-local projection yollarından
  çözülür. Eski BNG service adı geriye uyumlu alias olarak korunur.
- Her failure family aynı typed simulation result'ı üretir: potential scope,
  projected affected/protected/unknown, failover basis, strict virtual-time
  RuleVersion, simulated compensation ve SLA. Historical verified evidence
  hiçbir noktada projected sonuca karışmaz. Port, failure-domain ve
  subscription-connection aileleri yeni büyük domain semantiği gerektirdiği
  için bilinçli olarak deferred kaldı.
- Snapshot 74 representative live acceptance: `BNG-İZM-002` (2,930 potential
  subscription, 2,882 projected affected, 48 protected), `OLT-ESE-004` (384 /
  384 / 0) ve `LNK-AGG-İST-003-OLT-ESE-003` (384 / 384 / 0). Candidate yalnız
  explicit SLA target override ile her üçünde `sla_breached` değerini true'dan
  false'a değiştirdi; müşteri kapsamı uydurulmadı. Strict selected
  `BB-FULL-OUTAGE-TIERED:v1` compensation evaluation bağlamında manual-review,
  0.00 TRY döndürdü; fallback rule seçilmedi.
- 91 ana CE-MCR olayının 68'i artık projectable: 52 device, 9 link ve 7 line.
  Bounded backtest 68 olayı 27.6 sn'de çalıştırdı: 5 exact, 57 acceptable, 6
  mismatch. Altı mismatch link-only runtime bug'ı değildir: historical
  kayıtların scope metadata'sı link yanında cihaz/line/port propagation
  kapsamı taşır; güvenli yönlü link projection bu ek semantiği varsayarak scope
  genişletmez. Operasyon tabloları ve Snapshot 74 değişmedi. Sonraki görev:
  `MAIN-078`.

## MAIN-078 ProcessTwin Public API (2026-08-17)

- Authenticated `/api/simulation/` namespace eklendi. Analyst/Admin; generic
  `network_device`, `network_link` ve `line_connection` scenario validate/create,
  baseline/candidate run create, synchronous start, status, pause/resume/stop,
  replay, persisted-result ve cursor event endpoints'lerine erişebilir.
- Result endpointi canonical runtime'ı tekrar çalıştırmaz: persisted typed result
  okunur; historical evidence ve hypothetical projection, unknown/protected ve
  compensation/strict RuleVersion alanları ayrı taşınır. Eski BNG device inputu
  `source_device_code` alias'ı ile backward-compatible kalır.
- Event polling `sequence ASC`, `sequence > cursor`, bounded limit ve
  `next_cursor`/`has_more` kullanır; raw event payload veya topology/impact
  yeniden hesaplaması yapılmaz. Invalid anchor, snapshot, override ve lifecycle
  geçişleri kontrollü public error contract ile döner.
- Focused API/runtime testleri 22 passed; Django check, Ruff, migration dry-run
  ve diff check geçti. Migration yoktur. API simulation-local kayıtlar dışında
  CausalEvent, Alarm, Incident, Outage, CustomerImpactAssessment veya
  CompensationEvaluation yazmaz. Sonraki görev: `MAIN-079` frontend.

## MAIN-079 ProcessTwin Workspace (2026-08-17)

- Statik ProcessTwin placeholder'ı, authenticated mevcut `/api/simulation/`
  contract'ını kullanan baseline/candidate workspace'e dönüştürüldü. Kullanıcı
  exact snapshot, desteklenen generic anchor (`network_device`, `network_link`,
  `line_connection`), virtual start, deterministic seed, 1x/10x/60x hız ve
  explicit candidate override ile scenario/run oluşturabilir.
- UI yalnız persisted canonical result'ı gösterir. Historical evidence ve
  hypothetical projection ayrı bölümlerdedir; projected değerler verified veya
  production fact olarak sunulmaz, unknown sıfıra dönüştürülmez ve null
  RuleVersion/manual-review sonucu fallback olmadan korunur.
- Candidate replay önce bağlı baseline replay'ini, sonra candidate replay'ini
  başlatır. Timeline cursor ile append edilir (`sequence > cursor`); synchronous
  start nedeniyle sahte canlı clock/progress/stream yoktur. Device topology
  summary yalnız read-only bağlam olarak opsiyoneldir; yeni graph/backend
  endpointi eklenmedi. Sonraki görev: `MAIN-080` simulation evidence.

### MAIN-079 manual lifecycle correction (2026-08-17)

- Manual UI smoke found that the frontend started a baseline before creating
  its candidate. The runtime correctly rejects that transition. The workspace
  now creates baseline and candidate contexts first, then starts baseline and
  candidate in order. No simulation core, API, schema, or evidence behavior
  changed.
- Snapshot 74 focused smoke passed with `BNG-İZM-002`: both runs completed,
  projected scope stayed unchanged, SLA target changed 300 to 900,
  `sla_breached` changed true to false, and cursor pages continued `1,2,3`
  then `4,5,6` without overlap. Next: `MAIN-080`.
