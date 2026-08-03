# SYN 2026 Alarm Kataloğu

> Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Amaç

Multi-city realism snapshot içinde kullanılan 30 sentetik alarm tipinin kod, kaynak, önem ve korelasyon anlamını tanımlar.

## Katalog

| Kod | Kategori | Kaynak/etki özeti |
|---|---|---|
| `BNG_UNREACHABLE` | erişilebilirlik | BNG erişilemez; geniş alt topolojide full outage adayıdır. |
| `METRO_AGG_UNREACHABLE` | erişilebilirlik | Metro aggregation erişilemez; alt erişim cihazlarını etkileyebilir. |
| `OLT_UNREACHABLE` | erişilebilirlik | OLT erişilemez; bağlı PON abonelikleri etkilenebilir. |
| `DSLAM_UNREACHABLE` | erişilebilirlik | DSLAM erişilemez; bağlı DSL hatlarında kesinti adayıdır. |
| `ACCESS_NODE_UNREACHABLE` | erişilebilirlik | Erişim cihazına ulaşılamaz; etki cihaz alt ağında hesaplanır. |
| `UPLINK_DOWN` | link | Üst bağlantı down durumunu gösterir. |
| `FIBER_CUT_SUSPECTED` | fiber | Fiber rota kesintisi şüphesini ve ortak yol etkisini gösterir. |
| `LINK_PACKET_LOSS_HIGH` | link | Paket kaybı yüksek; hizmet sürebilir ancak kalite düşer. |
| `LINK_FLAPPING` | link | Link’in kısa aralıklarla tekrarlı down/up olduğunu gösterir. |
| `BACKUP_LINK_UNAVAILABLE` | link | Primary çalışırken backup yolun kullanılamadığını gösterir. |
| `PON_PORT_DOWN` | GPON | PON portunun down olduğunu gösterir. |
| `OPTICAL_SIGNAL_LOW` | GPON | Optik sinyal eşik altında; degradation adayıdır. |
| `OPTICAL_SIGNAL_LOSS` | GPON | Fiber optik sinyal tamamen kaybolmuştur. |
| `ONT_DISCONNECT_SURGE` | GPON | Aynı PON portunda çok sayıda ONT kopması vardır. |
| `PON_CAPACITY_THRESHOLD` | GPON | PON kapasite kullanım eşiği aşılmıştır. |
| `DSL_PORT_DOWN` | DSL | DSL servis portu down durumundadır. |
| `DSL_LINE_QUALITY_DEGRADED` | DSL | Attenuation/SNR metrikleri line quality degradation gösterir. |
| `DSL_RETRAIN_FREQUENT` | DSL | DSL hattında sık retrain oluşur; intermittent adaydır. |
| `DSLAM_PORT_SATURATION` | DSL | DSLAM servis port kapasitesi baskı altındadır. |
| `DEDICATED_PORT_DOWN` | Metro | Kurumsal dedicated port down durumundadır. |
| `SLA_LATENCY_BREACH` | SLA | Contractual latency threshold aşılmıştır. |
| `SLA_PACKET_LOSS_BREACH` | SLA | Contractual packet-loss threshold aşılmıştır. |
| `PRIMARY_PATH_DOWN` | failover | Primary yol down olmuştur. |
| `FAILOVER_UNSUCCESSFUL` | failover | Trafik backup yola aktarılamamış ve full outage adayı oluşmuştur. |
| `DEVICE_RESOURCE_HIGH` | kaynak | Cihaz CPU/memory kaynak baskısı yüksektir; tek başına outage kanıtı değildir. |
| `BANDWIDTH_UTIL_HIGH` | kapasite | Link veya port bant genişliği eşik üstündedir; kalite baskısı oluşturabilir. |
| `COMMERCIAL_POWER_LOSS` | enerji | Ticari enerji kaybı vardır. |
| `BACKUP_POWER_DEGRADED` | enerji | Backup power state/capacity zayıflamıştır. |
| `HIGH_TEMPERATURE` | çevre | Cihaz sıcaklığı eşik üstündedir. |
| `COOLING_FAILURE` | çevre | Soğutma sistemi arızası gözlenmiştir. |

## Severity, Kaynak ve Korelasyon

Her alarmın `severity`, `allowed_source_kinds`, `supported_device_types`, `service_impact` ve `root_cause_candidate` değerleri mevcut `AlarmType` kayıtlarından alınır. Alarm kendi başına müşteri telafisi hesaplamaz. Zaman yakınlığı, topoloji, alarm family ve failure-domain üyeliği ile correlation yapılır.

## Referanslar

Bu katalogdaki kodların tamamı multi-city `AlarmType` kayıtlarıyla birebir karşılaştırılmalıdır. Alarm yaşam döngüsü ve incident ayrımı `SYN-OPERATIONS-LIFECYCLE-2026` prosedüründe açıklanır.
