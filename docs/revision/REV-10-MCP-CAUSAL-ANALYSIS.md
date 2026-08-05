# REV-10 MCP Causal Analysis

REV-10A tamamlandı: Network MCP (9) `correlate_alarms` ve
`rank_root_cause_candidates`, Customer MCP (7) `get_customer_outage_history`
araçlarında additive `causal_event_code` ile read-only causal analysis özeti
sunar. MCP handler'ları InternalAPIClient kullanır; backend business logic'i
tekrar edilmez. Public aggregate ve reason code'lar döner; PII/raw payload/PK
dönmez. REV-10B de tamamlandı: Rule MCP (8) `get_rule_evidence` ve
Compensation MCP (6) `get_compensation_evidence` causal event read-only
özetini map eder. Rule RAG retrieval aracı değişmedi.

REV-10 kapanışı tamamlandı: causal çağrılar `causal_event_code` ile legacy
identifier olmadan geçerlidir; legacy çağrılar legacy identifier ile aynı
kalır ve iki çağrı biçimi birlikte kabul edilmez. Internal API gerçek causal
role sayıları, failover-protected assessment sayısı ve mevcut compensation
aggregate'ini döndürür; değerlendirme yoksa açık pending/null alanları
kullanılır. Dört MCP, InternalAPIClient üzerinden bu read-only sonucu map
eder. Tool sayıları 9 / 7 / 8 / 6 olarak korunur. Sıradaki REV-11'dir.

Kapanış doğrulaması: dört MCP hedefli tool testi 80 passed; causal API ile
REV-06/07/08 küçük regresyonları 14 passed; shared backend-client,
security ve MCP contract paketiyle MCP hedefli testler 121 passed. Touched
Python dosyaları için Ruff ve `manage.py check` temizdir.
