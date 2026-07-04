# R&D Knowledge Map — Nornickel Hackathon

Mining & metallurgy research knowledge map: ingest PDFs/DOCX, build a Neo4j graph, and run semantic RAG (RU/EN) with citations.

**Repo:** [NornikelHack](https://github.com/vsham05/NornikelHack) · branch `scientific-tangle`

---

## Quick start

**Docker only** — Neo4j, Qdrant, MinIO, Ollama, backend, and frontend all run in containers.

### Linux / macOS

```bash
git clone https://github.com/vsham05/NornikelHack.git
cd NornikelHack
git checkout scientific-tangle
cd scientific-tangle

cp .env.example .env.docker
chmod +x start-docker.sh scripts/*.sh
./start-docker.sh
```

Or with Make:

```bash
make up
```

### Windows

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

| OS | Start | Stop |
|----|-------|------|
| Linux / macOS | `./start-docker.sh` or `make up` | `docker compose down` or `make down` |
| Windows | `.\start-docker.bat` | `docker compose down` |

After **code changes** to the backend only (faster than a full restart):

```bash
./scripts/restart-backend.sh    # Linux / macOS
make rebuild-backend            # same via Make
```

```powershell
docker compose --env-file .env.docker up -d --no-deps --build backend
```

---

## First run (important)

The **first** start takes **10–30+ minutes** because Docker will:

1. Pull container images
2. Build backend + frontend
3. Download Ollama models (~10 GB):
   - `qwen3:8b` (default) — text LLM
   - `mxbai-embed-large` — embeddings
   - `minicpm-v` — image tables (VLM)

Watch model download progress:

```bash
docker compose logs -f ollama-pull
```

The backend waits until models are ready. Later starts are much faster.

### Prerequisites

| Requirement | Notes |
|-------------|--------|
| **Docker** | [Docker Engine](https://docs.docker.com/engine/install/) (Linux) or [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows / macOS) |
| **NVIDIA GPU** | Required for Ollama inference (CPU-only mode is blocked) |
| **Disk** | ~25 GB free (images + models) |
| **Ports** | `3000`, `8000`, `11434`, `7474`, `6333`, `9000` available |

**No separate Ollama install** — models run inside Docker.

---

## GPU setup

### Linux (NVIDIA)

1. Install [NVIDIA drivers](https://www.nvidia.com/Download/index.aspx) and verify: `nvidia-smi`
2. Install [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html):

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

3. Test GPU inside Docker:

```bash
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

4. Run `./start-docker.sh` — it verifies GPU-only Ollama before finishing.

### Windows

- Install NVIDIA drivers
- Docker Desktop → **Settings → Resources → GPU** → enable
- Run `.\start-docker.bat`

### Verify Ollama uses GPU

```bash
docker exec skg-ollama ollama ps    # must show GPU, not CPU
make verify-gpu                      # full probe
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

```bash
# Start everything (Linux / macOS)
./start-docker.sh
# or
docker compose --env-file .env.docker up -d --build

# Stop (keeps data)
docker compose down

# Rebuild after code changes
docker compose --env-file .env.docker up -d --build

# Backend only (fast)
./scripts/restart-backend.sh

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
LLM_MODEL=qwen3:8b
OLLAMA_PULL_MODELS=qwen3:8b,mxbai-embed-large,minicpm-v
```

### Model tiers

| Tier | `LLM_MODEL` | `OLLAMA_PULL_MODELS` (LLM part) | VRAM |
|------|-------------|----------------------------------|------|
| **default** | `qwen3:8b` | `qwen3:8b,...` | ~6 GB |
| **light** | `qwen2.5:7b-instruct` | `qwen2.5:7b-instruct,...` | ~8 GB |
| **standard** | `qwen2.5:14b-instruct` | `qwen2.5:14b-instruct,...` | ~16 GB |
| **premium** | `qwen2.5:32b-instruct` | `qwen2.5:32b-instruct,...` | ~24 GB |

After changing tier: `docker compose --env-file .env.docker run --rm ollama-pull`

### Yandex Cloud (optional)

Long PDFs and DOCX files (>28 estimated pages) use Yandex when keys are set **and** the API is reachable. Shorter files always use local Ollama. If Yandex is down, misconfigured, or rate-limited, the backend **automatically falls back to local Ollama** (`LLM_YANDEX_FALLBACK_LOCAL=true` by default). Check status via `GET /api/config/llm` (`yandex_usable`, `effective_provider`).

```env
YANDEX_API_KEY=your-key
YANDEX_FOLDER_ID=your-folder-id
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `docker: command not found` | Install Docker Engine (Linux) or Docker Desktop |
| `Docker daemon is not running` | `sudo systemctl start docker` (Linux) or start Docker Desktop |
| `Docker cannot access the NVIDIA GPU` | Install `nvidia-container-toolkit`, restart Docker (see GPU setup) |
| `permission denied` on `./start-docker.sh` | `chmod +x start-docker.sh scripts/*.sh` |
| `qdrant unhealthy` | `docker compose up -d qdrant` |
| Backend not starting | Wait for `ollama-pull`: `docker compose logs ollama-pull` |
| Port in use | Free 3000/8000 or edit `docker-compose.yaml` |
| Slow ingest | Use GPU or Yandex keys for large PDFs |
| Yandex errors / fallback | Local Ollama used automatically; see `GET /api/config/llm` |
| Out of disk | `docker system prune` or use light model tier |
| Script `^M` / bad interpreter (Linux) | Files use LF via `.gitattributes`; `git checkout -- scripts/` |

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
