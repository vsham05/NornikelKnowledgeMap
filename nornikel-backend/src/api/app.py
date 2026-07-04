from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from api.routers import ingestion, search, graph, config

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
_FAVICON_PATH = _STATIC_DIR / "favicon.svg"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown hooks."""
    # Startup
    from settings import get_settings
    from storage.graph_db import GraphDB
    
    settings = get_settings()
    # Pre-connect to Neo4j
    try:
        db = GraphDB(settings)
        with db.driver.session() as session:
            session.run("RETURN 1").single()
        print(f"Neo4j connected: {settings.neo4j_uri}")

        from storage.vector_db import VectorDB
        from ingestion.dedup_service import cleanup_duplicate_documents

        cleanup = cleanup_duplicate_documents(db, VectorDB(settings))
        if cleanup["removed_count"]:
            print(f"Removed {cleanup['removed_count']} duplicate document(s) on startup")
    except Exception as e:
        print(f"Neo4j connection failed: {e}")
    
    yield
    
    # Shutdown (cleanup если нужно)
    print("Shutting down")


app = FastAPI(
    title="R&D Knowledge Map API",
    description="""
    Unified R&D knowledge map for mining and metallurgy.
    
    **Capabilities:**
    - Ingest articles, reports, patents (RU/EN)
    - NLP extraction: materials, processes, equipment, experiments, experts
    - Neo4j knowledge graph with provenance and geography
    - Multi-parameter structured queries + semantic RAG
    - Gap analysis, contradictions, JSON-LD export
    """,
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(ingestion.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(graph.router, prefix="/api/v1")
app.include_router(config.router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "name": "Научный клубок",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": {
            "ingestion": "/api/v1/ingest",
            "search": "/api/v1/search",
            "graph": "/api/v1/graph",
            "analytics": "/api/v1/graph/analytics"
        }
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    if _FAVICON_PATH.is_file():
        return FileResponse(_FAVICON_PATH, media_type="image/svg+xml")
    return Response(status_code=204)


@app.get("/health")
async def health():
    from infra.llm_runtime import get_llm_provider, get_yandex_model
    from settings import get_settings

    settings = get_settings()
    provider = get_llm_provider()
    return {
        "status": "ok",
        "build": "hackathon-rd-knowledge-map-v1",
        "llm_provider": provider,
        "llm_model": (
            f"gpt://{settings.yandex_folder_id}/{get_yandex_model()}"
            if provider == "yandex"
            else settings.llm_model
        ),
        "features": [
            "mining-metallurgy-ontology",
            "document-dedup",
            "query-rewrite",
            "multi-query-rrf",
            "idf-rerank",
            "context-compression",
            "dynamic-confidence",
            "multilingual-ru-en",
            "document-scoped-rag",
            "cross-encoder-rerank",
            "citation-isolation",
            "document-disambiguation",
            "aggregate-map-reduce",
            "structured-graph-query",
            "geography-filter",
            "numeric-range-filter",
            "contradiction-detection",
            "json-ld-export",
            "full-graph-visualization",
        ],
    }