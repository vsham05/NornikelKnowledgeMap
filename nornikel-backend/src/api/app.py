from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import ingestion, search, graph


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
    title="Научный клубок API",
    description="""
    Система для работы с научными знаниями в материаловедении.
    
    **Возможности:**
    - Загрузка PDF/DOCX/веб-страниц
    - Автоматическое извлечение материалов, экспериментов, свойств
    - Построение графа знаний
    - Семантический поиск (RAG)
    - Визуальный поиск изображений
    - Анализ пробелов в данных
    """,
    version="0.1.0",
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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "build": "rag-v4-professional",
        "features": [
            "document-dedup",
            "query-rewrite",
            "multi-query-rrf",
            "idf-rerank",
            "context-compression",
            "dynamic-confidence",
        ],
    }