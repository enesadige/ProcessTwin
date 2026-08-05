# ProcessTwin Codex Handoff

## 1. Mevcut Checkpoint

- Aktif branch: `main`.
- Doğrulanmış HEAD: REV-05 tamamlandıktan sonra alınan `feat: generate causal GPON operations data` commit'idir; kesin hash için güncel `git rev-parse HEAD` çıktısı kaynak alınmalıdır.
- Bu checkpoint'te working tree temiz bırakılmalıdır.
- Son doğrulanmış tam test baseline'i repository root'tan `.venv/bin/pytest -q` ile **612 passed** sonucudur. Bu sonuç REV-00 baseline dokümanında kayıtlıdır; bu handoff hazırlanırken testler yeniden çalıştırılmamalıdır.
- REV-00, mevcut sistemin ve test baseline'ının belgelenmesiyle `c820d317bf115672b517563aa85f33e95f80aa9f` commit'inde tamamlandı. REV-01, hedef operasyon modeli ve uygulama planıyla tamamlandı; REV-02, modelden bağımsız nedensellik/etki sözleşmelerini `dfca89dff6f4a2c3a1127d2d1b009ad463ba20c3` commit'iyle tamamladı. REV-03, nedensel operasyon modelleri ve migration çalışmasıyla; REV-04 ise GPON alarm/topoloji compatibility validator ve katalog kararıyla tamamlandı.
- Görev 52 henüz başlamadı. Kesin tanımı: **QueryRun modelini oluştur**; `original_query`, `structured_query`, `planned_tools`, `executed_tools`, `status`, `final_result`, model ve prompt version alanlarıyla her AI sorgusunun kaydedilebilmesini hedefler.
- REV-00–REV-12 tamamlandı; sıradaki görev Görev 52'dir. Native multi-city/RAG validation mevcut eski snapshotın REV-05 verisini taşımadığını gösterdi; `SourceDocument.data_snapshot=PROTECT` blocker'ı destructive çözüm olmadan açık teknik takip maddesidir.

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
  Sıradaki görev Görev 52'dir.

## 12. Açık Sorular

Session identity mapping, masking ve retention; stop/restart/continue semantiği; geç veya eksik kayıtlar; alarm source mapping ve clear semantics; GPON senaryo ağırlıkları; ticari iade koşulları; Yusuf/Sercan'dan gelecek örnek kayıtların alan eşlemesi açık konulardır. Kaynağı olmayan kurum içi bilgi uydurulmaz.

## 13. Yeni Codex Oturumu İçin Kurallar

İşe `git status --short`, `git rev-parse HEAD` ve son commit ile başla. Tamamlanmış görevleri yeniden uygulama, kullanıcı değişikliklerini silme, görevin dışına refactor taşıma. Her görevde tüm repo kataloglanmaz; önce bu handoff ve ilgili REV-01/REV-00 dokümanları okunur. Uygulama görevinde yalnız ilgili testler, önemli entegrasyon kapısında veya finalde full suite çalıştırılır. Her tamamlanan görev ayrı commit alır. 24 saat kuralı doğrulanmadan kodlanmaz; canlı simülasyon veya yeni MCP kendiliğinden başlatılmaz. REV-12 tamamlanmadan Görev 52'ye geçilmez.

## 14. Yeni Oturuma Yapıştırılacak Başlangıç Promptu

```text
docs/CODEX_HANDOFF.md dosyasını tamamen oku. Handoff'ın yönlendirdiği güncel
REV-01 ve REV-00 belgelerini oku. git status, HEAD ve son commit'i doğrula.
Belgeyle kod çelişirse güncel kod/git durumunu kaynak kabul et. Henüz
implementasyon yapmadan checkpoint'i en fazla 10 maddede özetle. Sonraki
görev promptunu kullanıcıdan bekle.
```
