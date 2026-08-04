# REV-02 Operasyonel Nedensellik ve Etki Sözleşmeleri

## Amaç

Bu belge ve `apps.operations.contracts` modülü, REV-03 modellerinden önce ortak
operasyon kimliği, session kanıtı ve bağlantı seviyesindeki etki değerlendirmesi
anlamlarını sabitler. Bunlar henüz Django modelleri, DRF serializer'ları veya MCP
şemaları değildir.

## CausalEvent

`CausalEventContract`, aynı operasyon zincirindeki alarm, incident, outage,
operational event, quality measurement ve gelecekteki session/impact kayıtlarının
ortak kimliğidir. `event_code`, event type, lifecycle status, timezone-aware
başlangıç/bitiş, source system, synthetic/imported origin ve opsiyonel root
resource taşır. Type kataloğu device/link/port/access segment failure,
environmental anomaly, power, degradation, maintenance ve unknown ile sınırlıdır.

Anomaly ile failure aynı zincirin ardışık gözlemleriyse tek event lifecycle'ında
ilerler; bağımsız root resource veya zaman penceresi varsa ilişkili ayrı eventler
olur. `resolved`, `closed` ve `cancelled` status'ları `ended_at` gerektirir;
bitış başlangıçtan önce olamaz. `metadata` ve ilerideki raw-source kayıtları
internaldır, public serialization'a girmez.

## SessionEvent

`SessionEventContract`, normalize edilmiş `start`, `continue` ve `stop` internet
oturumu kanıtıdır. External event id, source system, timezone-aware occurred time
ve subscription veya connection referansı zorunludur; received time, NAS, service
ve session identifier opsiyoneldir. Raw payload ileride saklanabilir fakat public
çıktıda bulunmaz; session/subscriber identifier'ları da public serialization'da
dışlanır.

STOP tek başına outage kanıtı değildir. STOP ile sonraki START/CONTINUE arasındaki
aralık ancak event/topology penceresiyle birlikte aday interruption evidence'tır.
Olay öncesi offline abonelik `pre_existing_offline`; eksik, geç veya sırası bozuk
session verisi `insufficient_evidence` sonucuna gider. Identity mapping, masking,
retention ve kesin süre eşikleri açık sorudur; bu sözleşme bunları hard-code etmez.

## CustomerImpactAssessment

`CustomerImpactAssessmentContract`, bir CausalEvent'in subscription veya
SubscriptionConnection üzerindeki connection-level sonucudur. Status değerleri:

| Status | Anlam |
|---|---|
| `potential_impact` | Topoloji, shared upstream veya failure domain ile aday etki bulundu. |
| `verified_impact` | Potential aday için session/operasyon kanıtı interruption veya degradation'ı doğruladı. |
| `verified_no_impact` | Potential adayın session'ı devam etti veya failover hizmeti korudu. |
| `insufficient_evidence` | Potential aday var, ancak yeterli ve sıralı kanıt yok. |

`verified_impact`, `verified_no_impact` ve `insufficient_evidence` yalnız
`potential_impact=true` ile oluşabilir. Assessment subscription veya connection
referansı taşır; aggregate müşteri sayıları bu satırlardan deterministik olarak
hesaplanır. Full outage sonucu, failover session'ı koruduysa üretilmez.

Reason katalogu topology match, stop/recovery match, session active, failover
protected, shared upstream/failure domain, missing evidence, window dışı event,
unrelated session drop ve pre-existing offline içerir. Confidence yüzdesi bu
sözleşmede yoktur.

## Alarm Korelasyonu ve Kaynak Referansı

Correlation role değerleri `root`, `child`, `symptom`, `supporting`, `unrelated`
ve `noise`dur. Reason değerleri same resource, topology parent/child, shared
upstream, shared failure domain, temporal propagation, matching customer/session
impact ve matching clear/recovery sequence'dir. `root`, `child`, `symptom` ve
`supporting` en az bir reason gerektirir.

Mevcut `IncidentAlarm` mapping'i additive kalır: `primary -> root`,
`supporting -> supporting`, `correlated -> child`. Yeni `symptom`, `unrelated` ve
`noise` rollerinin kalıcı ilişkisi REV-03/REV-06'da değerlendirilir; mevcut model
bu görevde değişmemiştir.

`ResourceReference`, database primary key veya model instance yerine `resource_type`,
stable `business_code`, opsiyonel `parent_code`, subtype ve technology taşır. Device,
link, port, line, access segment, failure domain ve subscription connection
desteklenir. Customer number, IP, MAC, serial number, username ve secret bu
sözleşmeye girmez.

## Serialization ve Privacy

Her contract `to_public_dict()` ile timezone-aware ISO-8601 datetime, sabit enum
stringleri, açık null alanları ve stabil sıralı listeler üretir. Raw payload,
metadata ve hassas session identifier'ları varsayılan public çıktıda yoktur.
Aynı input aynı output'u üretir; assessment evidence event kodları sıralanır.
Validation hataları mevcut `DomainValidationError` envelope'unu kullanır.

## REV-03 Eşlemesi ve Açık Sorular

REV-03 `CausalEvent`, `SessionEvent` ve `CustomerImpactAssessment` modellerini
bu alan/enumların kalıcı karşılığı olarak ekleyecek; mevcut Alarm, Incident,
Outage, OperationalEvent ve QualityMeasurement'e nullable causal relation
planlanmaktadır. Mevcut Outage operasyonel interruption anlamını koruyacak,
legacy kayıtlar additive verification semantiği gelene kadar legacy/unverified
olarak ele alınacaktır.

Açık konular: session identity mapping/masking/retention, received-time toleransı,
STOP-START kanıt eşiği, alarm source/clear mapping, GPON scenario weights ve
ticari telafi koşulları. “24 saat” ifadesi doğrulanmış bir kural değildir.
