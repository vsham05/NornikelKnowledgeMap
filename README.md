# R&D Knowledge Map — Научный Клубок

Mining & metallurgy R&D knowledge map: ingest PDF/DOCX, build a Neo4j graph, explore entities interactively, and run semantic RAG in **Russian and English** with citations.

**Repository:** [NornikelKnowledgeMap](https://github.com/vsham05/NornikelKnowledgeMap)

---

## What it does

| Capability | Description |
|------------|-------------|
| **Ingest** | PDF/DOCX → MinIO · text chunks → Qdrant · entities → Neo4j |
| **Graph UI** | Materials, processes, experiments, teams, facilities — clustered layout |
| **RAG Q&A** | Hybrid retrieval (embeddings + keywords) with cited answers |
| **RU / EN** | Questions and documents in either language; Russian queries use a translate→search→answer→translate pipeline |
| **Hybrid LLM** | Local Ollama (GPU) for short docs; optional Yandex API for long PDFs |

---

## Quick start

**Docker only** — Neo4j, Qdrant, MinIO, Ollama, backend, and frontend run in containers. **NVIDIA GPU required** for Ollama (CPU inference is blocked).

### Linux / macOS

```bash
git clone https://github.com/vsham05/NornikelKnowledgeMap.git
cd NornikelKnowledgeMap

cp .env.example .env.docker
chmod +x start-docker.sh scripts/*.sh
./start-docker.sh
```

Or: `make up`

### Windows

```powershell
git clone https://github.com/vsham05/NornikelKnowledgeMap.git
cd NornikelKnowledgeMap

copy .env.example .env.docker
.\start-docker.bat
```

Open **http://localhost:3000** when startup finishes.

| Service | URL | Credentials |
|---------|-----|-------------|
| **App** | http://localhost:3000 | — |
| **API docs** | http://localhost:8000/docs | — |
| **Neo4j** | http://localhost:7474 | `neo4j` / `password123` |
| **MinIO** | http://localhost:9001 | `minioadmin` / `minioadmin` |

### Daily use

| OS | Start | Stop |
|----|-------|------|
| Linux / macOS | `./start-docker.sh` or `make up` | `make down` or `docker compose down` |
| Windows | `.\start-docker.bat` | `docker compose down` |

**Backend-only rebuild** after code changes (faster):

```bash
./scripts/restart-backend.sh   # Linux / macOS
make rebuild-backend
```

```powershell
docker compose --env-file .env.docker up -d --no-deps --build backend
```

---

## First run

The first start takes **10–30+ minutes** (images, builds, ~10 GB Ollama models):

| Model | Role |
|-------|------|
| `qwen3:8b` | Text LLM (default) |
| `mxbai-embed-large` | Embeddings |
| `minicpm-v` | Table/image VLM |

```bash
docker compose logs -f ollama-pull
```

### Prerequisites

- [Docker Engine](https://docs.docker.com/engine/install/) (Linux) or [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows)
- **NVIDIA GPU** + drivers; [Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) on Linux
- ~25 GB disk · ports `3000`, `8000`, `11434`, `7474`, `6333`, `9000` free

Verify GPU: `docker exec skg-ollama ollama ps` (must show **GPU**, not CPU)

---

## Configuration (`.env.docker`)

Copy from `.env.example`:

```env
LLM_MODEL=qwen3:8b
OLLAMA_PULL_MODELS=qwen3:8b,mxbai-embed-large,minicpm-v
RAG_RU_TRANSLATE_PIPELINE=true
```

| Tier | `LLM_MODEL` | VRAM |
|------|-------------|------|
| **default** | `qwen3:8b` | ~6 GB |
| light | `qwen2.5:7b-instruct` | ~8 GB |
| standard | `qwen2.5:14b-instruct` | ~16 GB |
| premium | `qwen2.5:32b-instruct` | ~24 GB |

**Yandex Cloud (optional)** — long PDFs (>28 pages) can route to Yandex when keys are set; falls back to local Ollama automatically:

```env
YANDEX_API_KEY=your-key
YANDEX_FOLDER_ID=your-folder-id
```

Check runtime provider: `GET /api/config/llm`

**Russian RAG** — when `RAG_RU_TRANSLATE_PIPELINE=true`, Russian questions are translated to English for retrieval, answered in English from excerpts, then translated back to Russian.

---

## Architecture

```
Browser (:3000)
  → Next.js frontend
  → FastAPI backend
  → Neo4j (graph) · Qdrant (vectors) · MinIO (files) · Ollama (LLM/embeddings/VLM)
```

---

## API

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/v1/ingest/file` | Upload PDF/DOCX |
| GET | `/api/v1/ingest/active` | Ingest in progress (Q&A blocked while true) |
| POST | `/api/v1/search/json` | RAG search with filters |
| GET | `/api/v1/graph/explore` | Full knowledge graph |
| GET | `/api/v1/graph/export/json-ld` | JSON-LD export |

Interactive docs: http://localhost:8000/docs

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Docker not running | Start Docker Desktop or `sudo systemctl start docker` |
| GPU not available in Docker | Install `nvidia-container-toolkit`, restart Docker |
| `permission denied` on scripts | `chmod +x start-docker.sh scripts/*.sh` |
| Backend waits forever | `docker compose logs -f ollama-pull` |
| Port in use | Free 3000/8000 or edit `docker-compose.yaml` |
| Russian Q&A misses context | Ensure `RAG_RU_TRANSLATE_PIPELINE=true`, rebuild backend |
| Out of disk | `docker system prune` or use a lighter model tier |
| Full reset | `docker compose down -v` |

---

## Demo data

1. [Corpus on Yandex Disk](https://disk.yandex.ru/d/npigiuw4Rbe9Pg)
2. Upload via http://localhost:3000
3. Wait for ingest to complete before searching

---

## Tech stack

Next.js 16 · FastAPI · Neo4j · Qdrant · MinIO · Ollama · LangChain
