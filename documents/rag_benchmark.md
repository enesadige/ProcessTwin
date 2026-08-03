# RAG Benchmark Mini Seti

Görev 051, mevcut RAG retrieval davranışını değiştirmeden 16 sabit vaka ile ölçer.
Benchmark sürümü `rag-benchmark-v1` değeridir.

## Profiller

- `deterministic`: 10 PostgreSQL `full_text` vakasıdır. Exact-code, tarihsel
  REFUND sürümü, snapshot izolasyonu, global doküman ve kontrollü filtre
  davranışını CI ve offline ortamda ölçer.
- `semantic`: 6 Türkçe paraphrase vakasıdır. Üç `semantic` ve üç `hybrid`
  sorgu içerir; yalnız `gemini-embedding-2`, 768 boyut ve
  `asymmetric-retrieval-v1` metadata'sıyla çalışır.

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
python manage.py benchmark_rag --profile all --category exact_code
python manage.py benchmark_rag --case-code RAG-HISTORY-REFUND-V2
```

Desteklenen seçenekler:

- `--profile deterministic|semantic|all`
- `--format text|json`
- tekrarlanabilir `--case-code`
- tekrarlanabilir `--category`

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

`RAG-SEM-FAILED-FAILOVER`, `RAG-SEM-PACKET-LOSS-SLA` ve
`RAG-SEM-DEGRADATION` vakalarında doğru doküman ilk üçte bulunmasına rağmen hedef
bölüm seçilememiştir. Bu vakalar `chunk_selection_quality_issue` olarak kayıtlıdır;
beklenti gevşetilmez ve ayrı retrieval-quality düzeltmesi yapılana kadar başarısız
kalır.

## Sınırlar

Benchmark kaynak retrieval ölçer. Rule selection, eligibility, root cause,
customer impact, compensation amount, LLM cevabı veya `DecisionEvidence`
üretmez. Rule MCP smoke ayrı yürütülür; benchmark command MCP process başlatmaz.
