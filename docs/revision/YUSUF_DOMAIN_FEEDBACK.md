# Yusuf Domain Feedback

Bu not, revizyon öncesi kurum içi görüşmede aktarılan ve ekranda gözlenen bilgileri kaydeder. Üretim sistemi sözleşmesi değildir. Kişisel veri, erişim bilgisi ve gerçek abone tanımlayıcısı içermez.

## Etiketler

- `CONFIRMED_FROM_MEETING`: Görüşmede domain bilgisi olarak açıkça aktarıldı; kaynak sistem dokümanı ile ayrıca doğrulanmalıdır.
- `OBSERVED_IN_SCREEN`: Paylaşılan ekran örneğinde görüldü; tüm ortamlar için şema garantisi değildir.
- `PROJECT_DECISION`: ProcessTwin kapsamı veya uygulama sırası için alınan karar.
- `OPEN_QUESTION`: İş kuralı veya veri sözleşmesi kesinleşmedi.
- `INFERENCE`: Aktarılan bilgilerden çıkarılan teknik yorum; kurum kuralı değildir.

## 1. Alarm ve kesinti ayrımı

- `CONFIRMED_FROM_MEETING` Network katmanındaki kesintiler fault-management sistemlerinde yakalanan alarmlarla başlayabilir.
- `CONFIRMED_FROM_MEETING` Bir alarmın oluşması tek başına gerçek müşteri kesintisi anlamına gelmez. Müşteri etkisi ayrıca doğrulanmalıdır.
- `CONFIRMED_FROM_MEETING` Bir cihazın topolojisindeki her müşteri alarmdan gerçekten etkilenmiş olmayabilir.
- `CONFIRMED_FROM_MEETING` Alarm sürerken müşteri session'ı devam ediyorsa alarmın gerçek müşteri etkisi oluşturmadığı değerlendirilebilir.
- `INFERENCE` ProcessTwin'de `potential impact` ile doğrulanmış müşteri etkisinin ayrı kavramlar olarak izlenmesi gerekir.

## 2. Alarm doğrulama süreci

- `CONFIRMED_FROM_MEETING` Müşterinin IP alıp almadığını veya aktif internet oturumu bulunup bulunmadığını anlık kontrol eden API'ler vardır.
- `CONFIRMED_FROM_MEETING` Geçmiş session kayıtları veritabanı sorgularıyla incelenebilir.
- `CONFIRMED_FROM_MEETING` Session bitişi ile yeni session başlangıcı/devamı arasındaki zaman, diğer koşullar da sağlandığında gerçek kesinti süresinin doğrulanmasında kullanılabilir.
- `INFERENCE` Alarm, topoloji, session ve zaman kanıtları birlikte değerlendirilmeden kesin outage sonucu üretilmemelidir.

## 3. Session/IP verileri

- `OBSERVED_IN_SCREEN` Activity tarafında `subscriberId`, `activityId`, `logDate`, `activityType`, `activityStatus`, `activityData`, `workflowResult`, `servis`, `NAS`, `download`, `upload` ve toplam kullanım benzeri alanlar görüldü.
- `CONFIRMED_FROM_MEETING` Session kayıtlarında Session Başlangıç, Session Devam ve Session Bitiş benzeri kayıt türleri bulunabilir.
- `OPEN_QUESTION` Alanların kesin tipleri, null politikası, tutulma süresi, kaynak sistemleri ve ProcessTwin'e aktarılabilecek maskelenmiş tanımlayıcıları belirlenmedi.

## 4. Geçmiş session sorguları

- `CONFIRMED_FROM_MEETING` Geçmiş session verileri database sorgularıyla araştırılabilir.
- `INFERENCE` Zaman aralığı sorguları; bitişten sonraki ilk başlangıç/devam olayını, eksik kayıtları ve saat dilimini açıkça ele almalıdır.
- `OPEN_QUESTION` Geçmiş veri erişim SLA'sı, gecikme, kayıt bütünlüğü ve kaynak sistemdeki geç düzeltmeler bilinmiyor.

## 5. Topoloji ve zaman bazlı korelasyon

- `CONFIRMED_FROM_MEETING` Saat 09.00'daki müşteri kesintisinin kök nedeni, saat 08.00'de üst katmandaki bir cihazda başlayan problem olabilir.
- `CONFIRMED_FROM_MEETING` Yalnız eşzamanlı alarmlar değil; event sırası, zaman ilişkisi, üst-alt cihaz hiyerarşisi ve alarm yayılımı birlikte değerlendirilmelidir.
- `CONFIRMED_FROM_MEETING` Event ve hiyerarşi bazlı alarm korelasyonu düz eşleştirmeden daha gelişmiş ve değerli olabilir.
- `INFERENCE` Korelasyon penceresi, yönlü topoloji mesafesi ve kanıt kalitesi ayrı skor bileşenleri olarak izlenebilir; kesin ağırlıklar henüz kararlaştırılmamıştır.

## 6. GPON, OLT ve PON port olayları

- `CONFIRMED_FROM_MEETING` OLT arızaları ve GPON altyapısındaki port problemleri önemli, gerçekçi örnek olaylardır.
- `CONFIRMED_FROM_MEETING` Aynı zaman aralığında birden fazla GPON/OLT node alarmı bulunabilir.
- `CONFIRMED_FROM_MEETING` BNG üst katmandadır; ana örnek vaka olarak OLT/PON olayları kadar sık veya uygun olmayabilir.
- `PROJECT_DECISION` İlk eksiksiz ve gerçekçi altyapı GPON olacaktır.
- `PROJECT_DECISION` Bu bir kapsam daraltması değildir. BNG, DSLAM, VDSL, ADSL, Metro Ethernet, backup ve failover kapsamda kalır; GPON'dan sonra veri ve zaman yeterliliğine göre aynı kalite seviyesinde geliştirilecektir.

## 7. Cihaz anomaly örnekleri

- `CONFIRMED_FROM_MEETING` Cihaz sıcaklığı gibi anomaly'ler daha sonraki operasyon problemlerinin erken belirtisi olabilir.
- `OPEN_QUESTION` Ölçüm kaynağı, normal aralık, eşik, örnekleme sıklığı ve anomaly'nin alarm/incident yaşam döngüsündeki kesin rolü belirlenmedi.

## 8. Telafi/iade hakkındaki açık bilgiler

- `OPEN_QUESTION` / `NEEDS_CONFIRMATION` “24 saatten kısa kesintide iade yapılmıyor” bilgisi görüşmede aktarıldı, fakat yürürlükte ve uygulanabilir kesin iş kuralı olarak doğrulanmadı.
- `OPEN_QUESTION` Müşteri tipi, hizmet tipi ve GPON/broadband kapsamı kesin değil.
- `OPEN_QUESTION` Full outage ile partial outage/degradation ayrımı kesin değil.
- `OPEN_QUESTION` Kesintisiz 24 saat şartı ve aynı ay içindeki olayların birleştirilmesi kesin değil.
- `OPEN_QUESTION` Planlı bakım istisnası, müşteri başvurusu şartı ve tutar formülü kesin değil.
- `PROJECT_DECISION` Bu bilgi doğrulanana kadar mevcut `REFUND-001` veya başka rule/version verisi değiştirilmemelidir.

## 9. ProcessTwin yaklaşımına verilen olumlu geri bildirim

- `CONFIRMED_FROM_MEETING` Bir eşik 120 dakikadan 180 dakikaya değiştiğinde etkilenen müşteri, iade kapsamından çıkan müşteri, toplam telafi maliyeti ve son 30 günde iade alan müşteriler üzerindeki farkın baseline-candidate karşılaştırmasıyla gösterilmesi olumlu karşılandı.
- `CONFIRMED_FROM_MEETING` Alarm korelasyonu, olay hiyerarşisi ve kural değişikliği simülasyonu projenin güçlü yönleri olarak değerlendirildi.

## 10. Kesinleşmemiş konular ve açık sorular

- `OBSERVED_IN_SCREEN` Alarm örneğinde `ALARMHEADER`, `NODE1`, `EVENTTIME`, `HANDLEDBY`, `AUTONOTIFICATION`, `SERVICENAME`, `NODETYPE`, `OCNAME` ve `EKIP` benzeri alanlar görüldü.
- `OBSERVED_IN_SCREEN` Örnek alarm kodu `DISTRIBUTION_CABLE_DOWN` idi.
- `OBSERVED_IN_SCREEN` Bazı kaynak alanların `NULL` veya eksik olabildiği görüldü.
- `OPEN_QUESTION` Kaynak alanların kanonik adları, tipleri, enum katalogları, timezone davranışı ve hangi alanların zorunlu olduğu netleşmelidir.
- `OPEN_QUESTION` Alarm `clear timestamp`, auto-correlation ve ekip sahipliği yaşam döngüsü doğrulanmalıdır.
- `OPEN_QUESTION` Session ile alarm arasındaki kimlik eşleme anahtarları ve gizlilik/masking sözleşmesi belirlenmelidir.
- `OPEN_QUESTION` GPON için gerçekçi olay kataloğu, topoloji derinliği, PON port kapasitesi ve müşteri etkisi doğrulama kriterleri örnek verilerle teyit edilmelidir.
- `PROJECT_DECISION` Gerçek müşteri numarası, hizmet numarası, IP, MAC, seri numarası, kullanıcı adı, parola veya token hiçbir revizyon dokümanına alınmayacaktır.
