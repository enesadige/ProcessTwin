# SYN Failover ve Planlı Bakım Prosedürü 2026

> Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Amaç

Primary/backup yol geçişleri ile planlı bakım etkilerini aynı sentetik olay akışında ayırır.

## Failover Adımları

Primary path down olduğunda backup bağlantının varlığı, geçiş sonucu ve transition duration birlikte değerlendirilir. Hitless ve near-hitless geçiş müşteri outage’ı oluşturmaz. 5–30 saniyelik geçiş evidence-only, SLA’yı aşan 30–60 saniyelik geçiş Metro kısa interruption adayıdır. Başarılı fakat kaliteyi bozan geçiş degraded failover, geçişin yapılamadığı durum failed failover’dır.

## Backup ve Shared-Risk

`BACKUP_LINK_UNAVAILABLE` primary çalışırken oluşuyorsa protection loss’tur ve otomatik outage telafisi değildir. Required path diversity ile observed `partially_diverse`, `shared_risk` veya `unknown` eşleşmiyorsa SLA evidence ve gerektiğinde manual review üretilir. Shared-risk yedek yol bağımsız kabul edilmez.

## Planlı Bakım

Planlı pencere içindeki ve beklenen kapsamda tamamlanan bakım normal planned maintenance’tır. Pencere dışına taşan gerçek etki overrun olarak kaydedilir. Beklenmeyen müşteri etkisi veya bağımsız plansız incident oluşursa mevcut bakım planı sessizce değiştirilmez; bağlı ayrı unplanned incident oluşturulur.

## İstisnalar ve Kanıt

Primary çalışırken backup kaybı full outage değildir. Failed failover ile broadband full outage aynı olay için iki ayrı base ödeme olarak toplanmaz. Transition duration, maintenance window, observed path diversity, backup bağlantısı ve impact class Decision Evidence’a yazılır.

## Referanslar

`GT-MCR-NET-FAILED-FAILOVER-001`, `GT-MCR-NET-SHARED-RISK-001`, `GT-MCR-RULE-FAILOVER-45S-001`, `GT-MCR-RULE-PROTECTION-LOSS-001`, `GT-MCR-RULE-PLANNED-NORMAL-001` ve `GT-MCR-RULE-MAINT-OVERRUN-001` örnekleridir.
