# REV-10 MCP Causal Analysis

REV-10A tamamlandı: Network MCP (9) `correlate_alarms` ve
`rank_root_cause_candidates`, Customer MCP (7) `get_customer_outage_history`
araçlarında additive `causal_event_code` ile read-only causal analysis özeti
sunar. MCP handler'ları InternalAPIClient kullanır; backend business logic'i
tekrar edilmez. Public aggregate ve reason code'lar döner; PII/raw payload/PK
dönmez. REV-10B de tamamlandı: Rule MCP (8) `get_rule_evidence` ve
Compensation MCP (6) `get_compensation_evidence` causal event read-only
özetini map eder. Rule RAG retrieval aracı değişmedi. Sıradaki REV-11'dir.
