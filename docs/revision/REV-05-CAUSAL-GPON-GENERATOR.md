# REV-05 Nedensel GPON ve Multi-City Veri Üretimi

## Üretim modeli

`CONFIRMED` Multi-city timeline artık alarm, incident ve outage satırlarını
ayrı döngülerde üretip pozisyonla bağlamaz. Her scenario instance önce bir
`CausalEvent` ve topology-compatible root resource oluşturur; sonra relative
timeline üzerinden alarm, gerektiğinde incident/outage, operational event,
quality measurement ve privacy-safe synthetic `SessionEvent` kanıtları
türetilir. `IncidentAlarm` yalnız aynı causal event içindeki alarm satırlarına
bağlanır.

## GPON senaryoları

Yedi merkezi senaryo vardır: OLT erişilemezliği, tek PON port arızası,
distribution cable/access fiber arızası, sıcaklık kaynaklı degradation,
upstream/uplink yayılımı, session devam eden no-impact adayı ve intermittent
optical degradation. Root alarm child alarmdan önce üretilir; clear/recovery
ve CausalEvent bitişi son ilişkilendirilmiş kayıttan sonra kalır.

`DESIGN_DECISION` No-impact, yalnız sıcaklık anomaly, hitless failover ve
degradation vakaları otomatik Outage üretmez. SessionEvent paternleri yalnız
REV-07 doğrulamasına kanıttır; bu görev `CustomerImpactAssessment` veya
verified-impact kararı üretmez.

## Kalibrasyon ve kapsam

Scenario seçimi sabit 70 alarm veya eşit scenario sayısı yerine seed-tabanlı
ağırlıklarla yapılır. Event bütçesi yaklaşık eski ölçeği korur; kesin sayı
operasyonel gerçeklik iddiası değildir ve `synthetic calibration` olarak
saklanır. GPON ilk ayrıntılı zincirdir; BNG, aggregation, DSL/xDSL, Metro
Ethernet ve failover catalog senaryoları üretimde kalır.

Alarm kaydedilmeden önce REV-04 compatibility validator çalışır. Geçersiz
kaynak, scenario code ve stabil validator reason code ile üretimi durdurur.
Mevcut legacy multi-city satırları otomatik düzeltilmez; yeni doğru kayıtlar
seed tekrar üretildiğinde gelir. Maltepe generator ve REFUND-001 regression
değiştirilmedi.

## Snapshot ve sonraki işler

Snapshot row-count doğrulaması artık causal/session satırlarını gerçek tablo
sayılarıyla içerir ve timeline için mutlak alarm/incident/outage sayısı yerine
nedensel bağlantı invariant'larını denetler. RAG'a, API/MCP'ye, correlation
algoritmasına ve compensation davranışına müdahale edilmedi.

REV-06 temporal/topological correlation ve root-cause ranking'i bu kayıtları
kullanacak; REV-07 session evidence'tan potential/verified impact assessment
çıkaracaktır. Açık sorular: gerçek alarm clear semantiği, PON slot/card
mapping'i, scenario ağırlık kalibrasyonu ve session stop/recovery eşikleridir.
