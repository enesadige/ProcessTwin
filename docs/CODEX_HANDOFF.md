# ProcessTwin Codex Handoff

## 1. Mevcut Checkpoint

- Aktif branch: `main`.
- Doğrulanmış HEAD: 052-056 integration gate commit'i sonrasında güncel
  `git rev-parse HEAD` çıktısı kaynak alınmalıdır.
- Bu checkpoint'te working tree temiz bırakılmalıdır.
- Son doğrulanmış tam test baseline'i repository root'tan `.venv/bin/pytest -q` ile **612 passed** sonucudur. Bu sonuç REV-00 baseline dokümanında kayıtlıdır; bu handoff hazırlanırken testler yeniden çalıştırılmamalıdır.
- REV-00, mevcut sistemin ve test baseline'ının belgelenmesiyle `c820d317bf115672b517563aa85f33e95f80aa9f` commit'inde tamamlandı. REV-01, hedef operasyon modeli ve uygulama planıyla tamamlandı; REV-02, modelden bağımsız nedensellik/etki sözleşmelerini `dfca89dff6f4a2c3a1127d2d1b009ad463ba20c3` commit'iyle tamamladı. REV-03, nedensel operasyon modelleri ve migration çalışmasıyla; REV-04 ise GPON alarm/topoloji compatibility validator ve katalog kararıyla tamamlandı.

## Görev Takip Durumu

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

Mevcut ürün; deterministik backend servisleri, dört MCP sunucusu ve kaynak retrieval için RAG içerir. İleride LLM/orchestrator katmanı doğal dil sorgularını kontrollü araç planlarına dönüştürecektir; deterministic hesaplama, kök neden, uygunluk veya telafi tutarı LLM'e bırakılmayacaktır.

## 3. Mevcut Teknik Mimari

Backend Python 3.12.5, Django 5.2.16 ve DRF kullanır; PostgreSQL 14.18 üzerinde pgvector 0.8.5 aktiftir. Ana uygulamalar datasets/geography/network/customers/operations/rules/compensation/rag ile core ve accounts katmanlarıdır. İç API'ler service-token kimlik doğrulaması ve correlation ID sözleşmesiyle korunur; dışa açık yüzey bu aşamada sınırlıdır.

Temel veri zinciri müşteri etkisi için `Customer -> Subscription -> SubscriptionConnection -> LineConnection -> NetworkPort -> NetworkDevice` biçimindedir. Operasyon zinciri `AlarmType -> Alarm -> IncidentAlarm -> Incident -> Outage`; kural ve telafi zinciri rule versioning üzerinden `CompensationEvaluation -> immutable DecisionEvidence`; RAG zinciri `SourceDocument -> DocumentChunk -> DocumentChunkEmbedding` şeklindedir. Mevcut müşteri etkisi servisleri topoloji ve sağlıklı yedek yol bilgisine göre potansiyel etki çıkarır; session kanıtına dayalı kalıcı verified impact henüz yoktur.

Dört MCP sunucusu yalnız authenticated backend internal API'lerini çağırır, MCP süreçlerinde Django ORM kullanılmaz: Network 9 tool, Customer 7 tool, Rule 8 tool, Compensation 6 tool. Registry, health ve shared contract testleri bu sayıları korur.

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
  Ana plan takibinde sıradaki görev `MAIN-061 — Frontend uygulama kabuğunu
  tasarla`dır; `ORCH-052–ORCH-060` tamamlanmış ek seridir.

## 12. Açık Sorular

Session identity mapping, masking ve retention; stop/restart/continue semantiği; geç veya eksik kayıtlar; alarm source mapping ve clear semantics; GPON senaryo ağırlıkları; ticari iade koşulları; Yusuf/Sercan'dan gelecek örnek kayıtların alan eşlemesi açık konulardır. Kaynağı olmayan kurum içi bilgi uydurulmaz.

## 13. Yeni Codex Oturumu İçin Kurallar

İşe `git status --short`, `git rev-parse HEAD` ve son commit ile başla. Tamamlanmış görevleri yeniden uygulama, kullanıcı değişikliklerini silme, görevin dışına refactor taşıma. Her görevde tüm repo kataloglanmaz; önce bu handoff ve ilgili REV-01/REV-00 dokümanları okunur. Uygulama görevinde yalnız ilgili testler, önemli entegrasyon kapısında veya finalde full suite çalıştırılır. Her tamamlanan görev ayrı commit alır. 24 saat kuralı doğrulanmadan kodlanmaz; canlı simülasyon veya yeni MCP kendiliğinden başlatılmaz. Görev seçerken `Görev Takip Durumu` bölümündeki MAIN/REV/ORCH ayrımını kullan.

## 14. Yeni Oturuma Yapıştırılacak Başlangıç Promptu

```text
docs/CODEX_HANDOFF.md dosyasını tamamen oku. Handoff'ın yönlendirdiği güncel
REV-01 ve REV-00 belgelerini oku. git status, HEAD ve son commit'i doğrula.
Belgeyle kod çelişirse güncel kod/git durumunu kaynak kabul et. Henüz
implementasyon yapmadan checkpoint'i en fazla 10 maddede özetle. Sonraki
görev promptunu kullanıcıdan bekle.
```
