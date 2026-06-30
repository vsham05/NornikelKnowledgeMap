"""Зависимости для FastAPI endpoints."""

from functools import lru_cache

from ingestion.pipeline import IngestionPipeline
from search.rag_service import RAGService
from storage.graph_db import GraphDB
from storage.vector_db import VectorDB
from storage.document_db import DocumentDB
from settings import Settings, get_settings


@lru_cache
def get_graph_db() -> GraphDB:
    """Singleton GraphDB."""
    return GraphDB(get_settings())


@lru_cache
def get_vector_db() -> VectorDB:
    """Singleton VectorDB."""
    return VectorDB(get_settings())


@lru_cache
def get_document_db() -> DocumentDB:
    """Singleton DocumentDB."""
    return DocumentDB(get_settings())


@lru_cache
def get_ingestion_pipeline() -> IngestionPipeline:
    """Singleton IngestionPipeline."""
    return IngestionPipeline(get_settings())


@lru_cache
def get_rag_service() -> RAGService:
    """Singleton RAGService."""
    return RAGService(get_settings())