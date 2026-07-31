# MCP Health ve Registry

Görev 044, dört temel MCP sunucusunun statik tanımını ve canlı stdio durumunu
gösteren backend internal endpointlerini sağlar. Business tool çağrısı yapılmaz;
health probe yalnız MCP initialize ve `list_tools` işlemlerini çalıştırır.

Endpointler:

- `GET /api/internal/v1/mcp/registry/`: canlı process başlatmadan registry tanımlarını döndürür.
- `GET /api/internal/v1/mcp/health/`: kısa ömürlü stdio probe ile canlı durumu kontrol eder.

Her iki endpoint service-token auth ve correlation ID kullanır. `active`, initialize ve
`list_tools` probe'unun başarıyla tamamlandığını; `unavailable`, process veya probe
hatasını; `disabled`, descriptor'ın yapılandırma ile kapalı olduğunu ifade eder.
Health sonucu veritabanına yazılmaz ve her çağrıda yeniden üretilir.

İsteğe bağlı query parametreleri:

- `service=network|customer|rules|compensation`
- `timeout_seconds=0.25..10`

Registry tool listesi statik kopya olarak taşımaz. Canlı tool listesi MCP SDK'nın
`list_tools` cevabından, version ve server name ise initialize cevabından alınır.
