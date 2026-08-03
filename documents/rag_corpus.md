# RAG İlk Sentetik Korpusu

Görev 047, 10 adet Türkçe ve tamamen sentetik `SourceDocument` kaydı üretir.

- 2 global prosedür dokümanı
- 6 multi-city `DataSnapshot` dokümanı
- 2 Maltepe `DataSnapshot` dokümanı

Canonical kaynaklar `documents/rules`, `documents/procedures`,
`documents/alarm_catalog` ve `documents/compensation` altında Markdown olarak
tutulur. `backend/apps/rag/corpus_manifest.py` dosya, scope, sürüm, geçerlilik ve
coverage referanslarının tek kaynağıdır.

## Komut

```bash
python backend/manage.py seed_rag_corpus
python backend/manage.py seed_rag_corpus --validate-only
python backend/manage.py seed_rag_corpus --reset
```

Komut exact snapshot key ile çalışır; aktif snapshot’a fallback yapmaz. Aynı
version altında içerik veya kritik metadata değişirse sessiz update yapmaz.

Bu görevde `DocumentChunk=0`, `IndexRun` değişmez ve embedding üretilmez.
Chunking ve ingestion Görev 048’dedir.
