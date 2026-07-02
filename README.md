# R&D Knowledge Map — Nornickel Hackathon

Unified **mining & metallurgy** research knowledge map: links publications, experiments, materials, processes, equipment, facilities, experts, and verified conclusions in a Neo4j graph with semantic RAG (RU/EN).

## Problem we solve

| Pain | Solution |
|------|----------|
| Scattered institutional memory | Ingest PDF/DOCX/URLs → normalized graph + vector index |
| Duplicate literature reviews | Structured search + graph traversal shows what was already studied |
| Disparate interdisciplinary data | Entity links: material → process → experiment → publication |
| Slow manual synthesis | RAG answers with numbered citations + confidence |
| Contradictory conclusions | Contradiction panel + source reliability on documents |

## Architecture

```
Next.js UI (:3000)
    ↓ REST
FastAPI (:8000) — ingest · NLP · RAG · graph analytics
    ↓
Neo4j (graph) · Qdrant (vectors) · MinIO (files) · Ollama (LLM + embeddings)
```

**Models (local, no API keys):**
- LLM: `qwen2.5:7b-instruct`
- Embeddings: `mxbai-embed-large` (1024-dim)

## Entity ontology

| Type | Neo4j label | Example |
|------|-------------|---------|
| Publication | `Document` | Article, report, patent |
| Material | `Material` | Nickel cathode, copper matte |
| Process | `Process` | Electrowinning, heap leaching |
| Experiment | `Experiment` | Protocol + parameters + status |
| Property | `Property` | Concentration, flow rate |
| Equipment | `Equipment` | Diaphragm cell, PVD furnace |
| Facility | `Facility` | Plant, laboratory + country |
| Expert / Team | `Expert`, `Team` | Authors, competence holders |

**Key relationships:** `USES_MATERIAL`, `USES_PROCESS`, `DESCRIBED_IN`, `MEASURED`, `AUTHORED`, `HAS_TOPIC`, `WORKS_AT`, `MENTIONS_EQUIPMENT`

## Hackathon features

- **Multi-parameter queries:** material + process + geography + year + numeric limits
- **Geography:** domestic (Russia/CIS) vs international/global on documents
- **Provenance:** source excerpts [1][2], document type reliability, update metadata
- **Gap analysis:** materials without experiments, missing properties
- **Contradictions:** conflicting measurements for same material + property
- **Coverage matrix:** material × property grid
- **Graph visualization:** full knowledge map with filters
- **Export:** Markdown report, JSON, JSON-LD (`/api/v1/graph/export/json-ld`)
- **Multilingual:** Russian & English queries and documents

## Quick start

```powershell
docker compose up -d
.\scripts\pull-ollama-models.ps1
.\start-backend.bat
npm run dev
```

Open http://localhost:3000

### Demo queries (from case)

1. *What water desalination methods are suitable if feed water has sulfates/chlorides at 200–300 mg/L?*
2. *Catholyte circulation during nickel electrowinning — global practice and optimal flow rate?*
3. *Distribution of Au, Ag, PGMs between matte and slag (last 5 years)?* — use year filter `2021–2026`
4. *Mine water pumping to deep horizons — Russia vs abroad?* — geography: **domestic** / **international**

### Ingest case data

Download corpus from [Yandex Disk](https://disk.yandex.ru/d/npigiuw4Rbe9Pg), then upload PDFs/DOCX via the UI. Run **enrich-all** (auto on first load) to populate graph entities.

## API highlights

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/ingest/file` | Upload document |
| `POST /api/v1/search/json` | RAG + structured filters |
| `GET /api/v1/graph/explore` | Full graph for visualization |
| `GET /api/v1/graph/query` | Structured multi-param search |
| `GET /api/v1/graph/analytics/gaps` | Knowledge gaps |
| `GET /api/v1/graph/analytics/contradictions` | Conflicting values |
| `GET /api/v1/graph/export/json-ld` | FAIR JSON-LD export |

## Tech stack

Next.js 16 · FastAPI · Neo4j · Qdrant · MinIO · Ollama · LangChain

Branch: `scientific-tangle` on [NornikelHack](https://github.com/vsham05/NornikelHack)
