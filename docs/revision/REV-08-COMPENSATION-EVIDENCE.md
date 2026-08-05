# REV-08 — Compensation ve DecisionEvidence

Yalnız `verified_impact` connection assessment'leri mevcut deterministic
CompensationService'e aday scope verir. `potential_impact` ve
`verified_no_impact` değerlendirmeye girmez; `insufficient_evidence` eligible
sayılmaz ve aggregate içinde pending/manual-review olarak kalır. Mevcut rule
selection, RuleVersion, formula, cap/floor ve duplicate davranışı korunur.

Outage modeli değiştirilmez: verified impact operasyonel outage kapsamını
destekleyebilir; failover-protected/no-impact veya yalnız degradation kanıtı
full outage/customer compensation sonucu üretmez. Baseline/candidate çağrıları
aynı verified scope ile çalışır; bu adapter compensation kaydı yazmaz.

Evidence aggregate CausalEvent/outage public code, impact sayı/reasonları,
rule-version ve deterministic provenance taşır. Raw session/alarm payload,
IP/MAC, subscriber veya credential yazılmaz. Evidence hash ile get-or-create
idempotent, finalized kayıt immutable kalır. Doğrulanmamış 24 saat kuralı
uygulanmadı. REV-09 API yüzeyini ele alacaktır.
