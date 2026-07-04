"""Hybrid ingest routing: page count → local/Yandex, fallback when API down."""

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from domain.dto.document import DocumentChunkDTO, DocumentDTO
from domain.enums import DocumentType
from ingestion.pipeline import IngestionPipeline
from settings import Settings


def _doc(*, pages: int = 0, chunks: int = 1, estimated: int | None = None) -> DocumentDTO:
    chunk_list = [
        DocumentChunkDTO(
            id=uuid4(),
            document_id=uuid4(),
            text="sample",
            chunk_index=i,
            page_number=pages if pages > 0 else None,
        )
        for i in range(chunks)
    ]
    return DocumentDTO(
        id=uuid4(),
        title="test",
        document_type=DocumentType.REPORT,
        file_path="test.pdf",
        chunks=chunk_list,
        estimated_page_count=estimated,
    )


@pytest.fixture
def pipeline() -> IngestionPipeline:
    settings = Settings(
        ingest_hybrid_routing=True,
        ingest_local_max_pages=28,
        yandex_api_key="key",
        yandex_folder_id="folder",
        llm_yandex_fallback_local=True,
    )
    return IngestionPipeline(settings)


def test_short_pdf_routes_local(pipeline: IngestionPipeline):
    provider, reason = asyncio.run(
        pipeline._resolve_ingest_provider(pages=10, chunks=0)
    )
    assert provider == "local"
    assert "short" in reason.lower()


def test_long_pdf_routes_yandex_when_api_ok(pipeline: IngestionPipeline):
    with patch("ingestion.pipeline.check_yandex_api", new_callable=AsyncMock, return_value=True):
        provider, reason = asyncio.run(
            pipeline._resolve_ingest_provider(pages=40, chunks=0)
        )
    assert provider == "yandex"
    assert "long" in reason.lower()


def test_long_pdf_falls_back_local_when_api_down(pipeline: IngestionPipeline):
    with patch("ingestion.pipeline.check_yandex_api", new_callable=AsyncMock, return_value=False):
        provider, reason = asyncio.run(
            pipeline._resolve_ingest_provider(pages=40, chunks=0)
        )
    assert provider == "local"
    assert "unavailable" in reason.lower()


def test_long_docx_uses_estimated_pages(pipeline: IngestionPipeline):
    document = _doc(pages=0, chunks=5, estimated=35)
    with patch("ingestion.pipeline.check_yandex_api", new_callable=AsyncMock, return_value=True):
        provider, _ = asyncio.run(pipeline._resolve_ingest_provider(document))
    assert provider == "yandex"


def test_short_docx_stays_local(pipeline: IngestionPipeline):
    document = _doc(pages=0, chunks=3, estimated=12)
    provider, reason = asyncio.run(pipeline._resolve_ingest_provider(document))
    assert provider == "local"
    assert "short" in reason.lower()


def test_short_local_doc_caps_extraction_batches(pipeline: IngestionPipeline):
    cap = pipeline._resolve_extraction_batch_cap(fast=False, pages=12)
    assert cap == 4


def test_long_local_doc_uncapped_extraction_batches(pipeline: IngestionPipeline):
    cap = pipeline._resolve_extraction_batch_cap(fast=True, pages=40)
    assert cap == 0
