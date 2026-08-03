# REFUND-001 v1 Sentetik Kaynak Metni

> Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Amaç

Maltepe MVP regression dataset’inde kullanılan `REFUND-001` kuralının v1 tarihsel kaynak metnidir.

## Kapsam

Bu sürüm 2026-01-01T00:00:00+03:00 ile 2026-07-14T23:59:59+03:00 aralığında geçerlidir. Veritabanındaki UTC karşılığı aynı zaman aralığını temsil eder.

## Koşullar

Olay `full_outage` olmalı; abonelik olay sırasında aktif ve fiziksel bağlantı olayla örtüşür olmalıdır. Minimum etki süresi `180 dakika`dır. Zorunlu alanlardan biri eksikse sonuç manual review olur.

## Formül ve Price Basis

Price basis `contracted_monthly_price` değeridir. Aday tutar recurring aylık ücretin `%10`u olarak `TRY`, iki ondalık ve `ROUND_HALF_UP` ile hesaplanır. Bu metin teknik regression kuralını açıklar; gerçek ticari politika değildir.

## İstisnalar

Pending veya cancelled abonelik, geçerli bağlantısı olmayan kayıt ve minimum süre altındaki olay uygun değildir. Payment debt/late payment, campaign discount ve previous compensation bu v1 kuralının deferred input’larıdır; tek başına operatör kaynaklı olay exclusion’ı değildir. Eksik kanıt otomatik sıfır tutar değil manual review sonucudur.

## Kanıt ve Referanslar

Evaluation event time, seçilen RuleVersion v1, duration, subscription validity, connection overlap, price basis ve rounding trace ile açıklanır. `REFUND-001` RuleVersion v1 ve Maltepe `OUT-MAL-BNG-001` regression kaydı bu metnin teknik referanslarıdır.
