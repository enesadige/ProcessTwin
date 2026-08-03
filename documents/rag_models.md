# RAG Model Altyapısı

Görev 046 yalnızca RAG kaynaklarının saklanacağı veri modelini sağlar.

## Modeller

- `SourceDocument`: Doküman metni, kaynak türü, sürüm ve geçerlilik bilgisi.
- `DocumentChunk`: Dokümanın sıralı parçaları, bölüm yolu, kural referansı ve ilerideki embedding alanı.
- `IndexRun`: Gelecekteki ingestion/embedding çalıştırmalarının metadata kaydı.

`data_snapshot` boşsa doküman genel prosedür/kural kaynağıdır. Doluysa doküman belirli
bir sentetik snapshot kapsamındadır. RuleSet, Rule ve RuleVersion ile doğrudan foreign key
kurulmaz; `DocumentChunk.rule_code` ve `rule_version` yalnız structured referanstır.

`section_path` JSON liste olarak tutulur. Örneğin `["Kapsam", "İstisnalar"]`.

Embedding alanı nullable `vector(768)` alanıdır. 046’da embedding üretimi yapılmaz.
Provider, ingestion, chunking ve arama sonraki görevlerin kapsamındadır.

Full-text alanları, GIN, HNSW ve IVFFlat indeksleri 049’a bırakılmıştır.
