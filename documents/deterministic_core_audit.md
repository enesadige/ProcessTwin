# Deterministic Core Audit - Gorev 037

Bu not, MCP ve LLM katmanina gecmeden once cekirdek deterministik servislerin
hangi testlerle dogrulandigini ozetler. GroundTruthCase yalniz test oracle'i
olarak kullanilir; production servisleri ground truth okumaz.

| Servis | Kabul kriteri | Test kapsami |
| --- | --- | --- |
| NetworkTopologyService | BNG cocuklari, ancestor, subgraph, cross-snapshot izolasyonu, dongu korumasi | `backend/apps/network/tests/test_topology_service.py` |
| OutageService | Kapali/ongoing outage suresi, saniye bazli hesap, evaluation_time zorunlulugu, naive datetime reddi | `backend/apps/operations/tests/test_outage_service.py` |
| CustomerImpactService | Ana BNG ve kisa outage musteri/abonelik etkisi ground truth ile eslesir, duplicate musteri tekillesir, cross-snapshot ve gecersiz baglanti dislanir | `backend/apps/customers/tests/test_customer_impact_service.py`, `backend/apps/core/tests/test_deterministic_core_integration.py` |
| AlarmCorrelationService | MVP alarm katalogu ile korelasyon skoru, baska BNG dali dislama, cross-snapshot dislama, deterministik siralama | `backend/apps/operations/tests/test_alarm_correlation_service.py`, `backend/apps/core/tests/test_deterministic_core_integration.py` |
| RootCauseService | Ana BNG root cause `confirmed`, baska BNG dali dislanir, eksik/uzak alarm `unknown`, ongoing/naive hata kontrolleri | `backend/apps/operations/tests/test_root_cause_service.py`, `backend/apps/core/tests/test_deterministic_core_integration.py` |
| RuleEvaluationService | REFUND-001 v1/v2 tarih secimi, 179/180 ve 119/120 dakika esikleri saniye bazinda, missing field/operator/version manual_review | `backend/apps/rules/tests/test_rule_evaluation_service.py`, `backend/apps/core/tests/test_deterministic_core_integration.py` |
| CompensationService | Eligible/ineligible/manual_review, Decimal tutar, 399.90 -> 39.99, 499.90 -> 49.99, toplam 5173.50 TRY, cift abonelik ayri hesap, yan etkisizlik | `backend/apps/compensation/tests/test_compensation_service.py`, `backend/apps/core/tests/test_deterministic_core_integration.py` |

## Entegrasyon Sonuclari

- Ana outage `OUT-MAL-BNG-001`:
  - Sure: 12000 saniye / 200 dakika
  - Etkilenen abonelik: 150
  - Etkilenen musteri: 140
  - Root cause: `BNG-MAL-001`
  - Root cause classification: `confirmed`
  - Rule: `REFUND-001 v2`
  - Eligibility: `eligible`
  - Toplam telafi: `5173.50 TRY`

- Kisa outage'lar:
  - `OUT-MAL-OLT-001`: 2700 saniye, `REFUND-001 v1`, ineligible, `0.00 TRY`
  - `OUT-MAL-DSLAM-001`: 4200 saniye, `REFUND-001 v2`, ineligible, `0.00 TRY`

- Yan etkisizlik:
  - Servis cagrilari yeni `Alarm`, `Incident`, `Outage`, `CompensationEvaluation`,
    `Rule`, `RuleVersion`, `Subscription` veya `SubscriptionConnection` kaydi
    olusturmaz.
  - Ayni girdilerle tekrar cagrilar ayni sirali ciktilari uretir.
