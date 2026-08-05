# REV-11 RAG Causal Analysis Corpus ve Benchmark

REV-11, RAG'i karar motoru yapmadan causal analysis terminolojisini kaynak
retrieval ve açıklama amacıyla günceller. Yeni global `SYN-CAUSAL-ANALYSIS-2026`
v1; `SYN-ALARM-CATALOG-2026` v2; ve `SYN-COMP-2026-ELIGIBILITY` v2 manifestte
yer alır. Eski v1 kaynakları değiştirilmez.

Yeni bölümler alarmın outage olmadığını; CausalEvent sınırını, delayed
propagation ve root/child/symptom/supporting semantiğini; LOS/Dying Gasp
ayrımını; producer ile physical root ayrımını; session/failover impact
durumlarını; verified-impact compensation kapsamını; immutable
DecisionEvidence ve read-only baseline/candidate simulation'ı açıklar.

Manifest 10'dan 13 SourceDocument descriptor'ına çıktı. Son doğrulanmış canlı
baseline 10 SourceDocument / 74 DocumentChunk / 296 embedding idi; bu çalışma
ortamında PostgreSQL bağlantısı sandbox tarafından engellendiği için native seed
ve selected-document index çalıştırılmadı ve yeni canlı sayılar iddia edilmedi.
Seed aynı identity'de content/metadata değişikliğini reddeder; index reset'siz
aynı chunk spec'inde unchanged davranır.

Dokuz causal benchmark vakası eklendi; benchmark manifesti 25 vakadır.
Qwen `qwen3-embedding:4b` ve Gemini `gemini-embedding-2` ayrı setler olarak
768 dimension ile korunur; Qwen query prompt `qwen3-telecom-query-v1`dir.
CSV, PII, credential ve raw payload corpus'a eklenmedi. `SourceDocument`
snapshot `PROTECT` reset blocker'ı değiştirilmedi. Sıradaki görev REV-12'dir.
