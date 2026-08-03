# SYN-COMP-2026 v1 Uygunluk ve Dışlama Kuralları

> Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Amaç

Bir olayın sentetik telafi değerlendirmesine girip girmeyeceğini açıklar.

## Kapsam

Bu metin `ELIG-SUBSCRIPTION-VALID`, `ELIG-CUSTOMER-IMPACT-CONFIRMED`, `EXCL-PENDING-CANCELLED`, `EXCL-SUSPENSION-POLICY`, `EXCL-PLANNED-MAINTENANCE-NORMAL`, `EXCL-PROTECTION-LOSS-ONLY` ve `EXCL-DUPLICATE-COMPENSATION` kodlarını kapsar.

## Tanımlar

Abonelik olay zamanında geçerli olmalı ve fiziksel bağlantısı olayla örtüşmelidir. Müşteri etkisi deterministik `CustomerImpactService` sonucu ile doğrulanır. Ödeme kaydındaki overdue veya late durumu tek başına exclusion değildir.

## Kurallar

`ELIG-SUBSCRIPTION-VALID` aktif ve olay sırasında geçerli aboneliği geçirir. `ELIG-CUSTOMER-IMPACT-CONFIRMED` doğrulanmış müşteri etkisi ister. `EXCL-PENDING-CANCELLED` pending veya olaydan önce cancelled aboneliği otomatik olarak uygun olmayan sonuca götürür.

Suspended abonelikte `suspension_reason` incelenir. `customer_request` ve `payment_related` otomatik telafiye girmez. `provider_fault` normal uygunluk akışına girebilir. `administrative` ve `unknown` manual review sonucudur.

## Planlı Bakım ve Protection

Pencere içinde tamamlanan `planned_maintenance`, `EXCL-PLANNED-MAINTENANCE-NORMAL` ile otomatik parasal telafi dışında kalabilir. Backup yolun kaybı primary çalışırken gerçekleşmişse `EXCL-PROTECTION-LOSS-ONLY` evidence-only davranışı üretir; outage varsayılmaz.

## Duplicate ve Eksik Kanıt

Aynı subscription ve incident için kesinleşmiş telafi varsa `EXCL-DUPLICATE-COMPENSATION` ikinci sonucu engeller. Olay zamanı, fiyat, müşteri etkisi veya gerekli kanıt eksikse otomatik tutar üretilmez ve `MR-UNKNOWN-MISSING-EVIDENCE` ile manual review yapılır.

## Kanıt ve Referanslar

Değerlendirme source snapshot, event time, subscription status, suspension reason, impact sonucu ve duplicate kontrolünü kanıtlamalıdır. İlgili ground-truth örnekleri `GT-MCR-RULE-PAYMENT-SUSPENSION-001`, `GT-MCR-RULE-PROVIDER-FAULT-SUSPENSION-001`, `GT-MCR-RULE-DUPLICATE-001` ve `GT-MCR-RULE-UNKNOWN-ROOT-001` kodlarıdır.
