# Bekleyen İş ve Senaryo Kararları

Bu dosya, ProcessTwin projesinde ilerleyen görevlerden önce kullanıcıyla netleştirilmesi gereken iş, veri, senaryo ve demo kararlarını takip eder.

## Çalışma Kuralı

- Bu dosyadaki değerler kafadan doldurulmaz.
- Her başlık kullanıcıyla soru-cevap şeklinde tek tek netleştirilir.
- Karar verilmeden model, migration, seed veya iş kuralı kodu yazılmaz.
- Karar kesinleşince ilgili madde `KARAR VERİLDİ` olarak güncellenir.
- İlk 6 başlık netleşmeden Görev 019 başlatılmaz.

## 1. Görev 019 Öncesi Zorunlu Kararlar

Durum: `KARAR BEKLİYOR`

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
- Maltepe mahalle, cihaz, port ve müşteri sayıları: `KISMEN KARAR VERİLDİ`
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
  - Erişim cihazı, port, hat, müşteri ve teknoloji dağılımı: `KISMEN KARAR VERİLDİ`
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
    - Port, hat, abonelik, müşteri ve teknoloji yük dağılımı: `KARAR BEKLİYOR`
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
  - Bu karar kapsamında henüz model, migration veya seed değişikliği yapılmaz.

## 2. Alarm ve Incident Kararları

Durum: `KARAR BEKLİYOR`

- Alarm kataloğu: `KARAR BEKLİYOR`
- Severity değerleri: `KARAR BEKLİYOR`
- Parent-child alarm ilişkileri: `KARAR BEKLİYOR`
- Korelasyon eşikleri: `KARAR BEKLİYOR`
- Incident oluşturma koşulları: `KARAR BEKLİYOR`
- Kök neden ve belirti ayrımı: `KARAR BEKLİYOR`

## 3. İş Kuralları ve Telafi

Durum: `KARAR BEKLİYOR`

- İade eşikleri: `KARAR BEKLİYOR`
- Hesaplama formülü: `KARAR BEKLİYOR`
- Alt/üst tutar sınırları: `KARAR BEKLİYOR`
- Müşteri segmenti farkları: `KARAR BEKLİYOR`
- Ödeme ve geçmiş telafi etkisi: `KARAR BEKLİYOR`
- Kampanya birlikte kullanım kuralları: `KARAR BEKLİYOR`
- Manuel inceleme koşulları: `KARAR BEKLİYOR`
- Kural sürümleri ve öncelikler: `KARAR BEKLİYOR`

## 4. Ground Truth

Durum: `KARAR BEKLİYOR`

- Gerçek kök neden: `KARAR BEKLİYOR`
- Alarm grupları: `KARAR BEKLİYOR`
- Etkilenen ve etkilenmeyen müşteriler: `KARAR BEKLİYOR`
- Beklenen müşteri sayıları: `KARAR BEKLİYOR`
- Beklenen kural ve telafi sonuçları: `KARAR BEKLİYOR`
- Negatif ve bozuk veri senaryoları: `KARAR BEKLİYOR`

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
