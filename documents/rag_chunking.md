# RAG Ingestion ve Chunking

Görev 048, aktif `SourceDocument.content` kayıtlarını canonical Markdown metni
olarak işler. Dosya sistemi altındaki kaynak Markdown dosyaları bu aşamada yeniden
okunmaz.

## Sabitler

- `chunking_version`: `heading-char-v1`
- `max_chars`: `1800`
- `overlap_chars`: `200`
- `section_path`: JSON liste; örneğin `["Ana başlık", "Alt başlık"]`
- `sequence`: her dokümanda `0` ile başlayan kesintisiz sıra

H1, H2 ve H3 başlıkları bölüm sınırıdır. Chunk metni kaynak içeriğin birebir
`char_start` inclusive, `char_end` exclusive dilimidir. Kısa bölümler korunur;
uzun bölümlerde önce paragraf/liste/tablo gibi doğal sınırlar, son çare olarak
karakter sınırı kullanılır. Overlap yalnız karakter bölmesinde uygulanır.

## Komut

```bash
python manage.py index_rag_documents
python manage.py index_rag_documents --document-code SYN-COMP-2026-BROADBAND
python manage.py index_rag_documents --snapshot-identifier <snapshot-key>
python manage.py index_rag_documents --validate-only
python manage.py index_rag_documents --reset --snapshot-identifier <snapshot-key>
```

`--snapshot-identifier` önce exact `snapshot_key`, sonra tekil dataset slug
olarak çözülür; aktif snapshot'a sessiz fallback yoktur. Snapshot seçildiğinde
global dokümanlar da seçime dahil edilir. `--validate-only` hiçbir kayıt yazmaz.

## IndexRun ve tekrar indeksleme

Her yazan command invocation için bir `IndexRun` oluşturulur ve `pending` ->
`running` -> `succeeded` veya `failed` akışı izlenir. Source content hash'i,
chunking sabitleri ve seçilen kaynaklar üzerinden deterministic `source_digest`
üretilir. Beklenen chunk seti mevcut setle aynıysa kayıtlar değiştirilmez;
farklıysa yalnız ilgili dokümanın chunk'ları tek transaction içinde yenilenir.

Token offsetleri, embedding alanları ve embedding provider bilgileri bu aşamada
boş kalır. Bunlar sonraki embedding/search çalışmasının girdisidir.
