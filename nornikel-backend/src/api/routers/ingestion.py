"""Ingestion endpoints — загрузка и обработка документов."""

import asyncio
import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field, HttpUrl

from urllib.parse import urlparse

from api.deps import get_ingestion_pipeline, get_document_db, get_graph_db, get_vector_db
from ingestion.dedup import canonicalize_url
from ingestion.dedup_service import cleanup_duplicate_documents
from ingestion.pipeline import IngestionPipeline
from ingestion.parsers.web_scraper import WebScraper
from storage.document_db import DocumentDB

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingestion"])

BLOCKED_INGEST_HOSTS = frozenset({
    "example.com",
    "www.example.com",
    "example.org",
    "www.example.org",
    "localhost",
    "127.0.0.1",
})


def _validate_ingest_url(url: str) -> None:
    host = urlparse(url).netloc.lower()
    if host in BLOCKED_INGEST_HOSTS:
        raise HTTPException(
            status_code=400,
            detail=f"This URL is blocked for ingest ({host}). Use real source documents only.",
        )


# ================== Task Storage (in-memory) ==================

class TaskStatus(BaseModel):
    """Статус фоновой задачи."""
    task_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    progress: float = Field(0.0, ge=0.0, le=1.0)
    message: str = ""
    result: dict | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None


# In-memory task store
_tasks: dict[str, TaskStatus] = {}


# ================== Request/Response Models ==================

class IngestUrlRequest(BaseModel):
    """Запрос на загрузку веб-страницы."""
    url: HttpUrl
    use_playwright: bool = Field(False, description="Использовать JS-рендеринг")


class IngestResponse(BaseModel):
    """Ответ на загрузку документа."""
    task_id: str
    status: str
    message: str


class DocumentInfo(BaseModel):
    """Информация о загруженном документе."""
    id: str
    title: str
    document_type: str
    authors: list[str]
    year: int | None
    chunks_count: int
    images_count: int
    created_at: str


# ================== Endpoints ==================

@router.post("/file", response_model=IngestResponse)
async def ingest_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
):
    """
    Загружает и обрабатывает файл (PDF/DOCX).
    
    Обработка идет в фоне — сразу возвращается task_id.
    """
    # Валидация типа файла
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: .pdf, .docx"
        )
    
    # Сохраняем файл во временную папку
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    
    # Создаем задачу
    task_id = str(uuid.uuid4())
    _tasks[task_id] = TaskStatus(
        task_id=task_id,
        status="pending",
        message=f"Queued processing of {file.filename}"
    )
    
    # Запускаем в фоне
    background_tasks.add_task(
        _process_file_task,
        task_id=task_id,
        file_path=tmp_path,
        original_filename=file.filename or "unknown",
        pipeline=pipeline
    )
    
    logger.info(f"Created task {task_id} for file: {file.filename}")
    
    return IngestResponse(
        task_id=task_id,
        status="pending",
        message=f"Processing started for {file.filename}"
    )


@router.post("/url", response_model=IngestResponse)
async def ingest_url(
    request: IngestUrlRequest,
    background_tasks: BackgroundTasks,
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
):
    """
    Загружает и обрабатывает веб-страницу по URL.
    """
    url = canonicalize_url(str(request.url))
    _validate_ingest_url(url)

    task_id = str(uuid.uuid4())
    _tasks[task_id] = TaskStatus(
        task_id=task_id,
        status="pending",
        message=f"Queued processing of {request.url}"
    )
    
    background_tasks.add_task(
        _process_url_task,
        task_id=task_id,
        url=url,
        use_playwright=request.use_playwright,
        pipeline=pipeline,
    )
    
    logger.info(f"Created task {task_id} for URL: {url}")
    
    return IngestResponse(
        task_id=task_id,
        status="pending",
        message=f"Processing started for {url}"
    )


@router.get("/status/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """Получить статус задачи обработки."""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/tasks", response_model=list[TaskStatus])
async def list_tasks(limit: int = 50):
    """Список всех задач."""
    tasks = sorted(
        _tasks.values(),
        key=lambda t: t.created_at,
        reverse=True
    )
    return tasks[:limit]


@router.get("/documents", response_model=list[dict])
async def list_documents(graph_db=Depends(get_graph_db)):
    """List all ingested documents from the graph."""
    return graph_db.list_documents()


@router.post("/dedupe/cleanup")
async def dedupe_cleanup(
    graph_db=Depends(get_graph_db),
    vector_db=Depends(get_vector_db),
):
    """Remove duplicate documents already stored in the graph/vector DB."""
    return cleanup_duplicate_documents(graph_db, vector_db)


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    graph_db=Depends(get_graph_db),
    vector_db=Depends(get_vector_db),
):
    """Delete a document and its chunks from Neo4j and Qdrant."""
    deleted = graph_db.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        vector_db.delete_document_chunks(document_id)
    except Exception as e:
        logger.warning(f"Qdrant cleanup for {document_id}: {e}")

    return {"status": "deleted", "document_id": document_id}


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    graph_db=Depends(get_graph_db)
):
    """Детальная информация о документе."""
    db = graph_db
    with db.driver.session() as session:
        result = session.run("""
            MATCH (d:Document {id: $id})
            OPTIONAL MATCH (d)-[:CONTAINS_IMAGE]->(i:Image)
            OPTIONAL MATCH (e:Experiment)-[:DESCRIBED_IN]->(d)
            OPTIONAL MATCH (m:Material)<-[:USES_MATERIAL]-(e)
            RETURN d,
                   collect(DISTINCT {
                       id: i.id,
                       type: i.image_type,
                       caption: i.caption,
                       description: i.ai_description
                   }) as images,
                   collect(DISTINCT {
                       experiment_id: e.id,
                       regime: e.regime_name,
                       material: m.name
                   }) as experiments
        """, {"id": document_id})
        
        record = result.single()
        if not record:
            raise HTTPException(status_code=404, detail="Document not found")
        
        doc = dict(record["d"])
        doc["images"] = [img for img in record["images"] if img.get("id")]
        doc["experiments"] = [exp for exp in record["experiments"] if exp.get("experiment_id")]
        
        return doc


# ================== Background Tasks ==================

def _task_result_from_ingest(result, source_label: str) -> dict:
    if result.skipped:
        return {
            "document_id": result.document_id,
            "action": result.action,
            "deduplicated": True,
            "title": source_label,
        }
    document = result.document
    assert document is not None
    return {
        "document_id": result.document_id,
        "action": result.action,
        "deduplicated": False,
        "title": document.title,
        "chunks_count": len(document.chunks),
        "images_count": len(document.images),
    }


async def _process_file_task(
    task_id: str,
    file_path: Path,
    original_filename: str,
    pipeline: IngestionPipeline
):
    """Фоновая задача обработки файла."""
    task = _tasks[task_id]
    task.status = "processing"
    task.progress = 0.1
    task.message = f"Parsing {original_filename}..."
    
    try:
        result = await pipeline.process_file(file_path, original_filename=original_filename)
        task.progress = 1.0
        task.status = "completed"
        task.completed_at = datetime.now()
        task.message = result.message
        task.result = _task_result_from_ingest(result, original_filename)
        logger.info(f"Task {task_id} completed: {result.document_id} ({result.action})")
    
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        task.status = "failed"
        task.error = str(e)
        task.completed_at = datetime.now()
        task.message = f"Failed: {str(e)}"
    
    finally:
        # Удаляем временный файл
        try:
            file_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file: {e}")


async def _process_url_task(
    task_id: str,
    url: str,
    use_playwright: bool,
    pipeline: IngestionPipeline
):
    """Фоновая задача обработки веб-страницы."""
    task = _tasks[task_id]
    task.status = "processing"
    task.progress = 0.1
    task.message = f"Scraping {url}..."
    
    try:
        scraper = WebScraper(use_playwright=use_playwright)
        try:
            task.progress = 0.3
            task.message = f"Scraping {url}..."
            document = await scraper.scrape(url)

            task.progress = 0.7
            task.message = "Checking for duplicates..."
            result = await pipeline.ingest_url_document(document, url)

            task.progress = 1.0
            task.status = "completed"
            task.completed_at = datetime.now()
            task.message = result.message
            task.result = _task_result_from_ingest(result, document.title)
            logger.info(f"Task {task_id} completed: {result.document_id} ({result.action})")
        finally:
            await scraper.close()
    
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        task.status = "failed"
        task.error = str(e)
        task.completed_at = datetime.now()
        task.message = f"Failed: {str(e)}"