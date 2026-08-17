# ProcessTwin AI

ProcessTwin AI, telekom operasyonlari icin yapay zeka destekli, aciklanabilir analiz ve simulasyon platformudur.

## Temel Kararlar

- Calisma modeli native process yapisidir.
- Backend Python `.venv` icinden calisacak Django ve Django REST Framework uygulamasidir.
- Frontend React, TypeScript, Vite, ECharts ve Cytoscape.js ile gelistirilecektir.
- PostgreSQL, Redis ve Ollama yerel sistem servisleri olarak ele alinacaktir.
- MCP sunuculari ayri Python process'leri olarak calisacaktir.
- Servis yonetimi icin `scripts/dev.py` gelistirilecektir.
- Standart cihaz terimi `BNG` olacaktir.
- LLM musteri sayisi, kesinti suresi, iade tutari, KPI veya kural sonucu hesaplamaz.
- Kesin hesaplamalar deterministik domain servislerinde yapilir.
- RAG yalnizca kural, prosedur ve metinsel kaynak erisimi icin kullanilir.
- Decision Evidence her ana analizde zorunludur.
- Gelistirme kume kume ilerler: her gorev tamamlanir, kontrol edilir, gunluge yazilir ve sonra sonraki goreve gecilir.

## LLM Provider Yaklasimi

LLM Orchestrator dogrudan belirli bir modele bagli olmayacaktir.

Akis:

```text
LLM Orchestrator
-> Provider Registry
-> Secili Provider
-> Gemini API / Ollama / Mock
```

Desteklenecek provider'lar:

- Gemini API
- Ollama
- Mock provider

Provider secimi environment veya sistem ayariyla yapilir. Provider degistiginde Orchestrator, MCP, RAG, Decision Evidence ve ProcessTwin kodu degismez.

Ornek Gemini ayarlari:

```env
LLM_PROVIDER=gemini
LLM_MODEL=<gemini-model-name>
GEMINI_API_KEY=...
```

Ornek Ollama ayarlari:

```env
LLM_PROVIDER=ollama
LLM_MODEL=gemma4:12b-it-qat
OLLAMA_BASE_URL=http://localhost:11434
```

## MVP Kapsami

Ilk MVP Maltepe uzerinde calisan dikey dilimdir.

Zorunlu MCP sunuculari:

- Network MCP
- Customer MCP
- Rule MCP
- Compensation MCP

MVP'de Analytics MCP zorunlu degildir. Ana sorgudaki "en uzun kesinti" islemi Network MCP veya operations tarafindaki deterministik servis uzerinden cozulur.

ProcessTwin MVP icindedir; ilk asamada Django icindeki `SimulationService` ve domain servisleriyle calisir. ProcessTwin, ayni sentetik olay senaryosunu baseline ve candidate rule set ile ayni baslangic kosullarinda calistiran, virtual clock ile ilerleyen, izole, deterministik, tekrar oynatilabilir ve sifirlanabilir sentetik simulasyon katmanidir. Alarm, operational event, incident, outage/degradation, musteri etkisi ve telafi degerlendirmeleri run icinde zamanla olusur; harita, topoloji ve event timeline calisan run'a gore guncellenir. RAG yalniz kural/prosedur kaynaklarini getirir; LLM araclari orkestre eder ve deterministik sonuclari aciklar, hesaplama yapmaz. Ayri Simulation MCP, 075-081 runtime altyapisini disa acan adapter olarak daha sonra gelistirilir.

## Ana Demo Sorgusu

```text
Maltepe'de gecen ay en uzun suren kesinti hangisiydi,
kac musteri etkilendi, kok nedeni neydi ve
hangi telafi secenekleri uygulanabilir?
```

## Ana ProcessTwin Senaryosu

```text
Maltepe'deki BNG arizasi 90 dakika yerine 180 dakika surse
ve iade esigi 120 dakikaya dusse ne degisir?
```

## Calisma Ortami

Bu proje native macOS veya Linux process'leriyle calisacak sekilde tasarlanir.

Beklenen yerel servisler:

- PostgreSQL
- Redis
- Ollama

Uygulama process'leri:

- Django backend
- React frontend
- MCP sunuculari
- Celery worker

Redis ve Celery; buyuk ProcessTwin calismalari, toplu kural replay, genis dataset uretimi, RAG yeniden indeksleme ve uzun analitik islemler icin korunur. Basit sorgular senkron calisabilir.

## Environment Stratejisi

Gelistirme ayarlari `.env` uzerinden okunur. Repo icinde yalnizca `.env.example` tutulur; gercek secret degerleri commit edilmez.

Temel servis portlari:

- Backend: `8000`
- Frontend: `5173`
- Network MCP: `8101`
- Customer MCP: `8102`
- Rule MCP: `8103`
- Compensation MCP: `8104`
- Analytics MCP: `8105`
- Simulation MCP: `8106`

Network MCP stdio runtime icin kisa not:

```bash
MCP_BACKEND_BASE_URL="http://127.0.0.1:8000" \
MCP_BACKEND_SERVICE_TOKEN="<internal-service-token>" \
python -m mcp_servers.network
```

Ayrinti: `documents/network_mcp.md`.

PostgreSQL, Redis ve Ollama dis sistem servisi kabul edilir. Django, React, MCP sunuculari ve Celery worker uygulama process'i olarak baslatilir.

`scripts/dev.py` su beklentilerle gelistirilecektir:

- Istenen servisleri secerek baslatma
- Process loglarini ayirma
- Port cakismalarini kontrol etme
- Health check calistirma
- Ctrl+C ile alt process'leri duzgun kapatma

Kurulum, seed, test ve servis calistirma komutlari ilgili gorevler tamamlandikca bu dosyaya eklenecektir.

## Gelistirme Komutlari

Backend kontrolleri:

```bash
.venv/bin/python backend/manage.py check
.venv/bin/pytest
.venv/bin/ruff check .
```

Frontend kontrolleri:

```bash
cd frontend
npm run build
npm run lint
npm run test
```

Native servis kontrolu:

```bash
.venv/bin/python scripts/check_native.py
```

Servisleri baslatma:

```bash
.venv/bin/python scripts/dev.py
.venv/bin/python scripts/dev.py --services backend frontend celery
.venv/bin/python scripts/dev.py --health
```

Port override:

```bash
.venv/bin/python scripts/dev.py --services backend frontend --backend-port 8010 --frontend-port 5174
```

Baslatici varsayilan olarak frontend'in `/api` isteklerini Vite proxy uzerinden secilen backend portuna yonlendirir. Bu, local browser oturumunun ayni-origin kalmasini ve CORS gerektirmemesini saglar. Farkli bir dogrudan API adresi gerekiyorsa `--api-base-url` ile acikca verilebilir.
