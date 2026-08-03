# RAG Embedding Provider'ları

## Bağımsız Seçim

`LLM_PROVIDER` ile `RAG_EMBEDDING_PROVIDER` bağımsız ayarlardır. Online profil
Gemini/Gemini, lokal profil Ollama/Ollama kullanır; Gemini/Ollama ve
Ollama/Gemini karışık seçimleri de geçerlidir. Bir ayar diğerini değiştirmez.

Embedding provider seçimi environment üzerinden yalnız provider adını seçer.
Model, dimensions, embedding version ve prompt version merkezi registry'deki
allowlist descriptor'ından gelir. Internal search API ve Rule MCP serbest provider
veya model adı kabul etmez.

## Embedding Kimliği

Bir document embedding kaydı şu tam kimlikle seçilir:

- provider
- model
- dimensions
- embedding version
- document prompt version
- chunk content hash

Query embedding aynı descriptor'ın query prompt version'ını kullanır. Gemini,
Nomic ve Qwen vektörleri 768 boyutlu olsalar bile aynı uzay kabul edilmez.
Eksik/kısmi aktif set semantic aramayı durdurur; sessiz provider fallback yoktur.
Bir provider generation hatası diğer provider kayıtlarını değiştirmez.

## Provider Profilleri

- `gemini`: `gemini-embedding-2`, 768,
  `asymmetric-retrieval-v1`, `rag-section-aware-document-v2`.
- `ollama-nomic-v2`: `nomic-embed-text-v2-moe`, 768; kalite karşılaştırması
  için tarihsel lokal aday.
- `ollama-qwen3-0.6b`: `qwen3-embedding:0.6b`, 768,
  `qwen3-embedding-0.6b-768-v1`, `qwen3-section-document-v1` ve
  `qwen3-telecom-query-v1`; kalite karşılaştırması için tarihsel lokal aday.
- `ollama-qwen3-4b`: aktif lokal descriptor; `qwen3-embedding:4b`, 768,
  `qwen3-embedding-4b-768-v1`, `qwen3-section-document-v1` ve
  `qwen3-telecom-query-v1`.
- `ollama-qwen3-4b-baseline`: yalnız kontrollü benchmark karşılaştırması için
  instruction kullanmayan, aynı 4B document embedding setini kullanan profil.
- `mock`: yalnız unit test içindir; production semantic provider değildir.

Qwen query girdisi sabit instruction ile `Instruct: ...\nQuery: ...` biçimindedir.
Document girdisi title, document code, section path, heading ve content alanlarını
ayrı taşır; Nomic prefix'i veya query instruction içermez. Ollama `/api/embed`
isteği `dimensions=768`, `truncate=false` ve `keep_alive=0` gönderir; runtime
otomatik model indirmez. Kurulu Ollama 0.30.8 üzerinde native smoke,
`/api/embed` yanıtından hemen sonra modelin `ollama ps` listesinden çıktığını
doğrulamıştır. Interactive query timeout'u 30 saniye, tek atomik document batch
timeout'u 300 saniyedir. Bulk çağrıda model bütün batch boyunca yüklü kalır ve
yanıt sonrasında çıkarılır.

## Doğrulanmış Lokal Model

Nomic ve Qwen3 0.6B sabit Türkçe telecom benchmarkında 6/6 kalite kapısını
geçemediği için aktif değildir. Ollama model dosyaları geliştirme cihazından
kaldırılmış, mevcut `DocumentChunkEmbedding` kayıtları karşılaştırma geçmişi
olarak korunmuştur.

Qwen3 Embedding 4B genel ve case-independent `qwen3-telecom-query-v1`
instruction'ı ile semantic `6/6`, Hit@1 `0.500`, Hit@3 `1.000` ve MRR `0.722`
sonucunu verdi. Aynı modelin no-instruction baseline sonucu `4/6` oldu. Gemini
`gemini-embedding-2` semantic sonucu da `6/6` olarak korunmuştur. Her iki aktif
provider için 74 güncel document embedding kaydı vardır.

74 document vector'u corpus/index değişmedikçe yeniden kullanılabilir; her
kullanıcı sorusunda yalnız tek query vector üretilir. Native M1 16 GB ölçümünde
Qwen3 4B document generation yaklaşık 154 saniye, warm query median yaklaşık
510 ms, p95 yaklaşık 689 ms ve cold load yaklaşık 5.04 saniyedir.

## Lokal Bellek Politikası

M1 16 GB varsayılan lokal akışında Qwen3 Embedding 4B ile
`gemma4:12b-it-qat` aynı anda sürekli bellekte tutulmaz. Query embedding ve
pgvector retrieval tamamlandıktan sonra Qwen unload edilir; ardından Gemma LLM
yüklenir. Sunumda kaynak baskısı görülürse `LLM_PROVIDER=ollama` ile
`RAG_EMBEDDING_PROVIDER=gemini` hibrit profili kullanılabilir.

Gelecekteki Gemma `/api/chat` adapter'ı her çağrıda top-level `think=false`
gönderecektir. Thinking kullanıcı veya environment ile açılamaz; response, log,
DecisionEvidence veya veritabanında saklanmaz. `/api/embed` isteğine `think`
alanı eklenmez.

## Komutlar

```bash
python backend/manage.py generate_rag_embeddings \
  --provider ollama \
  --embedding-profile ollama-qwen3-4b \
  --force

python backend/manage.py benchmark_rag \
  --profile semantic \
  --embedding-profile ollama-qwen3-4b
```

Legacy `DocumentChunk.embedding` alanları bu aşamada kaldırılmaz. Yeni generation
ve search yalnız `DocumentChunkEmbedding` kullanır; legacy alanların kaldırılması
ayrı migration görevidir. Bu veri hacminde HNSW veya IVFFlat eklenmez.
