# REV-06 — Correlation ve Root-Cause

## Sınırlar

Correlation, alarmı tek başına outage veya müşteri etkisi kabul etmez. Yeni
`CausalEvent` kayıtlarında event kimliği birincil sınırdır: farklı event'ler,
yakın zamanlı veya aynı topoloji dalında olsalar da birleştirilmez. Legacy
`causal_event=NULL` kayıtları mevcut dar zaman/topoloji skorlamasıyla
konservatif çalışmaya devam eder; backfill yapılmaz.

## Kanıt ve roller

Servis sonuçları `root`, `child`, `symptom`, `supporting`, `unrelated` ve
`noise` contract rollerini, mevcut `CorrelationReason` değerlerinden türetilen
stabil reason-code listesini ve privacy-safe kısa açıklamayı taşır. Eski
`IncidentAlarm` rolleri schema değiştirilmeden REV-02'nin additive mapping'iyle
uyumludur.

Same-CausalEvent değerlendirmesi zaman yayılımı (iki saate kadar), kaynak
hiyerarşisi, shared failure domain, alarm family/type uyumu ve clear/recovery
tutarlılığını birlikte kullanır. Clear sırası çelişirse skor düşer. Teknoloji
uyumsuzluğu ve farklı CausalEvent kesin dışlama nedenidir.

## Root-cause sıralaması

Outage bir CausalEvent'e bağlıysa yalnız o event'in alarmları aday üretir.
Structured physical root resource; erken alarm, root-capable alarm ve sınırlı
child/symptom fanout ile birlikte öncelik alır. Eşitlikte root resource,
başlangıç zamanı ve stabil cihaz kodu kullanılır; database PK sıralaması
kullanılmaz. Failure-domain veya link root'u bir producer adıyla değiştirilmez;
`ACA Korelasyon` fiziksel cihaz adayı değildir.

GPON'da OLT/uplink ve PON root kaynakları üst aday, distribution-cable için
fiziksel link/failure-domain kök kanıtıdır. Dying Gasp ve Device Not Active
symptom, high temperature supporting kanıtı olarak kalır. Optical flap tek
başına kesin root değildir. No-impact ve hitless failover için bu servis
customer-impact veya outage sonucu üretmez.

## Kapsam dışı ve açık sorular

REV-06 SessionEvent doğrulaması, CustomerImpactAssessment, compensation,
generator, API/MCP/RAG ve SourceDocument reset blocker'ını değiştirmez.
REV-07, session kanıtıyla potential/verified/no-impact/insufficient sonuçlarını
uygulayacaktır. Açık konular: gerçek feed clear semantics, source-level
inventory çözümü ve session identity/late-record toleransıdır.
