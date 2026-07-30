# Bekleyen İş ve Senaryo Kararları

Bu dosya, ProcessTwin projesinde ilerleyen görevlerden önce kullanıcıyla netleştirilmesi gereken iş, veri, senaryo ve demo kararlarını takip eder.

## Çalışma Kuralı

- Bu dosyadaki değerler kafadan doldurulmaz.
- Her başlık kullanıcıyla soru-cevap şeklinde tek tek netleştirilir.
- Karar verilmeden model, migration, seed veya iş kuralı kodu yazılmaz.
- Karar kesinleşince ilgili madde `KARAR VERİLDİ` olarak güncellenir.
- İlk 6 başlık netleşmeden Görev 019 başlatılmaz.

## 1. Görev 019 Öncesi Zorunlu Kararlar

Durum: `KARAR VERİLDİ`

- Cihaz türleri ve topoloji hiyerarşisi: `KARAR VERİLDİ`
  - Maltepe MVP seed topolojisi müşteri etkisi hesabı için basitleştirilmiş mantıksal topoloji olarak kabul edilir.
  - Temel zincir: `BNG -> erişim cihazı -> port -> hat -> abonelik -> müşteri`.
  - Fiber/GPON erişim zinciri: `BNG -> OLT -> port -> hat -> abonelik -> müşteri`.
  - VDSL/ADSL erişim zinciri: `BNG -> DSLAM -> port -> hat -> abonelik -> müşteri`.
  - Bu yapı gerçek fiziksel şebekenin tüm transport katmanlarını birebir temsil etmez; demo ve deterministik müşteri etki hesabı için kullanılan sadeleştirilmiş topolojidir.
  - Access node, switch veya saha dolabı ana Maltepe seed topolojisinde zorunlu ara katman değildir; gerekiyorsa özel senaryolarda sınırlı kullanılabilir.
- Switch, saha dolabı ve modem modelleme kararı: `KARAR VERİLDİ`
  - Ana müşteri etki zinciri değişmez: `BNG -> OLT/DSLAM -> port -> hat -> abonelik -> müşteri`.
  - Switch ve saha dolabı ilk MVP'de zorunlu katman değildir.
  - Gerektiğinde 1-2 örnek topoloji dalında mevcut `access_node` cihaz türü altında temsil edilebilir.
  - Switch ve saha dolabı için şimdilik ayrı yeni cihaz türü veya model oluşturulmaz.
  - Opsiyonel access node kayıtları tüm müşterilerin ana bağlantı zincirine zorunlu eklenmez.
  - Modem/CPE kayıtları ilk MVP seed'inde üretilmez.
  - Modem kaynaklı arıza, ölçüm ve müşteri cihazı ilişkileri sonraki genişleme kapsamında bırakılır.
- Yedek bağlantı yapısı: `KARAR VERİLDİ`
  - İlk MVP seed'inde yedek bağlantı bulunmaz.
  - Yedek bağlantı senaryosu daha sonra ProcessTwin içinde baseline/candidate karşılaştırması olarak ele alınır.
- Fiber/GPON/VDSL/ADSL teknoloji uyumluluk matrisi: `KARAR VERİLDİ`
  - `ServicePackage.technology`, müşteriye sunulan erişim/ürün ailesini temsil eder.
  - `LineConnection.technology`, fiziksel veya teknik erişim türünü temsil eder.
  - MVP uyumluluk matrisi:
    - `fiber` paket -> `fiber` hat: uyumlu
    - `fiber` paket -> `gpon` hat: uyumlu
    - `vdsl` paket -> `vdsl` hat: uyumlu
    - `adsl` paket -> `adsl` hat: uyumlu
    - `metro_ethernet` service type -> yalnız `fiber` hat: uyumlu
    - diğer kombinasyonlar: uyumsuz
  - Seed verisinde `gpon` isimli müşteri paketi üretilmez.
  - GPON, fiber paketlerin çalışabildiği hat/altyapı teknolojisi olarak kullanılır.
  - VDSL ve ADSL aynı xDSL ailesinde olmasına rağmen MVP'de birbirleriyle uyumlu kabul edilmez.
  - İlk Maltepe MVP seed'inde Metro Ethernet müşterisi, paketi, hattı veya outage senaryosu üretilmez.
  - `metro_ethernet`, fiziksel `AccessTechnology` değildir; `ServicePackage.service_type`
    değeridir.
  - Metro Ethernet sonraki kurumsal genişleme kapsamında P2P/dedicated fiber, ayrı
    topoloji, SLA, yedeklilik ve telafi kararlarıyla ele alınır.
  - Gelecekte eklenirken otomatik olarak OLT/DSLAM zincirine bağlanacağı varsayılmaz; ayrı servis/topoloji akışı değerlendirilerek modellenir.
  - Upgrade, downgrade veya teknoloji dönüşümü senaryoları sonraki kapsama bırakılır.
  - Uyumluluk mantığı model içinde dağınık koşullar olarak yazılmaz; ileride ortak `is_package_line_compatible` helper veya servis üzerinden yönetilir ve test edilir.
- Müşteri segmentleri ve VIP modeli: `KARAR VERİLDİ`
  - `Customer.segment` şu değerlerle devam eder:
    - `individual`
    - `sme`
    - `enterprise`
    - `public`
  - VIP müşteri segmenti değildir.
  - Aynı segment içindeki bazı müşteriler VIP olabilir.
  - VIP bilgisi serbest `metadata` içinde tutulmaz.
  - Segmentten ayrı, açık ve doğrulanabilir bir `Customer.priority_level` alanı kullanılacak şekilde planlanır.
  - İlk MVP `priority_level` değerleri:
    - `standard`
    - `vip`
  - Gerekçe:
    - Bireysel, KOBİ, kurumsal veya kamu müşterilerinin her biri gerektiğinde VIP olabilir.
    - İş kuralları, filtreleme, ground truth ve Decision Evidence bu alanı güvenilir şekilde kullanabilir.
    - `metadata["priority"]` gibi serbest yapı iş açısından kritik bir değer için fazla gevşek kalır.
    - VIP'yi ayrı segment yapmak müşteri türü ile hizmet önceliğini birbirine karıştırır.
  - Görev 019 seed başlamadan önce küçük teknik görev olarak `Customer.priority_level` alanı eklenmelidir.
  - Bu karar kapsamında henüz model, migration veya seed değişikliği yapılmaz.
- Kalite ölçümlerinin cihaz/abonelik kapsamı: `KARAR VERİLDİ`
  - İlk MVP'nin ana senaryosu BNG kaynaklı tam kesinti olduğu için Görev 019 öncesinde abonelik bazlı kalite modeli eklenmez.
  - Mevcut `QualityMeasurement -> NetworkDevice` yapısı yalnızca cihaz ve ağ seviyesi telemetriyi temsil eder:
    - latency
    - jitter
    - packet loss
    - availability
  - Bu ölçümler belirli bir müşterinin veya aboneliğin hız/kalite sonucu gibi yorumlanmaz.
  - Cihaz bazlı packet loss değerinden doğrudan “şu müşteri hız kaybı yaşadı” sonucu üretilmez.
  - İlk MVP'de müşteri etkisi deterministik olarak şu kaynaklardan hesaplanır:
    - outage
    - kaynak cihaz
    - topoloji
    - olay zamanında aktif hat ve abonelik bağlantıları
  - Abonelik bazlı hız, gecikme, packet loss ve servis bozulması analizi sonraki kapsamdır.
  - Teknik kapı: Servis bozulması veya müşteri bazlı kalite senaryosuna başlanmadan önce `SubscriptionQualityMeasurement` veya eşdeğer abonelik/hat bazlı ölçüm modeli tasarlanmalıdır.
  - Bu teknik kapıda ölçüm kaynağı, hedef hız, gerçekleşen hız, zaman aralığı, örnekleme sıklığı ve kalite eşikleri netleştirilmelidir.
  - ProcessTwin candidate senaryolarında müşteri bazlı kalite veya hız iyileştirmesi kullanılacaksa bu model Görev 079'dan önce tamamlanmalıdır.
  - Bu karar kapsamında henüz model, migration veya seed değişikliği yapılmaz.
- Maltepe mahalle, cihaz, port ve müşteri sayıları: `KARAR VERİLDİ`
  - Mahalle seçimi: `KARAR VERİLDİ`
  - İlk Maltepe seed'inde 5 mahalle kullanılır:
    - Altayçeşme
    - Cevizli
    - Küçükyalı
    - Zümrütevler
    - Fındıklı
  - İdealtepe yerine Fındıklı seçildi; amaç birbirine çok benzeyen veya yakın mahalle dalları yerine daha çeşitli sentetik topoloji profilleri oluşturmaktır.
  - Mahalle isimleri gerçek idari bölgelerdir.
  - Cihaz, port, hat, müşteri, teknoloji ve arıza dağılımları tamamen sentetik olacaktır.
  - Seed veya sunum, gerçek Turkcell şebeke topolojisini temsil ettiği iddiasında bulunmaz.
  - Mahallelerin nüfusu, gerçek müşteri sayısı veya gerçek cihaz sayısı kendiliğinden tahmin edilmez.
  - Her mahallede aynı sayıda cihaz ve müşteri olmak zorunda değildir; dağılım sonraki sorularda belirlenir.
  - Maltepe veya herhangi bir mahalle kod içinde hard-code edilmez; bunlar yalnızca ilk dataset/config girdileri olur.
  - BNG sayısı ve hizmet kapsamı: `KARAR VERİLDİ`
    - İlk Maltepe seed'inde 2 BNG bulunur:
      - `BNG-MAL-001`
      - `BNG-MAL-002`
    - İlk sentetik dağılım:
      - `BNG-MAL-001`: Altayçeşme, Cevizli, Küçükyalı
      - `BNG-MAL-002`: Zümrütevler, Fındıklı
    - Ana demo outage olayı `BNG-MAL-001` üzerinde gerçekleşir.
    - `BNG-MAL-001` altındaki erişim cihazları ve aktif abonelikler etkilenir.
    - `BNG-MAL-002` altındaki abonelikler etkilenmez.
    - Bu yapı etkilenen ve etkilenmeyen müşteriler için güçlü ground truth oluşturur.
    - Mimari ilişki doğrudan `BNG -> mahalle` şeklinde kurulmaz.
    - Gerçek hesap zinciri:
      - `BNG`
      - `NetworkLink` ile bağlı `OLT/DSLAM`
      - `NetworkPort`
      - `LineConnection`
      - `SubscriptionConnection`
      - `Subscription`
      - `Customer`
    - Mahalle yalnızca cihazın, hattın veya müşterinin coğrafi konum bilgisidir.
    - Veri modelinde “bir mahalle yalnızca bir BNG'ye bağlı olabilir” şeklinde constraint veya hard-code bulunmaz.
    - İlk seed'de dağılım sade tutulabilir; ileride aynı mahallede farklı BNG'lere bağlı erişim cihazları desteklenebilmelidir.
    - İlk MVP'de yedek bağlantı olmadığı için `BNG-MAL-001` altındaki geçerli aktif aboneliklerin ana outage sırasında etkilendiği kabul edilebilir.
  - Erişim cihazı, port, hat, müşteri ve teknoloji dağılımı: `KARAR VERİLDİ`
    - OLT/DSLAM sayısı: `KARAR VERİLDİ`
    - `BNG-MAL-001` dağılımı:
      - Altayçeşme: 1 OLT, 1 DSLAM
      - Cevizli: 1 OLT, 1 DSLAM
      - Küçükyalı: 1 OLT, 1 DSLAM
    - `BNG-MAL-002` dağılımı:
      - Zümrütevler: 1 OLT, 1 DSLAM
      - Fındıklı: 1 OLT, 1 DSLAM
    - Toplam:
      - 5 OLT
      - 5 DSLAM
      - 10 erişim cihazı
    - Bu yapı ilk seed için basitleştirilmiş mantıksal topolojidir.
    - Gerçek şebekede her mahallede yalnızca bir OLT ve bir DSLAM bulunduğu iddia edilmez.
    - Cihaz sayıları dengeli olsa da port kapasitesi, aktif port sayısı ve müşteri yükü her mahallede eşit olmak zorunda değildir.
    - OLT'ler fiber/GPON hatlara, DSLAM'lar VDSL/ADSL hatlara hizmet eder.
    - Her erişim cihazı `NetworkLink` ile ilgili BNG'ye bağlanır.
    - Mahalle ilişkisi coğrafi konum bilgisidir; modelde mahalle başına tam olarak bir OLT ve bir DSLAM zorunluluğu veya hard-code oluşturulmaz.
    - Cihaz isimleri tutarlı formatta üretilebilir:
      - `OLT-MAL-ALT-001`
      - `DSLAM-MAL-ALT-001`
      - `OLT-MAL-CEV-001`
      - `DSLAM-MAL-CEV-001`
    - Müşteri, abonelik ve aktif hat bağlantısı ölçeği: `KARAR VERİLDİ`
      - İlk Maltepe seed ölçeği:
        - 225 benzersiz müşteri
        - 240 abonelik
        - 240 aktif `SubscriptionConnection` / aktif hat bağlantısı
      - 15 müşterinin iki aboneliği olabilir.
      - Diğer müşterilerin birer aboneliği olur.
      - BNG dağılımı abonelik üzerinden yapılır:
        - `BNG-MAL-001`: yaklaşık 150 aktif abonelik
        - `BNG-MAL-002`: yaklaşık 90 aktif abonelik
      - Dağılım cihazlar ve mahalleler arasında eşit olmak zorunda değildir.
    - Port kapasitesi kararı: `KARAR VERİLDİ`
      - `NetworkPort` anlamı: `KARAR VERİLDİ`
      - `NetworkPort`, cihaz üzerindeki fiziksel veya sentetik fiziksel portu temsil eder.
      - `LineConnection`, bu fiziksel port üzerinden sunulan müşteri erişim hattını temsil eder.
      - `SubscriptionConnection`, aboneliğin belirli zaman aralığında hangi `LineConnection` üzerinden hizmet aldığını temsil eder.
      - DSLAM / VDSL / ADSL genel davranışı:
        - 1 fiziksel müşteri portu -> 1 aktif `LineConnection`.
        - Bir DSLAM müşteri portunda aynı anda birden fazla aktif müşteri hattı bulunmaz.
      - OLT / GPON genel davranışı:
        - Bir fiziksel PON portuna birden fazla `LineConnection` bağlanabilir.
        - GPON abonelikleri için müşteri başına ayrı fiziksel `NetworkPort` üretilmez.
        - Splitter ve ONT/ONU ilk MVP'de ayrı model olarak eklenmez.
        - PON portundan birden fazla müşteri hattına geçiş, basitleştirilmiş mantıksal fan-out olarak temsil edilir.
      - Mevcut model kontrolü:
        - `LineConnection.port` alanı `NetworkPort` için ForeignKey kullanır.
        - Mevcut model ve migrationlarda aynı `NetworkPort` üzerinde birden fazla `LineConnection` oluşmasını engelleyen global unique constraint yoktur.
        - Bu nedenle GPON fan-out için şu aşamada model/migration değişikliği gerekmemektedir.
        - DSLAM için 1 port -> 1 aktif hat kuralı bütün teknolojilere uygulanan global unique constraint olarak yazılmaz; seed/servis mantığında teknolojiye göre korunur.
      - Bu karar gerçek fiziksel GPON topolojisinin eksiksiz modeli değil, MVP için basitleştirilmiş mantıksal temsildir.
      - Fiber/GPON fiziksel hat dağılımı:
        - GPON fiziksel hat: 100 abonelik
        - Genel fiber / noktadan noktaya fiber hat: 30 abonelik
        - Toplam fiber paket aboneliği: 130
      - `BNG-MAL-001` fiber fiziksel erişim dağılımı:
        - 62 GPON
        - 18 genel fiber
        - Toplam 80 fiber abonelik
      - `BNG-MAL-002` fiber fiziksel erişim dağılımı:
        - 38 GPON
        - 12 genel fiber
        - Toplam 50 fiber abonelik
      - GPON müşteri paketi değildir; fiber paketleri taşıyan fiziksel erişim teknolojisi olarak kalır.
      - GPON PON port kapasitesi:
        - 100 GPON aboneliği
        - 10 aktif fiziksel PON portu
        - 2 boş/rezerve PON portu
        - Toplam 12 PON portu
        - Aktif PON portu başına ortalama 10 abonelik
      - Her PON portunda tam olarak 10 abonelik bulunmak zorunda değildir.
      - Gerçekçi ve dengesiz dağılım kullanılabilir:
        - bazı portlarda 8 abonelik
        - bazı portlarda 9 abonelik
        - bazı portlarda 11 abonelik
        - bazı portlarda 12 abonelik
      - Genel ortalama yaklaşık 10 abonelik/PON port olur.
      - 5 OLT'nin her birinde 2 aktif PON portu bulunur.
      - İki boş/rezerve PON porttan biri `BNG-MAL-001` tarafındaki bir OLT'ye, diğeri `BNG-MAL-002` tarafındaki bir OLT'ye verilebilir.
      - DSLAM VDSL/ADSL port kapasitesi:
        - 110 aktif DSLAM müşteri portu
        - 20 boş/rezerve DSLAM portu
        - Toplam 130 DSLAM portu
      - 5 DSLAM için başlangıç kapasitesi:
        - Her DSLAM: 22 aktif port
        - Her DSLAM: 4 boş/rezerve port
        - Her DSLAM toplam: 26 port
      - DSLAM toplam kontrolü:
        - 5 x 22 = 110 aktif port
        - 5 x 4 = 20 boş/rezerve port
        - Genel toplam 130 port
      - VDSL ve ADSL portları teknoloji tipine göre açık şekilde ayrılır.
      - Boş/rezerve portların tamamının teknoloji ataması zorunlu değilse `unassigned/reserved` tutulabilir.
      - Mevcut model buna izin vermiyorsa seed başlamadan önce çözüm önerisi sunulur.
      - DSLAM tarafında genel davranış:
        - 1 aktif fiziksel müşteri portu
        - 1 aktif `LineConnection`
        - 1 aktif abonelik bağlantısı
      - Genel fiber port kapasitesi:
        - 30 aktif genel fiber portu
        - 5 boş/rezerve genel fiber portu
        - Toplam 35 fiziksel port
      - Genel fiber bağlantıları OLT üzerindeki PON portları gibi gösterilmez.
      - GPON dışındaki noktadan noktaya genel fiber hatlar, `access_node` veya switch rolündeki erişim cihazları üzerinden temsil edilir.
      - İlk seed'de 2 adet opsiyonel access node kullanılabilir:
        - Access node 1: 15 aktif + 3 boş/rezerve port
        - Access node 2: 15 aktif + 2 boş/rezerve port
      - Bu access node cihazları ana GPON veya DSL zincirinin zorunlu katmanı değildir; yalnızca 30 genel fiber hattın fiziksel erişim noktasıdır.
    - Teknoloji yük dağılımı: `KARAR VERİLDİ`
      - 240 aktif aboneliğin paket teknolojisi dağılımı:
        - Fiber: 130
        - VDSL: 90
        - ADSL: 20
        - Metro Ethernet: 0
        - GPON paket: 0
      - `BNG-MAL-001` toplam 150 abonelik:
        - Fiber: 80
        - VDSL: 55
        - ADSL: 15
      - `BNG-MAL-002` toplam 90 abonelik:
        - Fiber: 50
        - VDSL: 35
        - ADSL: 5
      - Toplam kontrolü:
        - Fiber: 130
        - VDSL: 90
        - ADSL: 20
        - Genel toplam: 240
      - Bu değerlerin Maltepe'nin veya Turkcell şebekesinin gerçek müşteri dağılımı olduğu iddia edilmez.
      - Değerler güncel genişbant eğilimine uygun, sentetik ve kontrollü demo değerleridir.
      - Her OLT yalnız fiber/GPON fiziksel hatlara hizmet eder.
      - Her DSLAM yalnız VDSL/ADSL hatlara hizmet eder.
      - Fiber aboneliklerin fiziksel erişim dağılımı ve port kapasitesi port kapasitesi kararında netleştirilmiştir.
- Tam kesinti, servis bozulması ve kademeli geri dönüş yapısı: `KARAR VERİLDİ`
  - Kontrollü B yaklaşımı seçildi.
  - İlk MVP'nin ana ve karar üreten senaryosu tam kesintidir:
    - BNG kaynaklı outage
    - olay zamanındaki aktif topoloji ve abonelik bağlantıları
    - etkilenen benzersiz müşteriler
    - daha sonra uygulanacak deterministik telafi kuralları
  - Seed verisinde ağ ortamını daha gerçekçi göstermek için en fazla 1-2 cihaz seviyesinde kalite bozulması kaydı bulunabilir:
    - kısa süreli latency artışı
    - packet loss yükselmesi
    - sonradan normale dönen cihaz seviyesi kalite alarmı
  - Kalite bozulması kayıtları için sınırlar:
    - müşteri veya abonelik bazlı kalite sonucu üretilmez
    - etkilenen müşteri sayısı hesaplanmaz
    - telafi/iade değerlendirmesine girmez
    - ana “en uzun kesinti” ve BNG müşteri etkisi sorgusuna karışmaz
    - Decision Evidence içinde müşteri etkisi kanıtı olarak kullanılmaz
    - yalnızca cihaz telemetrisi ve operasyonel arka plan verisi olarak tutulur
    - ana BNG outage ile aynı cihaz ve aynı zaman aralığında oluşturulup kafa karışıklığı yaratılmaz
    - kullanıcı arayüzünde gösterilirse “cihaz seviyesi kalite sinyali” olarak açıkça etiketlenir
  - Tam kesinti ve servis bozulması ayrı kavramlardır:
    - Tam kesinti: Outage ve müşteri etki akışına girer.
    - Servis bozulması: İlk MVP'de yalnızca cihaz seviyesi `QualityMeasurement`/alarm verisidir.
  - Abonelik bazlı servis bozulması analizi, `SubscriptionQualityMeasurement` ve ilgili eşik/ground truth kuralları tasarlandıktan sonra sonraki kapsama alınır.
  - Ana demo outage zamanı:
    - Kaynak cihaz: `BNG-MAL-001`
    - Süre: 3 saat 20 dakika
    - Dataset reference datetime: `2026-08-01T00:00:00+03:00`
    - Ana outage başlangıcı: `2026-07-20T10:15:00+03:00`
    - Ana outage bitişi: `2026-07-20T13:35:00+03:00`
    - Zaman dilimi: Europe/Istanbul
  - Tarih üretim kuralı:
    - Ana sorgu “geçen ay en uzun kesinti” olacağı için seed config içinde açık bir `reference_datetime` veya eşdeğer dataset referans zamanı bulunur.
    - Outage, bu referans zamanın bir önceki takvim ayında üretilir.
    - Seed generator başka bir reference date ile çalıştırılırsa olay tarihleri bir önceki aya göre hesaplanabilir olmalıdır.
    - Böylece “geçen ay” sorgusu zaman geçince bozulmaz.
  - Kademeli hizmet dönüşü:
    - Ana outage tek kayıt olarak başlar ve biter.
    - Operasyonel event kayıtlarında toparlanma sinyalleri bulunabilir.
    - Örnek sinyaller: alarm yoğunluğunun azalması, cihaz erişim sinyalinin dönmesi, teknik müdahale notu.
    - İlk MVP'de belirli müşteri gruplarının daha erken hizmet aldığı iddia edilmez.
    - Kısmi müşteri restorasyonu hesaplanmaz.
    - Etkilenen müşteri sayısı outage tamamlanana kadar tek ground truth olarak kalır.
    - Operasyonel eventler telafi tutarını veya müşteri etki hesabını değiştirmez.
    - Gerçek kademeli müşteri dönüşü daha sonra zaman aralıklı impact/restoration modeliyle ele alınır.
  - Aynı önceki takvim ayı içinde iki kısa outage daha üretilir:
    - Bir OLT kaynaklı yaklaşık 45 dakikalık outage
    - Bir DSLAM kaynaklı yaklaşık 70 dakikalık outage
  - Kısa outage kuralları:
    - Ana BNG outage ile zaman olarak çakışmazlar.
    - Farklı cihazlarda gerçekleşirler.
    - En az biri `BNG-MAL-002` tarafında olur.
    - Ana `BNG-MAL-001` outage her durumda ayın en uzun outage kaydı olur.
    - Bu kısa outage kayıtları kendi topoloji dallarındaki müşterileri etkileyebilir.
    - Kesin müşteri sayıları ground truth aşamasında hesaplanıp kaydedilir.
    - Bunlar servis bozulması değil, kısa tam outage kayıtlarıdır.
  - Bu karar kapsamında henüz model, migration veya seed değişikliği yapılmaz.

## 2. Alarm ve Incident Kararları

Durum: `MVP İÇİN KARAR VERİLDİ`

- Alarm kataloğu: `KARAR VERİLDİ`
  - İlk MVP resmi alarm kataloğu yalnızca 3 alarm tipinden oluşur:
    - `BNG_UNREACHABLE`
      - severity: `critical`
      - category: `core`
    - `ACCESS_DEVICE_UNREACHABLE`
      - severity: `major`
      - category: `access`
    - `LINK_DOWN`
      - severity: `major`
      - category: `transport`
  - Bu katalog, Görev 024 kapsamında resmi MVP alarm kataloğu olarak sabitlenir.
  - Yaklaşık 27 alarm tipi hedefi post-MVP alarm katalog genişletmesi olarak takip edilir.
  - Kullanılmayacak alarm tipleri kafadan üretilmez.
  - `DEVICE_RECOVERY` alarm tipi eklenmez; recovery bilgisi `OperationalEvent.event_type=auto_recovery` olarak tutulur.
  - `LOS_DETECTED` ilk MVP kataloguna eklenmez.
  - Kalite alarmı ilk MVP kataloguna eklenmez.
- Severity değerleri: `KARAR VERİLDİ`
  - `BNG_UNREACHABLE`: `critical`
  - `ACCESS_DEVICE_UNREACHABLE`: `major`
  - `LINK_DOWN`: `major`
- Parent-child alarm ilişkileri: `MVP İÇİN SINIRLANDIRILDI`
  - İlk MVP'de ayrı bir parent-child alarm modeli veya geniş alarm ağacı kurulmaz.
  - Incident ile alarm ilişkisi `IncidentAlarm.role` üzerinden tutulur:
    - ana alarm: `primary`
    - destekleyici alarm: `supporting`
  - Ana BNG outage için `BNG_UNREACHABLE` primary alarmdır.
  - Gerekli senaryoda `LINK_DOWN` supporting alarm olarak incident'e bağlanabilir.
- Korelasyon eşikleri: `SONRAKİ KAPSAM`
  - Zaman penceresi, alarm yoğunluğu veya otomatik korelasyon eşiği bu MVP alarm katalog görevinde tanımlanmaz.
  - İlk MVP seed'i deterministik senaryo kayıtları üretir; gerçek alarm korelasyon algoritması sonraki kapsamdır.
- Incident oluşturma koşulları: `MVP İÇİN KARAR VERİLDİ`
  - Ana BNG outage için bir incident üretilir.
  - Kısa OLT ve DSLAM outage kayıtları için ayrı incident kayıtları üretilebilir.
  - Incident kayıtları seed senaryosunun deterministik parçasıdır; otomatik korelasyon motoru bu aşamada yazılmaz.
- Kök neden ve belirti ayrımı: `MVP İÇİN KARAR VERİLDİ`
  - Ana outage kök neden kategorisi `bng_failure` olarak tutulur.
  - LOS, ilk MVP'de kök neden veya alarm tipi olarak kullanılmaz.
  - LOS gibi belirti alarmları post-MVP alarm katalog genişletmesinde ayrıca değerlendirilecektir.
- Görev 025 audit notu: `KARAR VERİLDİ`
  - Görev 019-023 yeniden kapsamlandırıldığı için Görev 025'in üretim kabul kriterleri mevcut implementation içinde önceden karşılanmıştır.
  - `078d8e0 feat: seed maltepe operations events` commit'iyle:
    - `BNG-MAL-001` kaynaklı ana outage üretildi.
    - `INC-MAL-BNG-001` incident kaydı üretildi.
    - `BNG_UNREACHABLE` primary alarm olarak bağlandı.
    - `LINK_DOWN` supporting alarm olarak bağlandı.
    - Outage kapanış ve süre bilgileri üretildi.
    - Recovery bilgisi alarm olarak değil `OperationalEvent.event_type=auto_recovery` olarak üretildi.
    - Kısa OLT/DSLAM outage kayıtlarında `ACCESS_DEVICE_UNREACHABLE` kullanıldı.
  - `0905201 feat: validate maltepe seed output` commit'iyle:
    - Ana BNG outage'ın snapshot `reference_datetime` değerine göre önceki ayın en uzun outage'ı olduğu validator ile doğrulandı.
    - Bu doğrulama sistem tarihine bağlı değildir.
  - Görev 025 kapsamında yeni alarm, incident, outage veya operational event üretilmeyecektir.
  - Ground truth, customer impact ve telafi/iade değerlendirmesi sonraki görevlerde ele alınacaktır.

## 3. İş Kuralları ve Telafi

Durum: `MVP İÇİN KARAR VERİLDİ`

- İade eşikleri: `KARAR VERİLDİ`
  - `REFUND-001` v1:
    - geçerlilik başlangıcı: `2026-01-01T00:00:00+03:00`
    - geçerlilik bitişi: `2026-07-14T23:59:59+03:00`
    - minimum etki süresi: 180 dakika
  - `REFUND-001` v2:
    - geçerlilik başlangıcı: `2026-07-15T00:00:00+03:00`
    - geçerlilik bitişi: açık
    - minimum etki süresi: 120 dakika
  - Ana BNG outage `2026-07-20` tarihinde olduğu için v2 seçilmelidir.
  - Mevcut kısa outage tarihleri değiştirilmez; v1 seçimi unit test ile ayrıca doğrulanır.
- Uygunluk koşulları: `KARAR VERİLDİ`
  - outage türü `full_outage` olmalıdır
  - abonelik outage sırasında aktif olmalıdır
  - `SubscriptionConnection` outage zamanıyla çakışmalıdır
  - hesaplanan etki süresi ilgili kural sürümünün eşiğine eşit veya büyük olmalıdır
- Hesaplama formülü: `KARAR VERİLDİ`
  - Sentetik MVP formülü: `refund_amount = subscription.monthly_price * 0.10`
  - İki ondalığa yuvarlanır.
  - Para birimi: TRY
  - Minimum tutar yoktur.
  - Ek üst sınır yoktur; tutar aylık ücretin yüzde 10'udur.
  - Bu formül gerçek Turkcell politikası olarak sunulmaz; sentetik demo kuralıdır.
  - v1 ve v2'de formül aynıdır; yalnızca süre eşiği değişir.
- Alt/üst tutar sınırları: `KARAR VERİLDİ`
  - Minimum tutar yok.
  - Ek üst sınır yok.
- Müşteri segmenti ve VIP farkları: `KARAR VERİLDİ`
  - `standard` ve `vip` aynı kuralı kullanır.
  - `individual`, `sme`, `enterprise` ve `public` aynı kuralı kullanır.
  - VIP'ye özel oran, öncelik veya SLA bu görevde eklenmez.
- Ödeme, kampanya ve geçmiş telafi etkisi: `SONRAKİ KAPSAM`
  - Bu görevde eligibility koşuluna dahil edilmez:
    - ödeme borcu/gecikme
    - kampanya indirimi
    - daha önce telafi alınması
  - Görev 021 kapsamında `PaymentRecord`, `CampaignEnrollment` ve `CompensationHistory` seedlenmez.
  - Bu kayıtlar gerçek iade formülü, fatura dönemi, kampanya indirimi ve geçmiş telafi kontrolleri tasarlanmadan önce zorunlu olarak netleştirilmelidir.
  - `PaymentRecord` için en az fatura dönemi, ödeme durumu, gecikme/borç etkisi ve tutar üretim mantığı belirlenmelidir.
  - `CampaignEnrollment` için kampanya indirimi, kampanya birlikte kullanım kuralı, geçerlilik dönemi ve telafiyle etkileşim kararı verilmelidir.
  - `CompensationHistory` için geçmiş telafi referansı, tutar, karar tarihi, tekrar telafi etkisi ve manuel inceleme koşulu netleştirilmelidir.
- Kampanya birlikte kullanım kuralları: `SONRAKİ KAPSAM`
- Manuel inceleme koşulları: `KARAR VERİLDİ`
  - Zorunlu veri eksikse otomatik red verilmez.
  - Sonuç `manual_review` olur.
  - Eksik `monthly_price`, outage zamanı, bağlantı veya kural sürümü gibi durumlarda hesaplama yapılmaz.
- Kural sürümleri ve öncelikler: `KARAR VERİLDİ`
  - RuleVersion seçimi `Outage.started_at` tarihine göre yapılır.
  - Aynı tarihte birden fazla geçerli RuleVersion bulunmasına izin verilmez.
  - Sürüm tarih aralıkları çakışmaz.
  - Hiç sürüm bulunamazsa veya birden fazla sürüm bulunursa güvenli `manual_review` sonucu oluşur.
  - Kafadan “en yeni sürümü seç” davranışı yazılmaz.

## 4. Ground Truth

Durum: `KARAR VERİLDİ`

- Kapsam: `KARAR VERİLDİ`
  - Ground truth üç outage için üretilir:
    - ana BNG outage
    - kısa OLT outage
    - kısa DSLAM outage
  - Ana BNG outage pozitif telafi senaryosudur.
  - Kısa OLT ve DSLAM outage kayıtları süre eşiğini geçmeyen negatif senaryolardır.
- Saklanacak etki kayıtları: `KARAR VERİLDİ`
  - Her outage için ayrı ground truth kaydı tutulur.
  - Kaydedilecek alanlar:
    - outage code
    - beklenen kaynak cihaz kodu
    - beklenen incident kodu
    - beklenen alarm type kodları
    - beklenen süre dakika değeri
    - beklenen rule code ve rule version
    - etkilenen subscription kodları ve sayısı
    - etkilenen customer kodları ve sayısı
    - etkilenen segment sayımları
    - etkilenen priority sayımları
    - beklenen eligibility
    - beklenen reason code
    - beklenen toplam iade tutarı
    - currency
  - DB primary key saklanmaz.
  - `CUST-MAL-*`, `SUB-MAL-*`, `OUT-MAL-*` gibi deterministik business code değerleri saklanır.
  - Etkilenen müşteri ve abonelik listeleri sıralı ve deterministik tutulur.
  - Etkilenen müşteri ve abonelik listeleri için ayrıca SHA-256 hash değeri saklanır.
- Etkilenmeyen kayıtlar: `KARAR VERİLDİ`
  - Etkilenmeyen müşteri ve aboneliklerin tam listesi saklanmaz.
  - Yalnız `unaffected_customer_count` ve `unaffected_subscription_count` tutulur.
  - Etkilenmeyen set snapshot toplamından affected set çıkarılarak doğrulanır.
- Beklenen kural ve telafi sonuçları: `KARAR VERİLDİ`
  - Ana BNG outage için:
    - expected eligibility: `eligible`
    - expected rule: `REFUND-001`
    - expected rule version: `v2`
    - iade abonelik başına hesaplanır.
    - formül: `subscription.monthly_price * 0.10`
    - iki ondalığa yuvarlanır.
    - currency: `TRY`
    - toplam beklenen iade tutarı saklanır.
  - Aynı müşterinin iki etkilenen aboneliği varsa iki ayrı abonelik sonucu olabilir.
  - Kısa OLT ve DSLAM outage için:
    - expected eligibility: `ineligible`
    - expected reason: `duration_below_threshold`
    - expected refund amount: `0.00`
    - olay tarihinde geçerli beklenen RuleVersion açıkça saklanır.
- Ground truth bağımsızlığı: `KARAR VERİLDİ`
  - Ground truth üretimi ileride yazılacak servisleri kullanmaz:
    - CustomerImpactService
    - CompensationService
    - MCP tool
    - production rule evaluation service
  - Ground truth, seed config, deterministik business code dağılımları ve bilinen senaryo kararlarından üretilen bağımsız oracle kabul edilir.
  - Aynı hesaplama kodu hem ground truth hem production serviste ortak kullanılmaz.
- Negatif ve bozuk veri senaryoları: `SONRAKİ KAPSAM`
  - Bu görevde eksik bağlantı, bozuk müşteri, yanlış cihaz veya duplicate olay eklenmez.
  - Ana dataset temiz ve validated kalır.
  - Eksik/bozuk veri senaryoları sonraki servis unit testlerinde fixture olarak oluşturulur.
- Snapshot ve validation: `KARAR VERİLDİ`
  - Ground truth kayıtları `DataSnapshot` kaydına bağlıdır.
  - `--reset` ile deterministik biçimde yeniden oluşur.
  - Duplicate kayıt oluşmaz.
  - Validator ground truth kayıtlarının outage, source device, incident, alarm, customer ve subscription kodlarıyla tutarlı olduğunu doğrular.
  - Affected ve unaffected sayıları snapshot toplamlarıyla tutarlı olmalıdır.
  - `affected_subscription_count`, `affected_customer_count` değerinden küçük olamaz.
  - Ana BNG outage için affected subscription sayısı BNG-MAL-001 tarafındaki 150 bağlantıyla uyumlu olmalıdır.

## 5. RAG Kaynakları

Durum: `KARAR BEKLİYOR`

- İade politikası: `KARAR BEKLİYOR`
- SLA metni: `KARAR BEKLİYOR`
- Alarm kataloğu: `KARAR BEKLİYOR`
- Müdahale prosedürü: `KARAR BEKLİYOR`
- Kampanya koşulları: `KARAR BEKLİYOR`
- Incident kapanış raporları: `KARAR BEKLİYOR`

## 6. Decision Evidence

Durum: `KARAR BEKLİYOR`

- Saklanacak veri kanıtları: `KARAR BEKLİYOR`
- Saklanacak kural kanıtları: `KARAR BEKLİYOR`
- Saklanacak hesaplama kanıtları: `KARAR BEKLİYOR`
- Saklanacak tool çağrısı kanıtları: `KARAR BEKLİYOR`
- Replay için gerekli sürüm bilgileri: `KARAR BEKLİYOR`
- Kullanıcıya gösterilecek ayrıntı seviyesi: `KARAR BEKLİYOR`

## 7. ProcessTwin

Durum: `KARAR VERİLDİ`

- ProcessTwin gerçek üretim ağı değildir; canlıya benzer sentetik simülasyondur.
- Aynı sentetik olay senaryosu baseline ve candidate rule set ile aynı başlangıç
  koşullarında çalıştırılır.
- Run sırasında virtual clock ilerler; desteklenecek hızlar en az 1x, 10x ve 60x
  olur.
- Alarm, operational event, incident, outage/degradation, müşteri etkisi ve telafi
  değerlendirmeleri run içinde zamanla oluşur.
- Harita, mantıksal topoloji ve event timeline çalışan run'a göre güncellenir.
- Run izole, deterministik, tekrar oynatılabilir ve sıfırlanabilir olur.
- Start, status, pause, resume, stop/cancel, replay ve result işlemleri bulunur.
- RAG yalnız kural/prosedür kaynaklarını getirir.
- LLM araçları orkestre eder ve deterministik sonuçları açıklar; hesaplama yapmaz.
- Simulation MCP, Görev 075-081 runtime altyapısını dışarı açan ince adapter olarak
  ele alınır.

## 8. Faz 039.5 - Gerçekçi Simülasyon Verisi ve İş Kuralları Genişletme

Durum: `KARAR BEKLİYOR`

Bu faz, mevcut Maltepe MVP dataset'inin yalnız teknik altyapıyı doğrulayan minimal
sentetik örnek olduğunu kabul eder. Bu karar kapıları tamamlanmadan Network MCP,
Customer MCP, Rule MCP, Compensation MCP, RAG veya orchestrator görevlerine geçilmez.

### 8.1 Mevcut Gerçekçilik Gap Analizi

Durum: `KARAR VERİLDİ`

- Mevcut dataset yalnız İstanbul / Maltepe / 5 mahalle kapsamındadır.
- Mevcut alarm kataloğu yalnız 3 teknik alarm tipinden oluşur:
  - `BNG_UNREACHABLE`
  - `ACCESS_DEVICE_UNREACHABLE`
  - `LINK_DOWN`
- Mevcut outage kütüphanesi 3 outage kaydıdır.
- Mevcut iş kuralı yalnız `REFUND-001` v1/v2 teknik örneğidir.
- Mevcut telafi formülü gerçek politika değildir; sentetik MVP demo kuralıdır.
- PaymentRecord, CampaignEnrollment ve CompensationHistory modelleri vardır ancak seed
  kapsamında üretilmemiştir.
- QualityMeasurement modeli cihaz bazlıdır; abonelik bazlı kalite ölçümü henüz yoktur.
- RAG, Decision Evidence ve ProcessTwin kararları ayrıca beklemektedir.
- Kod, model, migration, seed, MCP veya RAG değişikliği yapılmadan gap analizi
  tamamlanmıştır.

### 8.2 Coğrafya ve Topoloji Profilleri

Durum: `KISMEN KARAR VERİLDİ`

- Simülasyon şehir sayısı: `KARAR VERİLDİ`
  - Simülasyon 4 şehir içerecek:
    - İstanbul
    - Ankara
    - İzmir
    - Kocaeli
  - Bu karar “daha fazla şehir daha iyidir” mantığıyla verilmemiştir; dört şehrin
    birbirinden farklı simülasyon profilleri üretmesi nedeniyle seçilmiştir.
  - İstanbul:
    - yüksek yoğunluk
    - karma eski/yeni altyapı
    - toplu müşteri etkisi
  - Ankara:
    - kamu
    - kurumsal müşteri
    - SLA profili
  - İzmir:
    - konut ve ticari kullanım dengesi
    - orta-yüksek yoğunluk profili
  - Kocaeli:
    - sanayi
    - KOBİ
    - enterprise
    - kritik hizmet profili
  - Bursa ve Kocaeli birlikte kullanılmayacak; sanayi profilini Kocaeli temsil edecek.
  - Antalya, Konya, Gaziantep veya başka şehirler şimdilik eklenmeyecek.
  - Şehir sayısı daha sonra kendiliğinden artırılmayacak.
  - Bu şehirler gerçek Turkcell envanteri veya gerçek cihaz dağılımı iddiası
    taşımayacak.
  - Veriler gerçeğe yakın fakat tamamen sentetik olacak.
  - Mevcut Maltepe dataset'i silinmeyecek; İstanbul içindeki temel regression/demo
    senaryosu olarak korunacak.
  - Henüz ilçe, mahalle, cihaz, müşteri, abonelik veya teknoloji adetleri belirlenmedi.
- İstanbul ilçe seçimleri: `KARAR VERİLDİ`
  - İstanbul için seçilen ilçeler:
    - Maltepe
    - Şişli
    - Esenyurt
  - Maltepe mevcut regression ve ana demo ilçesi olarak korunacak.
  - Şişli merkezi iş alanı, ticari/kurumsal müşteri, yüksek SLA hassasiyeti ve yoğun
    gündüz kullanımı profilini temsil edecek.
  - Esenyurt yüksek konut yoğunluğu, kapasite baskısı, port doluluğu ve çok sayıda
    müşteriyi etkileyen geniş kesinti senaryolarını temsil edecek.
  - Tuzla seçilmedi; sanayi, lojistik ve enterprise profilini Kocaeli şehri temsil
    edecek.
  - Kadıköy seçilmedi; konut ve ticari karma profil Maltepe ve İzmir tarafında kısmen
    temsil edilecek.
  - Başakşehir ve Ümraniye modern altyapı açısından faydalı olabilir ancak Şişli +
    Esenyurt kombinasyonu operasyonel senaryolar açısından daha güçlü ve daha farklı
    iki uç profil sağlıyor.
  - Bu ilçeler gerçek Turkcell altyapısını temsil ettiği iddiasıyla kullanılmayacak.
  - İlçelerin genel kent profillerinden esinlenen tamamen sentetik altyapı ve müşteri
    dağılımları oluşturulacak.
- İstanbul mahalle seçimleri: `KARAR VERİLDİ`
  - Maltepe:
    - Altayçeşme
    - Cevizli
    - Küçükyalı
    - Zümrütevler
    - Fındıklı
  - Şişli:
    - Mecidiyeköy
    - Esentepe
    - Halaskargazi
    - Teşvikiye
  - Esenyurt:
    - Akçaburgaz
    - Mehterçeşme
    - Pınar
    - Saadetdere
    - Talatpaşa
- Ankara, İzmir ve Kocaeli ilçe/mahalle seçimleri: `KARAR VERİLDİ`
  - Ankara:
    - Çankaya:
      - Kızılay
      - Kavaklıdere
      - Çukurambar
      - Söğütözü
      - Bahçelievler
    - Yenimahalle:
      - Ostim
      - İvedikköy
      - Serhat
      - Macun
      - Ergazi
    - Etimesgut:
      - Eryaman
      - Bağlıca
      - Elvan
      - Süvari
      - Yapracık
  - İzmir:
    - Konak:
      - Alsancak
      - Göztepe
      - Güzelyalı
      - Kültür
      - İsmet Kaptan
    - Bornova:
      - Kazımdirik
      - Erzene
      - Evka 3
      - Atatürk
      - Yeşilova
    - Karşıyaka:
      - Bostanlı
      - Mavişehir
      - Yalı
      - Alaybey
      - Şemikler
  - Kocaeli:
    - İzmit:
      - Yenişehir
      - Yahyakaptan
      - Alikahya Atatürk
      - Yeşilova
      - Sanayi
    - Gebze:
      - Arapçeşme
      - Osman Yılmaz
      - Barış
      - Tatlıkuyu
      - İstasyon
    - Körfez:
      - Güney
      - Mimar Sinan
      - Yukarı Hereke
      - Kirazlıyalı
      - Hacı Osman
  - İdari isim düzeltmeleri:
    - `Ostim OSB` ve `İvedik OSB` ayrı mahalle gibi kullanılmayacak.
    - Bu sanayi profilleri ilgili mahallelerin metadata/profile bilgisinde temsil
      edilebilir.
    - Genel `Alikahya` adı kullanılmayacak; resmî mahalle adı `Alikahya Atatürk`
      olacak.
    - `Yarımca`, `Tütünçiftlik` ve genel `Hereke` mahalle adı olarak kullanılmayacak.
    - Bu profiller Körfez içindeki onaylı mahallelerin metadata/profile bilgisinde
      temsil edilebilir.
- İlçe seçim stratejisi ne olacak?
- Bölge profilleri nasıl tanımlanacak?
  - merkez
  - yoğun yerleşim
  - düşük yoğunluk
  - kurumsal bölge
  - karma bölge
- Şehir/ilçe yoğunluğuna göre müşteri ve cihaz dağılımı nasıl değişecek?
- İlçe altyapı profil etiketleri: `KARAR VERİLDİ`
  - Bu seviyeler henüz yüzde veya adet değildir; yalnızca göreli profil etiketleridir.
  - İstanbul / Maltepe:
    - Mevcut regression datası aynen korunur.
    - GPON: orta-yüksek
    - Noktadan noktaya fiber: düşük-orta
    - VDSL: orta
    - ADSL: düşük
    - Kapasite baskısı: orta
    - Yedeklilik ihtiyacı: orta
  - İstanbul / Şişli:
    - GPON: yüksek
    - Noktadan noktaya fiber / Metro Ethernet: yüksek
    - VDSL: düşük-orta
    - ADSL: çok düşük
    - Müşteri sayısından ziyade trafik ve servis yoğunluğu çok yüksek kabul edilir.
    - Kapasite baskısı: yüksek
    - Yedeklilik ve SLA ihtiyacı: çok yüksek
    - Metro Ethernet yalnız kurumsal/uygun ticari aboneliklerde kullanılır.
  - İstanbul / Esenyurt:
    - GPON: orta-yüksek
    - VDSL: yüksek
    - ADSL: düşük-orta
    - Metro Ethernet: çok düşük, yalnız sınırlı SME/enterprise
    - Müşteri yoğunluğu: çok yüksek
    - Kapasite baskısı: çok yüksek
    - Yedeklilik ihtiyacı: düşük-orta
    - Ana özelliği toplu müşteri etkisi ve port doluluğudur.
  - Ankara / Çankaya:
    - GPON: yüksek
    - Noktadan noktaya fiber / Metro Ethernet: yüksek
    - VDSL: orta
    - ADSL: çok düşük
    - Kamu/enterprise/SLA yoğunluğu: yüksek
    - Kapasite baskısı: orta-yüksek
    - Yedeklilik ihtiyacı: çok yüksek
  - Ankara / Yenimahalle:
    - GPON: orta
    - Noktadan noktaya fiber / Metro Ethernet: orta-yüksek, özellikle sanayi profilli
      mahallelerde
    - VDSL: orta
    - ADSL: düşük
    - Kapasite baskısı: yüksek
    - Yedeklilik ihtiyacı: yüksek
  - Ankara / Etimesgut:
    - GPON: yüksek
    - VDSL: düşük-orta
    - ADSL: çok düşük
    - Metro Ethernet: çok düşük, yalnız sınırlı kurumsal kullanım
    - Yeni yerleşim profili nedeniyle boş/rezerve kapasite diğer yoğun ilçelere göre
      daha yüksek olur.
    - Kapasite baskısı: orta
    - Yedeklilik ihtiyacı: düşük-orta
  - İzmir / Konak:
    - GPON: orta
    - Noktadan noktaya fiber / Metro Ethernet: düşük-orta
    - VDSL: orta-yüksek
    - ADSL: düşük-orta
    - Eski ve yeni altyapı birlikte bulunur.
    - Kapasite baskısı: orta-yüksek
    - Yedeklilik ihtiyacı: orta-yüksek
  - İzmir / Bornova:
    - GPON: orta-yüksek
    - Noktadan noktaya fiber / Metro Ethernet: orta
    - VDSL: orta
    - ADSL: düşük
    - Üniversite, ticari ve konut profilleri birlikte temsil edilir.
    - Kapasite baskısı: yüksek
    - Yedeklilik ihtiyacı: orta-yüksek
  - İzmir / Karşıyaka:
    - GPON: yüksek
    - VDSL: düşük-orta
    - ADSL: çok düşük
    - Metro Ethernet: düşük
    - Kapasite baskısı: orta-yüksek
    - Yedeklilik ihtiyacı: orta
  - Kocaeli / İzmit:
    - GPON: orta-yüksek
    - Noktadan noktaya fiber / Metro Ethernet: orta
    - VDSL: orta
    - ADSL: düşük
    - Kapasite baskısı: orta-yüksek
    - Yedeklilik ihtiyacı: yüksek
  - Kocaeli / Gebze:
    - GPON: orta-yüksek
    - Noktadan noktaya fiber / Metro Ethernet: çok yüksek
    - VDSL: düşük
    - ADSL: çok düşük
    - Enterprise/SME yoğunluğu ve kritik servis ihtiyacı yüksek olur.
    - Kapasite baskısı: yüksek
    - Yedeklilik ihtiyacı: çok yüksek
  - Kocaeli / Körfez:
    - Konut alanlarında GPON: orta
    - Kritik işletmelerde noktadan noktaya fiber / Metro Ethernet: çok yüksek
    - VDSL: düşük-orta
    - ADSL: çok düşük
    - Kapasite baskısı: orta-yüksek
    - Yedeklilik ve iş sürekliliği ihtiyacı: çok yüksek
- Altyapı profili genel kuralları: `KARAR VERİLDİ`
  - GPON erişim teknolojisi, Metro Ethernet ise kurumsal/özel erişim profili olarak
    ayrı değerlendirilir.
  - Metro Ethernet konut müşterilerine rastgele dağıtılmaz.
  - ADSL bütün ilçelerde küçük bir legacy katman olarak kalır; ana teknoloji yapılmaz.
  - Kritik/yedekli profil kararı şimdilik tasarım gereksinimi olarak kaydedilir.
  - NetworkLink modeline hemen alan veya migration eklenmez.
  - Bu profiller gerçek Turkcell altyapısı iddiası taşımayan sentetik simülasyon
    kararlarıdır.
  - Mevcut Maltepe regression datasının sayıları henüz değiştirilmez.
- Farklı BNG dalları, OLT/DSLAM kapasiteleri, port dolulukları ve yedek kapasite
  oranları nasıl belirlenecek?
- Yedek bağlantı ve alternatif topoloji senaryoları bu fazda nasıl ele alınacak?
- Arayüz yapılacakları: `KARAR NOTU`
  - Şehir, ilçe ve cihazların gösterileceği coğrafi harita.
  - BNG, OLT, DSLAM ve access node için mantıksal topoloji görünümü.
  - Alarm ve kesintilerin zaman çizelgesi veya canlı simülasyon şeklinde gösterimi.
  - Cihaza tıklanınca alarm, kesinti, müşteri etkisi ve topoloji detaylarının açılması.
  - Daha sonra kullanıcının sağlayabileceği koordinatların sisteme eklenebilmesi.
  - Şimdilik koordinat modeli veya migration oluşturulmayacak.
  - Koordinat konusu arayüz/coğrafya karar kapısında ayrıca ele alınacak.

### 8.3 Alarm Kataloğu ve Olay Senaryoları

Durum: `KARAR VERİLDİ`

- Model yaklaşımı: `KARAR VERİLDİ`
  - Kontrollü A+ genişletmesi seçildi.
  - Mevcut `AlarmType`, `Alarm`, `Incident`, `IncidentAlarm`, `Outage`,
    `OperationalEvent` ve `QualityMeasurement` modelleri korunur.
  - Kapsamlı event-sourcing refactor yapılmaz.
  - Gerekli structured alanlar ve küçük `MaintenanceWindow` modeli eklenir.
  - Kritik domain bilgileri serbest metadata içine gizlenmez.
- Alarm katalogu: `KARAR VERİLDİ`
  - Büyük gerçekçi dataset için tam 30 sentetik alarm tipi planlanır.
  - Bunlar gerçek kurum alarm kodu veya gizli veri değildir.
  - Mevcut Maltepe 3 alarm tipi minimal regression katalogu olarak korunur:
    - `BNG_UNREACHABLE`
    - `ACCESS_DEVICE_UNREACHABLE`
    - `LINK_DOWN`
  - Birleştirilen alarm kararları:
    - `CPU_HIGH` + `MEMORY_HIGH` -> `DEVICE_RESOURCE_HIGH`
    - `LINE_ATTENUATION_HIGH` + `SNR_LOW` -> `DSL_LINE_QUALITY_DEGRADED`
    - `BATTERY_ON_DISCHARGE` + `LOW_BATTERY_CAPACITY` -> `BACKUP_POWER_DEGRADED`
  - Katalogdan çıkarılan ham olmayan alarm kararları:
    - `METRO_SERVICE_DEGRADED`
    - `WIDESPREAD_QUALITY_DEGRADATION`
  - Nihai 30 alarm kodu:
    - `BNG_UNREACHABLE`
    - `METRO_AGG_UNREACHABLE`
    - `OLT_UNREACHABLE`
    - `DSLAM_UNREACHABLE`
    - `ACCESS_NODE_UNREACHABLE`
    - `UPLINK_DOWN`
    - `FIBER_CUT_SUSPECTED`
    - `LINK_PACKET_LOSS_HIGH`
    - `LINK_FLAPPING`
    - `BACKUP_LINK_UNAVAILABLE`
    - `PON_PORT_DOWN`
    - `OPTICAL_SIGNAL_LOW`
    - `OPTICAL_SIGNAL_LOSS`
    - `ONT_DISCONNECT_SURGE`
    - `PON_CAPACITY_THRESHOLD`
    - `DSL_PORT_DOWN`
    - `DSL_LINE_QUALITY_DEGRADED`
    - `DSL_RETRAIN_FREQUENT`
    - `DSLAM_PORT_SATURATION`
    - `DEDICATED_PORT_DOWN`
    - `SLA_LATENCY_BREACH`
    - `SLA_PACKET_LOSS_BREACH`
    - `PRIMARY_PATH_DOWN`
    - `FAILOVER_UNSUCCESSFUL`
    - `COMMERCIAL_POWER_LOSS`
    - `BACKUP_POWER_DEGRADED`
    - `HIGH_TEMPERATURE`
    - `COOLING_FAILURE`
    - `DEVICE_RESOURCE_HIGH`
    - `BANDWIDTH_UTIL_HIGH`
- Severity ve servis etkisi: `KARAR VERİLDİ`
  - Severity değerleri:
    - `critical`
    - `major`
    - `minor`
    - `warning`
    - `info`
  - Service impact class değerleri:
    - `full_outage`
    - `partial_outage`
    - `short_interruption`
    - `degradation`
    - `protection_loss`
    - `no_direct_customer_impact`
    - `unknown`
  - Severity ile müşteri etkisi aynı kavram değildir.
- Alarm lifecycle: `KARAR VERİLDİ`
  - `Alarm.status` yalnız şu değerleri taşır:
    - `open`
    - `cleared`
    - `suppressed`
  - `acknowledged`, status değildir; `acknowledged_at` ile tutulur.
  - `correlated`, status değildir; `IncidentAlarm.role` ve correlation evidence ile temsil edilir.
  - `detected_at`, alarmın kaynakta gerçekleştiği/event zamanıdır; aynı anlamda yeni
    `event_time` alanı eklenmez.
  - Ek zaman ve lifecycle alanları:
    - `received_at`
    - `acknowledged_at`
    - `last_seen_at`
    - `occurrence_count`
    - `deduplication_key`
    - `suppression_reason`
    - `recurrence_group_key`
- Alarm kaynağı: `KARAR VERİLDİ`
  - `AlarmType` birden fazla `allowed_source_kinds` ve `supported_device_types`
    taşıyabilir.
  - Bir gerçek `Alarm` kaydı tam olarak bir structured source taşır:
    - `device`
    - `network_link`
    - `network_port`
    - `line_connection`
    - `failure_domain`
    - `subscription_connection`
  - Kaynak port/line/subscription_connection ise bağlı cihaz ve üst topoloji servis
    tarafından türetilir; aynı bilgi gereksiz FK olarak tekrar edilmez.
- Deduplication ve flapping: `KARAR VERİLDİ`
  - Açık alarm tekilliği `data_snapshot + alarm_type + deduplication_key` üzerinden
    korunur.
  - Aynı açık alarm tekrar gelirse yeni kayıt açmak yerine `last_seen_at` güncellenir
    ve `occurrence_count` artar.
  - Clear sonrası tekrar açılan kayıtlar ayrı alarm olabilir; aynı tekrar ailesi
    `recurrence_group_key` ile bağlanabilir.
- Incident ve Outage ayrımı: `KARAR VERİLDİ`
  - `Incident` alanları:
    - `incident_type`
    - `service_impact_class`
    - `correlation_method`
    - `failover_result`
    - `transition_duration_seconds`
    - `restored_at`
  - `IncidentType` değerleri:
    - `network_outage`
    - `service_degradation`
    - `protection_event`
    - `intermittent`
    - `planned_maintenance`
    - `unknown`
  - `FailoverResult` değerleri:
    - `hitless`
    - `near_hitless`
    - `short_interruption`
    - `degraded`
    - `failed`
    - `unknown`
  - `Outage` yalnız gerçek hizmet erişilebilirliği kaybında oluşturulur:
    - `full_outage`
    - `partial_outage`
    - `short_interruption`
  - Sadece `degradation`, `protection_loss` veya `no_direct_customer_impact` için
    Outage kaydı oluşturulmaz.
- Quality measurement kaynakları: `KARAR VERİLDİ`
  - `QualityMeasurement` geriye uyumlu şekilde genişletilir.
  - Tam olarak bir kaynak seçilir:
    - `device`
    - `network_link`
    - `line_connection`
    - `subscription_connection`
  - Structured metrikler:
    - `latency_ms`
    - `jitter_ms`
    - `packet_loss_percent`
    - `availability_percent`
    - `bandwidth_utilization_percent`
- Planlı bakım: `KARAR VERİLDİ`
  - Küçük structured `MaintenanceWindow` modeli eklenir.
  - Bakım kapsamı structured device ve NetworkLink ilişkileriyle tutulur.
  - Bakım normal tamamlanırsa planned maintenance olarak kalır.
  - Bakım süresi aşılır veya beklenmeyen müşteri etkisi oluşursa mevcut plan kaydı
    plansız olaya dönüştürülmez; MaintenanceWindow'a bağlı ayrı unplanned Incident
    oluşturulur.
- Korelasyon ve root cause: `KARAR VERİLDİ`
  - LLM kullanılmaz; korelasyon deterministik kalır.
  - Skor alanları:
    - zaman yakınlığı: 0-30
    - topoloji/failure-domain ilişkisi: 0-35
    - alarm family uyumu: 0-25
    - severity/root-candidate: 0-10
  - Eşikler:
    - 70 ve üzeri: strong
    - 50-69: candidate
    - 50 altı: unrelated/noise
  - Mevcut Maltepe davranışı ve ground truth sonucu değişmez.
- Olay senaryoları: `KARAR VERİLDİ`
  - Büyük dataset için 22 config-driven senaryo şablonu tanımlanır.
  - `SCN-NOISE-001` alarm üretir ancak tek başına Incident oluşturmaz.
  - `SCN-ACCESS-NODE-001` büyük dataset içinde İstanbul / Şişli olarak sabitlenir.
  - Planned maintenance overrun, MaintenanceWindow'a bağlı ayrı unplanned Incident
    oluşturur.
  - Başarılı failover senaryolarında full outage oluşturulmaz.
  - Büyük dataset bu aşamada seedlenmez; senaryolar 039.5.6 aşamasında kullanılacaktır.
- Kesin veri hacmi hedefleri: `KARAR VERİLDİ`
  - AlarmType: 30
  - Alarm: 2.100
  - cleared alarm: 1.680
  - open alarm: 210
  - suppressed alarm: 210
  - açık alarmların yaklaşık 105 tanesi acknowledged
  - Incident: 210
  - Outage: 78
  - degradation sınıflı incident: yaklaşık 60
  - protection-loss incident: yaklaşık 22
  - MaintenanceWindow: 30
  - OperationalEvent: 900
  - QualityMeasurement: 12.000
  - timeline: 60 gün
  - yoğun olay günü: 9
  - planlı bakım yoğun günü: 3
  - recurring/flapping günü: 4
  - 039.5.6 seed aşamasında küçük deterministik yuvarlama farkı oluşursa nedeni raporlanır.

### 8.4 Müşteri, Paket, SLA, Ödeme ve Kampanya Dağılımları

Durum: `KARAR VERİLDİ`

- Dataset ayrımı: `KARAR VERİLDİ`
  - Mevcut 225 müşteri / 240 abonelik içeren Maltepe dataset'i regression dataset'i
    olarak aynen korunur.
  - Yeni gerçekçi çok şehirli dataset ayrı oluşturulur:
    - ayrı DatasetVersion
    - ayrı DataSnapshot
    - ayrı generator version
    - ayrı deterministik kod alanı
  - Yeni gerçekçi dataset içinde Maltepe ayrıca genişletilmiş biçimde bulunur.
  - Mevcut regression kayıtları büyütülmez ve regression test sayıları değiştirilmez.
  - Küçük Maltepe regression dataset'i normal testlerde kullanılmaya devam eder.
  - 14.400 müşterilik dataset her unit testte yeniden seedlenmez.
  - Büyük dataset için ayrı acceptance/smoke test profili planlanır.
  - Seed süresi ve servis performansı ölçülür.
  - Cihaz sayıları henüz belirlenmez; abonelik teknolojileri, port kapasitesi ve
    yedeklilik kararlarından sonra türetilir.
- Temel ölçek: `KARAR VERİLDİ`
  - Seçilen ölçek: B - dengeli simülasyon.
  - Yeni gerçekçi çok şehirli dataset:
    - 14.400 müşteri.
    - 16.200 abonelik.
  - C seçeneğine çıkılmaz.
  - Gerçekçilik yalnız satır sayısıyla değil; ilçe, müşteri, teknoloji, ödeme,
    kampanya, alarm ve olay çeşitliliğiyle sağlanır.
- İlçe bazında kesin ölçek: `KARAR VERİLDİ`
  - İstanbul:
    - Maltepe: 1.400 müşteri / 1.550 abonelik.
    - Şişli: 1.100 müşteri / 1.320 abonelik.
    - Esenyurt: 2.200 müşteri / 2.350 abonelik.
  - Ankara:
    - Çankaya: 1.400 müşteri / 1.650 abonelik.
    - Yenimahalle: 1.100 müşteri / 1.260 abonelik.
    - Etimesgut: 1.000 müşteri / 1.080 abonelik.
  - İzmir:
    - Konak: 1.000 müşteri / 1.100 abonelik.
    - Bornova: 1.100 müşteri / 1.230 abonelik.
    - Karşıyaka: 900 müşteri / 990 abonelik.
  - Kocaeli:
    - İzmit: 1.000 müşteri / 1.110 abonelik.
    - Gebze: 1.300 müşteri / 1.500 abonelik.
    - Körfez: 900 müşteri / 1.060 abonelik.
  - Toplam:
    - 14.400 müşteri.
    - 16.200 abonelik.
- Müşteri segment dağılımları: `KARAR VERİLDİ`
  - Sıralama: individual / SME / enterprise / public.
  - Maltepe: %78 / %15 / %5 / %2.
  - Şişli: %35 / %35 / %25 / %5.
  - Esenyurt: %88 / %10 / %1,5 / %0,5.
  - Çankaya: %50 / %22 / %18 / %10.
  - Yenimahalle: %55 / %32 / %10 / %3.
  - Etimesgut: %82 / %13 / %3 / %2.
  - Konak: %68 / %24 / %6 / %2.
  - Bornova: %72 / %20 / %5 / %3.
  - Karşıyaka: %82 / %14 / %3 / %1.
  - İzmit: %60 / %27 / %10 / %3.
  - Gebze: %35 / %38 / %25 / %2.
  - Körfez: %45 / %32 / %20 / %3.
  - Yuvarlama deterministik olur ve her ilçenin toplamı kesin müşteri sayısına
    eşitlenir.
- Priority dağılımları: `KARAR VERİLDİ`
  - VIP nadir ve anlamlı bir öncelik etiketi olarak kalır.
  - Maltepe: %5.
  - Şişli: %9.
  - Esenyurt: %3.
  - Çankaya: %9.
  - Yenimahalle: %6.
  - Etimesgut: %4.
  - Konak: %5.
  - Bornova: %5.
  - Karşıyaka: %6.
  - İzmit: %6.
  - Gebze: %8.
  - Körfez: %8.
  - Toplam yaklaşık 862 VIP müşteri oluşur.
  - VIP müşteriler yalnız enterprise/public içinde bulunmaz; bütün segmentlerde
    bulunabilir.
  - Enterprise, public ve kritik SME profillerinde VIP ağırlığı daha yüksek olabilir.
  - VIP şimdilik telafi davranışını değiştirmez.
- Abonelik durumu ve olay zamanı geçerliliği: `KARAR VERİLDİ`
  - "Olay tarihinde geçersiz" bir subscription status olarak kullanılmaz.
  - Güncel abonelik durumu ile olay zamanındaki geçerlilik ayrı kavramlardır.
  - Güncel abonelik durumu:
    - active
    - suspended
    - terminated/cancelled veya mevcut modeldeki eşdeğeri
  - Genel hedef:
    - active: yaklaşık %93-95.
    - suspended: yaklaşık %2-4.
    - kapalı/geçmiş kayıt: yaklaşık %2-4.
  - İlçe profiline göre küçük farklar olabilir ancak toplamlar açıkça raporlanır.
  - Olay zamanındaki geçerlilik `valid_from`, `valid_to`, SubscriptionConnection tarih
    aralığı ve LineConnection tarih aralığı üzerinden değerlendirilir.
  - Belirli test olaylarında aboneliklerin küçük bir kısmı zaman aralığı çakışmadığı
    için etkisiz kalabilir.
  - Bu durum güncel status yüzdesine karıştırılmaz.
- Çok abonelikli müşteri oranı: `KARAR VERİLDİ`
  - İlçe bazlı rastgele yüzde uygulanmaz.
  - Çok abonelik ihtimali segmentle ilişkili olur:
    - individual: düşük.
    - SME: orta.
    - enterprise: yüksek.
    - public: orta-yüksek.
  - Sonuç, kesin toplamlar olan 14.400 müşteri ve 16.200 aboneliği sağlamalıdır.
  - Aynı müşterinin abonelikleri farklı hizmet noktalarında ve uygun senaryolarda
    farklı teknolojilerde olabilir.
- Teknoloji kavram ayrımı: `KARAR VERİLDİ`
  - GPON erişim/hat teknolojisidir.
  - Genel noktadan noktaya fiber erişim/hat teknolojisidir.
  - Metro Ethernet kurumsal hizmet/erişim profilidir.
  - ServicePackage technology ve LineConnection technology ayrı kavramlar olarak
    değerlendirilir.
  - Mevcut uyumluluk yaklaşımı korunur.
  - Metro Ethernet GPON/OLT müşteri hattı gibi zorla mevcut zincire sokulmaz.
  - Model eksikliği varsa seed yazmadan önce gap olarak raporlanır.
- Fiziksel erişim dağılımı: `KARAR VERİLDİ`
  - Metro Ethernet, GPON/P2P fiber/VDSL/ADSL ile aynı seviyede birbirini dışlayan
    beşinci fiziksel teknoloji olarak sayılmaz.
  - Metro Ethernet, P2P/dedicated fiber erişim üzerinden sunulan kurumsal hizmet
    profili olarak ele alınır.
  - Metro Ethernet abonelikleri P2P fiber hatların alt kümesi olur ve toplam abonelik
    hesabına ikinci kez eklenmez.
  - Fiziksel erişim sırası: GPON / P2P fiber / VDSL / ADSL.
  - Maltepe, 1.550 abonelik:
    - %48 / %8 / %38 / %6.
    - 744 / 124 / 589 / 93.
  - Şişli, 1.320 abonelik:
    - %50 / %22 / %26 / %2.
    - 660 / 290 / 343 / 27.
  - Esenyurt, 2.350 abonelik:
    - %46 / %4 / %44 / %6.
    - 1.081 / 94 / 1.034 / 141.
  - Çankaya, 1.650 abonelik:
    - %52 / %18 / %28 / %2.
    - 858 / 297 / 462 / 33.
  - Yenimahalle, 1.260 abonelik:
    - %42 / %14 / %39 / %5.
    - 529 / 177 / 491 / 63.
  - Etimesgut, 1.080 abonelik:
    - %62 / %5 / %31 / %2.
    - 670 / 54 / 335 / 21.
  - Konak, 1.100 abonelik:
    - %36 / %8 / %46 / %10.
    - 396 / 88 / 506 / 110.
  - Bornova, 1.230 abonelik:
    - %45 / %10 / %40 / %5.
    - 554 / 123 / 492 / 61.
  - Karşıyaka, 990 abonelik:
    - %60 / %6 / %32 / %2.
    - 594 / 59 / 317 / 20.
  - İzmit, 1.110 abonelik:
    - %44 / %10 / %41 / %5.
    - 488 / 111 / 455 / 56.
  - Gebze, 1.500 abonelik:
    - %40 / %24 / %34 / %2.
    - 600 / 360 / 510 / 30.
  - Körfez, 1.060 abonelik:
    - %38 / %25 / %34 / %3.
    - 403 / 265 / 360 / 32.
  - Toplam fiziksel erişim:
    - GPON: 7.577.
    - P2P fiber: 2.042.
    - VDSL: 5.894.
    - ADSL: 687.
    - Genel toplam: 16.200.
  - Yaklaşık genel oran:
    - GPON: %46,8.
    - P2P fiber: %12,6.
    - VDSL: %36,4.
    - ADSL: %4,2.
- Metro Ethernet hizmet profili: `KARAR VERİLDİ`
  - Metro Ethernet, P2P fiber aboneliklerinin alt kümesidir.
  - İlçe bazında Metro Ethernet hizmet profili sayıları:
    - Maltepe: 0.
    - Şişli: 106.
    - Esenyurt: 5.
    - Çankaya: 116.
    - Yenimahalle: 38.
    - Etimesgut: 5.
    - Konak: 11.
    - Bornova: 18.
    - Karşıyaka: 5.
    - İzmit: 22.
    - Gebze: 120.
    - Körfez: 74.
  - Toplam Metro Ethernet hizmeti:
    - 520 abonelik.
    - toplam aboneliklerin yaklaşık %3,2'si.
    - fiziksel olarak P2P fiber toplamının içinde.
  - Dağıtım kuralları:
    - individual: Metro Ethernet yok.
    - enterprise: ana hedef.
    - public: kritik/kamu profillerinde.
    - SME: yalnız seçili kritik, ticari veya sanayi müşterilerinde.
    - Metro Ethernet rastgele konut aboneliğine verilmez.
    - Her Metro Ethernet aboneliğinin fiziksel hattı P2P fiber olur.
- Model gap karar kapısı: `KARAR VERİLDİ`
  - Seçilen tasarım: Seçenek B - tam temizlik.
  - AccessTechnology yalnız fiziksel erişim teknolojilerini içerir:
    - gpon.
    - fiber.
    - vdsl.
    - adsl.
  - ServiceType ayrı hizmet tipi olarak ServicePackage üzerinde tutulur:
    - broadband.
    - metro_ethernet.
  - ServicePackage.service_type kullanılır; Subscription üzerine service_type eklenmez.
  - Mevcut paketler migration sonucunda broadband olarak korunur.
  - Metro Ethernet paketi:
    - ServicePackage.technology = fiber.
    - ServicePackage.service_type = metro_ethernet.
    - LineConnection.technology = fiber.
  - Uyumluluk:
    - broadband + fiber paket -> fiber veya gpon hat.
    - metro_ethernet paket -> yalnız fiber hat.
    - vdsl paket -> yalnız vdsl hat.
    - adsl paket -> yalnız adsl hat.
  - Metro Ethernet segment uygunluğu seed/servis tasarımında ayrıca doğrulanır:
    - individual: uygun değil.
    - enterprise/public: uygun.
    - SME: yalnız seçili kurumsal veya kritik profillerde uygun.
  - SLAProfile, büyük seed veya cihaz/port hesaplaması bu karar sırasında uygulanmadı;
    sonraki karar kapılarında ele alınacak.
- Metro Ethernet primary/backup topoloji kararı: `KARAR VERİLDİ`
  - SubscriptionConnection üzerinde connection_role kullanılır:
    - primary.
    - backup.
  - Mevcut kayıtlar migration ile primary yapılır.
  - Aynı Subscription için aynı role değerinde yalnız bir açık aktif bağlantı bulunur.
  - Aynı Subscription için en fazla bir açık primary ve bir açık backup desteklenir.
  - LineConnection üzerindeki tek aktif abonelik bağlantısı constraint'i korunur.
  - Backup bağlantısı açıkken overlapping aktif primary bulunması deterministic
    validation katmanında zorunlu tutulur.
  - NetworkDevice üzerinde access_role kullanılır:
    - standard_access.
    - corporate_fiber_aggregation.
  - access_role yalnız ACCESS_NODE cihazlarda dolu olabilir.
  - ACCESS_NODE cihazlarda access_role zorunludur; diğer cihazlarda null kalır.
  - Mevcut Maltepe access node kayıtları standard_access olarak korunur.
  - Metro Ethernet zinciri:
    - BNG.
    - NetworkLink.
    - corporate_fiber_aggregation ACCESS_NODE.
    - dedicated NetworkPort.
    - LineConnection(technology=fiber).
    - SubscriptionConnection(primary veya backup).
    - Subscription.
    - ServicePackage(service_type=metro_ethernet, technology=fiber).
  - NetworkLink üzerine primary/backup veya failover role alanı eklenmedi.
  - Primary/backup rolünün yol/abonelik bağlantısına ait olduğu kabul edildi.
  - CustomerImpactService failover-aware hale getirildi:
    - yalnız primary varsa ve yolu etkilenmişse impacted.
    - primary sağlamsa backup etkilenmiş olsa bile impacted değil.
    - primary etkilenmiş, backup sağlamsa full outage değil ve protected sayılır.
    - primary ve backup birlikte etkilenmişse impacted.
    - aynı abonelik iki bağlantı yüzünden iki kez sayılmaz.
  - Sonuç sözleşmesine geriye uyumlu alanlar eklendi:
    - failover_protected_subscription_codes.
    - failover_protected_subscription_count.
    - failover_warnings.
  - Warning/error ayrımı:
    - Aynı role için çakışık açık bağlantı, backup without primary, standard access node
      üzerinden Metro Ethernet ve dedicated port ihlali validation error'dur.
    - Primary ve backup'ın aynı access node veya aynı upstream link'i paylaşması şimdilik
      validator/impact warning seviyesindedir.
- Çok şehirli topoloji ve kapasite kapanışı: `KARAR VERİLDİ`
  - Büyük gerçekçi dataset, küçük Maltepe regression dataset'inden ayrı olacaktır.
  - Küçük Maltepe regression dataset'inin doğrudan BNG -> erişim cihazı bağlantıları
    geriye uyumluluk için korunur.
  - Büyük gerçekçi dataset'in temel zinciri:
    - BNG.
    - metro aggregation.
    - OLT / DSLAM / ACCESS_NODE.
    - müşteri erişim hattı.
  - Onaylanan cihaz kapasite tabanı:
    - BNG: 8.
    - metro aggregation: 16.
    - OLT: 32.
    - DSLAM: 95.
    - standard_access node: 51.
    - corporate_fiber_aggregation node: 33.
    - toplam cihaz: 235.
  - Onaylanan servis erişim port kapasitesi:
    - aktif PON portu: 322.
    - toplam PON port kapasitesi: 512.
    - aktif DSL portu: 6.581.
    - toplam DSL port kapasitesi: 9.120.
    - dedicated fiber primary portu: 2.042.
    - backup için ayrılan dedicated port kapasitesi: en fazla 261.
    - toplam planlanan dedicated fiber kullanılan kapasite: en fazla 2.303.
  - 13.664 değeri toplam fiziksel port kapasitesi olarak adlandırılmayacak; doğru
    adlandırma toplam servis erişim port kapasitesidir.
  - Yaklaşık NetworkLink planı:
    - BNG -> metro aggregation primary link: 16.
    - metro aggregation -> erişim cihazı primary link: 211.
    - kritik corporate yollar için alternatif erişim/aggregation link kapasitesi:
      yaklaşık 18.
    - toplam yaklaşık 245 NetworkLink.
  - 1:64 GPON fan-out ana dataset'te kullanılmayacak; stres senaryosu olarak bekleyen
    kapsama yazıldı.
  - Metro Ethernet backup için 261 sayısı aktif backup SubscriptionConnection sayısı
    değil, provisioned backup port kapasitesidir.
  - Gerçek backup bağlantı sayısı SLA, paket, müşteri segmenti ve kritik hizmet
    profili kararlarıyla kesinleşecektir.
- Minimum failure-domain modeli: `KARAR VERİLDİ`
  - Kapsamlı SRLG/risk-group modeli şimdilik seçilmedi.
  - FailureDomain alanları:
    - data_snapshot.
    - code.
    - name.
    - domain_type:
      - site.
      - power_zone.
      - fiber_route.
    - description.
  - Açık üyelik modelleri:
    - DeviceFailureDomainMembership.
    - NetworkLinkFailureDomainMembership.
    - LineConnectionFailureDomainMembership.
  - Bir cihaz, link veya hat birden fazla failure domain'e üye olabilir.
  - Duplicate membership unique constraint ile engellenir.
  - Snapshot tutarlılığı deterministic validation/model clean katmanında kontrol edilir.
  - GenericForeignKey kullanılmaz.
  - Failure-domain bilgisi metadata string alanlarına gömülmez.
  - NetworkPort için şimdilik ayrı membership tablosu oluşturulmaz.
  - access_node ve upstream_link, FailureDomain.domain_type yapılmaz; doğrudan
    topolojiden karşılaştırılır.
- Path-diversity değerlendirmesi: `KARAR VERİLDİ`
  - Deterministic sınıflar:
    - fully_diverse.
    - partially_diverse.
    - shared_risk.
    - unknown.
  - Karşılaştırılan kanıtlar:
    - primary/backup access device.
    - metro aggregation node.
    - BNG dalı.
    - upstream NetworkLink'ler.
    - ortak site domain'i.
    - ortak power_zone domain'i.
    - ortak fiber_route domain'i.
    - eksik failure-domain verisi.
  - Ortak site, power_zone veya fiber_route varsa shared_risk döner.
  - Aynı access node, aggregation node, upstream link veya BNG dalı tam çeşitlilik
    sayılmaz.
  - Failure-domain kayıtları eksikse sistem yanlış şekilde fully_diverse demez;
    unknown veya partially_diverse üretir.
  - Şimdilik bütün backup bağlantılarının fully_diverse olması zorunlu değildir.
  - SLA modeli geldiğinde gereken çeşitlilik seviyesi pakete göre doğrulanacaktır.
  - CustomerImpactService mevcut failover davranışını korur; path-diversity sonucunu
    geriye uyumlu warning/evidence olarak kullanabilir.
- Kapsam dışı/kalan kararlar:
  - Failover geçiş süresi ve kısa degradation hesabı alarm/olay senaryolarında ele
    alınacak.
  - Büyük dataset seed'i henüz oluşturulmayacak.
  - Gerçek backup SubscriptionConnection sayısı SLA/paket aşamasında kesinleşecek.
  - Kapsamlı SRLG modeli post-MVP/ileri kurumsal SLA kapsamına bırakıldı.
- 039.5.4 ticari/SLA model kararları: `KARAR VERİLDİ`
  - Seçilen yaklaşım kontrollü A+ genişletmesidir.
  - Kapsamlı ProductCatalog, BillingAccount, Invoice veya CRM/faturalama domain'i
    kurulmaz.
  - Eklenen/planlanan structured modeller ve alanlar:
    - `SLAProfile`.
    - `ServicePackage.default_sla_profile`.
    - `Subscription.sla_profile`.
    - `ServicePackagePriceVersion`.
    - `Campaign`.
    - `ServicePackageAllowedSegment`.
    - `CampaignAllowedSegment`.
    - `CampaignAllowedServiceType`.
    - `CampaignAllowedTechnology`.
    - PaymentRecord fatura dönemi ve tutar kırılımı.
    - CompensationHistory decision/settlement lifecycle ayrımı.
  - ServicePackage.default_sla_profile paket katalog varsayılanıdır.
  - Subscription.sla_profile müşterinin sözleşilmiş gerçek SLA profilidir.
  - Kural motoru ve müşteri etki servisleri gerektiğinde Subscription.sla_profile
    değerini esas alacaktır.
- Kesin müşteri/abonelik toplamları: `KARAR VERİLDİ`
  - Müşteri: 14.400.
  - Abonelik: 16.200.
  - Segment toplamları:
    - individual: 9.208.
    - SME: 3.243.
    - enterprise: 1.517.
    - public: 432.
  - Priority toplamları:
    - VIP: 862.
    - standard: 13.538.
  - Müşteri abonelik sayısı:
    - tek abonelikli: 12.830.
    - iki abonelikli: 1.340.
    - üç abonelikli: 230.
    - 4+ abonelikli müşteri v1 dataset'inde üretilmez.
  - Abonelik status toplamları:
    - active: 15.256.
    - suspended: 465.
    - cancelled: 306.
    - pending: 173.
- SubscriptionConnection sayıları: `KARAR VERİLDİ`
  - Reference datetime anındaki açık primary bağlantı:
    - active: 15.256.
    - suspended: 465.
    - toplam: 15.721.
  - Geçmişte kapanmış cancelled primary bağlantı: 306.
  - Toplam primary SubscriptionConnection kaydı: 16.027.
  - Pending abonelikler SubscriptionConnection taşımaz ve aktif fiziksel porta bağlanmaz.
  - Gerçek backup SubscriptionConnection sayısı: 208.
  - Toplam SubscriptionConnection kaydı: 16.235.
- Paket katalogu: `KARAR VERİLDİ`
  - Toplam 27 sentetik paket tanımlanır.
  - ADSL:
    - `ADSL-16-SYN`
    - `ADSL-24-SYN`
  - VDSL:
    - `VDSL-35-SYN`
    - `VDSL-50-SYN`
    - `VDSL-100-SYN`
    - `SME-VDSL-50-SYN`
    - `SME-VDSL-100-SYN`
    - `PUB-VDSL-50-SYN`
  - Fiber broadband:
    - `FIBER-100-SYN`
    - `FIBER-200-SYN`
    - `FIBER-500-SYN`
    - `FIBER-1000-SYN`
    - `FIBER-NC-100-SYN`
    - `SME-FIBER-100-SYN`
    - `SME-FIBER-300-SYN`
    - `SME-FIBER-500-SYN`
    - `ENT-FIBER-500-SYN`
    - `ENT-FIBER-1000-SYN`
    - `ENT-FIBER-2000-SYN`
    - `PUB-FIBER-200-SYN`
    - `PUB-FIBER-500-SYN`
    - `PUB-FIBER-1000-SYN`
  - Metro Ethernet:
    - `METRO-50-SYN`
    - `METRO-100-SYN`
    - `METRO-200-SYN`
    - `METRO-500-SYN`
    - `METRO-1000-SYN`
  - Paketler tamamen sentetiktir; gerçek kurum ürünü veya fiyatı iddiası taşımaz.
  - Metro Ethernet paketleri:
    - service_type = `metro_ethernet`.
    - technology = `fiber`.
    - yalnız SME, enterprise veya public segmentleri.
    - LineConnection.technology = `fiber`.
    - corporate_fiber_aggregation access node üzerinden bağlanır.
- SLA profilleri: `KARAR VERİLDİ`
  - Kesin 5 profil:
    - `best_effort`.
    - `business_standard`.
    - `business_plus`.
    - `mission_critical`.
    - `public_critical`.
  - Süre hedefleri dakika cinsinden structured saklanır.
  - Telafi oranı veya formülü SLAProfile içine konmaz; 039.5.5 iş kurallarında
    ayrıca belirlenecektir.
- Backup dağılımı: `KARAR VERİLDİ`
  - Gerçek backup sayısı: 208.
  - İlçe dağılımı:
    - Maltepe: 0.
    - Şişli: 46.
    - Esenyurt: 1.
    - Çankaya: 50.
    - Yenimahalle: 8.
    - Etimesgut: 1.
    - Konak: 2.
    - Bornova: 4.
    - Karşıyaka: 1.
    - İzmit: 7.
    - Gebze: 55.
    - Körfez: 33.
  - Segment dağılımı:
    - enterprise: 145.
    - public: 34.
    - kritik SME: 29.
    - individual: 0.
  - Actual path-diversity dağılımı:
    - fully_diverse: 112.
    - partially_diverse: 60.
    - shared_risk: 24.
    - unknown: 12.
  - Mission/public critical SLA'nın fully_diverse istemesine rağmen shared_risk veya
    unknown çıkan kayıtlar intentional SLA violation / realism senaryosu olarak
    işaretlenebilir; yanlışlıkla uygun kabul edilmez.
- Fiyat semantiği: `KARAR VERİLDİ`
  - ServicePackage.monthly_price güncel katalog liste fiyatıdır.
  - Subscription.monthly_price abonelik kurulurken sözleşilmiş recurring aylık ücrettir.
  - CampaignEnrollment dönemsel indirim hakkıdır; paket veya subscription fiyatını
    mutasyona uğratmaz.
  - PaymentRecord.billed_amount ilgili fatura döneminde gerçekten faturalanan toplamdır.
  - PaymentRecord.paid_amount tahsil edilen tutardır.
  - PaymentRecord.outstanding_amount kalan borçtur.
  - Tek seferlik ücretler monthly_price içine karıştırılmaz.
  - Paket fiyat geçmişi `ServicePackagePriceVersion` ile tutulur.
  - Hedef fiyat versiyonu kaydı: 72.
- PaymentRecord semantiği: `KARAR VERİLDİ`
  - PaymentRecord ham banka işlemi değil, bir aboneliğin bir fatura dönemindeki
    tahakkuk/tahsilat durumudur.
  - Structured alanlar:
    - billing_period_start.
    - billing_period_end.
    - due_date.
    - recurring_amount.
    - one_time_amount.
    - discount_amount.
    - billed_amount.
    - paid_amount.
    - outstanding_amount.
    - currency.
    - paid_at.
    - status.
  - Tutar denklemi:
    - billed_amount = recurring_amount + one_time_amount - discount_amount.
  - Vergi ve ayrıntılı invoice-line sistemi bu fazda modellenmez.
  - Kesin PaymentRecord hedefi: 59.600.
  - Status dağılımı:
    - paid_on_time: 48.000.
    - paid_late: 6.200.
    - overdue: 2.700.
    - partial: 1.500.
    - failed: 600.
    - reversed: 300.
    - voided: 300.
  - Timeline: Nisan-Temmuz 2026.
  - Pending abonelik ödeme kaydı üretmez.
  - Ödeme durumu 039.5.5'e kadar telafi uygunluğunu değiştirmez.
- Kampanya kararları: `KARAR VERİLDİ`
  - 10 sentetik Campaign kaydı:
    - `NEW_CUSTOMER_DISCOUNT`.
    - `COMMITMENT_12M`.
    - `FIBER_MIGRATION`.
    - `LOYALTY_RETENTION`.
    - `MULTI_SUBSCRIPTION`.
    - `SME_START`.
    - `ENTERPRISE_VOLUME`.
    - `PUBLIC_FRAMEWORK`.
    - `Q3_SEASONAL`.
    - `METRO_SLA_UPGRADE`.
  - CampaignEnrollment hedefi: 4.050.
  - Status dağılımı:
    - active: 2.650.
    - completed: 950.
    - cancelled: 200.
    - expired: 250.
  - Kampanya indirimi liste veya sözleşme fiyatını değiştirmez; fatura dönemindeki
    discount_amount hesabına yansır.
- CompensationHistory kararları: `KARAR VERİLDİ`
  - CompensationEvaluation motorun deterministik değerlendirme sonucudur.
  - CompensationHistory geçmişte kesinleşmiş karar ve settlement kaydıdır.
  - DecisionStatus:
    - approved.
    - rejected.
    - manual_review.
  - SettlementStatus:
    - not_applicable.
    - pending.
    - credited.
    - paid.
  - Toplam CompensationHistory hedefi: 1.100.
  - Decision dağılımı:
    - approved: 620.
    - rejected: 300.
    - manual_review: 180.
  - Approved 620 kayıt içindeki settlement dağılımı:
    - credited: 400.
    - paid: 140.
    - pending: 80.
  - Rejected ve manual_review kayıtlarında settlement_status = not_applicable olur.
  - Incident zorunlu, outage nullable olur.
  - Aynı subscription + incident + rule_version için duplicate final compensation
    engellenir.
  - 039.5.5'e kadar CompensationHistory yeni kararları etkilemez.
- Bu görevde büyük veri üretilmez:
  - 14.400 müşteri üretilmedi.
  - 16.200 abonelik üretilmedi.
  - 59.600 PaymentRecord üretilmedi.
  - 4.050 CampaignEnrollment üretilmedi.
  - 1.100 CompensationHistory üretilmedi.
  - Bunlar 039.5.6 büyük seed aşamasında oluşturulacaktır.

### 8.5 İş Kuralı Kataloğu

Durum: `KARAR VERİLDİ`

- `REFUND-001` yalnız teknik örnek olarak kalacaktır.
- Yeni büyük dataset kural seti:
  - RuleSet code: `SYN-COMP-2026`
  - version: 1
  - effective_from: `2026-07-01T00:00:00+03:00`
  - tamamen sentetik politika katalogudur; gerçek Turkcell veya operatör politikası
    iddiası taşımaz.
- Mimari karar:
  - Mevcut güvenli JSON `condition_tree` ve `action_config` korunur.
  - `eval`, Python script veya serbest çalıştırılabilir DSL kullanılmaz.
  - Kritik seçim alanları structured modellerde tutulur:
    - RuleSet
    - Rule.family
    - Rule.conflict_group
    - RuleVersion.priority
    - RuleVersion.action_type
    - RuleVersion.price_basis
    - RuleVersion.stackable
    - RuleVersion.active
    - RuleVersion.change_note
- SuspensionReason:
  - customer_request: otomatik telafi yok.
  - payment_related: otomatik telafi yok.
  - administrative: manual_review.
  - provider_fault: normal uygunluk değerlendirmesi.
  - unknown: manual_review.
  - Yalnız overdue/late/partial PaymentRecord bulunması telafiyi tek başına
    engellemez.
- Nihai 25 kural:
  1. `ELIG-SUBSCRIPTION-VALID`
  2. `ELIG-CUSTOMER-IMPACT-CONFIRMED`
  3. `EXCL-PENDING-CANCELLED`
  4. `EXCL-SUSPENSION-POLICY`
  5. `EXCL-PLANNED-MAINTENANCE-NORMAL`
  6. `EXCL-PROTECTION-LOSS-ONLY`
  7. `EXCL-DUPLICATE-COMPENSATION`
  8. `BB-FULL-OUTAGE-TIERED`
  9. `BB-PARTIAL-OUTAGE-PRORATED`
  10. `BB-DEGRADATION-QUALITY`
  11. `ME-SHORT-FAILOVER-INTERRUPTION`
  12. `ME-AVAILABILITY-BREACH`
  13. `ME-LATENCY-BREACH`
  14. `ME-JITTER-BREACH`
  15. `ME-PACKET-LOSS-BREACH`
  16. `ME-FAILED-FAILOVER`
  17. `ME-DEGRADED-FAILOVER`
  18. `MOD-GRADED-RESTORATION`
  19. `MOD-RECURRING-INCIDENT`
  20. `MOD-MAINTENANCE-OVERRUN`
  21. `MOD-RESTORATION-TARGET-BREACH`
  22. `SLA-PATH-DIVERSITY-BREACH`
  23. `SLA-BACKUP-MISSING`
  24. `MR-UNKNOWN-MISSING-EVIDENCE`
  25. `CAP-FLOOR-CONFLICT`
- PriceBasis:
  - `contracted_monthly_price`
  - `billed_recurring_amount`
  - `campaign_adjusted_recurring_amount`
  - `package_list_price`
  - Katalog v1 varsayılanı `contracted_monthly_price`.
  - Seçilen price basis yoksa fallback yapılmaz; sonuç `manual_review`.
- Para ve rounding:
  - currency: TRY.
  - Decimal.
  - iki ondalık.
  - ROUND_HALF_UP.
  - negatif tutar yasak.
  - gerçek billing period saniyesi kullanılır; sabit 30 gün varsayılmaz.
- Broadband full outage tier:
  - 0 <= süre < 30 dk: ineligible, 0 TRY.
  - 30 dk <= süre < 2 saat: basis x %2.
  - 2 saat <= süre < 6 saat: basis x %8.
  - 6 saat <= süre < 24 saat: basis x %20.
  - süre >= 24 saat: basis x %35.
  - minimum positive credit: 10 TRY.
  - incident cap: basis x %40.
- Partial outage:
  - amount = price_basis x affected_duration_seconds / billing_period_seconds x
    affected_capacity_ratio.
  - affected_capacity_ratio structured evidence'dan gelir; yoksa manual_review.
  - incident cap: basis x %25.
- Degradation:
  - QualityMeasurement ve SLA threshold üzerinden mild/moderate/severe türetilir.
  - rate: %2 / %5 / %8.
  - incident cap: basis x %20.
- Metro failover:
  - hitless: 0-1 sn, 0 TRY.
  - near_hitless: >1-5 sn, evidence only.
  - kısa geçiş: >5-30 sn, evidence only.
  - SLA'yı aşan kısa interruption: >30-60 sn, basis x %0,5, floor 10 TRY,
    cap 50 TRY.
  - >60 sn degraded veya failed failover rule'una yönlenir.
- Metro SLA matrix:
  - latency/jitter/packet-loss exceedance_ratio:
    - >1,00 ve <=1,25: %3.
    - >1,25 ve <=2,00: %7.
    - >2,00: %12.
  - Aynı incident içinde latency, jitter ve packet-loss tutarları toplanmaz; en yüksek
    rate'e sahip primary base rule seçilir.
  - Metro/SLA incident cap: basis x %60.
- Modifier:
  - GRADED_RESTORATION: +%10.
  - RECURRING_INCIDENT: 3. olay +%10, 4. olay +%15, 5+ olay +%25.
  - MAINTENANCE_OVERRUN: plan dışı overrun etkisi için +%10.
  - RESTORATION_TARGET_BREACH: contractual SLA target aşımı için +%10.
  - Modifier'lar bileşik uygulanmaz; toplam modifier rate %40'ı geçmez.
- Final policy:
  - Floor yalnız pozitif monetary sonuçta uygulanır.
  - Ineligible veya evidence-only sonuç floor ile parasal karara dönüşmez.
  - Broadband incident cap: basis x %40.
  - Metro/SLA incident cap: basis x %60.
  - Billing-period cumulative cap: basis x %75.
  - Pre-cap amount basis'in %100'ünü veya 10.000 TRY'yi aşarsa manual_review.
- Duplicate/idempotency:
  - Evaluation idempotency key snapshot, subscription, incident, conflict group ve
    RuleSet version anlamından türetilir.
  - Aynı incident için farklı RuleVersion ile sessiz ikinci final compensation
    oluşturulamaz.
  - CompensationHistory final duplicate kontrolü conflict group seviyesinde yapılır.
- Decision Evidence:
  - Durable ve immutable DecisionEvidence yapısı kullanılacaktır.
  - Business logic evidence JSON içinden serbest biçimde çalıştırılmaz.
  - LLM ileride yalnız evidence'ı açıklayabilir; yeni sayı, kural veya gerekçe
    üretemez.
- 039.5.7 için ground-truth adayları config seviyesinde hazır tutulur:
  - eligible full outage
  - ineligible under-30-minute outage
  - partial outage
  - broadband degradation
  - Metro latency breach
  - 45-second successful failover
  - failed failover
  - protection loss only
  - planned maintenance normal
  - maintenance overrun
  - recurring incident
  - duplicate prevention
  - monthly cap
  - payment-related suspension
  - provider-fault suspension
  - missing price
  - unknown root cause
  - shared-risk diversity breach
  - missing mandatory backup
- Büyük müşteri/olay seed'i bu görevde üretilmez; 039.5.6'ya bırakılır.

### 8.6 Genişletilmiş Seed Generator

Durum: `KARAR VERİLDİ`

- Büyük gerçekçi dataset, Maltepe MVP regression dataset'inden ayrı tutulur.
- Dataset slug: `multi-city-realism-v1`
- Snapshot: `Multi-city Realism Snapshot v1`
- Reference datetime: `2026-08-01T00:00:00+03:00`
- Seed varsayılan olarak yeni snapshot'ı aktif etmez; Maltepe MVP active kalır.
- `--reset` yalnız `multi-city-realism-v1` dataset ağacını siler.
- `--validate-only` mevcut snapshot'ı DB sorgularıyla doğrular.
- Tekrar çalıştırma duplicate üretmez; mevcut dataset valid ise yeniden seed yapmadan çıkar.
- Transaction rollback davranışı korunur.
- Büyük seed şu hacimleri üretir:
  - 4 şehir, 12 ilçe, 59 mahalle
  - 235 cihaz, 245 NetworkLink
  - 14.400 müşteri, 16.200 abonelik
  - 16.027 primary ve 208 backup SubscriptionConnection
  - 27 ServicePackage, 5 SLAProfile, 10 Campaign
  - 59.600 PaymentRecord, 4.050 CampaignEnrollment, 1.100 CompensationHistory
  - `SYN-COMP-2026` v1 RuleSet, 25 Rule, 25 RuleVersion
  - 30 AlarmType, 2.100 Alarm, 210 Incident, 78 Outage
  - 30 MaintenanceWindow, 900 OperationalEvent, 12.000 QualityMeasurement
- 039.5.7 final ground truth kayıtları bu görevde üretilmez.

### 8.7 Genişletilmiş Ground Truth

Durum: `KARAR BEKLİYOR`

- Pozitif telafi senaryoları.
- Negatif telafi senaryoları.
- Eşik altı, eşik ve eşik üstü senaryolar.
- Partial outage.
- Degradation.
- Tekrar eden kesinti.
- Alarm gürültüsü ve yanlış korelasyon adayları.
- Cross-snapshot kayıtlar.
- Eksik veri / manual review.
- VIP, segment, kampanya ve ödeme farklılıkları.
- Bir müşterinin birden fazla aboneliği.
- Farklı RuleVersion seçimi.
- Her senaryo için root cause, affected setler, rule version, eligibility, reason code,
  telafi tutarı ve evidence beklentileri.

### 8.8 Deterministik Servis Uyarlamaları

Durum: `KARAR BEKLİYOR`

- Mevcut servisler korunacaktır:
  - NetworkTopologyService
  - OutageService
  - CustomerImpactService
  - AlarmCorrelationService
  - RootCauseService
  - RuleEvaluationService
  - CompensationService
- Yeni veri ve iş kuralları belirlendikten sonra servislerde gereken genişletmeler
  ayrı görevler halinde planlanacaktır.
- Mevcut servisler tek Maltepe senaryosuna göre tamamlanmış kabul edilmeyecektir.

### 8.9 Validator ve RAG Karar Kapısı

Durum: `KARAR BEKLİYOR`

- Genişletilmiş dataset için config-driven validator yaklaşımı.
- Row count, dağılım, topoloji, alarm, outage, payment, campaign, rule ve ground truth
  kontrolleri.
- RAG kararları:
  - hangi prosedür ve politika dokümanları kullanılacak
  - gerçek kurum dokümanı mı, sentetik doküman mı
  - doküman metadata alanları
  - geçerlilik tarihleri
  - doküman versiyonları
  - hangi sorular RAG ile yanıtlanacak
  - hangi bilgiler deterministik servislerden, hangileri dokümandan gelecek
  - örnek kullanıcı sorguları
  - citation ve evidence davranışı
