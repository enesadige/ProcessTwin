# REV-03 Nedensel Operasyon Modelleri

## Amaç

REV-03, REV-02'deki modelden bağımsız sözleşmelerin Django ve database
karşılığını ekler. Bu görev generator, correlation, session verification,
API/MCP veya RAG davranışını değiştirmez.

## Model Sahipliği

`DESIGN_DECISION` Üç yeni model `operations` app içinde tutulur. `CausalEvent`
operasyon zincirinin ortak köküdür; `SessionEvent` session/IP kanıtını operasyon
olayı bağlamında saklar; `CustomerImpactAssessment` causal event ile
subscription/connection arasındaki kalıcı etki değerlendirmesidir. Customer ve
network modelleri FK hedefi olarak kullanılır, fakat bu görevde onların domain
sahipliği genişletilmez.

## Eklenen Modeller

### CausalEvent

Temel alanlar:

- `data_snapshot`
- `event_code`
- `event_type`
- `status`
- `started_at`
- `ended_at`
- `source_system`
- `origin`
- root resource FK'leri: device, link, port, line, access segment, failure
  domain veya subscription connection
- `metadata`
- `created_at`, `updated_at`

`event_code` snapshot içinde unique'dir. Root resource için mevcut alarm source
yaklaşımına benzer structured nullable FK modeli kullanılır; aynı satırda en
fazla bir root resource bulunabilir. Public resource identity database primary
key'e değil, hedef modelin business code alanına dayanır.

### SessionEvent

Temel alanlar:

- `data_snapshot`
- nullable `causal_event`
- `external_event_id`
- `event_type`: `start`, `continue`, `stop`
- `occurred_at`, `received_at`
- `source_system`
- `subscription`, `subscription_connection`
- hashed service/session/subscriber referans alanları
- opsiyonel `nas_identifier`
- `raw_payload`, `metadata`

`source_system + external_event_id + snapshot` dolu external id için idempotency
anahtarıdır. External id boş sentetik kayıtlar engellenmez. Public serialization
raw payload, IP, token, session id veya subscriber reference sızdırmaz.

### CustomerImpactAssessment

Temel alanlar:

- `data_snapshot`
- `causal_event`
- `subscription`, `subscription_connection`
- `status`: `potential_impact`, `verified_impact`, `verified_no_impact`,
  `insufficient_evidence`
- `potential_impact`
- `connection_role`
- assessment zaman penceresi
- `reasons`
- `evidence_session_event_codes`
- `metadata`

İlk revizyonda ayrı versioning modeli kurulmaz. Aynı causal event için aynı
subscription connection'a tek aktif assessment; connection yoksa aynı
subscription'a tek assessment izinlidir.

## Mevcut Relation'lar

Şu modellere nullable `causal_event` FK eklendi:

- `Alarm`
- `Incident`
- `Outage`
- `OperationalEvent`
- `QualityMeasurement`

`on_delete=SET_NULL` seçildi. CausalEvent silinirse legacy operasyon kayıtları
silinmez; causal relation düşer. `CustomerImpactAssessment` ise audit sonucu
olduğu için CausalEvent'e `PROTECT` ile bağlıdır.

## Database ve Application Invariant'ları

Database düzeyi:

- Causal event code snapshot içinde unique.
- Causal event `ended_at >= started_at`.
- Terminal causal status `ended_at` gerektirir.
- Causal event sıfır veya bir root resource taşır.
- Session event `received_at >= occurred_at`.
- Session event en az subscription, connection veya hashed service reference
  taşır.
- Impact assessment zaman aralığı ters olamaz.
- Verified/insufficient assessment `potential_impact=true` gerektirir.
- Assessment subscription veya connection taşır.
- Duplicate event/connection ve event/subscription assessment kayıtları
  engellenir.

Application/model validation düzeyi:

- Datetime alanları timezone-aware olmalıdır.
- Root resource, causal relation, subscription ve connection FK'leri aynı
  snapshot'a ait olmalıdır.
- `verified_no_impact` en az bir reason gerektirir.
- `reasons` değerleri REV-02 `ImpactReason` kataloğuyla uyumlu olmalıdır.
- Subscription connection verilmişse seçili subscription ile tutarlı olmalıdır.

Potential impact kümesinin gerçek topoloji hesaplaması REV-07 servislerinde
korunacaktır; bu görev yalnız saklama ve çelişkili kayıtları engelleme temelini
kurar.

## Migration ve Backward Compatibility

Migration `operations.0004` üç yeni tabloyu ve nullable relation'ları ekler.
Mevcut Alarm, Incident, Outage, OperationalEvent ve QualityMeasurement kayıtları
`causal_event=NULL` ile geçerli kalır. Sahte CausalEvent backfill yapılmaz.

Migration ayrıca güvenli küçük data düzeltmesi olarak `DataSnapshot.row_counts`
içindeki `ground_truth_cases` değerini gerçek `GroundTruthCase` sayısıyla
eşitler. Başka row-count alanı tahmin edilmez ve generator çalıştırılmaz.

## Privacy Kararları

Session event modelinde açık IP, MAC, kullanıcı adı, parola veya token için
public alan yoktur. Gerçek kaynak payload ileride internal `raw_payload` içinde
saklanabilir; public/deterministic çıktı raw payload ve hassas identifier
alanlarını dışlar. Service/session/subscriber eşleşmeleri hashed referans
alanlarıyla temsil edilir.

## REV-04/REV-05'e Bırakılanlar

- Alarm katalog/source/technology uyum validator'ları.
- OLT/PON/GPON topology consistency.
- Nedensel GPON generator ve scenario weight'leri.
- Alarm role üretimi ve correlation/root-cause algoritması.
- Session stop/restart eşikleri ve verified impact servisleri.
- Outage verification state, compensation ve DecisionEvidence bağlama.

## Açık Sorular

- Session identity mapping, masking formatı ve retention süresi.
- Kaynak session event gecikme toleransı.
- Alarm clear semantiği ve source-system mapping.
- GPON scenario ağırlıkları.
- Ticari telafi koşulları, özellikle doğrulanmamış 24 saat ifadesi.
