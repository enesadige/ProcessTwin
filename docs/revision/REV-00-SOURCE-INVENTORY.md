# REV-00 Source Inventory

Tarama kökü: repository root, `ca225f3`. `.git` ve `.venv` üçüncü taraf içerikleri hariç tutuldu. İnternetten dosya indirilmedi ve repository dışındaki kişisel klasörler kaynak kabul edilmedi.

## Beklenen domain kaynakları

| Aranan kaynak | Durum | Repo yolu | Not |
|---|---|---|---|
| BTK Elektronik Haberleşme Pazar Verileri PDF | Yok | - | PDF bulunmadı. |
| Turkcell/KAP faaliyet raporu PDF | Yok | - | PDF bulunmadı. |
| OpenConfig alarm YANG | Yok | - | `.yang` dosyası bulunmadı. |
| `synthetic_data_review_pack.zip` | Yok | - | ZIP bulunmadı. Export command/test mevcut, paket artefact'ı repo içinde değil. |
| Yusuf/Sercan örnek CSV | Yok | - | Domain CSV bulunmadı. |
| Yusuf/Sercan örnek log | Yok | - | Kimliği doğrulanmış domain log'u bulunmadı. |

## Repository içinde bulunan log dosyaları

Bu dosyalar uygulama geliştirme loglarıdır; Yusuf/Sercan domain örnekleri olarak sınıflandırılmamıştır.

| Yol | Boyut (byte) | Tür | SHA-256 |
|---|---:|---|---|
| `logs/dev/backend.log` | 683 | ASCII text | `fbf72a5d34462d77da4d9560f85e68d161dd1eeadcc79c81565035fb885124bc` |
| `logs/dev/celery.log` | 1128 | ASCII text | `f8f02dfd56e0fea7f28e09bac9710a317f57dfba1fcee529718af4fc9c443a0f` |
| `logs/dev/frontend.log` | 262 | UTF-8 text | `cb6c2d7e34b498205d6c6608a2c099b0bd831ee8093b929ec4e08e434ef4dbc3` |
| `logs/manual/backend-admin.log` | 0 | empty | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Tarama yöntemi

- Ad/desen taraması: `BTK`, `KAP`, `Turkcell`, `OpenConfig`, `Yusuf`, `Sercan`, `synthetic_data_review_pack`.
- Uzantı taraması: `.pdf`, `.yang`, `.zip`, `.csv`, `.log`.
- Bulunan dosyalarda `stat`, `file` ve `shasum -a 256` kullanıldı.
- Dosya içeriği bu görevde domain analizi amacıyla işlenmedi.

## Sonuç

Revizyon girdisi olacak harici PDF/YANG/CSV/ZIP kaynakları henüz repository'ye alınmamıştır. İleride eklenecek dosyalar PII/secret taramasından geçirilmeli ve checksum ile envantere bağlanmalıdır.
