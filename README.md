# R&D Knowledge Map — Nornickel Hackathon

Mining & metallurgy research knowledge map: ingest PDFs/DOCX, build a Neo4j graph, and run semantic RAG (RU/EN) with citations.

**Repo:** [NornikelHack](https://github.com/vsham05/NornikelHack) · branch `scientific-tangle`

---

## Quick start

**Only Docker Desktop required** — everything else runs in containers (including Ollama + models).

```powershell
git clone https://github.com/vsham05/NornikelHack.git
cd NornikelHack
git checkout scientific-tangle
cd scientific-tangle

copy .env.example .env.docker
.\start-docker.bat
```

Open http://localhost:3000 when startup finishes.

| What | URL |
|------|-----|
| **App (UI)** | http://localhost:3000 |
| **API docs** | http://localhost:8000/docs |
| Neo4j Browser | http://localhost:7474 (`neo4j` / `password123`) |
| MinIO console | http://localhost:9001 (`minioadmin` / `minioadmin`) |

### Daily use

1. Start **Docker Desktop**
2. Run `.\start-docker.bat`
3. Open http://localhost:3000

Stop:

```powershell
docker compose down
```

---

## First run (important)

The **first** `start-docker.bat` takes **10–30+ minutes** because Docker will:

1. Pull container images
2. Build backend + frontend
3. Download Ollama models (~10 GB):
   - `qwen2.5:7b-instruct` — text LLM
   - `mxbai-embed-large` — embeddings
   - `minicpm-v` — image tables (VLM)

Watch model download progress:

```powershell
docker compose logs -f ollama-pull
```

The backend waits until models are ready. Later starts are much faster.

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) — **only requirement**
- **~25 GB** free disk (images + models)
- Ports free: `3000`, `8000`, `11434`, `7474`, `6333`, `9000`

**No separate Ollama install needed.**

---

## Linux / macOS

```bash
cp .env.example .env.docker
docker compose --env-file .env.docker up -d --build
```

---

## What's in Docker

| Service | Role |
|---------|------|
| **frontend** | Next.js UI |
| **backend** | FastAPI — ingest, RAG, graph |
| **neo4j** | Knowledge graph |
| **qdrant** | Vector search |
| **minio** | Document storage |
| **ollama** | LLM + embeddings + vision |
| **ollama-pull** | One-shot model download on first start |

---

## Useful commands

```powershell
# Start everything
docker compose --env-file .env.docker up -d --build

# Stop (keeps data)
docker compose down

# Rebuild after code changes
docker compose --env-file .env.docker up -d --build

# Logs
docker compose logs -f backend
docker compose logs -f ollama-pull

# Re-pull models after changing tier in .env.docker
docker compose --env-file .env.docker run --rm ollama-pull
docker compose --env-file .env.docker up -d backend

# Full reset (graph, vectors, uploads, models)
docker compose down -v
```

---

## Configuration (`.env.docker`)

```env
LLM_MODEL=qwen2.5:7b-instruct
OLLAMA_PULL_MODELS=qwen2.5:7b-instruct,mxbai-embed-large,minicpm-v
```

### Model tiers

| Tier | `LLM_MODEL` | `OLLAMA_PULL_MODELS` (LLM part) | VRAM |
|------|-------------|----------------------------------|------|
| **light** (default) | `qwen2.5:7b-instruct` | `qwen2.5:7b-instruct,...` | ~8 GB |
| **standard** | `qwen2.5:14b-instruct` | `qwen2.5:14b-instruct,...` | ~16 GB |
| **premium** | `qwen2.5:32b-instruct` | `qwen2.5:32b-instruct,...` | ~24 GB |

After changing tier: `docker compose --env-file .env.docker run --rm ollama-pull`

### Yandex Cloud (optional)

```env
YANDEX_API_KEY=your-key
YANDEX_FOLDER_ID=your-folder-id
```

### GPU (optional, NVIDIA)

```powershell
docker compose -f docker-compose.yaml -f docker-compose.gpu.yaml --env-file .env.docker up -d --build
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Docker compose failed` | Start Docker Desktop |
| `qdrant unhealthy` | `docker compose up -d qdrant` (fixed healthcheck in latest compose) |
| Backend not starting | Wait for `ollama-pull`: `docker compose logs ollama-pull` |
| Port in use | Free 3000/8000 or edit `docker-compose.yaml` |
| Slow ingest | Use GPU overlay or Yandex keys for large PDFs |
| Out of disk | `docker system prune` or use light model tier |

---

## Load demo data

1. Download corpus from [Yandex Disk](https://disk.yandex.ru/d/npigiuw4Rbe9Pg)
2. Upload PDFs via http://localhost:3000
3. Wait for ingest

---

## Architecture

```
Browser (:3000)
    → Next.js + FastAPI (Docker)
    → Neo4j · Qdrant · MinIO · Ollama (all Docker)
```

---

## API quick reference

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/ingest/file` | Upload document |
| `POST /api/v1/search/json` | RAG + filters |
| `GET /api/v1/graph/explore` | Full graph |
| `GET /api/v1/graph/export/json-ld` | JSON-LD export |

Docs: http://localhost:8000/docs

---

## Tech stack

Next.js 16 · FastAPI · Neo4j · Qdrant · MinIO · Ollama · LangChain
