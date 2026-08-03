# SYN Operasyon Olay Yaşam Döngüsü 2026

> Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Amaç

Sentetik ağ olaylarının alarmdan müşteri etkisine ve deterministik değerlendirmeye kadar izlediği akışı açıklar.

## Kapsam

Alarm, operational event, incident, outage, degradation, protection event ve root-cause evidence akışları bu prosedürde anlatılır.

## İşlem Adımları

1. Kaynak cihaz, link veya port üzerinde alarm oluşur.
2. Alarm `open`, `cleared` veya `suppressed` lifecycle durumlarından biriyle saklanır; duplicate olaylar occurrence count ve deduplication key ile birleştirilir.
3. Zaman yakınlığı, topoloji, alarm family ve failure-domain kanıtlarıyla correlation yapılır.
4. Yeterli kanıt varsa incident ve impact class belirlenir; yetersiz kanıt `unknown` kalır.
5. Gerçek hizmet erişilebilirliği kaybında outage oluşturulur. Degradation ve protection loss yalnız incident, quality measurement ve operational event olarak kalabilir.
6. CustomerImpactService deterministik müşteri ve abonelik aggregate’ini üretir.
7. RuleEvaluationService ve CompensationService ayrı aşamada değerlendirme yapar.

## Tanımlar ve İstisnalar

Tek noise alarmı tek başına incident oluşturmaz. Child alarm, aynı root cause’a bağlı correlation kanıtı olarak kullanılabilir. Root cause tahmin edilemiyorsa servis unknown sonucu ve kanıt eksikliğini korur; prosedür kesin sebep uydurmaz.

## Kanıt ve Referanslar

Her geçiş event time, source, topology/failure-domain, correlation score, impact ve evidence alanlarıyla açıklanır. Multi-city örnekleri `GT-MCR-NET-BNG-WIDE-001`, `GT-MCR-NET-METRO-AGG-001`, `GT-MCR-NET-FIBER-ROUTE-001`, `GT-MCR-NET-POWER-ZONE-001`, `GT-MCR-NET-PON-PARTIAL-001`, `GT-MCR-NET-DSLAM-GROUP-001`, `GT-MCR-NET-FLAPPING-001`, `GT-MCR-NET-UNKNOWN-RCA-001`, `GT-MCR-RULE-NOISE-NO-INCIDENT-001`, `GT-MCR-RULE-PAYMENT-SUSPENSION-001` ve `GT-MCR-RULE-PROVIDER-FAULT-SUSPENSION-001` kodlarıdır.
