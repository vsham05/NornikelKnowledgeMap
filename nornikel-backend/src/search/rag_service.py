"""RAG orchestration: query rewrite → hybrid retrieve → compress → cited answers."""

from __future__ import annotations

import logging
from uuid import UUID

from domain.dto.query import SearchResultDTO, SourceExcerptDTO, UserQueryDTO
from infra.embedding_client import EmbeddingClient
from infra.llm_client import LLMClient
from search.citations import (
    ANSWER_SYSTEM,
    citation_coverage,
    extract_person_facts_from_chunks,
    format_grounded_answer,
    is_name_question,
    validate_facts,
)
from search.context import compress_chunks
from search.query_rewrite import auxiliary_retrieval_queries, rewrite_query_for_retrieval
from search.relevance import compute_confidence
from search.retrieval import HybridRetriever
from settings import Settings
from storage.graph_db import GraphDB
from storage.vector_db import VectorDB

logger = logging.getLogger(__name__)

RETRIEVAL_LIMIT = 8


class RAGService:
    """Production-style RAG: rewrite → hybrid multi-query retrieve → answer with citations."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm_client = LLMClient(settings)
        self.embedding_client = EmbeddingClient(settings)
        self.vector_db = VectorDB(settings)
        self.graph_db = GraphDB(settings)
        self.retriever = HybridRetriever(
            self.vector_db, self.graph_db, self.embedding_client
        )

    async def answer_question(self, query: UserQueryDTO) -> SearchResultDTO:
        logger.info(f"Answering question: {query.text}")
        question = (query.text or "").strip()

        rewritten = await rewrite_query_for_retrieval(self.llm_client, question)
        aux = [] if is_name_question(question) else auxiliary_retrieval_queries(rewritten)

        retrieved = await self.retriever.retrieve(
            question,
            limit=RETRIEVAL_LIMIT,
            auxiliary_queries=aux,
        )
        context_chunks = [chunk.as_context_dict() for chunk in retrieved]
        context_chunks = compress_chunks(context_chunks, question)

        if not context_chunks:
            return SearchResultDTO(
                experiment_ids=[],
                document_ids=[],
                image_ids=[],
                answer_text=(
                    "No indexed text found for this query yet. "
                    "Re-ingest your documents so chunks are embedded in Qdrant and stored in the graph."
                ),
                confidence=0.0,
                sources=[],
            )

        full_context = self._assemble_context(context_chunks)
        answer, used_grounded = await self._generate_answer(
            question, full_context, context_chunks
        )

        document_ids = list({
            UUID(str(chunk["document_id"]))
            for chunk in context_chunks
            if chunk.get("document_id")
        })

        confidence = compute_confidence(context_chunks, "hybrid", answer)
        coverage = citation_coverage(answer, len(context_chunks))
        if coverage > 0:
            confidence = round(min(1.0, confidence * 0.65 + coverage * 0.35), 3)

        sources = self._build_source_excerpts(context_chunks)

        logger.info(
            f"Generated answer: {len(answer)} chars, {len(document_ids)} docs, "
            f"confidence={confidence:.0%}, grounded={used_grounded}, coverage={coverage:.0%}"
        )

        return SearchResultDTO(
            experiment_ids=[],
            document_ids=document_ids,
            image_ids=[],
            answer_text=answer,
            confidence=confidence,
            sources=sources,
        )

    async def _generate_answer(
        self, question: str, context: str, context_chunks: list[dict]
    ) -> tuple[str, bool]:
        num_sources = len(context_chunks)

        if is_name_question(question):
            facts = validate_facts(
                extract_person_facts_from_chunks(context_chunks), num_sources
            )
            if facts:
                return format_grounded_answer(facts), True

        answer = await self._generate_direct_answer(question, context)
        return answer, False

    async def _generate_direct_answer(self, question: str, context: str) -> str:
        user_message = f"""QUESTION: {question}

EXCERPTS:
{context}

Answer the question directly using only the excerpts above."""

        return await self.llm_client.chat(
            user_message=user_message,
            system_message=ANSWER_SYSTEM,
            temperature=0.1,
        )

    def _assemble_context(self, text_chunks: list[dict]) -> str:
        parts = ["NUMBERED EXCERPTS:"]
        for index, chunk in enumerate(text_chunks, start=1):
            title = chunk.get("title")
            header = f"[{index}]"
            if title:
                header += f" ({title})"
            parts.append(f"\n{header}\n{chunk['text']}")
        return "\n".join(parts)

    def _build_source_excerpts(self, context_chunks: list[dict]) -> list[SourceExcerptDTO]:
        title_cache: dict[str, str | None] = {}
        sources: list[SourceExcerptDTO] = []

        for index, chunk in enumerate(context_chunks, start=1):
            doc_id = str(chunk.get("document_id") or "")
            title = chunk.get("title")
            if not title and doc_id:
                if doc_id not in title_cache:
                    title_cache[doc_id] = self.graph_db.get_document_title(doc_id)
                title = title_cache[doc_id]

            text = (chunk.get("text") or "").strip()
            if not text:
                continue

            sources.append(
                SourceExcerptDTO(
                    index=index,
                    text=text,
                    document_id=doc_id,
                    title=title,
                    score=chunk.get("score"),
                )
            )
        return sources
