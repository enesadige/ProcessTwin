# Synthetic Review Pack Export

`export_synthetic_review_pack` komutu, ProcessTwin sentetik veri modelini Turkcell veri incelemesi için read-only bir paket olarak dışa aktarır.

Komut seed, reset, snapshot activation veya DB update yapmaz. Snapshot açıkça seçilmelidir; aktif snapshot'a sessiz fallback yoktur.

Örnek kullanım:

```bash
python manage.py export_synthetic_review_pack \
  --dataset-slug multi-city-realism-v1 \
  --include-full-data \
  --include-maltepe-regression \
  --sample-size 50 \
  --output-dir "$HOME/Desktop/processtwin_synthetic_data_review_pack" \
  --zip \
  --overwrite
```

Üretilen paket:

- `00_OKU_BENI.md`: sentetik veri kapsamı ve inceleme yönergesi
- `02_table_catalog.csv`: tablo kataloğu
- `03_data_dictionary.csv`: model alan sözlüğü
- `review/*.csv`: Turkcell yorum kolonları içeren inceleme dosyaları
- `sample_data/`: deterministik temsilî kayıtlar
- `full_data/`: opsiyonel tam sentetik export
- `validation/`: validator, ground-truth ve regression özetleri
- `diagrams/model_relationships.mmd`: model ilişki diyagramı

PNG diyagram ve XLSX geri bildirim formu yalnız mevcut runtime ortamında gerekli araçlar varsa üretilir; komut bunun için yeni bağımlılık kurmaz.
