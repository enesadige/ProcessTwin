# RAG Embedding ve Arama

Bu belge Gorev 049 kapsamindaki deterministic embedding ve arama davranisini
aciklar. RAG yalniz sentetik kural ve prosedur kaynaklarini bulur; kural secimi,
customer impact veya telafi tutari hesaplamaz.

## Embedding

`EmbeddingProvider` arayuzu `mock` ve `gemini` provider'larini destekler.
Gemini modeli `gemini-embedding-2`, boyut 768 ve embedding surumu
`asymmetric-retrieval-v1` olarak sabittir. Dokuman girdisi
`rag-section-aware-document-v2` ile document title, document code, normalized
section path, section heading ve chunk content alanlarini ayri satirlarda tasir.
Chunk'in ilk Markdown heading satiri `section_heading` alaninda zaten temsil
ediliyorsa embedding input content bolumunde tekrarlanmaz; SourceDocument ve
DocumentChunk icerigi degistirilmez. Sorgu girdisi
`task: search result | query: ...` formatinda kalir. Mock provider, test ve offline
gelistirme icin SHA-256 tabanli, deterministic ve L2-normalized vektor uretir.

`generate_rag_embeddings` yalniz aktif `SourceDocument` chunk'larini isler.
Provider/model/surum veya chunk hash degismediyse kayit unchanged kabul edilir.
Provider ciktilari tamamen dogrulanmadan database yazilmaz; hata durumunda
onceki gecerli embedding korunur. Her gercek calisma bir `IndexRun` kaydi ile
izlenir.

## Arama

Authenticated internal endpoint:

`POST /api/internal/v1/rag/search/`

`snapshot_identifier` zorunludur. Cozumleme once exact `snapshot_key`, sonra
tekil dataset slug ile yapilir; aktif snapshot'a sessiz fallback yoktur. Secilen
snapshot dokumanlari ile global dokumanlar birlikte aranir. `evaluation_time`
verilirse hem kaynak hem chunk gecerlilik araligi uygulanir.

Desteklenen modlar:

- `full_text`: PostgreSQL `simple` configuration ile expression-based arama.
- `semantic`: pgvector `CosineDistance` ve gecerli 768 boyutlu embedding'lerle
  raw cosine skoru korunurken `semantic-section-v2` ile section
  butunlugu ikincil sinyal olarak kullanilir. Yalniz sentetiklik uyarisindan
  olusan H1 chunk'lari `0.95`, karakter sinirinda bolunmus/overlap chunk'lari
  `0.97` genel factor ile siralanir; exact code eslesmeleri penalize edilmez.
- `hybrid`: `hybrid-section-v2` raw semantic section skorunu ana sinyal olarak
  kullanir. Full-text rank katkisi `0.02 / (1 + rank)` ile sinirlidir; exact code
  eslesmesi `1.0` bonus alir. Case, query terimi veya document code'a ozel kural
  yoktur.

Hybrid provider kullanilamazsa response `effective_mode=full_text_fallback` ve
acik bir warning doner. Semantic modda sessiz fallback yapilmaz. Sonuclarda
chunk metni, belge/bolum bilgisi, skorlar ve evidence metadata bulunur; ham
embedding vektoru disari acilmaz.

## Kapsam sinirlari

Bu gorevde model veya migration degisikligi, SearchVectorField/GIN, HNSW veya
IVFFlat indeksleri, Rule MCP tool'u, LLM ve RAG orchestrator eklenmez.

## Rule MCP adapter'i

Gorev 050 ile `search_rule_documents`, bu internal endpoint'i shared
BackendClient uzerinden read-only olarak acar. Tool RAG skorlarini yeniden
hesaplamaz veya siralamaz; backend sonucu, snapshot metadata ve warning'leri
ortak MCP response sozlesmesine aktarir.
