# RAG Embedding ve Arama

Bu belge Gorev 049 kapsamindaki deterministic embedding ve arama davranisini
aciklar. RAG yalniz sentetik kural ve prosedur kaynaklarini bulur; kural secimi,
customer impact veya telafi tutari hesaplamaz.

## Embedding

`EmbeddingProvider` arayuzu `mock`, `gemini` ve yerel `ollama` provider'larini
destekler. Provider descriptor'lari merkezi allowlist registry'den çözülür;
request serbest model adı kabul etmez.
Gemini modeli `gemini-embedding-2`, boyut 768 ve embedding surumu
`asymmetric-retrieval-v1` olarak sabittir. Dokuman girdisi
`rag-section-aware-document-v2` ile document title, document code, normalized
section path, section heading ve chunk content alanlarini ayri satirlarda tasir.
Chunk'in ilk Markdown heading satiri `section_heading` alaninda zaten temsil
ediliyorsa embedding input content bolumunde tekrarlanmaz; SourceDocument ve
DocumentChunk icerigi degistirilmez. Sorgu girdisi
`task: search result | query: ...` formatinda kalir. Mock provider, test ve offline
gelistirme icin SHA-256 tabanli, deterministic ve L2-normalized vektor uretir.

Gemini ve Ollama embedding kayıtları `DocumentChunkEmbedding` tablosunda aynı
anda saklanır. Semantic sorgu yalnız aktif descriptor ile provider, model,
dimensions, embedding version, document prompt version ve content hash birebir
eşleşen tam seti kullanır. Farklı model uzayları, her ikisi de 768 boyutlu olsa
bile karıştırılmaz.

Aktif lokal descriptor `qwen3-embedding:4b`, 768 boyut,
`qwen3-embedding-4b-768-v1`, `qwen3-section-document-v1` ve
`qwen3-telecom-query-v1` tam kimliğidir. Interactive Ollama query isteği
`keep_alive=0` ile tamamlandıktan sonra modeli bellekten çıkarır. Document
generation tek batch boyunca modeli yüklü tutar ve yanıt sonrasında unload eder;
74 document embedding normal kullanıcı sorgusunda yeniden üretilmez.

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
- `semantic`: pgvector `CosineDistance` ve seçili descriptor'ın eksiksiz 768
  boyutlu embedding setiyle çalışır. Final limitten bağımsız en az 20 dense aday
  alınır. Raw cosine skoru korunurken `semantic-section-v3` ile normalize dense
  skor ana sinyal (`0.92`); heading (`0.03`), section path (`0.02`) ve chunk
  content (`0.03`) lexical ilgisi sınırlı ikincil sinyaldir. Yalniz sentetiklik uyarisindan
  olusan H1 chunk'lari `0.95`, karakter sinirinda bolunmus/overlap chunk'lari
  `0.97` genel factor ile siralanir; exact code eslesmeleri penalize edilmez.
- `hybrid`: `hybrid-section-v3` semantic section skorunu ana sinyal olarak
  kullanir. Full-text rank katkisi `0.02 / (1 + rank)` ile sinirlidir; exact code
  eslesmesi `1.0` bonus alir. Case, query terimi veya document code'a ozel kural
  yoktur.

Seçili descriptor seti eksik veya kısmiysa semantic ve hybrid arama açık
`embedding_prerequisite_error` döndürür. Eksiksiz set varken runtime provider
geçici olarak kullanılamazsa hybrid response `effective_mode=full_text_fallback` ve
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
