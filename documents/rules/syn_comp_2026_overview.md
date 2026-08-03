# SYN-COMP-2026 v1 Sentetik Telafi Politikası

> Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Amaç

`SYN-COMP-2026` v1, multi-city realism snapshot içindeki müşteri etkisi ve telafi adaylarını deterministik biçimde açıklayan sentetik kural setidir. Kural motoru sonuç üretir; bu metin yalnızca kaynağı ve yorumlamayı açıklar.

## Kapsam

Kural seti 2026-07-01T00:00:00+03:00 tarihinde yürürlüğe girer ve `multi-city-realism-v1` snapshot’ına aittir. Gerçek operatör politikası değildir.

## Tanımlar

- **Eligibility:** Olay zamanında aboneliğin ve müşteri etkisinin değerlendirmeye uygun olmasıdır.
- **Exclusion:** Sonucu otomatik olarak dışlayan veya manual review’a yönlendiren koşuldur.
- **Base rule:** Aynı hizmet etkisi için seçilen tek temel parasal kuraldır.
- **Modifier:** Base amount üzerine uygulanan izinli ek etkidir.
- **Decision Evidence:** Seçim, fiyat, koşul, formül ve sınırların makine tarafından doğrulanabilir açıklamasıdır.

## Değerlendirme Sırası

1. Snapshot, olay zamanı ve bağlam doğrulanır.
2. Olay zamanına uygun `RuleSet` ve `RuleVersion` seçilir.
3. Abonelik geçerliliği ve müşteri etkisi kontrol edilir.
4. Kesin exclusion kuralları uygulanır.
5. Aynı conflict group içindeki base adayları priority, specificity ve rule code sırasıyla değerlendirilir.
6. Yalnız bir primary base rule seçilir.
7. İzin verilen modifier’lar ilk base amount üzerinden uygulanır.
8. Floor, incident cap ve billing-period cap uygulanır.
9. Duplicate ve manual review kontrolleri yapılır.
10. Sonuç Decision Evidence ile açıklanır.

## Kural Aileleri

`ELIG-SUBSCRIPTION-VALID`, `ELIG-CUSTOMER-IMPACT-CONFIRMED`, `EXCL-PENDING-CANCELLED`, `EXCL-SUSPENSION-POLICY`, `EXCL-PLANNED-MAINTENANCE-NORMAL`, `EXCL-PROTECTION-LOSS-ONLY` ve `EXCL-DUPLICATE-COMPENSATION` uygunluk/exclusion ailesidir.

`BB-FULL-OUTAGE-TIERED`, `BB-PARTIAL-OUTAGE-PRORATED` ve `BB-DEGRADATION-QUALITY` broadband ailesidir. `ME-*` kuralları Metro Ethernet, SLA ve failover olaylarını kapsar. `MOD-*`, `SLA-*`, `MR-UNKNOWN-MISSING-EVIDENCE` ve `CAP-FLOOR-CONFLICT` modifier, kanıt ve final policy davranışını tanımlar.

## Koşullar ve İstisnalar

Kural kodları, condition tree ve action config mevcut `RuleVersion` kayıtlarının kaynak değerleridir. Eksik fiyat, olay zamanı, root cause veya zorunlu kanıt otomatik sıfır tutara çevrilmez; `manual_review` sonucuna yönelir. `protection_loss` ve `no_direct_customer_impact` tek başına parasal outage üretmez.

## Kanıt ve Açıklanabilirlik

Kural seçimi, başarısız koşullar, dışlanan adaylar, seçilen price basis, formül girdileri, modifier’lar ve cap/floor izleri Decision Evidence içinde tutulur. LLM bu kanıtı açıklayabilir ancak hesaplama yapamaz.

## İlgili Referanslar

Bu doküman `SYN-COMP-2026` altındaki 25 kuralı, multi-city 30 ground-truth vakasını ve `SYN-ALARM-CATALOG-2026` alarm kataloğunu kapsayan genel referanstır.
