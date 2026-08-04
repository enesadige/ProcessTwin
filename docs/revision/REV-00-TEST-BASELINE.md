# REV-00 Test Baseline

Çalışma tarihi: 4 Ağustos 2026. Repository başlangıç commit'i: `ca225f3`. Çalışma dizini bütün komutlarda repository root'tur: `/Users/enesdasci/Desktop/turkcell - proje/proje`.

Bu görev test veya uygulama davranışı düzeltmez. Aşağıdaki sonuçlar mevcut sistemin read-only/doğrulama baseline'ıdır.

## Sonuç özeti

| Kontrol | Komut | Sonuç | Süre / not |
|---|---|---|---|
| Collection | `.venv/bin/pytest --collect-only -q` | 612 test collected; 0 error | 1.25 s |
| Full suite | `.venv/bin/pytest -q` | 612 passed; 0 failed; 0 skipped; 0 xfailed; 0 deselected; 0 collection error | 684.05 s pytest / 685.51 s wall |
| Critical targeted gates | `.venv/bin/pytest -q backend/apps/datasets/tests/test_multicity_ground_truth.py backend/apps/datasets/tests/test_seed_maltepe_mvp.py backend/apps/rag/tests/test_rag_embedding_providers.py backend/apps/rag/tests/test_rag_embedding_migration.py mcp_servers/shared/tests backend/apps/core/tests/test_mcp_shared_contracts.py backend/apps/core/tests/test_mcp_registry.py backend/apps/core/tests/test_mcp_health.py` | 122 passed; 0 failed/skipped/xfail/deselected | 164.19 s pytest / 165.55 s wall |
| Ruff | `.venv/bin/ruff check .` | All checks passed | - |
| Django system check | `.venv/bin/python backend/manage.py check` | System check identified no issues (0 silenced) | - |
| Migration drift | `.venv/bin/python backend/manage.py makemigrations --check --dry-run` | No changes detected | - |
| Applied migration state | read-only `MigrationExecutor` audit | 53 applied, 0 pending | PostgreSQL 14.18 / pgvector 0.8.5 |
| Multi-city generator validation | `.venv/bin/python backend/manage.py seed_multicity_realism --validate-only` | PASS; 16.200 subscriptions validated | 22.15 s |
| Maltepe validator | direct read-only `validate_maltepe_mvp_snapshot` | PASS; 20 checks | database unchanged |
| Deterministic RAG benchmark | `.venv/bin/python backend/manage.py benchmark_rag --profile deterministic --format text` | 10/10; Hit@1 1.000; Hit@3 1.000; MRR 1.000; forbidden 0; fallback 0 | 2.13 s |
| Local semantic RAG benchmark | `.venv/bin/python backend/manage.py benchmark_rag --profile semantic --embedding-profile ollama-qwen3-4b --format text` | 6/6; Hit@1 0.500; Hit@3 1.000; MRR 0.722; forbidden 0; fallback 0 | 24.40 s |

## Test kapsamı

- Backend model/service/API/generator/regression testleri `backend/apps/*/tests/` altında.
- MCP tool unit testleri `mcp_servers/{network,customer,rules,compensation}/tests/` altında.
- Ortak MCP BackendClient/contract/security testleri `mcp_servers/shared/tests/` ve core testleri altında.
- PostgreSQL/pgvector migration, provider, multi-set isolation, semantic/hybrid search ve benchmark testleri `backend/apps/rag/tests/` altında.
- Maltepe fixed regression ve multi-city 30/30 ground truth testleri dataset testleri içindedir.

## Veritabanı ve smoke notları

- Audit sorguları yalnız `SELECT`/Django ORM read işlemleri yaptı; seed veya migration üretmedi.
- `SourceDocument=10`, `DocumentChunk=74`, physical `DocumentChunkEmbedding=296` doğrulandı.
- Aktif embedding setleri Gemini 74 ve Qwen3 4B 74'tür; tarihsel Nomic ve Qwen3 0.6B setleri 74'er kayıttır.
- Local semantic benchmark Ollama/Qwen3 4B'yi kullandı. Gemma chat/LLM çağrısı yapılmadı.
- Gemini external API smoke bu REV-00'da tekrar çalıştırılmadı; external credential/network baseline'a zorunlu kılınmadı. Gemini adapter ve provider isolation full suite kapsamındadır.

## Warning ve başarısızlık politikası

Full suite ve targeted gate özetlerinde warning raporlanmadı. Skip, xfail, deselected veya collection error oluşmadı. Bir doğrulama başarısız olsaydı REV-00 kapsamında kod/test düzeltilmeden komut ve root cause burada belgelenecekti.
