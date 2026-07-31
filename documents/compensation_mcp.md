# Compensation MCP

Compensation MCP, ProcessTwin telafi uygunluğu, tutar hesaplama dry-run'ı,
opsiyon değerlendirmesi, kampanya kayıt özeti ve mevcut DecisionEvidence kayıtlarını
LLM araç çağrılarına açan MCP server'dır. İş kuralı veya telafi formülü yeniden
yazmaz; authenticated internal API üzerinden mevcut deterministik servisleri çağırır.

## Runtime

- SDK: `mcp==2.0.0`
- Varsayılan transport: stdio
- Başlatma:

```bash
MCP_BACKEND_BASE_URL="http://127.0.0.1:8000" \
MCP_BACKEND_SERVICE_TOKEN="<internal-service-token>" \
python -m mcp_servers.compensation
```

Gerekli environment değişkenleri:

- `MCP_BACKEND_BASE_URL`
- `MCP_BACKEND_SERVICE_TOKEN`
- `MCP_BACKEND_TIMEOUT_SECONDS` opsiyonel

Backend tarafında aynı token `INTERNAL_API_SERVICE_TOKEN` olarak ayarlı olmalıdır.
Token repo içine yazılmaz.

## Tool Kataloğu

- `evaluate_refund_eligibility`
- `calculate_refund_amount`
- `evaluate_compensation_options`
- `check_campaign_eligibility`
- `rank_compensation_options`
- `get_compensation_evidence`

Bütün tool input'larında `snapshot_identifier` zorunludur. Identifier önce
`DataSnapshot.snapshot_key`, sonra tekil `DatasetVersion.slug` olarak çözülür.
Aktif snapshot'a sessiz fallback yapılmaz.

## Persist Politikası

`evaluate_refund_eligibility`, `evaluate_compensation_options`,
`check_campaign_eligibility`, `rank_compensation_options` ve
`get_compensation_evidence` read-only çalışır. `calculate_refund_amount` varsayılan
olarak dry-run'dır ve kayıt yazmaz.

Kalıcı kayıt yalnız `calculate_refund_amount(persist=true)` ile, kapalı/finalizable
outage için oluşturulur. Bu akış transaction içinde `CompensationEvaluation` ve
immutable `DecisionEvidence` üretir veya aynı canonical identity için mevcut sonucu
döndürür. Ongoing outage için persist reddedilir.

## Sorumluluk Sınırı

Compensation MCP yeni campaign eligibility motoru, yeni ranking algoritması, settlement
veya `CompensationHistory` üretmez. Network topolojisi, root-cause ve customer impact
hesaplarını yeniden yazmaz. Rule seçimi, tutar hesabı, cap/floor, modifier ve duplicate
kontrolleri mevcut deterministik servislerden alınır.
