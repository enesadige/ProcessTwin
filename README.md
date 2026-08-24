# ProcessTwin

ProcessTwin is an explainable telecom operations platform built around two complementary workflows:

- **AI Analysis** answers Turkish operational questions about alarms, outages, network topology, verified customer impact, root-cause correlation, compensation, rules, and evidence.
- **ProcessTwin** compares a baseline and a candidate what-if scenario for a simulated network failure without changing the source operational world.

All business facts come from deterministic backend and domain services. An LLM can help interpret bounded language and produce a grounded narrative, but it does **not** calculate operational facts, select a `RuleVersion`, determine customer impact, or invent evidence.

> **Synthetic-data notice:** the repository contains a deterministic, multi-city synthetic telecom dataset and synthetic rule/procedure documents. It contains no production network connection, real customer data, or real commercial policy.

## Main Capabilities

- **AI Analysis:** deterministic structured-query parsing, orchestration, clarification, and safe fallback behavior for Turkish operational requests.
- **MCP tool layer:** Network, Customer, Rules, Compensation, and Simulation adapters expose bounded backend capabilities without duplicating business logic.
- **Deterministic operations domain:** customer/subscription impact, topology traversal, path diversity and failover classification, alarm correlation, root-cause ranking, and compensation evaluation.
- **RAG for approved documents:** rule and procedure sources are ingested as versioned documents, chunks, and embeddings; retrieval preserves source provenance.
- **Evidence:** `QueryRun`, `EvidenceRecord`, and `DecisionEvidence` preserve execution provenance and deterministic calculation references.
- **ProcessTwin simulation:** deterministic baseline/candidate runs, virtual time, projected impact, SLA comparison, simulated compensation, replay lineage, and `SimulationEvidence`.
- **Snapshot-based data world:** exact snapshot selection prevents cross-snapshot mixing and makes the synthetic data generation reproducible.

## Architecture

```text
React + Vite frontend
        |
        | /api through the Vite proxy
        v
Django REST API
        |
        +-- Orchestration and deterministic tool planning
        |       |
        |       +-- MCP adapter/tool boundary
        |               |
        |               +-- authenticated internal Django API
        |
        +-- Domain services -> PostgreSQL + pgvector
        +-- RAG indexing/retrieval -> approved document corpus
        +-- LLM provider -> grounded narration only
```

MCP is an adapter boundary, not a separate source of business truth and not a direct database access layer. In normal runtime, `ORCHESTRATION_MCP_TRANSPORT=direct` routes the tool call through the application adapter and the internal API. The allowlisted `stdio` transport is supported for local/acceptance scenarios; persistent MCP listeners on ports 8101-8106 are **not** the normal application runtime model.

RAG is used for approved synthetic rule/procedure documents. It does not calculate alarm counts, customer impact, compensation amounts, or simulation results. LLM provider output is validated against backend-produced canonical facts before it reaches the user.

## Technology Stack

| Area | Technology |
| --- | --- |
| Backend | Python 3.12, Django, Django REST Framework |
| Frontend | React, TypeScript, Vite |
| Primary data store | PostgreSQL with pgvector |
| Background support | Redis and Celery (optional for the interactive presentation flow) |
| RAG | `SourceDocument`, deterministic chunking, pgvector/full-text retrieval, provider-specific embeddings |
| LLM providers | Groq GPT-OSS, Gemini, NVIDIA, Ollama; mock provider for tests only |
| Integration boundary | MCP SDK adapters with authenticated internal Django API calls |

## Dataset and Snapshots

The main application dataset is a deterministic **multi-city synthetic telecom world**. It models network devices, links, subscriptions, alarms, causal events, outages, verified impact assessments, rules, compensation evaluations, and simulation-local records.

`DatasetVersion` stores generator/version/seed metadata. `DataSnapshot` represents an exact immutable source-data view. The frontend sends an exact snapshot identifier; services do not silently substitute another active snapshot. ProcessTwin reads a source snapshot and writes only simulation-local scenario/run/evidence records.

The canonical presentation snapshot is built in three deterministic stages:

1. base multi-city dataset,
2. checkpointed V3 candidate built from that base snapshot,
3. V3 repair revision used by the frontend.

The repository intentionally does not ship a database dump. A clean clone creates the schema and synthetic data with the commands below.

## Local Setup

### Prerequisites

- macOS or Linux
- Python **3.12**
- Node.js **20+** and npm
- PostgreSQL **16+** with the `pgvector` extension available
- Git
- A supported LLM API key for live AI narration (Groq GPT-OSS is the recommended presentation configuration)
- One embedding option for semantic RAG:
  - Gemini embedding with `GEMINI_API_KEY`, or
  - Ollama with `qwen3-embedding:4b`

Redis is needed when you run Celery-backed work. It is not required for the normal interactive presentation startup sequence below, where Celery is intentionally not started.

### Clone and Install

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

Python packages are pinned in `requirements.txt`; frontend dependencies are locked in `frontend/package-lock.json`. Prefer `npm ci` for a clean, reproducible frontend installation.

### PostgreSQL and pgvector

Create an empty local database and enable pgvector. Adjust the commands and the connection string for your PostgreSQL user, password, host, and port.

```bash
createdb processtwin
psql processtwin -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

### Environment Configuration

```bash
cp .env.example .env
chmod 600 .env
```

Set the following values in `.env`. Do not commit that file or any real secret.

```env
DJANGO_SECRET_KEY=<long-random-django-secret>
DATABASE_URL=postgres://<user>:<password>@127.0.0.1:5432/processtwin

# Recommended presentation LLM: fixed Groq GPT-OSS provider/model contract.
LLM_PROVIDER=groq
GROQ_API_KEY=<groq-api-key>

# LLM and embeddings are intentionally independent choices.
RAG_EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434

# These two values must be the same long random secret.
INTERNAL_API_SERVICE_TOKEN=<long-random-service-token>
MCP_BACKEND_SERVICE_TOKEN=<same-service-token>
MCP_BACKEND_BASE_URL=http://127.0.0.1:8000
ORCHESTRATION_MCP_TRANSPORT=direct
```

Provider choices:

| Use case | Configuration | Requirement |
| --- | --- | --- |
| Groq GPT-OSS narration | `LLM_PROVIDER=groq` | `GROQ_API_KEY`; the provider uses the allowlisted `openai/gpt-oss-120b` model. |
| Gemini embeddings | `RAG_EMBEDDING_PROVIDER=gemini` | `GEMINI_API_KEY` |
| Local Qwen embeddings | `RAG_EMBEDDING_PROVIDER=ollama` | Ollama plus `qwen3-embedding:4b` |
| Local LLM, optional | `LLM_PROVIDER=ollama` | The allowlisted Gemma model in Ollama |

Gemma is **not** required when using Groq GPT-OSS. To use local Qwen embeddings only, install the embedding model:

```bash
ollama pull qwen3-embedding:4b
```

Do not export `VITE_API_BASE_URL` for the normal local flow. The frontend startup command below deliberately unsets it and uses the same-origin Vite `/api` proxy.

### Database Schema and Deterministic Seed

Apply migrations first:

```bash
./.venv/bin/python backend/manage.py migrate
```

Then build the synthetic data chain in order. The Maltepe seed below is a legacy synthetic compatibility prerequisite for the current RAG corpus validation; it is not the main application dataset or the presentation scenario.

```bash
# Compatibility seed required by the current RAG corpus validator.
./.venv/bin/python backend/manage.py seed_maltepe_mvp

# Main multi-city source world.
./.venv/bin/python backend/manage.py seed_multicity_realism

# Resolve IDs dynamically: do not assume a fixed database primary key.
BASE_SNAPSHOT_ID=$(./.venv/bin/python backend/manage.py shell -c \
  "from apps.datasets.models import DataSnapshot; print(DataSnapshot.objects.get(dataset_version__slug='multi-city-realism-v1').pk)")

./.venv/bin/python backend/manage.py seed_multicity_realism \
  --checkpointed-v3 --source-snapshot-id "$BASE_SNAPSHOT_ID"

V3_SNAPSHOT_ID=$(./.venv/bin/python backend/manage.py shell -c \
  "from apps.datasets.models import DataSnapshot; print(DataSnapshot.objects.get(dataset_version__slug='multi-city-realism-v3').pk)")

./.venv/bin/python backend/manage.py seed_multicity_realism \
  --repair-v3 --repair-source-snapshot-id "$V3_SNAPSHOT_ID"
```

If a checkpointed seed is interrupted, resume it with the corresponding command:

```bash
./.venv/bin/python backend/manage.py seed_multicity_realism \
  --checkpointed-v3 --resume --source-snapshot-id "$BASE_SNAPSHOT_ID"

./.venv/bin/python backend/manage.py seed_multicity_realism \
  --repair-v3 --repair-resume --repair-source-snapshot-id "$V3_SNAPSHOT_ID"
```

Optional validation:

```bash
./.venv/bin/python backend/manage.py seed_multicity_realism \
  --dataset-slug multi-city-realism-v3-repair-r1 --validate-only
```

### RAG Corpus, Indexing, and Embeddings

The source Markdown files required by the RAG manifest are versioned under `documents/`. Ingest them into `SourceDocument`, create `DocumentChunk` records, and generate embeddings:

```bash
./.venv/bin/python backend/manage.py seed_rag_corpus
./.venv/bin/python backend/manage.py index_rag_documents

# Local Qwen embedding profile.
./.venv/bin/python backend/manage.py generate_rag_embeddings \
  --provider ollama --embedding-profile ollama-qwen3-4b
```

For Gemini embeddings, use:

```bash
./.venv/bin/python backend/manage.py generate_rag_embeddings --provider gemini
```

### Local Users

Create or reset the local demo accounts with a password of your choice:

```bash
./.venv/bin/python backend/manage.py seed_demo_users --password '<at-least-8-characters>'
```

This prepares `demo_viewer`, `demo_analyst`, `demo_engineer`, and `demo_admin`. For Django's `/admin/` interface, create a Django superuser separately:

```bash
./.venv/bin/python backend/manage.py createsuperuser
```

## Presentation Cold Start

Start the backend first. Do not start Celery or persistent MCP listener processes for this interactive flow.

### 1. Check Existing Processes

```bash
for port in 8000 5173 11434 6379; do
  echo "--- port $port ---"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN || true
done
```

Only stop stale Django or Vite processes that belong to this project. Do not stop PostgreSQL, Ollama, Redis, or unrelated applications without identifying them first.

### 2. Start Django

In terminal one:

```bash
./.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
```

Wait for a successful health response before starting the frontend:

```bash
curl -fsS http://127.0.0.1:8000/api/health/
```

### 3. Verify MCP Readiness

Load the local environment without printing its values, then call the authenticated internal health endpoint:

```bash
set -a
source .env
set +a

curl -fsS \
  -H "Authorization: Bearer ${INTERNAL_API_SERVICE_TOKEN}" \
  "http://127.0.0.1:8000/api/internal/v1/mcp/health/?timeout_seconds=5"
```

The response should report readiness for Network, Customer, Rules, Compensation, and Simulation descriptors/probes. If it fails, verify backend health, `MCP_BACKEND_BASE_URL`, and that both service-token variables are non-empty and equal. Never print or share the token values.

### 4. Start Vite in Proxy Mode

In terminal two:

```bash
cd frontend
env -u VITE_API_BASE_URL \
  VITE_API_PROXY_TARGET=http://127.0.0.1:8000 \
  npm run dev -- --host 127.0.0.1 --port 5173
```

### 5. Readiness Checks

```bash
curl -fsS http://127.0.0.1:8000/api/health/
curl -fsSI http://127.0.0.1:5173/
curl -sS -o /dev/null -w "Vite proxy CSRF status: %{http_code}\n" \
  http://127.0.0.1:5173/api/auth/csrf/
```

Expected results: backend health succeeds, the frontend returns `200`, and the proxy CSRF request returns `200`. Open `http://127.0.0.1:5173` in a browser.

## Troubleshooting

| Symptom | Check first | Typical resolution |
| --- | --- | --- |
| `Failed to fetch` | Backend health and Vite terminal | Start Django first, then restart Vite with the proxy command. |
| CORS or CSRF issue | `VITE_API_BASE_URL` | Keep it unset and use the Vite `/api` proxy. |
| MCP readiness failure | backend health, internal URL, service tokens | Use `http://127.0.0.1:8000`; both service tokens must be non-empty and equal. |
| Empty RAG result | corpus, chunks, embeddings | Run corpus seed, indexing, and embedding generation in order. |
| Ollama embedding failure | Ollama process/model | Ensure Ollama is running and `qwen3-embedding:4b` is installed. |
| PostgreSQL `vector` or relation error | migrations and pgvector | Run migrations and enable `CREATE EXTENSION vector`. |
| Port conflict | `lsof` output | Stop only a confirmed stale ProcessTwin Django/Vite process. |

## Development Checks

```bash
./.venv/bin/python backend/manage.py check
./.venv/bin/pytest -q

cd frontend
npm run typecheck
npm run build
```

`scripts/dev.py` can orchestrate backend, frontend, and Celery for development. The manual cold-start sequence above is preferred for presentation use because Celery is not needed and the launcher stops related child processes when one exits.

## Security and Contribution Notes

Before committing, check the worktree and make sure secret files remain ignored:

```bash
git status --short
git check-ignore -v .env
git diff --check
```

Do not commit `.env`, API keys, service tokens, database backups, local virtual environments, `node_modules`, or personal data. `.env.example` contains only variable names and safe placeholders.

## Scope

ProcessTwin is an educational/demonstration project. It does not operate a production network, control network equipment, or process real subscriber data.
