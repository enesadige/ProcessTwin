# Ertelenen Teknik Notlar

Bu dosya, kapsamdan cikarilmayan fakat daha dogru gorevde eklenecek teknik parcalari takip eder.

## Frontend Paketleri

### ECharts

Durum: Ertelendi.

Neden:
- Gorev 005'te hedef minimum React/Vite iskeletini calisir hale getirmekti.
- Chart ekranlari henuz gelistirilmedigi icin ECharts'i erken eklemek dependency setini gereksiz buyutuyordu.

Ne zaman eklenecek:
- KPI, kesinti sureleri, musteri etkisi veya telafi dagilimi gibi grafik ekranlari gelistirilirken.

### Cytoscape.js

Durum: Ertelendi.

Neden:
- Gorev 005'te topoloji veya graph ekranlari henuz uygulanmadi.
- Network topology UI gelmeden Cytoscape.js eklemek erken dependency yukuydu.

Ne zaman eklenecek:
- BNG, alt cihaz, port, modem ve musteri etkisi graph/topoloji ekranlari gelistirilirken.

## Frontend Test Kutuphaneleri

### Vitest, Testing Library ve jsdom

Durum: Ertelendi.

Neden:
- Ilk kurulum denemesinde test/browser paket zinciri npm tarafinda gereksiz sekilde buyudu.
- Gorev 005 icin minimum kabul kriteri build ve TypeScript typecheck ile saglandi.

Ne zaman eklenecek:
- Frontend component davranislari kalici hale geldiginde.
- API state, form, filtre, tablo veya graph interaction testleri yazilacagi zaman.

## Frontend Lint

### Oxlint veya ESLint

Durum: Ertelendi.

Neden:
- Gorev 005'te hizli, temiz ve minimum React kurulumu hedeflendi.
- Simdilik `npm run lint`, TypeScript typecheck olarak calisiyor.

Ne zaman eklenecek:
- Frontend component sayisi arttiginda.
- Import sirasi, React hook kurallari ve style disiplinini otomatik denetlemek gerektiginde.
