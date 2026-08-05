# REV-05A Anonim Alarm Kalibrasyonu

## Amaç ve kaynak sınırı

Bu küçük kalibrasyon, Yusuf'un repository dışında tutulan anonim alarm örneğini yalnız alias, family, severity ve symptom-fanout sinyali olarak kullanır. CSV runtime girdisi değildir, repository'ye alınmaz ve gerçek Turkcell alarm oranı, outage, customer impact veya telafi kuralı iddiası üretmez.

## Normalizasyon

`apps.operations.alarm_normalization` ham başlığı deterministik olarak family, nullable subtype/canonical code, beklenen kaynak seviyesi, alarm-role adayı, producer semantiği ve güvenli reason code'a çevirir. Dying Gasp, feeder/OLT LOS, ONU LOS, PON LOS, generic LOS ve Device Not Active tek tipe körlemesine birleştirilmez. Kaynak seviyesi olmadan upstream Ethernet, GPON-port flap ve PON communication alias'ları canonical code üretmez.

`ACA Korelasyon` correlation producer'ıdır; fiziksel NetworkDevice türü değildir. Observed node type ile physical-resource expectation ayrı metadata alanlarıdır. NODETYPE/CITY/COUNTY veya kaynak çözümü eksik olduğunda sonuç reddedilmez; `partially_resolved`, `insufficient_source_context` ya da `unmapped_title` döner.

## Severity ve fanout

Geçerli raw severity katalog severity'sinin önündedir; katalog değeri yalnız boş/geçersiz raw değer için fallback'tir. CSV'deki Dying Gasp, LOS ve board dağılımları genel operatör politikası olarak yorumlanmaz.

Distribution-cable ve OLT/optical zincirlerine topology kapsamıyla sınırlı, seed-tabanlı değişken ONT-disconnect/Dying-Gasp symptom fanout'u eklendi. Nadir device-state symptom temsil edilir. Her alarm mevcut REV-04 topology validator'ından geçer. Scenario weights, temperature/no-impact ve hitless failover davranışı değiştirilmedi.

## Kullanılmayan alanlar ve açık takip

Örnek CSV'nin event ve clearance timestamp'leri topluca anonimize edildiği için temporal sıra, 48 saat süre, outage, session impact, eligibility veya refund çıkarılmadı. `SourceDocument.data_snapshot=PROTECT` nedeniyle native multi-city reset blocker'ı ayrı teknik konudur; bu görev relation veya reset helper'ını değiştirmez. REV-06 temporal/topological correlation ve root-cause ranking işini devralır.
