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

## Sınırlar

Benchmark kaynak retrieval ölçer. Rule selection, eligibility, root cause,
customer impact, compensation amount, LLM cevabı veya `DecisionEvidence`
üretmez. Rule MCP smoke ayrı yürütülür; benchmark command MCP process başlatmaz.
