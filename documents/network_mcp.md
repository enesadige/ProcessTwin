# Network MCP

Network MCP, ProcessTwin ağ ve operasyon verilerini LLM araç çağrılarına açan
read-only MCP server'dır. Business logic hesaplamaz; authenticated internal API
üzerinden deterministik backend servislerini çağırır.

## Runtime

- SDK: `mcp==2.0.0`
- Varsayılan transport: stdio
- Başlatma:

```bash
MCP_BACKEND_BASE_URL="http://127.0.0.1:8000" \
MCP_BACKEND_SERVICE_TOKEN="<internal-service-token>" \
python -m mcp_servers.network
```

Gerekli environment değişkenleri:

- `MCP_BACKEND_BASE_URL`
- `MCP_BACKEND_SERVICE_TOKEN`
- `MCP_BACKEND_TIMEOUT_SECONDS` opsiyonel

Backend tarafında aynı token `INTERNAL_API_SERVICE_TOKEN` olarak ayarlı olmalıdır.
Token repo içine yazılmaz.

## Tool Kataloğu

- `get_device_details`
- `get_device_topology`
- `search_alarms`
- `search_outages`
- `get_outage_details`
- `calculate_customer_impact`
- `correlate_alarms`
- `rank_root_cause_candidates`
- `get_longest_outage`

Bütün tool input'larında `snapshot_identifier` zorunludur. Identifier önce
`DataSnapshot.snapshot_key`, sonra tekil `DatasetVersion.slug` olarak çözülür.
Aktif snapshot'a sessiz fallback yapılmaz.

## Sorumluluk Sınırı

Network MCP cihaz, topoloji, alarm, outage, RCA adayı ve aggregate customer
impact bilgilerini döndürür. Müşteri profil detayı, ödeme/kampanya geçmişi ve
telafi tutarı Customer MCP, Rule MCP ve Compensation MCP kapsamındadır.

