# SYN-COMP-2026 v1 Modifier, Sınır ve Manual Review Kuralları

> Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Amaç

Base rule sonucuna izin verilen modifier’ların, cap/floor sınırlarının ve evidence eksikliği durumlarının nasıl uygulandığını açıklar.

## Modifier Kuralları

`MOD-GRADED-RESTORATION`, hizmetin kademeli döndüğü ve ilk restoration sonrasında ölçülebilir etkinin en az 30 dakika sürdüğü durumda base amount üzerinden `%10` ekler. `MOD-RECURRING-INCIDENT`, aynı subscription, probable cause family ve ilişkili branch içinde resolved önceki olayları değerlendirir; child alarm ve duplicate olay recurring sayılmaz. `MOD-MAINTENANCE-OVERRUN`, yalnız planlı pencere dışındaki gerçek etkiyi dikkate alır ve 30 dakikayı aşan overrun’da `%10` ekler. `MOD-RESTORATION-TARGET-BREACH`, contractual restoration target aşıldığında Metro/business SLA base sonucuna `%10` ekler.

Modifier’lar bileşik uygulanmaz; ilk base amount üzerinden hesaplanır ve toplam modifier oranı `%40` ile sınırlıdır.

## Cap ve Floor

Pozitif parasal sonuçta minimum meaningful credit `10 TRY`dir. Broadband incident cap basis’in `%40`ı, Metro/SLA cap basis’in `%60`ı, billing-period cumulative cap basis’in `%75`idir. Pre-cap tutar basis’in `%100`ünü veya `10.000 TRY`yi aşarsa otomatik final settlement yerine manual review gerekir.

## Conflict ve Stackable

Aynı hizmet etkisini temsil eden base rule’lar toplanmaz. En yüksek priority, eşitlikte condition specificity ve son olarak alfabetik rule code seçimi kullanılır. Yalnız açıkça stackable olan modifier’lar uygulanır; seçilmeyen adaylar Decision Evidence içinde excluded olarak kalır.

## Kanıt ve Manual Review

Path diversity required/observed uyumsuzluğu, missing backup, unknown root cause, missing price, eksik quality ölçümü veya çelişkili evidence otomatik tutar üretmez. `MR-UNKNOWN-MISSING-EVIDENCE`, manual review nedenlerini ve eksik alanları evidence’a yazar.

## Referanslar

İlgili vakalar `GT-MCR-RULE-RECURRING-MOD-001`, `GT-MCR-RULE-MAINT-OVERRUN-001`, `GT-MCR-RULE-MONTHLY-CAP-001`, `GT-MCR-RULE-MISSING-PRICE-001`, `GT-MCR-RULE-UNKNOWN-ROOT-001`, `GT-MCR-RULE-SHARED-RISK-DIVERSITY-001` ve `GT-MCR-RULE-DUPLICATE-001` kodlarıdır.
