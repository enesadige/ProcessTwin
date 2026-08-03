# MCP Ortak Contract Testleri

Görev 045, Network, Customer, Rule ve Compensation MCP sunucularının ortak
sözleşmelerini parameterized test matrisiyle doğrular.

Kapsanan başlıklar:

- tool katalogları ve beklenen tool sayıları (`9/7/7/6`)
- Pydantic input validation ve zorunlu `snapshot_identifier`
- ortak `MCPToolResponse` envelope, metadata ve correlation ID
- internal API service-token auth ve HTTP hata eşleme
- timeout, validation, not-found, conflict ve upstream/internal hata davranışı
- timezone-aware tarih alanları
- secret, traceback, SQL ve özel bilgi sızıntısı
- Django/ORM ve MCP’ler arası import izolasyonu

Health/registry regression ve native initialize/list_tools smoke mevcut Görev 044
testleriyle birlikte çalıştırılır. Bu testler business tool hesaplarını yeniden
uygulamaz ve model, migration veya seed üretmez.
