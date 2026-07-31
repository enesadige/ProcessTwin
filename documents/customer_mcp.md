# Customer MCP

Customer MCP, ProcessTwin müşteri, abonelik ve ticari geçmiş verilerini LLM araç
çağrılarına açan read-only MCP server'dır. Yeni telafi, rule evaluation, root-cause
veya topoloji hesabı yapmaz; authenticated internal API üzerinden kontrollü backend
okuma adapter'larını ve mevcut deterministik servisleri çağırır.

## Runtime

- SDK: `mcp==2.0.0`
- Varsayılan transport: stdio
- Başlatma:

```bash
MCP_BACKEND_BASE_URL="http://127.0.0.1:8000" \
MCP_BACKEND_SERVICE_TOKEN="<internal-service-token>" \
python -m mcp_servers.customer
```

Gerekli environment değişkenleri:

- `MCP_BACKEND_BASE_URL`
- `MCP_BACKEND_SERVICE_TOKEN`
- `MCP_BACKEND_TIMEOUT_SECONDS` opsiyonel

Backend tarafında aynı token `INTERNAL_API_SERVICE_TOKEN` olarak ayarlı olmalıdır.
Token repo içine yazılmaz.

## Tool Kataloğu

- `get_customer_profile`
- `get_customer_subscription`
- `get_customer_payment_status`
- `get_customer_outage_history`
- `get_customer_compensation_history`
- `list_customers_by_device`
- `list_customers_by_location`

Bütün tool input'larında `snapshot_identifier` zorunludur. Identifier önce
`DataSnapshot.snapshot_key`, sonra tekil `DatasetVersion.slug` olarak çözülür.
Aktif snapshot'a sessiz fallback yapılmaz.

## Gizlilik

Customer MCP varsayılan olarak yalnız `masked_display_name` döndürür. Açık
`display_name`, sadece `include_display_name=true` verildiğinde ve snapshot sentetik
olduğunda response'a eklenir. Telefon, e-posta, kimlik, adres, raw metadata, token,
SQL veya traceback döndürülmez.

Ödeme, kampanya ve telafi geçmişi sentetik dataset kapsamında kontrollü özet olarak
açılır. Yeni telafi uygunluğu veya tutar hesabı Compensation MCP kapsamındadır.
