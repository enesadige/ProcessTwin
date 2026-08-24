# ProcessTwin

ProcessTwin, sentetik telekom operasyon verisi üzerinde iki ana iş akışı sunan bir Django + React uygulamasıdır:

- **AI Analizi:** Türkçe operasyon sorularını belirleyici servisler, MCP araçları ve gerektiğinde LLM destekli açıklama ile yanıtlar.
- **Süreç Simülasyonu:** Bir ağ arızasının referans ve aday koşullardaki varsayımsal etkisini, kaynak veriyi değiştirmeden karşılaştırır.

> **Veri ve güvenlik:** Bu depodaki veri üreticisi, RAG dokümanları ve demo senaryoları sentetiktir. Gerçek müşteri, kurum, ticari politika veya erişim anahtarı içermez. `.env`, veritabanı dosyaları, `node_modules` ve sanal ortam git tarafından izlenmez.

## Mimari Özeti

```text
React / Vite (127.0.0.1:5173)
        |
        | /api Vite proxy
        v
Django REST API (127.0.0.1:8000)
        |
        +-- Deterministik domain servisleri ve PostgreSQL / pgvector
        +-- Orchestration -> doğrudan MCP adapter -> dahili Django API
        +-- RAG indeksleme ve embedding sağlayıcısı
        +-- İsteğe bağlı LLM sağlayıcısı (Groq, Gemini, NVIDIA veya Ollama)
```

Normal geliştirme ve sunum akışında MCP sunucularını 8101-8106 portlarında sürekli çalıştırmak gerekmez. Varsayılan `ORCHESTRATION_MCP_TRANSPORT=direct` değeri, araç çağrılarını uygulama içindeki adapter üzerinden dahili API'ye taşır. `stdio` modu yalnız yerel/acceptance senaryoları için desteklenir.

## Gereksinimler

- macOS veya Linux
- Python **3.12**
- Node.js **20+** ve npm
- PostgreSQL **16+** ve `pgvector` eklentisi
- Git
- RAG için Gemini embedding veya Ollama + `qwen3-embedding:4b`
- AI Analizi için desteklenen bir LLM sağlayıcısının erişim anahtarı. Sunumda önerilen seçenek Groq GPT-OSS'tur (`GROQ_API_KEY`).

Redis ve Celery kuyruklu işler için desteklenir; aşağıdaki etkileşimli sunum başlatma akışında Celery başlatılmaz. Redis de o akışın zorunlu bir parçası değildir.

> Gemma indirmek zorunda değilsiniz. Ollama LLM adaptörü eski/alternatif yerel çalışma seçeneğidir; Groq GPT-OSS ile LLM çalıştırıp yalnız Qwen embedding'i yerelde kullanabilirsiniz.

## 1. Depoyu İndirme ve Bağımlılıkları Kurma

```bash
git clone https://github.com/enesadige/ProcessTwin.git
cd ProcessTwin

python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

cd frontend
npm ci
cd ..
```

Python paketleri `requirements.txt` içinde, frontend paketleri ise kilitli `frontend/package-lock.json` içinde tanımlıdır. Yeni paket gerekmedikçe `npm install` yerine `npm ci` kullanın.

## 2. PostgreSQL ve pgvector Hazırlığı

Yerel PostgreSQL sunucunuz çalışır durumda olmalıdır. Aşağıdaki örnek, mevcut macOS/Linux kullanıcınız için boş bir veritabanı oluşturur:

```bash
createdb processtwin
psql processtwin -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

Farklı PostgreSQL kullanıcısı, parola veya port kullanıyorsanız bir sonraki bölümdeki `DATABASE_URL` değerini buna göre değiştirin. `pgvector`, RAG embedding vektörlerinin PostgreSQL içinde aranması için gereklidir.

## 3. Ortam Değişkenleri

Örnek dosyayı kopyalayın. Gerçek `.env` dosyasını **asla** git'e eklemeyin.

```bash
cp .env.example .env
chmod 600 .env
```

`.env` içindeki aşağıdaki alanları doldurun. Örnek değerler şablondur; secret değerleri yalnız kendi bilgisayarınızda kalmalıdır.

```env
DJANGO_SECRET_KEY=<uzun-rastgele-django-secret>
DATABASE_URL=postgres://<kullanici>:<parola>@127.0.0.1:5432/processtwin

# Sunum için önerilen LLM: Groq GPT-OSS
LLM_PROVIDER=groq
GROQ_API_KEY=<groq-api-key>

# LLM'den bağımsız RAG embedding tercihi
RAG_EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434

# Dahili MCP -> Django çağrıları için aynı, rastgele ve gizli değer kullanılmalı.
INTERNAL_API_SERVICE_TOKEN=<uzun-rastgele-servis-tokeni>
MCP_BACKEND_SERVICE_TOKEN=<ayni-servis-tokeni>
MCP_BACKEND_BASE_URL=http://127.0.0.1:8000
ORCHESTRATION_MCP_TRANSPORT=direct
```

| Amaç | Ayar | Gereken |
| --- | --- | --- |
| Sunum LLM'i | `LLM_PROVIDER=groq` | `GROQ_API_KEY`; model sabit olarak `openai/gpt-oss-120b` kullanılır. |
| Bulut embedding | `RAG_EMBEDDING_PROVIDER=gemini` | `GEMINI_API_KEY` |
| Yerel embedding | `RAG_EMBEDDING_PROVIDER=ollama` | Ollama ve `qwen3-embedding:4b` |
| Yerel LLM (isteğe bağlı) | `LLM_PROVIDER=ollama` | Ollama'da projenin allowlist'inde bulunan Gemma modeli |

Yerel embedding seçeneği için yalnız embedding modelini indirin:

```bash
ollama pull qwen3-embedding:4b
```

`VITE_API_BASE_URL` değerini `.env` içinde ayarlamayın. Frontend aşağıdaki başlatma komutunda `/api` isteklerini Vite proxy ile backend'e iletir; bu sayede tarayıcı oturumu aynı origin'de kalır ve CORS riski oluşmaz.

## 4. Şema, Sentetik Veri ve RAG Kurulumu

Bu depoda PostgreSQL dump bulunmaz. Temiz bir klonda şema ve demo verisi aşağıdaki komutlarla üretilir. Veri üretimi belirleyicidir; aynı seed ve sürüm aynı kaynak veri dünyasını yeniden kurmayı hedefler.

### 4.1 Django şeması

```bash
./.venv/bin/python backend/manage.py migrate
```

### 4.2 Kanonik sentetik veri zinciri

Kullanıcı arayüzü, `multi-city-realism-v3-repair-r1` anlık görüntüsünü kullanır. Bu anlık görüntü; temel çok-şehirli veriden, checkpoint'li V3 adayından ve son onarım sürümünden oluşur. Komutları sırayla çalıştırın.

```bash
# RAG corpusunun Maltepe referanslarını doğrulayabilmesi için gerekir.
./.venv/bin/python backend/manage.py seed_maltepe_mvp

# Çok-şehirli temel sentetik veri dünyası.
./.venv/bin/python backend/manage.py seed_multicity_realism

# Temel anlık görüntünün kimliğini dinamik olarak alır; sabit DB id'si varsaymaz.
BASE_SNAPSHOT_ID=$(./.venv/bin/python backend/manage.py shell -c \
  "from apps.datasets.models import DataSnapshot; print(DataSnapshot.objects.get(dataset_version__slug='multi-city-realism-v1').pk)")

./.venv/bin/python backend/manage.py seed_multicity_realism \
  --checkpointed-v3 --source-snapshot-id "$BASE_SNAPSHOT_ID"

V3_SNAPSHOT_ID=$(./.venv/bin/python backend/manage.py shell -c \
  "from apps.datasets.models import DataSnapshot; print(DataSnapshot.objects.get(dataset_version__slug='multi-city-realism-v3').pk)")

./.venv/bin/python backend/manage.py seed_multicity_realism \
  --repair-v3 --repair-source-snapshot-id "$V3_SNAPSHOT_ID"
```

Uzun checkpoint'li bir seed işlemi kesilirse, aynı kaynak anlık görüntüsüyle aşağıdaki komutlardan uygun olanını kullanın:

```bash
./.venv/bin/python backend/manage.py seed_multicity_realism \
  --checkpointed-v3 --resume --source-snapshot-id "$BASE_SNAPSHOT_ID"

./.venv/bin/python backend/manage.py seed_multicity_realism \
  --repair-v3 --repair-resume --repair-source-snapshot-id "$V3_SNAPSHOT_ID"
```

İsteğe bağlı doğrulama:

```bash
./.venv/bin/python backend/manage.py seed_multicity_realism \
  --dataset-slug multi-city-realism-v3-repair-r1 --validate-only
```

### 4.3 RAG corpusunu indeksleme

RAG corpusundaki dokümanlar depoda, `documents/` altında bulunur; veritabanında `SourceDocument`, `DocumentChunk` ve embedding kayıtları olarak üretilmeleri gerekir.

```bash
./.venv/bin/python backend/manage.py seed_rag_corpus
./.venv/bin/python backend/manage.py index_rag_documents

# Yerel Qwen embedding profili ile tüm etkin dokümanları vektörleştirir.
./.venv/bin/python backend/manage.py generate_rag_embeddings \
  --provider ollama --embedding-profile ollama-qwen3-4b
```

Gemini embedding kullanıyorsanız son komutu aşağıdaki gibi değiştirin:

```bash
./.venv/bin/python backend/manage.py generate_rag_embeddings --provider gemini
```

### 4.4 Yerel demo kullanıcıları

```bash
./.venv/bin/python backend/manage.py seed_demo_users --password '<en-az-8-karakterli-parola>'
```

Bu komut `demo_viewer`, `demo_analyst`, `demo_engineer` ve `demo_admin` kullanıcılarını oluşturur/günceller. Django yönetim arayüzü için ayrıca kendi yönetici hesabınızı oluşturun:

```bash
./.venv/bin/python backend/manage.py createsuperuser
```

## 5. Güvenilir Sunum Başlatma Sırası

Bu akış backend'i önce başlatır, ardından MCP hazır oluşunu ve Vite proxy'yi doğrular. Celery ve kalıcı MCP port süreçleri bu interaktif sunum için gerekmez.

### 5.1 Eski uygulama süreçlerini kontrol edin

```bash
for port in 8000 5173 11434 6379; do
  echo "--- port $port ---"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN || true
done
```

Yalnız bu projeye ait eski Django veya Vite süreçleri varsa zarif biçimde kapatın. PostgreSQL, Ollama ya da başka bir uygulamaya ait süreçleri öldürmeyin.

### 5.2 Backend'i başlatın

Bir terminalde:

```bash
./.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
```

Başka bir terminalden health kontrolü başarılı olmadan frontend'e geçmeyin:

```bash
curl -fsS http://127.0.0.1:8000/api/health/
```

### 5.3 Dahili MCP hazır oluşunu kontrol edin

Token değeri terminale yazdırılmadan `.env` dosyasından alınır:

```bash
set -a
source .env
set +a

curl -fsS \
  -H "Authorization: Bearer ${INTERNAL_API_SERVICE_TOKEN}" \
  "http://127.0.0.1:8000/api/internal/v1/mcp/health/?timeout_seconds=5"
```

Yanıtta Network, Customer, Rules, Compensation ve Simulation descriptor/probe durumları başarılı görünmelidir. Başarısız olursa önce backend health sonucunu, `MCP_BACKEND_BASE_URL` değerini ve iki servis tokenının boş olmadığını/eşit olduğunu kontrol edin. Token değerini paylaşmayın.

### 5.4 Frontend'i proxy modunda başlatın

Ayrı bir terminalde:

```bash
cd frontend
env -u VITE_API_BASE_URL \
  VITE_API_PROXY_TARGET=http://127.0.0.1:8000 \
  npm run dev -- --host 127.0.0.1 --port 5173
```

Bu komut, `VITE_API_BASE_URL` değişkenini özellikle kaldırır ve `/api` isteklerini backend'e proxy'ler. Doğrudan cross-origin backend URL'si kullanmak CSRF/CORS hatalarına yol açabilir.

### 5.5 Readiness kontrolleri

```bash
curl -fsS http://127.0.0.1:8000/api/health/
curl -fsSI http://127.0.0.1:5173/
curl -sS -o /dev/null -w "Vite proxy CSRF status: %{http_code}\n" \
  http://127.0.0.1:5173/api/auth/csrf/
```

Beklenen sonuçlar backend health için başarılı yanıt, frontend için `200` ve Vite proxy CSRF kontrolü için `200` değeridir. Ardından tarayıcıdan `http://127.0.0.1:5173` adresini açın. Giriş, AI Analizi, Süreç Simülasyonu ve Karar Kanıtları ekranlarını kontrol edin.

## Sorun Giderme

| Belirti | Önce kontrol edin | Muhtemel çözüm |
| --- | --- | --- |
| `Failed to fetch` | `GET /api/health/`, Vite terminali | Backend'i önce başlatın; frontend'i proxy komutuyla yeniden başlatın. |
| CORS/CSRF hatası | `VITE_API_BASE_URL` | Bu değişkeni unset bırakın ve `/api` Vite proxy kullanın. |
| MCP health başarısız | Backend health, dahili base URL, servis tokenları | `MCP_BACKEND_BASE_URL=http://127.0.0.1:8000` olmalı; iki token aynı ve boş olmamalı. |
| RAG sonucu boş | RAG seed, index ve embedding kayıtları | `seed_rag_corpus`, `index_rag_documents`, `generate_rag_embeddings` adımlarını tamamlayın. |
| Ollama embedding hatası | Ollama servisi/modeli | `ollama serve` çalıştığından ve `qwen3-embedding:4b` indirildiğinden emin olun. |
| `relation` veya `vector` hatası | Migration ve pgvector | `migrate` çalıştırın; PostgreSQL'de `CREATE EXTENSION vector` komutunu uygulayın. |
| Port kullanımda | `lsof` | Sadece bu projeye ait eski Django/Vite sürecini kapatın. |

## Geliştirme Komutları

```bash
# Django yapı denetimi
./.venv/bin/python backend/manage.py check

# Backend testleri
./.venv/bin/pytest -q

# Frontend tip denetimi ve üretim build'i
cd frontend
npm run typecheck
npm run build
```

`scripts/dev.py` backend, frontend ve Celery'yi birlikte yönetebilen bir yardımcıdır. Sunum için yukarıdaki manuel sıra tercih edilir: Celery zorunlu değildir ve launcher'da bir alt sürecin bitmesi diğer süreçleri de kapatabilir.

## Gizli Bilgi Kontrolü ve Katkı

Commit öncesinde aşağıdaki kontrolleri çalıştırın:

```bash
git status --short
git check-ignore -v .env
git diff --check
```

`.env.example` yalnız değişken adlarını ve güvenli varsayımları içerir. Gerçek API anahtarlarını, Django secret'ını, servis tokenlarını, veritabanı yedeklerini ve kişisel verileri commit etmeyin.

## Lisans ve Kapsam

Bu proje eğitim/demonstrasyon amaçlı sentetik telekom operasyon verisi kullanır. Üretim ağına bağlanmaz, üretim ağ cihazlarını kontrol etmez ve gerçek müşteri verisi içermez.
