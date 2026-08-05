# REV-04 GPON Topoloji ve Alarm Kataloğu

## Amaç

`CONFIRMED` Alarm, tek başına doğrulanmış müşteri outage'ı değildir. REV-04,
mevcut topoloji kapsamını değiştirmeden AlarmType ile normalize kaynak
uyumluluğunu deterministik biçimde doğrular. Mevcut alarm kayıtları ve
generator ile üretilmiş olay zincirleri bu görevde değiştirilmez.

## Katalog kararları

- `REVISE` GPON cihaz/port/line alarmı kaynakları OLT ve GPON ile sınırlıdır:
  `OLT_UNREACHABLE`, `PON_PORT_DOWN`, `ONT_DISCONNECT_SURGE`,
  `PON_CAPACITY_THRESHOLD`, `OPTICAL_SIGNAL_LOW` ve `OPTICAL_SIGNAL_LOSS`.
- `ADD_NEW_RELATED_ALARM` `DISTRIBUTION_CABLE_DOWN` eklendi. Mevcut Alarm
  modelinde doğrudan `AccessSegment` kaynak FK'si olmadığından bu alarm bugün
  `network_link` veya `failure_domain` üzerinde normalize edilir. Access
  segment kaynak ilişkisi, generator'ın nedensel senaryo işinde REV-05'te
  kanıt/meta bağlamıyla ele alınacaktır.
- `REVISE` `HIGH_TEMPERATURE` yalnız device-level anomaly'dir. Sıcaklık,
  otomatik outage değil, root/supporting correlation kanıtıdır.
- `KEEP` DSL port/line ve dedicated port tipleri korunur: `DSL_PORT_DOWN`
  DSLAM portunda, DSL quality/retrain DSLAM/xDSL line'ında,
  `DEDICATED_PORT_DOWN` access-node portunda geçerlidir.
- `KEEP` `UPLINK_DOWN` yalnız link-level olaydır. `FAILOVER_UNSUCCESSFUL`
  ve diğer yüksek etki sınıfları dahi session/impact doğrulaması olmadan
  verified outage değildir.
- `MERGE_CANDIDATE` ve `REMOVE_CANDIDATE` REV-01 matrisindeki aday statülerini
  korur; bu görevde kod veya geçmiş kayıt silinmedi.

## Merkezi uyumluluk sözleşmesi

`apps.operations.alarm_topology` mevcut kalıcı AlarmType source-kind/device
ilişkilerini kullanır; migration açmadan gereken teknoloji, session ve direct
outage semantiğini typed policy olarak ekler. Catalog seed'i bu policy'yi
`AlarmType.metadata.topology_policy` altında sorgulanabilir, serializable
metadata olarak da saklar.

Validator `valid`, stabil reason code, kısa açıklama, alarm code, gerçek
source kind/technology ve beklenen source/technology listesini döndürür.
Başlıca reason code'lar: `unsupported_source_kind`,
`unsupported_device_type`, `unsupported_technology`,
`invalid_pon_port_source`, `invalid_dsl_port_source`,
`invalid_dsl_line_source`, `invalid_dedicated_port_source`,
`invalid_device_source` ve `invalid_link_source`.

PON kart/slot veya portun fiziksel PON alt-tipi için mevcut NetworkPort
şemasında ayrı inventory alanı yoktur. Bu nedenle bugünkü invariant
`PON_PORT_DOWN -> network_port -> OLT` şeklindedir; daha ayrıntılı PON
inventory doğrulaması kaynak mapping verisiyle sonraki revizyona bırakılır.

## Seed ve mevcut veri

Multi-city AlarmType seed'i idempotenttir: aynı snapshot/catalog tekrar
çağrıldığında type ve allowed source/device satırları çoğalmaz; seçili katalog
alanları güncellenir. Bu, alarm/incident/outage kayıtlarını üretmez veya
değiştirmez. Eski sentetik Alarm satırları yeni validator ile uyumsuz olabilir;
read-only audit sonucu REV-05 generator yeniden üretiminden önce veri düzeltme
olarak kullanılmayacaktır.

## REV-05'e bırakılanlar

Yedi GPON nedensel senaryosunun relative timeline'ı, CausalEvent bağlantıları,
alarm clear/recovery sırası, session evidence, no-impact/hitless failover ve
mevcut sabit alarm dağılımlarının kaldırılması REV-05 kapsamındadır.

## Açık sorular

- Kaynak sistemin distribution cable ve PON slot/port inventory mapping'i.
- OLT reachability alarmının device failure mı management-plane belirtisi mi
  olduğu.
- Alarm clear semantics, deduplication pencereleri ve gerçek alarm eşikleri.
- GPON scenario ağırlıkları ile gerçek örnek kayıtlar geldiğinde kalibrasyon.
