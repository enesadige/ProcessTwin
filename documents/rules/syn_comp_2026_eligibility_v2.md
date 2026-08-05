# SYN-COMP-2026 Uygunluk ve Kanıt v2

Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Verified Impact Kapsamı

Yalnız verified_impact assessment kayıtları mevcut deterministic compensation değerlendirmesine aday olabilir. potential_impact değerlendirmeye girmez; verified_no_impact kapsam dışıdır; insufficient_evidence otomatik eligible değildir. Failover-protected bağlantı full outage veya telafi kanıtı değildir.

## Immutable DecisionEvidence

DecisionEvidence immutable kalır ve CausalEvent public code, privacy-safe impact sayıları, reason code'lar, RuleVersion ve deterministic provenance özeti taşıyabilir. Customer kimliği, IP, MAC, credential veya raw payload içermez.

## Baseline ve Candidate Simulation

Baseline-vs-candidate simulation aynı verified-impact girdisini kullanır. Candidate simulation kalıcı CompensationEvaluation veya finalized DecisionEvidence sonucunu değiştirmez. Doğrulanmamış bir "24 saat" kuralı uygulanmaz.
