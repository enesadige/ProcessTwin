# REFUND-001 v2 Sentetik Kaynak Metni

> Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Amaç

Maltepe MVP regression dataset’inde kullanılan `REFUND-001` kuralının v2 tarihsel kaynak metnidir.

## Kapsam

Bu sürüm 2026-07-15T00:00:00+03:00 tarihinde yürürlüğe girer ve `valid_to=NULL` olarak devam eder.

## Koşullar

Olay `full_outage` olmalı; abonelik olay sırasında aktif ve fiziksel bağlantı olayla örtüşmelidir. Minimum etki süresi `120 dakika`dır. Zorunlu veri eksikse manual review sonucu kullanılır.

## Formül ve Price Basis

Price basis `contracted_monthly_price` değeridir. Aday tutar recurring aylık ücretin `%10`u olarak `TRY`, iki ondalık ve `ROUND_HALF_UP` ile hesaplanır. `maximum_amount` ve `minimum_amount` değerleri mevcut RuleVersion action config’inde null’dur.

## İstisnalar

Pending veya olaydan önce cancelled abonelikler uygun değildir. Geçerli connection overlap yoksa uygunluk oluşmaz. Payment debt/late payment, campaign discount ve previous compensation bu sentetik kuralda deferred input olarak kalır. Eksik fiyat, olay zamanı veya kanıt manual review’a gider.

## Maltepe Regression

`OUT-MAL-BNG-001` için v2 seçimi, 150 abonelik ve 140 müşterilik etkiyle mevcut regression akışında korunur. Toplam beklenen teknik regression sonucu `5173.50 TRY`dir. Bu değer yeni hesap değildir; mevcut ground-truth ve deterministic service sonucudur.

## Kanıt ve Referanslar

Decision Evidence seçilen RuleVersion v2, event time, duration, subscription validity, price basis, formül girdileri ve rounding sonucunu göstermelidir.
