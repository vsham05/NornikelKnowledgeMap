# Scientific Tangle

Full-stack research knowledge system: **Next.js UI** + **NornikelHack FastAPI backend** (Neo4j, Qdrant, MinIO, RAG via **Ollama**).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Next.js (Scientific Tangle UI)          :3000              │
│  Graph · RAG search · ingest · gap analysis                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST
┌──────────────────────────▼──────────────────────────────────┐
│  FastAPI (nornikel-backend)              :8000                  │
│  Ingest · NER · RAG · graph API                                 │
└──┬──────────────┬──────────────┬──────────────┬─────────────────┘
   │              │              │              │
 Neo4j         Qdrant          MinIO         Ollama
 :7687         :6333           :9000         :11434/v1
 graph         vectors         PDF/DOCX      LLM + embeddings
```

## Quick start

### 1. Infrastructure (Docker)

```bash
docker compose up -d
```

Services:
- Neo4j Browser: http://localhost:7474 (`neo4j` / `password123`)
- Qdrant: http://localhost:6333
- MinIO Console: http://localhost:9001 (`minioadmin` / `minioadmin`)

### 2. Ollama (LLM + embeddings)

Install from [https://ollama.com](https://ollama.com), then pull models:

```powershell
.\scripts\pull-ollama-models.ps1
```

Or manually:

```powershell
ollama pull qwen2.5:7b-instruct
ollama pull mxbai-embed-large
```

Verify:

```powershell
ollama list
curl http://localhost:11434/v1/models
```

Backend `.env` (`nornikel-backend/.env`) is preconfigured for Ollama:

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b-instruct
EMBEDDING_BASE_URL=http://localhost:11434/v1
EMBEDDING_MODEL=mxbai-embed-large
EMBEDDING_DIMENSIONS=1024
```

> If you change embedding models, reset the Qdrant volume so vector dimensions match.

### 3. Backend

```bash
cd nornikel-backend
python -m venv .venv
.\.venv\Scripts\activate          # Windows
pip install -e .
set PYTHONPATH=src
python run.py
```

Or from project root: `.\start-backend.bat`

API docs: http://localhost:8000/docs

### 4. Frontend

```bash
npm install
npm run dev
```

Open http://localhost:3000

## Features

| Layer | Capability |
|-------|------------|
| **Ingest** | Upload PDF/DOCX or URL → parse text → MinIO + Neo4j + Qdrant |
| **Graph** | Neo4j knowledge graph visualization |
| **RAG** | Qdrant retrieval + Ollama LLM synthesis |
| **Analytics** | Data gaps, coverage matrix |

## Project layout

```
scientific-tangle/
├── src/                    # Next.js frontend
├── nornikel-backend/       # FastAPI backend (NornikelHack)
├── docker-compose.yaml     # Neo4j, Qdrant, MinIO
├── start-backend.bat
└── scripts/pull-ollama-models.ps1
```

## API (backend)

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/ingest/file` | Upload PDF/DOCX |
| `POST /api/v1/search/json` | RAG query |
| `GET /api/v1/graph/explore` | Graph visualization |
| `GET /api/v1/graph/analytics/gaps` | Data gaps |

## Tech stack

**Frontend:** Next.js 16, React 19, TypeScript, Tailwind

**Backend:** FastAPI, Neo4j, Qdrant, MinIO, LangChain OpenAI client

**AI:** Ollama (`qwen2.5:7b-instruct` + `mxbai-embed-large`)

## License

Backend adapted from [NornikelHack](https://github.com/vsham05/NornikelHack).
