# SYN-COMP-2026 v1 Broadband Telafi Kuralları

> Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Amaç

Broadband hizmetlerinde full outage, partial outage ve degradation etkilerinin sentetik kural motorunda nasıl ayrıldığını açıklar.

## Koşullar

Temel fiyat kaynağı `contracted_monthly_price` değeridir. Fiyat bulunamazsa fallback yapılmaz ve manual review uygulanır. Süre sabit 30 gün varsayımıyla değil, gerçek billing period saniyeleriyle hesaplanır.

## Full Outage

`BB-FULL-OUTAGE-TIERED` yalnız broadband ve `full_outage` etkisinde kullanılır. 30 dakikanın altı `0.00` ve ineligible kabul edilir. 30 dakika–2 saat aralığı basis’in `%2`si, 2–6 saat `%8`, 6–24 saat `%20`, 24 saat ve üzeri `%35`tir. Pozitif sonuçta minimum meaningful credit `10.00 TRY`, incident cap basis’in `%40`ıdır.

## Partial Outage

`BB-PARTIAL-OUTAGE-PRORATED`, en az 1800 saniyelik partial outage için şu girdileri kullanır: price basis, affected duration seconds, billing period seconds ve `affected_capacity_ratio`. Oran 0–1 aralığında structured evidence’dan gelmelidir. Eksik oran varsayımla doldurulmaz; manual review yapılır. Incident cap basis’in `%25`idir.

## Degradation

`BB-DEGRADATION-QUALITY`, en az 1800 saniyelik quality degradation için SLA threshold aşımını kullanır. `SLA_EXCEEDANCE_TIERS` değerleri mevcut RuleVersion action config’inden okunur: aşım oranı `>1.00–1.25` için `%3`, `>1.25–2.00` için `%7`, `>2.00` için `%12`. Incident cap basis’in `%20`idir. Birden fazla ağır kalite ihlali severe sınıfını destekleyebilir.

## İstisnalar

Aynı incident içinde full outage, partial outage ve degradation base tutarları toplanmaz. Protection loss, no direct customer impact veya unknown etki bu dokümandaki parasal base kurallara dönüştürülmez.

## Kanıt ve Referanslar

Süre, impact class, quality measurement, SLA threshold, affected capacity ve seçilen price basis Decision Evidence’a yazılır. İlgili vakalar `GT-MCR-RULE-FULL-OUTAGE-001`, `GT-MCR-RULE-UNDER-30-001`, `GT-MCR-RULE-PARTIAL-PRORATED-001` ve `GT-MCR-RULE-BB-DEGRADATION-001` kodlarıdır.
