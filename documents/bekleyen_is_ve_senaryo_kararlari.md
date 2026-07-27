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
- Switch, saha dolabı ve modem modelleme kararı: `KARAR BEKLİYOR`
- Yedek bağlantı yapısı: `KARAR BEKLİYOR`
- Fiber/GPON/VDSL/ADSL teknoloji uyumluluk matrisi: `KARAR BEKLİYOR`
- Müşteri segmentleri ve VIP modeli: `KARAR BEKLİYOR`
- Kalite ölçümlerinin cihaz/abonelik kapsamı: `KARAR BEKLİYOR`
- Maltepe mahalle, cihaz, port ve müşteri sayıları: `KARAR BEKLİYOR`
- Tam kesinti, servis bozulması ve kademeli geri dönüş yapısı: `KARAR BEKLİYOR`

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
