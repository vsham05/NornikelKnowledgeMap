"""RAG orchestration: query rewrite → hybrid retrieve → compress → cited answers."""

from __future__ import annotations

import logging
from uuid import UUID

from domain.dto.query import DocumentCandidateDTO, SearchResultDTO, SourceExcerptDTO, UserQueryDTO
from infra.embedding_client import EmbeddingClient
from infra.llm_client import LLMClient
from search.citations import (
    build_answer_system,
    build_index_to_document,
    citation_coverage,
    enforce_citation_document_isolation,
    extract_person_facts_from_chunks,
    format_grounded_answer,
    is_name_question,
    validate_facts,
)
from search.context import compress_chunks
from search.document_scope import (
    DocumentScope,
    aggregate_document_scores,
    detect_disambiguation,
    group_chunks_by_document,
    query_requests_aggregate,
    query_requests_comparison,
    resolve_document_scope,
    scope_instruction,
)
from search.query_processing import answer_language_instruction, resolve_answer_language
from search.query_rewrite import auxiliary_retrieval_queries, rewrite_query_for_retrieval
from search.relevance import compute_confidence
from search.retrieval import HybridRetriever, RetrievedChunk
from settings import Settings
from storage.graph_db import GraphDB
from storage.vector_db import VectorDB

logger = logging.getLogger(__name__)

RETRIEVAL_LIMIT = 8
AGGREGATE_CHUNKS_PER_DOC = 4
MAX_AGGREGATE_DOCS = 12


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
        forced_doc_id = (query.document_id or query.filters.get("document_id") or "").strip() or None

        rewritten = await rewrite_query_for_retrieval(self.llm_client, question)
        aux = [] if is_name_question(question) else auxiliary_retrieval_queries(rewritten)

        all_documents = self.graph_db.list_documents()
        answer_lang = resolve_answer_language(question)

        if query_requests_aggregate(question) and not forced_doc_id:
            return await self._answer_aggregate(question, aux, answer_lang, all_documents)

        disambiguation = await self._check_disambiguation(
            question, aux, all_documents, forced_doc_id, answer_lang
        )
        if disambiguation is not None:
            return disambiguation

        retrieved, scope = await self._retrieve_scoped(
            question, aux, forced_document_id=forced_doc_id, all_documents=all_documents
        )
        context_chunks = [chunk.as_context_dict() for chunk in retrieved]
        context_chunks = compress_chunks(context_chunks, question)
        if scope.mode in ("multi", "aggregate"):
            context_chunks = self._sort_chunks_by_document(context_chunks)

        if not context_chunks:
            return self._empty_result(answer_lang)

        full_context = self._assemble_context(context_chunks, scope)
        graph_ctx = self._structured_graph_context(query, question)
        if graph_ctx:
            full_context = graph_ctx + "\n\n" + full_context
        answer, used_grounded = await self._generate_answer(
            question, full_context, context_chunks, answer_lang, scope
        )

        index_to_doc = build_index_to_document(context_chunks)
        answer, had_cross_doc = enforce_citation_document_isolation(answer, index_to_doc)
        if had_cross_doc:
            logger.info("Split cross-document citations in answer")

        document_ids = list({
            UUID(str(chunk["document_id"]))
            for chunk in context_chunks
            if chunk.get("document_id")
        })

        confidence = compute_confidence(context_chunks, "hybrid", answer)
        coverage = citation_coverage(answer, len(context_chunks))
        if coverage > 0:
            confidence = round(min(1.0, confidence * 0.65 + coverage * 0.35), 3)
        if scope.mode == "single" and len({c.get("document_id") for c in context_chunks}) == 1:
            confidence = round(min(1.0, confidence * 1.02), 3)
        if had_cross_doc:
            confidence = round(max(0.0, confidence * 0.92), 3)

        sources = self._build_source_excerpts(context_chunks)

        logger.info(
            f"Generated answer: {len(answer)} chars, {len(document_ids)} docs, "
            f"scope={scope.mode}/{scope.reason}, "
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

    async def _check_disambiguation(
        self,
        question: str,
        auxiliary_queries: list[str],
        all_documents: list[dict],
        forced_doc_id: str | None,
        answer_lang: str,
    ) -> SearchResultDTO | None:
        if forced_doc_id:
            return None
        if query_requests_comparison(question) or query_requests_aggregate(question):
            return None
        if len(all_documents) < 2:
            return None

        probe = await self.retriever.retrieve(
            question,
            limit=RETRIEVAL_LIMIT,
            auxiliary_queries=auxiliary_queries,
        )
        probe_chunks = [chunk.as_context_dict() for chunk in probe]
        ranked = aggregate_document_scores(probe_chunks)
        if len(ranked) < 2:
            return None

        result = detect_disambiguation(
            ranked,
            comparison=query_requests_comparison(question),
            aggregate=query_requests_aggregate(question),
        )
        if not result.ambiguous:
            return None

        if answer_lang == "ru":
            message = (
                "Найдена релевантная информация в нескольких документах. "
                "Выберите документ в фильтре выше и повторите поиск:\n"
            )
        else:
            message = (
                "Relevant information was found in multiple documents. "
                "Select a document from the filter above and search again:\n"
            )
        lines = [message]
        for candidate in result.candidates:
            label = candidate.title or candidate.document_id[:8]
            lines.append(f"- {label}")

        return SearchResultDTO(
            experiment_ids=[],
            document_ids=[],
            image_ids=[],
            answer_text="\n".join(lines),
            confidence=0.0,
            sources=[],
            needs_disambiguation=True,
            document_candidates=[
                DocumentCandidateDTO(
                    document_id=c.document_id,
                    title=c.title,
                    score=round(c.score, 4),
                )
                for c in result.candidates
            ],
        )

    async def _answer_aggregate(
        self,
        question: str,
        auxiliary_queries: list[str],
        answer_lang: str,
        all_documents: list[dict],
    ) -> SearchResultDTO:
        scope = DocumentScope(
            "aggregate",
            None,
            None,
            tuple(str(d.get("id") or "") for d in all_documents if d.get("id")),
            "aggregate_query",
        )
        sections: list[str] = []
        all_chunks: list[dict] = []
        doc_ids: list[UUID] = []

        for doc in all_documents[:MAX_AGGREGATE_DOCS]:
            doc_id = str(doc.get("id") or "")
            if not doc_id:
                continue
            retrieved = await self.retriever.retrieve(
                question,
                limit=AGGREGATE_CHUNKS_PER_DOC,
                auxiliary_queries=auxiliary_queries,
                document_id=doc_id,
                max_per_document=AGGREGATE_CHUNKS_PER_DOC,
            )
            if not retrieved:
                continue

            chunks = compress_chunks(
                [c.as_context_dict() for c in retrieved], question
            )
            title = doc.get("title") or self.graph_db.get_document_title(doc_id)
            for chunk in chunks:
                chunk["title"] = title

            start_index = len(all_chunks) + 1
            context = self._assemble_context(
                chunks, scope, start_index=start_index
            )
            section = await self._generate_direct_answer(
                question, context, answer_lang, scope
            )
            index_to_doc = {
                start_index + i: doc_id
                for i in range(len(chunks))
            }
            section, _ = enforce_citation_document_isolation(section, index_to_doc)

            label = title or doc_id[:8]
            sections.append(f"**{label}**\n{section}")
            all_chunks.extend(chunks)
            doc_ids.append(UUID(doc_id))

        if not sections:
            return self._empty_result(answer_lang)

        answer = "\n\n".join(sections)
        sources = self._build_source_excerpts(all_chunks, start_index=1)
        confidence = compute_confidence(all_chunks, "hybrid", answer)

        return SearchResultDTO(
            experiment_ids=[],
            document_ids=doc_ids,
            image_ids=[],
            answer_text=answer,
            confidence=confidence,
            sources=sources,
        )

    def _empty_result(self, answer_lang: str) -> SearchResultDTO:
        no_data = (
            "По этому запросу пока нет проиндексированного текста. "
            "Загрузите документы заново, чтобы фрагменты попали в Qdrant и граф."
            if answer_lang == "ru"
            else (
                "No indexed text found for this query yet. "
                "Re-ingest your documents so chunks are embedded in Qdrant and stored in the graph."
            )
        )
        return SearchResultDTO(
            experiment_ids=[],
            document_ids=[],
            image_ids=[],
            answer_text=no_data,
            confidence=0.0,
            sources=[],
        )

    async def _retrieve_scoped(
        self,
        question: str,
        auxiliary_queries: list[str],
        *,
        forced_document_id: str | None = None,
        all_documents: list[dict] | None = None,
    ) -> tuple[list[RetrievedChunk], DocumentScope]:
        """Probe retrieval, then focus on one document unless comparison is requested."""
        all_documents = all_documents or self.graph_db.list_documents()

        probe = await self.retriever.retrieve(
            question,
            limit=RETRIEVAL_LIMIT,
            auxiliary_queries=auxiliary_queries,
            document_id=forced_document_id,
        )
        probe_chunks = [chunk.as_context_dict() for chunk in probe]
        scope = resolve_document_scope(
            question,
            probe_chunks,
            all_documents=all_documents,
            forced_document_id=forced_document_id,
        )

        if scope.mode == "aggregate":
            return probe, scope

        if scope.mode in ("single", "explicit") and scope.primary_document_id:
            focused = await self.retriever.retrieve(
                question,
                limit=RETRIEVAL_LIMIT,
                auxiliary_queries=auxiliary_queries,
                document_id=scope.primary_document_id,
                max_per_document=RETRIEVAL_LIMIT,
            )
            if focused:
                return focused, scope
            return probe, scope

        if scope.mode == "multi":
            allowed = set(scope.document_ids)
            filtered = [
                chunk for chunk in probe
                if str(chunk.document_id) in allowed
            ]
            if filtered:
                return filtered[:RETRIEVAL_LIMIT], scope

        return probe, scope

    def _sort_chunks_by_document(self, chunks: list[dict]) -> list[dict]:
        ordered: list[dict] = []
        for _title, _doc_id, doc_chunks in group_chunks_by_document(chunks):
            ordered.extend(doc_chunks)
        return ordered or chunks

    async def _generate_answer(
        self,
        question: str,
        context: str,
        context_chunks: list[dict],
        answer_lang: str,
        scope: DocumentScope,
    ) -> tuple[str, bool]:
        num_sources = len(context_chunks)

        if is_name_question(question):
            facts = validate_facts(
                extract_person_facts_from_chunks(
                    context_chunks, answer_lang=answer_lang
                ),
                num_sources,
            )
            if facts:
                return format_grounded_answer(facts, lang=answer_lang), True

        answer = await self._generate_direct_answer(
            question, context, answer_lang, scope
        )
        return answer, False

    async def _generate_direct_answer(
        self,
        question: str,
        context: str,
        answer_lang: str,
        scope: DocumentScope,
    ) -> str:
        lang_line = answer_language_instruction(answer_lang)
        doc_line = scope_instruction(scope, answer_lang)
        user_message = f"""{lang_line}
{doc_line}

QUESTION: {question}

EXCERPTS:
{context}

Answer the question directly using only the excerpts above.
{doc_line}
{lang_line}"""

        return await self.llm_client.chat(
            user_message=user_message,
            system_message=build_answer_system(answer_lang),
            temperature=0.1,
        )

    def _assemble_context(
        self,
        text_chunks: list[dict],
        scope: DocumentScope | None = None,
        *,
        start_index: int = 1,
    ) -> str:
        multi_doc = (
            scope
            and scope.mode in ("multi", "aggregate")
            and len({chunk.get("document_id") for chunk in text_chunks}) > 1
        )

        if multi_doc:
            parts = [
                "NUMBERED EXCERPTS (multiple source documents — "
                "do not merge facts across documents):"
            ]
        else:
            parts = ["NUMBERED EXCERPTS:"]

        last_doc: str | None = None
        for offset, chunk in enumerate(text_chunks):
            index = start_index + offset
            doc_id = str(chunk.get("document_id") or "")
            title = chunk.get("title")
            if multi_doc and doc_id and doc_id != last_doc:
                label = title or f"Document {doc_id[:8]}"
                parts.append(f"\n=== Document: {label} ===")
                last_doc = doc_id
            header = f"[{index}]"
            if title:
                header += f" (document: {title})"
            parts.append(f"\n{header}\n{chunk['text']}")
        return "\n".join(parts)

    def _build_source_excerpts(
        self,
        context_chunks: list[dict],
        *,
        start_index: int = 1,
    ) -> list[SourceExcerptDTO]:
        title_cache: dict[str, str | None] = {}
        sources: list[SourceExcerptDTO] = []

        for offset, chunk in enumerate(context_chunks):
            index = start_index + offset
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

    def _structured_graph_context(self, query: UserQueryDTO, question: str) -> str:
        """Inject structured Neo4j matches into RAG context."""
        sf = query.structured
        payload = sf.model_dump(exclude_none=True) if sf else {}
        if not payload:
            payload = self._infer_filters_from_question(question)
        if not payload:
            return ""

        try:
            result = self.graph_db.structured_search(limit=12, **payload)
        except Exception as exc:
            logger.warning("Structured graph search failed: %s", exc)
            return ""

        experiments = result.get("experiments") or []
        if not experiments:
            return ""

        lines = [
            "STRUCTURED KNOWLEDGE GRAPH MATCHES "
            "(verified links: experiment → material → source document):"
        ]
        for row in experiments[:10]:
            rel = row.get("reliability")
            rel_txt = f" | reliability={rel:.0%}" if isinstance(rel, (int, float)) else ""
            geo = row.get("scope") or row.get("country") or ""
            geo_txt = f" | {geo}" if geo else ""
            lines.append(
                f"- Material: {row.get('material')} | Process: {row.get('regime') or row.get('process')} "
                f"| Source: {row.get('document_title')} ({row.get('year') or 'n/d'}){geo_txt}{rel_txt}"
            )
        return "\n".join(lines)

    @staticmethod
    def _infer_filters_from_question(question: str) -> dict:
        lower = question.lower()
        filters: dict = {}
        geo_markers = {
            "domestic": ("росси", "russia", "отечеств", "domestic", "cis"),
            "international": ("international", "global", "abroad", "зарубеж", "миров"),
        }
        for scope, markers in geo_markers.items():
            if any(m in lower for m in markers):
                filters["geography"] = scope
                break
        import re
        year_match = re.search(r"(20\d{2})\s*[-–]\s*(20\d{2})", question)
        if year_match:
            filters["year_from"] = int(year_match.group(1))
            filters["year_to"] = int(year_match.group(2))
        elif re.search(r"last\s+5\s+years", lower):
            filters["year_from"] = 2021
        return filters
