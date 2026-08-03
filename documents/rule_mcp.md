# Rule MCP

Rule MCP, ProcessTwin kural seti, kural versiyonu, conflict/priority bilgisi ve
mevcut DecisionEvidence kayıtlarını LLM araç çağrılarına açan read-only MCP
server'dır. Yeni eligibility, telafi tutarı, CompensationEvaluation veya
DecisionEvidence üretmez.

## Runtime

- SDK: `mcp==2.0.0`
- Varsayılan transport: stdio
- Başlatma:

```bash
MCP_BACKEND_BASE_URL="http://127.0.0.1:8000" \
MCP_BACKEND_SERVICE_TOKEN="<internal-service-token>" \
python -m mcp_servers.rules
```

Gerekli environment değişkenleri:

- `MCP_BACKEND_BASE_URL`
- `MCP_BACKEND_SERVICE_TOKEN`
- `MCP_BACKEND_TIMEOUT_SECONDS` opsiyonel

Backend tarafında aynı token `INTERNAL_API_SERVICE_TOKEN` olarak ayarlı olmalıdır.
Token repo içine yazılmaz.

## Tool Kataloğu

- `search_rules`
- `get_rule`
- `get_rules_effective_at`
- `get_rule_version_history`
- `find_related_rules`
- `detect_rule_conflicts`
- `get_rule_evidence`
- `search_rule_documents`

Bütün tool input'larında `snapshot_identifier` zorunludur. Identifier önce
`DataSnapshot.snapshot_key`, sonra tekil `DatasetVersion.slug` olarak çözülür.
Aktif snapshot'a sessiz fallback yapılmaz.

`search_rule_documents`, authenticated `POST /api/internal/v1/rag/search/`
endpoint'ini adapter olarak çağırır. `semantic`, `full_text` ve varsayılan
`hybrid` modlarını; timezone-aware `evaluation_time`, rule/document ve dil
filtrelerini destekler. Sonuçlarda kaynak doküman kodu ve sürümü, heading,
section path, chunk metni ve backend skorları bulunur. `document_version`
SourceDocument sürümüdür; `rule_version` RuleVersion referansıdır.

Hybrid semantic provider kullanılamadığında backend'in
`effective_mode=full_text_fallback` sonucu ve warning'i değiştirilmeden aktarılır.
Boş arama sonucu başarılı ve sıfır kayıtlı response olarak döner. Ham embedding
vektörü MCP response'una eklenmez.

## Çıktı Politikası

Rule MCP varsayılan olarak kural ve aksiyonları insan okunabilir özetle döndürür.
`condition_tree` ve `action_config` ham JSON alanları yalnız
`include_raw_config=true` verilirse response'a eklenir.

`get_rules_effective_at` ve `detect_rule_conflicts` condition değerlendirmesi
yapmaz. Conflict çıktısı yalnız `candidate_order` ve `ordering_hint` verir; winner,
final decision veya parasal sonuç üretmez.

## Sorumluluk Sınırı

Rule MCP RuleSet/Rule/RuleVersion arama, event-time version seçimi,
conflict/priority açıklaması ve mevcut DecisionEvidence okuma işlerini yapar.
RAG kaynak aramasını backend'e devreder; MCP içinde embedding, search veya
ranking hesabı yapmaz.
Yeni telafi uygunluğu, yeni tutar hesabı, CompensationEvaluation ve yeni
DecisionEvidence üretimi Compensation MCP kapsamındadır.
