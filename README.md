# R&D Knowledge Map — Nornickel Hackathon

Mining & metallurgy research knowledge map: ingest PDFs/DOCX, build a Neo4j graph, and run semantic RAG (RU/EN) with citations.

**Repo:** [NornikelHack](https://github.com/vsham05/NornikelHack) · branch `scientific-tangle`

---

## Quick start (daily use)

Every time you work on the project:

1. **Start Ollama** — open the Ollama app (system tray icon must be running).
2. **Start Docker Desktop** — wait until it says “Running”.
3. **Run one command** from the project folder:

```powershell
cd scientific-tangle
.\start-docker.bat
```

4. Open the app:

| What | URL |
|------|-----|
| **Frontend (UI)** | http://localhost:3000 |
| **Backend (API docs)** | http://localhost:8000/docs |
| **Health check** | http://localhost:8000/health |

That’s it — `start-docker.bat` starts **everything**: Neo4j, Qdrant, MinIO, **backend**, and **frontend**. There is no separate backend or `npm run dev` step.

To stop:

```powershell
docker compose down
```

---

## First-time setup (new PC)

Do this once on a new machine.

### Step 1 — Install software

| Software | Download | Purpose |
|----------|----------|---------|
| **Docker Desktop** | https://www.docker.com/products/docker-desktop/ | Databases + backend + frontend |
| **Ollama** | https://ollama.com/download | LLM, embeddings, vision (runs on your PC) |

You need **~15 GB** free disk. Ports `3000`, `8000`, and `11434` must be free.

### Step 2 — Clone the repo

```powershell
git clone https://github.com/vsham05/NornikelHack.git
cd NornikelHack
git checkout scientific-tangle
cd scientific-tangle
```

### Step 3 — Pull AI models (one-time)

Open Ollama, then in PowerShell or CMD:

```powershell
ollama pull qwen2.5:7b-instruct
ollama pull mxbai-embed-large
ollama pull minicpm-v
```

~10 GB download. Models stay on your PC — Docker does **not** download them again.

**Optional — better quality (more VRAM):**

```powershell
ollama pull qwen2.5:14b-instruct
```

Then set `LLM_MODEL=qwen2.5:14b-instruct` in `.env.docker`.

### Step 4 — Config file

```powershell
copy .env.example .env.docker
```

Edit `.env.docker` only if you need Yandex API keys or a different LLM model.

### Step 5 — Start

```powershell
.\start-docker.bat
```

Open http://localhost:3000 when it finishes.

---

## Linux / macOS

Same idea — install [Docker](https://docs.docker.com/get-docker/) and [Ollama](https://ollama.com/download), pull the three models, then:

```bash
cp .env.example .env.docker
docker compose --env-file .env.docker up -d --build
```

---

## Useful commands

```powershell
# Start (same as start-docker.bat, after Ollama is running)
docker compose --env-file .env.docker up -d --build

# Stop all containers (keeps your data)
docker compose down

# Rebuild after you changed code
docker compose --env-file .env.docker up -d --build

# Watch backend logs
docker compose logs -f backend

# Watch all services
docker compose logs -f

# Full reset — deletes graph, vectors, uploads (NOT Ollama models)
docker compose down -v
```

---

## Admin URLs

| Service | URL | Login |
|---------|-----|-------|
| App UI | http://localhost:3000 | — |
| API docs | http://localhost:8000/docs | — |
| Neo4j Browser | http://localhost:7474 | `neo4j` / `password123` |
| MinIO console | http://localhost:9001 | `minioadmin` / `minioadmin` |

---

## Configuration (`.env.docker`)

Copy from `.env.example`. Most users can leave defaults.

```env
# Local LLM (must match a model you pulled in Ollama)
LLM_MODEL=qwen2.5:7b-instruct

# Optional — better ingest on large PDFs (needs Yandex Cloud account)
YANDEX_API_KEY=
YANDEX_FOLDER_ID=
```

### Model tiers

| Tier | Ollama model | VRAM |
|------|--------------|------|
| light (default) | `qwen2.5:7b-instruct` | ~8 GB |
| standard | `qwen2.5:14b-instruct` | ~16 GB |
| premium | `qwen2.5:32b-instruct` | ~24 GB |

Embeddings and image-table vision always use `mxbai-embed-large` and `minicpm-v`.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Ollama is not running` | Open Ollama from the Start menu / Applications |
| `Missing models` | Run the three `ollama pull` commands in first-time setup |
| `Docker compose failed` | Start Docker Desktop and wait until it’s ready |
| UI loads but search/ingest fails | Check http://localhost:8000/health — backend must be up |
| Backend errors in logs | Keep Ollama running while using the app |
| Port already in use | Stop other apps on 3000/8000 or change ports in `docker-compose.yaml` |
| Slow ingest on big PDFs | Use 14B/32B model or add Yandex API keys |

---

## Load demo data

1. Download the case corpus from [Yandex Disk](https://disk.yandex.ru/d/npigiuw4Rbe9Pg)
2. Open http://localhost:3000
3. Upload PDFs/DOCX via the UI
4. Wait for ingest to finish (large PDFs can take a while on 7B)

### Sample questions

- *What water desalination methods work when feed water has sulfates/chlorides at 200–300 mg/L?*
- *Catholyte circulation during nickel electrowinning — global practice and optimal flow rate?*
- *Distribution of Au, Ag, PGMs between matte and slag (last 5 years)?*

---

## How it fits together

```
Browser (:3000)
    → Next.js frontend (Docker)
    → FastAPI backend (Docker)
    → Neo4j · Qdrant · MinIO (Docker)
    → Ollama on your PC (:11434)
        qwen2.5:7b-instruct  — text LLM
        mxbai-embed-large    — embeddings
        minicpm-v            — image tables (VLM)
```

**Hybrid ingest:** PDFs ≤28 pages use local Ollama; longer PDFs use Yandex API if keys are set in `.env.docker`.

---

## API quick reference

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/ingest/file` | Upload document |
| `POST /api/v1/search/json` | RAG + filters |
| `GET /api/v1/graph/explore` | Full knowledge graph |
| `GET /api/v1/graph/analytics/gaps` | Knowledge gaps |
| `GET /api/v1/graph/analytics/contradictions` | Conflicting values |
| `GET /api/v1/graph/export/json-ld` | JSON-LD export |

Interactive docs: http://localhost:8000/docs

---

## Tech stack

Next.js 16 · FastAPI · Neo4j · Qdrant · MinIO · Ollama · LangChain
