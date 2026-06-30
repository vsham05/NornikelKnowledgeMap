import asyncio
from pathlib import Path

import typer
from loguru import logger

from settings import get_settings
from ingestion.pipeline import IngestionPipeline
from search.rag_service import RAGService
from domain.dto.query import UserQueryDTO
from storage.graph_db import GraphDB

app = typer.Typer()


@app.command()
def ingest(file_path: Path):
    """Ingest a PDF or DOCX into the knowledge base."""
    if file_path.suffix.lower() not in (".pdf", ".docx"):
        logger.error(f"Unsupported file type: {file_path.suffix}")
        raise typer.Exit(1)

    async def run():
        pipeline = IngestionPipeline(get_settings())
        return await pipeline.process_file(file_path)

    result = asyncio.run(run())
    if result.skipped:
        typer.echo(f"Skipped (duplicate): {result.message}")
        typer.echo(f"Existing document ID: {result.document_id}")
        raise typer.Exit(0)

    document = result.document
    assert document is not None
    typer.echo(f"Action: {result.action}")
    typer.echo(f"Document ID: {document.id}")
    typer.echo(f"Title: {document.title}")
    typer.echo(f"Chunks: {len(document.chunks)}")


@app.command()
def search(query: str):
    """RAG search over ingested documents."""
    async def run():
        rag = RAGService(get_settings())
        return await rag.answer_question(UserQueryDTO(text=query))

    result = asyncio.run(run())
    typer.echo(result.answer_text or "No answer generated.")
    if result.document_ids:
        typer.echo(f"Sources: {', '.join(str(d) for d in result.document_ids)}")


@app.command()
def stats():
    """Knowledge graph statistics."""
    db = GraphDB(get_settings())
    counts = db.get_stats()
    typer.echo("Knowledge graph statistics:")
    for key, value in counts.items():
        typer.echo(f"  {key}: {value}")


if __name__ == "__main__":
    app()
