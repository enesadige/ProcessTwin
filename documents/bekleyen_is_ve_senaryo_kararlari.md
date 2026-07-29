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
    - `metro_ethernet` paket -> `metro_ethernet` hat: uyumlu
    - diğer kombinasyonlar: uyumsuz
  - Seed verisinde `gpon` isimli müşteri paketi üretilmez.
  - GPON, fiber paketlerin çalışabildiği hat/altyapı teknolojisi olarak kullanılır.
  - VDSL ve ADSL aynı xDSL ailesinde olmasına rağmen MVP'de birbirleriyle uyumlu kabul edilmez.
  - İlk Maltepe MVP seed'inde Metro Ethernet müşterisi, paketi, hattı veya outage senaryosu üretilmez.
  - `metro_ethernet` teknoloji seçeneği kodda korunur; kaldırılmaz.
  - Metro Ethernet sonraki kurumsal genişleme kapsamında ayrı topoloji, SLA, yedeklilik ve telafi kararlarıyla ele alınır.
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

Durum: `KARAR BEKLİYOR`

- Baseline değerleri: `KARAR BEKLİYOR`
- Candidate değişiklikleri: `KARAR BEKLİYOR`
- Karşılaştırılacak KPI'lar: `KARAR BEKLİYOR`
- Beklenen sonuç farkları: `KARAR BEKLİYOR`

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

Durum: `KARAR BEKLİYOR`

- 20-30 gerçeğe yakın sentetik alarm tipi üretilecek mi?
- Alarm katalog alanları nasıl tutulacak?
  - alarm code
  - alarm name
  - category
  - severity
  - kaynak cihaz tipi
  - desteklenen teknolojiler
  - probable cause
  - clear/recovery davranışı
  - parent/root alarm ilişkisi
  - suppression kuralları
  - deduplication anahtarı
  - correlation time window
  - incident oluşturma etkisi
  - servis etkisi seviyesi
- Hangi olay aileleri üretilecek?
  - fiber kesisi
  - cihaz erişilemezliği
  - link arızası
  - enerji problemi
  - planlı bakım
  - kısmi kesinti
  - tam kesinti
  - aralıklı kesinti
  - servis kalitesi bozulması
  - tekrar eden arıza
- Gerçek kurum alarm kodu veya gizli veri iddiası oluşturulmayacaktır.

### 8.4 Müşteri, Paket, Ödeme ve Kampanya Dağılımları

Durum: `KISMEN KARAR VERİLDİ`

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
- Hâlâ karar bekleyen veri grupları:
  - Paket katalogu.
  - Farklı aylık ücretler, taahhüt süreleri ve SLA profilleri.
- PaymentRecord kararları:
  - fatura dönemi
  - ödeme durumu
  - gecikmiş ödeme
  - borç durumu
  - tutar üretimi
- CampaignEnrollment kararları:
  - aktif/pasif kampanya
  - kampanyalı/indirimli fiyat
  - kampanya geçerlilik tarihleri
  - telafiyle etkileşim
- CompensationHistory kararları:
  - önceki telafi
  - karar tarihi
  - tekrar telafi etkisi
  - manuel inceleme koşulu

### 8.5 İş Kuralı Kataloğu

Durum: `KARAR BEKLİYOR`

- `REFUND-001` yalnız teknik örnek olarak kalacaktır.
- Yeni sentetik kural aileleri netleştirilecek:
  - tam kesinti telafisi
  - süre kademelerine göre farklı oranlar
  - servis bozulması telafisi
  - tekrar eden kesinti
  - aynı fatura dönemindeki birden fazla olay
  - minimum ve maksimum telafi
  - günlük/saatlik oranlama
  - kampanyalı fiyat mı abonelik fiyatı mı kullanılacağı
  - borç veya gecikmiş ödeme davranışı
  - daha önce telafi alınmış olması
  - VIP/SLA/segment farklılıkları
  - kurumsal ve kamu müşterisi davranışı
  - eksik veride `manual_review`
  - çakışan kurallarda öncelik
  - kural sürümleri ve geçerlilik tarihleri
- Her kural için beklenecek alanlar:
  - rule code
  - açıklama
  - uygunluk koşulları
  - action/formül
  - reason codes
  - geçerlilik dönemi
  - öncelik
  - gerekli veri alanları
  - pozitif/negatif örnek senaryolar

### 8.6 Genişletilmiş Seed Generator

Durum: `KARAR BEKLİYOR`

- Genişletilmiş dataset ayrı config/generator version olarak mı üretilecek?
- Mevcut Maltepe MVP seed'i nasıl korunacak?
- Reset, activate, reference datetime ve transaction atomic davranışları nasıl
  sürdürülecek?
- Deterministik business code formatları şehir/ilçe genişlemesinde nasıl olacak?

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
