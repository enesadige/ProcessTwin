# PRE-052 — Versioned Native Snapshot Refresh

## Sonuç

Eski `multi-city-realism-v1-multi-city-realism-snapshot-v1` snapshot'ı ve ona
bağlı `SourceDocument` kayıtları korunmuştur. `SourceDocument.data_snapshot`
ilişkisinin `PROTECT` davranışı değiştirilmemiş; reset, CASCADE veya silme
kullanılmamıştır.

Görev 052 için doğrulanmış snapshot:

`multi-city-realism-v2-causal-r1-multi-city-realism-snapshot-v1-multi-city-realism-v2-causal-r1`

Bu snapshot explicit identifier ile seçilmelidir; mevcut uygulamalardaki
explicit snapshot seçimi korunur, gizli bir global default eklenmemiştir.

## Non-destructive yaşam döngüsü

`seed_multicity_realism --dataset-slug <slug>` yeni bir `DatasetVersion` ve
pasif `DataSnapshot` üretir; aynı slug tekrar çalıştırıldığında yalnız hedef
snapshot'ı validate eder. Özel slug ile `--reset` reddedilir. Eski varsayılan
slug davranışı korunur.

İlk `multi-city-realism-v2-causal` denemesi, native üretimde bulunan iki eski
varsayımın ardından korunmuş ayrı bir snapshot olarak kalmıştır. Görev 052
yalnız yukarıdaki `r1` snapshot'ını kullanacaktır.

## Native doğrulama

`r1` snapshot'ın gerçek sayıları: 14.400 customer, 16.200 subscription, 31
AlarmType, 918 Alarm, 198 CausalEvent, 496 SessionEvent, 187 Incident, 100
Outage, 9.794 QualityMeasurement ve 30 GroundTruthCase. Snapshot row metadata
aynı sayılarla tutarlıdır; hedefli realism `--validate-only` gate PASS'tir.

Geçmiş compensation history yalnız çözümlenmiş incident seçer. Ground-truth
seeder, causal timeline'da bulunmayan iki eski public referansı boş bağlam
olarak güvenle taşır; mevcut legacy snapshot davranışı değiştirilmez.

## RAG

`seed_rag_corpus --multicity-snapshot-identifier <r1-key>` ilk çalışmada 9
source oluşturdu ve 4 kaynağı korudu; tekrarında `created=0, unchanged=13`
oldu. Yeni snapshot'ta 8 scoped source vardır. `SYN-CAUSAL-ANALYSIS-2026`,
`SYN-ALARM-CATALOG-2026` ve `SYN-COMP-2026-ELIGIBILITY` seçimi v1/v2 immutable
sürümleriyle 5 source ve 29 chunk olarak indexlendi; validate-only PASS'tir.

Bu snapshot scoped source'larında 23 chunk ve 0 embedding vardır. Gemini
`gemini-embedding-2` ile Qwen `qwen3-embedding:4b` provider validate-only
kontrolleri 29 pending chunk için başarılıdır; embedding batch'i bu görevde
üretilmemiştir. 768 dimension, ayrı provider setleri,
`qwen3-telecom-query-v1` ve `think:false` politikası korunmuştur.

CSV runtime/corpus bağımlılığı değildir; PII, credential veya raw payload
eklenmemiştir. `SourceDocument.data_snapshot=PROTECT` reset blocker'ı açık
teknik takip maddesi olarak kalır.

## Sıradaki görev

Görev 052 — QueryRun ve orchestration, explicit `r1` snapshot identifier ile
başlatılabilir.
