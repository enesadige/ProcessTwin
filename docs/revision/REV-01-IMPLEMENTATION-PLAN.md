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
| REV-10 — Dört MCP uyarlaması | Backend kanıtlarını MCP contract'i bozmadan yansıtmak | Network/Customer/Rule/Compensation response mapping; gerekirse kontrollü yeni read tool değerlendirmesi | `mcp_servers`, core registry | tool unit, shared contract/security, live health | Tool sayıları/isimleri açık karar olmadan değişmez; raw/PII sızmaz | `feat: surface verified operations evidence in MCP` |
| REV-11 — RAG corpus ve benchmark yenilemesi | Yeni operasyon semantiğini versioned kaynaklarla aratılabilir yapmak | source docs, chunks, iki aktif embedding seti, benchmark/Ground Truth evidence açıklamaları | `rag`, `documents` | corpus/hash/chunk/embed/search benchmark | Eski source version korunur; yeni corpus semantic/deterministic kapıları geçer | `docs: refresh RAG operations evidence corpus` |
| REV-12 — Final consistency ve regresyon | Yeni veri zincirini uçtan uca kapatmak | multi-city snapshot row counts, validators, export/audit, baseline comparison | tüm backend/MCP/datasets | full suite, 30/30 GT, Maltepe, native PostgreSQL, MCP health | Nedensel zincir, verified impact ve legacy regression birlikte geçer | `test: validate causal operations revision` |

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
