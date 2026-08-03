# Native Servis Notlari

Bu proje native process modeliyle calisir.

## PostgreSQL

Yerel servis:

```bash
brew services start postgresql@14
```

Bu makinedeki kontrol:

- PostgreSQL surumu: 14.18
- Servis durumu: started
- Proje database adi: `processtwin`
- Django database URL: `postgres://localhost:5432/processtwin`

## pgvector

Homebrew `pgvector` paketi bu makinede PostgreSQL 17 ve 18 icin hazir dosya kurdugu icin PostgreSQL 14 tarafinda extension otomatik gorunmedi.

Uygulanan cozum:

- pgvector 0.8.5 source arsivi indirildi.
- PostgreSQL 14 `pg_config` ile derlendi.
- Derlenen dosyalar PostgreSQL 14 extension klasorlerine kuruldu.
- `processtwin` database icinde `vector` extension aktif edildi.

Kontrol SQL'i:

```sql
select extname, extversion from pg_extension where extname = 'vector';
```

## Django Baglantisi

Django database ayari `backend/config/settings/base.py` icindeki `DATABASE_URL` okuma hattindan gelir.

Lokal `.env`:

```env
DATABASE_URL=postgres://localhost:5432/processtwin
```

Basit migration kontrolu:

```bash
.venv/bin/python backend/manage.py migrate
```

## Redis

Yerel servis:

```bash
brew services start redis
```

Kontrol:

```bash
redis-cli ping
```

Beklenen sonuc:

```text
PONG
```

## Ollama

Yerel servis/API:

```text
http://localhost:11434
```

Bu makinede gorulen model:

```text
gemma4:12b-it-qat
qwen3-embedding:4b
```

Kontrol:

```bash
curl -s http://localhost:11434/api/tags
```

Lokal embedding modeli `qwen3-embedding:4b` olarak doğrulanmıştır. Uygulama
runtime'da model indirmez; eksik kurulumda şu komut bir kez çalıştırılır:

```bash
ollama pull qwen3-embedding:4b
```

Gemma CLI smoke thinking kapalı yürütülür:

```bash
ollama run gemma4:12b-it-qat --think=false
```

## Celery

Celery Redis broker/result backend ile calisir.

```env
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

Worker:

```bash
cd backend
../.venv/bin/celery -A config worker -l info --pool=solo
```
