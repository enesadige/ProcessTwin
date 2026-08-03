# SYN-COMP-2026 v1 Metro Ethernet ve SLA Kuralları

> Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Amaç

Metro Ethernet aboneliklerinde contractual SLA, kalite ölçümleri ve failover davranışının sentetik değerlendirmesini açıklar.

## Tanımlar

Metro Ethernet aboneliği `service_type=metro_ethernet`, `technology=fiber` ve kurumsal/public segmentlerle sınırlıdır. `availability`, `latency`, `jitter` ve `packet_loss` değerleri Subscription.sla_profile eşikleriyle karşılaştırılır.

## SLA İhlalleri

`ME-AVAILABILITY-BREACH` availability shortfall değerini kullanır: `>0.00–0.10` için `%3`, `>0.10–0.50` için `%8`, `>0.50–1.00` için `%15`, `>1.00` için `%25`. `ME-LATENCY-BREACH`, `ME-JITTER-BREACH` ve `ME-PACKET-LOSS-BREACH` en az 15 dakikalık ihlal ve measured/threshold exceedance ratio ister. Oran tier’ları `%3`, `%7`, `%12`dir.

Aynı incident’ta latency, jitter ve packet-loss tutarları toplanmaz; en yüksek rate’li aday primary base olarak seçilir. Metro/SLA incident cap basis’in `%60`ıdır.

## Failover

`ME-SHORT-FAILOVER-INTERRUPTION` yalnız contractual Metro Ethernet için kullanılır. Hitless ve near-hitless geçişler evidence-only’dir. 30 saniyeyi aşan ve 60 saniyeye kadar olan SLA’yı aşan kısa geçiş `%0.5` oranını, `10 TRY` floor’unu ve `50 TRY` cap’ini kullanır.

`ME-DEGRADED-FAILOVER`, backup’a geçiş başarılı olsa da kalite SLA’sı ihlal edildiğinde kullanılır. `ME-FAILED-FAILOVER`, primary yolun başarısız olması, kullanılabilir backup bulunmaması veya geçişin başarısız olması ve müşteri full outage yaşaması durumundadır. Bu durumda süre tier’ları `%2`, `%6`, `%12`, `%25`, `%40`tır.

## İstisnalar

Başarılı failover broadband kuralına gönderilmez. Protection loss primary çalışırken oluşuyorsa outage değildir. Required path diversity ile observed diversity arasındaki uyumsuzluk parasal kredi değil evidence/manual review adayıdır.

## Kanıt ve Referanslar

SLA profili, ölçüm, transition duration, primary/backup sonucu ve path diversity evidence’a yazılır. İlgili vakalar `GT-MCR-RULE-ME-LATENCY-001`, `GT-MCR-RULE-FAILOVER-45S-001`, `GT-MCR-RULE-FAILED-FAILOVER-001` ve `GT-MCR-RULE-BACKUP-MISSING-001` kodlarıdır.
