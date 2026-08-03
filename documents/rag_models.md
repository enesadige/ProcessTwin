# RAG Model Altyapısı

Görev 046 yalnızca RAG kaynaklarının saklanacağı veri modelini sağlar.

## Modeller

- `SourceDocument`: Doküman metni, kaynak türü, sürüm ve geçerlilik bilgisi.
- `DocumentChunk`: Dokümanın sıralı parçaları, bölüm yolu, kural referansı ve ilerideki embedding alanı.
- `DocumentChunkEmbedding`: Bir chunk için provider/model/sürüm/prompt kimliğiyle
  ayrılmış embedding kaydı. Aynı chunk Gemini ve Ollama kayıtlarını birlikte
  taşıyabilir.
- `IndexRun`: Gelecekteki ingestion/embedding çalıştırmalarının metadata kaydı.

`data_snapshot` boşsa doküman genel prosedür/kural kaynağıdır. Doluysa doküman belirli
bir sentetik snapshot kapsamındadır. RuleSet, Rule ve RuleVersion ile doğrudan foreign key
kurulmaz; `DocumentChunk.rule_code` ve `rule_version` yalnız structured referanstır.

`section_path` JSON liste olarak tutulur. Örneğin `["Kapsam", "İstisnalar"]`.

Legacy `DocumentChunk.embedding` alanı geçiş sürecinde read-only tutulur. Yeni
generation ve search akışları `DocumentChunkEmbedding.embedding` üzerindeki
`vector(768)` alanını kullanır. Tam kimlik `provider`, `model`, `dimensions`,
`embedding_version`, `prompt_version` ve güncel chunk `content_hash` değerlerinden
oluşur. Provider adı tek başına vektör uzayı kimliği değildir.

Full-text alanları, GIN, HNSW ve IVFFlat indeksleri 049’a bırakılmıştır.
