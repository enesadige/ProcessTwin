# RAG Benchmark Mini Seti

Görev 051, mevcut RAG retrieval davranışını değiştirmeden 16 sabit vaka ile ölçer.
Benchmark sürümü `rag-benchmark-v1` değeridir.

## Profiller

- `deterministic`: 10 PostgreSQL `full_text` vakasıdır. Exact-code, tarihsel
  REFUND sürümü, snapshot izolasyonu, global doküman ve kontrollü filtre
  davranışını CI ve offline ortamda ölçer.
- `semantic`: 6 Türkçe paraphrase vakasıdır. Üç `semantic` ve üç `hybrid`
  sorgu içerir; seçilen production descriptor'ın 74 canonical chunk için tam
  embedding setini gerektirir. Gemini ve Ollama sonuçları ayrı kalite kanıtıdır.

Mock embedding deterministik test altyapısıdır; Türkçe semantic kalite kanıtı
olarak kullanılmaz. Semantic profil mock provider veya uyumsuz embedding seti
görürse çalışmaz ve aşağıdaki hazırlık komutunu bildirir:

```bash
python manage.py generate_rag_embeddings --provider gemini --force
```

Benchmark komutu embedding üretmez, `IndexRun` oluşturmaz ve veritabanına
yazmaz.

## Kullanım

```bash
python manage.py benchmark_rag
python manage.py benchmark_rag --profile deterministic --format json
python manage.py benchmark_rag --profile semantic
python manage.py benchmark_rag --profile semantic --embedding-provider gemini
python manage.py benchmark_rag --profile semantic --embedding-profile ollama-qwen3-4b
python manage.py benchmark_rag --profile all --category exact_code
python manage.py benchmark_rag --case-code RAG-HISTORY-REFUND-V2
```

Desteklenen seçenekler:

- `--profile deterministic|semantic|all`
- `--format text|json`
- tekrarlanabilir `--case-code`
- tekrarlanabilir `--category`
- kontrollü `--embedding-provider gemini|ollama`
- registry allowlist'inden `--embedding-profile`

Tüm seçili vakalar geçerse çıkış kodu sıfırdır. En az bir retrieval vakası veya
profil prerequisite kontrolü başarısızsa bütün çalışılabilir vakalar
tamamlandıktan sonra komut non-zero döner.

## Ölçümler

Toplam ve kategori bazında `hit_at_1`, `hit_at_3`,
`mean_reciprocal_rank`, forbidden document ihlali ve fallback sayısı raporlanır.
Kabul exact floating score değerlerine değil, sabit expected document/version
ve 1-indexed rank değerlerine dayanır. Tam chunk metni ve raw embedding benchmark
raporuna konmaz.

## Semantic Kabul Politikası

Semantic bir vaka şu koşullarla geçer:

- beklenen `document_code`, vaka için tanımlı rank sınırındadır; semantic MVP
  vakalarında bu sınır en fazla 3'tür,
- forbidden doküman bulunmaz,
- `effective_mode` istenen modla aynıdır ve fallback oluşmaz,
- provider/model/version canonical Gemini embedding setiyle eşleşir,
- heading eşleşmesi yalnız manifestte `require_heading_match=true` olan ve belirli
  bir bölümü hedefleyen vakalarda zorunludur.

Heading karşılaştırması Unicode NFC, trim, whitespace collapse, casefold ve
Markdown heading marker temizliği uygular. Türkçe karakterler ASCII'ye çevrilmez;
fuzzy eşleştirme yapılmaz. Exact-code ve tarihsel sürüm vakalarında ana kapı doğru
doküman ve sürümdür; bölüm hedeflenmiyorsa heading kabul kapısı değildir.

Heading zorunlu bir vakada aynı dokümanın birden fazla chunk'i sonuçlarda yer
alabilir. Evaluator, beklenen heading ile eşleşen chunk'in gerçek 1-indexed rank
değerini ölçer; dokümanın daha üstteki farklı bir bölümünü başarı saymaz.

Görev 051.1 ile Gemini document embedding girdisi `rag-section-aware-document-v2`
olarak sürümlendi. Görev 051.5 ile provider-independent iki aşamalı retrieval
`semantic-section-v3` ve `hybrid-section-v3` olarak sürümlendi. Benchmark sorguları, expected değerleri ve
rank sınırları değişmeden native Gemini sonucu deterministic `10/10`, semantic
`6/6`, semantic Hit@3 `1.0`, forbidden ihlali `0` ve fallback `0` oldu. Ayrı
Rule MCP retrieval smoke seti `4/4` geçti.

Aktif lokal `qwen3-embedding:4b` aynı değişmeyen benchmarkta semantic `6/6`,
Hit@1 `0.500`, Hit@3 `1.000`, MRR `0.722`, forbidden ihlali `0` ve fallback `0`
sonucunu verdi. Nomic ve Qwen3 0.6B sonuçları aktif lokal provider kabulü
sayılmaz; tarihsel karşılaştırma olarak saklanır.

## Sınırlar

Benchmark kaynak retrieval ölçer. Rule selection, eligibility, root cause,
customer impact, compensation amount, LLM cevabı veya `DecisionEvidence`
üretmez. Rule MCP smoke ayrı yürütülür; benchmark command MCP process başlatmaz.
