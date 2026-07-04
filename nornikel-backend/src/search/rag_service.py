"""RAG: embedding retrieval (Qdrant) + keyword search → LLM cited answer."""

from __future__ import annotations

import logging
from uuid import UUID

from domain.dto.query import (
    DocumentCandidateDTO,
    RetrievalScopeDTO,
    SearchResultDTO,
    SourceExcerptDTO,
    UserQueryDTO,
)
from infra.embedding_client import EmbeddingClient
from infra.llm_client import LLMClient, is_context_overflow
from search.citations import (
    build_answer_system,
    build_index_to_document,
    build_numeric_answer_instruction,
    citation_coverage,
    enforce_citation_document_isolation,
    extract_person_facts_from_chunks,
    format_grounded_answer,
    is_name_question,
    prune_unsupported_heading_bullets,
    validate_facts,
)
from search.context import compress_chunks, fit_chunks_to_context_budget, resolve_rag_max_chars, resolve_rag_chunk_max_chars, resolve_context_tokens
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
from search.extractive_answer import extractive_answer_from_chunks
from search.query_processing import (
    answer_language_instruction,
    detect_language,
    is_technical_quantitative_question,
    requests_experiment_list,
    resolve_answer_language,
    significant_terms,
)
from search.query_rewrite import RewrittenQuery, auxiliary_retrieval_queries, rewrite_query_for_retrieval
from search.query_translate import (
    should_use_translate_pipeline,
    translate_answer_to_russian,
    translate_question_to_english,
)
from search.relevance import compute_confidence
from search.retrieval import HybridRetriever, RetrievedChunk
from settings import Settings
from storage.graph_db import GraphDB
from storage.vector_db import VectorDB

logger = logging.getLogger(__name__)

RETRIEVAL_LIMIT = 10
RETRIEVAL_LIMIT_TECHNICAL = 16
AGGREGATE_CHUNKS_PER_DOC = 4
MAX_AGGREGATE_DOCS = 12


class RAGService:
    """Embed query → hybrid retrieve (dense + keyword) → LLM answer with citations."""

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

        filter_payload, filter_doc_ids, _graph_ctx, _ = (
            self._resolve_structured_filters(query, question)
        )
        has_structured_filters = bool(filter_payload) and not forced_doc_id
        retrieval_question = self._focus_retrieval_query(question, filter_payload)
        focus_terms = self._focus_terms(filter_payload, question)
        retrieval_limit = self._retrieval_limit(question)

        rewritten = await rewrite_query_for_retrieval(self.llm_client, retrieval_question)
        primary_retrieval, aux, english_question, use_translate = (
            await self._prepare_retrieval_queries(
                question, retrieval_question, rewritten
            )
        )

        all_documents = self.graph_db.list_documents()
        answer_lang = resolve_answer_language(question)

        if query_requests_aggregate(question) and not forced_doc_id:
            return await self._answer_aggregate(
                primary_retrieval,
                aux,
                answer_lang,
                all_documents,
                question=question,
                english_question=english_question,
                use_translate=use_translate,
            )

        disambiguation = await self._check_disambiguation(
            question,
            aux,
            all_documents,
            forced_doc_id,
            answer_lang,
            structured_document_ids=filter_doc_ids if has_structured_filters else None,
            retrieval_query=primary_retrieval,
        )
        if disambiguation is not None:
            return disambiguation

        retrieved, scope, retrieval_scope = await self._retrieve_scoped(
            primary_retrieval,
            aux,
            forced_document_id=forced_doc_id,
            all_documents=all_documents,
            structured_document_ids=filter_doc_ids if has_structured_filters else None,
            structured_filters_active=has_structured_filters,
            filter_payload=filter_payload,
            retrieval_limit=retrieval_limit,
        )
        context_chunks = [chunk.as_context_dict() for chunk in retrieved]
        context_chunks = self._append_graph_experiments_context(
            question, context_chunks, filter_payload
        )
        context_chunks = compress_chunks(
            context_chunks,
            retrieval_question,
            max_chunk_chars=resolve_rag_chunk_max_chars(
                self.settings, len(context_chunks) or retrieval_limit
            ),
        )
        context_chunks = fit_chunks_to_context_budget(
            context_chunks,
            retrieval_question,
            max_total_chars=resolve_rag_max_chars(self.settings),
            settings=self.settings,
        )
        if scope.mode in ("multi", "aggregate"):
            context_chunks = self._sort_chunks_by_document(context_chunks)

        if not context_chunks:
            return self._empty_result(answer_lang, retrieval_scope)

        vector_hits = sum(
            1 for c in context_chunks if "vector" in (c.get("retrieval_sources") or [])
        )
        logger.info(
            "Retrieved %s chunks (%s via embeddings, %s keyword/page only)",
            len(context_chunks),
            vector_hits,
            len(context_chunks) - vector_hits,
        )

        full_context = self._assemble_context(context_chunks, scope)
        used_extractive = False
        gen_lang = "en" if use_translate and not is_name_question(question) else answer_lang
        gen_question = english_question or question
        try:
            answer, used_grounded = await self._generate_answer(
                gen_question,
                full_context,
                context_chunks,
                gen_lang,
                scope,
                filter_payload=filter_payload,
            )
            if use_translate and not is_name_question(question) and answer_lang == "ru":
                answer = await translate_answer_to_russian(
                    self.llm_client, answer, question
                )
        except Exception as exc:
            logger.warning("LLM synthesis failed (%s); using embedding retrieval excerpts", exc)
            answer = extractive_answer_from_chunks(
                question, context_chunks, answer_lang=answer_lang
            )
            if not answer.strip():
                raise
            used_grounded = True
            used_extractive = True

        index_to_doc = build_index_to_document(context_chunks)
        answer, had_cross_doc = enforce_citation_document_isolation(answer, index_to_doc)
        answer = prune_unsupported_heading_bullets(
            answer,
            context_chunks,
            focus_terms=focus_terms,
        )
        if had_cross_doc:
            logger.info("Split cross-document citations in answer")

        document_ids = list({
            UUID(str(chunk["document_id"]))
            for chunk in context_chunks
            if chunk.get("document_id")
        })

        confidence = compute_confidence(context_chunks, "hybrid", answer)
        if used_extractive:
            confidence = round(min(confidence, 0.62), 3)
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
            retrieval_scope=retrieval_scope,
        )

    async def _prepare_retrieval_queries(
        self,
        question: str,
        retrieval_question: str,
        rewritten: RewrittenQuery,
    ) -> tuple[str, list[str], str | None, bool]:
        """Return (primary_query, auxiliary_queries, english_question, use_translate_pipeline)."""
        use_translate = should_use_translate_pipeline(
            question, enabled=self.settings.rag_ru_translate_pipeline
        )
        english_question: str | None = None
        if use_translate and not is_name_question(question):
            english_question = (rewritten.search_query_en or "").strip() or None
            if not english_question:
                english_question = await translate_question_to_english(
                    self.llm_client, retrieval_question
                )

        aux = [] if is_name_question(question) else auxiliary_retrieval_queries(rewritten)
        if english_question:
            if english_question not in aux:
                aux.insert(0, english_question)
            if (
                retrieval_question
                and retrieval_question not in aux
                and retrieval_question != english_question
            ):
                aux.append(retrieval_question)

        primary = english_question or retrieval_question
        max_aux = 4 if detect_language(question) in ("ru", "mixed") else 1
        if len(aux) > max_aux:
            aux = aux[:max_aux]

        if english_question:
            logger.info(
                "Cross-lingual RAG: retrieval in EN, answer EN→RU (%r)",
                english_question[:80],
            )
        return primary, aux, english_question, use_translate and bool(english_question)

    async def _check_disambiguation(
        self,
        question: str,
        auxiliary_queries: list[str],
        all_documents: list[dict],
        forced_doc_id: str | None,
        answer_lang: str,
        *,
        structured_document_ids: list[str] | None = None,
        retrieval_query: str | None = None,
    ) -> SearchResultDTO | None:
        if forced_doc_id:
            return None
        if structured_document_ids:
            return None
        if len(all_documents) <= 3:
            return None
        if query_requests_comparison(question) or query_requests_aggregate(question):
            return None
        if len(all_documents) < 2:
            return None

        probe = await self.retriever.retrieve(
            retrieval_query or question,
            limit=self._retrieval_limit(question),
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
        retrieval_query: str,
        auxiliary_queries: list[str],
        answer_lang: str,
        all_documents: list[dict],
        *,
        question: str = "",
        english_question: str | None = None,
        use_translate: bool = False,
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
                retrieval_query,
                limit=AGGREGATE_CHUNKS_PER_DOC,
                auxiliary_queries=auxiliary_queries,
                document_id=doc_id,
                max_per_document=AGGREGATE_CHUNKS_PER_DOC,
            )
            if not retrieved:
                continue

            compress_q = question or retrieval_query
            chunks = compress_chunks(
                [c.as_context_dict() for c in retrieved],
                compress_q,
                max_chunk_chars=resolve_rag_chunk_max_chars(
                    self.settings, AGGREGATE_CHUNKS_PER_DOC
                ),
            )
            chunks = fit_chunks_to_context_budget(
                chunks,
                compress_q,
                max_total_chars=resolve_rag_max_chars(self.settings) // MAX_AGGREGATE_DOCS,
                settings=self.settings,
            )
            title = doc.get("title") or self.graph_db.get_document_title(doc_id)
            for chunk in chunks:
                chunk["title"] = title

            start_index = len(all_chunks) + 1
            context = self._assemble_context(
                chunks, scope, start_index=start_index
            )
            gen_q = english_question or question or retrieval_query
            gen_lang = "en" if use_translate else answer_lang
            section = await self._generate_direct_answer(
                gen_q, context, gen_lang, scope, context_chunks=chunks
            )
            if use_translate and answer_lang == "ru":
                section = await translate_answer_to_russian(
                    self.llm_client, section, question or retrieval_query
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

    def _empty_result(
        self,
        answer_lang: str,
        retrieval_scope: RetrievalScopeDTO | None = None,
    ) -> SearchResultDTO:
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
            retrieval_scope=retrieval_scope or RetrievalScopeDTO(),
        )

    def _build_retrieval_scope(
        self,
        mode: str,
        filter_doc_ids: list[str],
        filter_payload: dict,
        *,
        graph_match_count: int | None = None,
    ) -> RetrievalScopeDTO:
        titles: list[str] = []
        for doc_id in filter_doc_ids:
            title = self.graph_db.get_document_title(doc_id)
            titles.append(title or doc_id[:8])
        return RetrievalScopeDTO(
            mode=mode,
            filter_document_ids=list(filter_doc_ids),
            filter_document_titles=titles,
            filters_applied=dict(filter_payload),
            graph_match_count=graph_match_count if graph_match_count is not None else len(filter_doc_ids),
        )

    async def _retrieve_scoped(
        self,
        question: str,
        auxiliary_queries: list[str],
        *,
        forced_document_id: str | None = None,
        all_documents: list[dict] | None = None,
        structured_document_ids: list[str] | None = None,
        structured_filters_active: bool = False,
        filter_payload: dict | None = None,
        retrieval_limit: int = RETRIEVAL_LIMIT,
    ) -> tuple[list[RetrievedChunk], DocumentScope, RetrievalScopeDTO]:
        """Probe retrieval, then focus on one document unless comparison is requested."""
        all_documents = all_documents or self.graph_db.list_documents()
        filter_payload = filter_payload or {}

        if forced_document_id:
            probe = await self.retriever.retrieve(
                question,
                limit=retrieval_limit,
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
            retrieval_scope = self._build_retrieval_scope(
                "explicit_document",
                [forced_document_id],
                filter_payload,
                graph_match_count=1,
            )
            return probe, scope, retrieval_scope

        if structured_filters_active:
            if structured_document_ids:
                scoped = await self.retriever.retrieve(
                    question,
                    limit=retrieval_limit,
                    auxiliary_queries=auxiliary_queries,
                    document_ids=structured_document_ids,
                )
                scope = DocumentScope(
                    "multi",
                    None,
                    None,
                    tuple(structured_document_ids),
                    "structured_filters",
                )
                retrieval_scope = self._build_retrieval_scope(
                    "structured_filters",
                    structured_document_ids,
                    filter_payload,
                )
                return scoped, scope, retrieval_scope

            probe = await self.retriever.retrieve(
                question,
                limit=retrieval_limit,
                auxiliary_queries=auxiliary_queries,
            )
            probe_chunks = [chunk.as_context_dict() for chunk in probe]
            scope = resolve_document_scope(
                question,
                probe_chunks,
                all_documents=all_documents,
                forced_document_id=None,
            )
            retrieval_scope = self._build_retrieval_scope(
                "structured_fallback",
                [],
                filter_payload,
                graph_match_count=0,
            )
            return probe, scope, retrieval_scope

        probe = await self.retriever.retrieve(
            question,
            limit=retrieval_limit,
            auxiliary_queries=auxiliary_queries,
        )
        probe_chunks = [chunk.as_context_dict() for chunk in probe]
        scope = resolve_document_scope(
            question,
            probe_chunks,
            all_documents=all_documents,
            forced_document_id=None,
        )
        retrieval_scope = RetrievalScopeDTO(mode="full_corpus")

        if scope.mode == "aggregate":
            return probe, scope, retrieval_scope

        if scope.mode in ("single", "explicit") and scope.primary_document_id:
            doc_id = scope.primary_document_id
            probe_for_doc = [
                chunk for chunk in probe if str(chunk.document_id) == doc_id
            ]
            if len(probe_for_doc) >= max(4, retrieval_limit // 2):
                return probe_for_doc[:retrieval_limit], scope, retrieval_scope

            focused = await self.retriever.retrieve(
                question,
                limit=retrieval_limit,
                auxiliary_queries=auxiliary_queries,
                document_id=scope.primary_document_id,
                max_per_document=retrieval_limit,
            )
            if focused:
                return focused, scope, retrieval_scope
            return probe, scope, retrieval_scope

        if scope.mode == "multi":
            allowed = set(scope.document_ids)
            filtered = [
                chunk for chunk in probe
                if str(chunk.document_id) in allowed
            ]
            if filtered:
                return filtered[:retrieval_limit], scope, retrieval_scope

        return probe, scope, retrieval_scope

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
        *,
        filter_payload: dict | None = None,
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
            question, context, answer_lang, scope, filter_payload=filter_payload or {},
            context_chunks=context_chunks,
        )
        return answer, False

    async def _generate_direct_answer(
        self,
        question: str,
        context: str,
        answer_lang: str,
        scope: DocumentScope,
        *,
        filter_payload: dict | None = None,
        context_chunks: list[dict] | None = None,
    ) -> str:
        lang_line = answer_language_instruction(answer_lang)
        doc_line = scope_instruction(scope, answer_lang)
        focus_line = self._answer_focus_instruction(filter_payload or {}, answer_lang)
        numeric_line = build_numeric_answer_instruction(question, answer_lang)
        user_message = f"""{lang_line}
{doc_line}
{focus_line}
{numeric_line}

QUESTION: {question}

EXCERPTS:
{context}

Answer the question directly using only the excerpts above.
Include specific numbers with units for every technical claim.
Do not list bare section or process titles — write full factual sentences with citations.
{doc_line}
{focus_line}
{numeric_line}
{lang_line}"""

        try:
            return await self.llm_client.chat(
                user_message=user_message,
                system_message=build_answer_system(answer_lang),
                temperature=0.0,
                max_tokens=2048,
            )
        except Exception as exc:
            trimmed: list[dict] | None = None
            if is_context_overflow(exc) and context_chunks:
                logger.warning(
                    "Answer generation exceeded context window; retrying with tighter excerpts"
                )
                trimmed = fit_chunks_to_context_budget(
                    context_chunks,
                    question,
                    max_total_chars=max(4000, resolve_rag_max_chars(self.settings) // 3),
                    settings=self.settings,
                )
                retry_context = self._assemble_context(trimmed, scope)
                retry_message = user_message.replace(context, retry_context)
                try:
                    return await self.llm_client.chat(
                        user_message=retry_message,
                        system_message=build_answer_system(answer_lang),
                        temperature=0.0,
                        max_tokens=1536,
                    )
                except Exception as retry_exc:
                    logger.warning(
                        "LLM retry failed (%s); falling back to embedding excerpts",
                        retry_exc,
                    )
                    exc = retry_exc

            if context_chunks:
                fallback = extractive_answer_from_chunks(
                    question,
                    trimmed or context_chunks,
                    answer_lang=answer_lang,
                )
                if fallback.strip():
                    return fallback
            raise exc

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

    def _resolve_structured_filters(
        self,
        query: UserQueryDTO,
        question: str,
    ) -> tuple[dict, list[str], str, dict | None]:
        """Resolve structured filters once for both retrieval scoping and graph context."""
        sf = query.structured
        payload = sf.model_dump(exclude_none=True) if sf else {}
        if not payload:
            payload = self._infer_filters_from_question(question)
        if not payload:
            return {}, [], "", None

        try:
            result = self.graph_db.structured_search(limit=50, **payload)
        except Exception as exc:
            logger.warning("Structured graph search failed: %s", exc)
            return payload, [], "", None

        doc_ids: list[str] = []
        seen: set[str] = set()
        for doc in result.get("documents") or []:
            doc_id = doc.get("id")
            if doc_id and str(doc_id) not in seen:
                seen.add(str(doc_id))
                doc_ids.append(str(doc_id))
        for row in result.get("experiments") or []:
            doc_id = row.get("document_id")
            if doc_id and str(doc_id) not in seen:
                seen.add(str(doc_id))
                doc_ids.append(str(doc_id))

        graph_ctx = self._format_structured_context(result)
        return payload, doc_ids, graph_ctx, result

    def _format_structured_context(self, result: dict) -> str:
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
        from datetime import datetime

        year_match = re.search(r"(20\d{2})\s*[-–]\s*(20\d{2})", question)
        if year_match:
            filters["year_from"] = int(year_match.group(1))
            filters["year_to"] = int(year_match.group(2))
        elif re.search(r"last\s+5\s+years|последн\w*\s+5\s+лет", lower):
            filters["year_from"] = datetime.now().year - 5
        return filters

    @staticmethod
    def _focus_retrieval_query(question: str, filter_payload: dict) -> str:
        parts: list[str] = []
        material = (filter_payload.get("material") or "").strip()
        process = (filter_payload.get("process") or "").strip()
        if material:
            parts.append(material)
        if process:
            parts.append(process)
        if not parts:
            return question
        return f"{' '.join(parts)} {question}".strip()

    @staticmethod
    def _focus_terms(filter_payload: dict, question: str) -> list[str]:
        terms: list[str] = []
        for key in ("material", "process", "property_name"):
            value = (filter_payload.get(key) or "").strip()
            if value:
                terms.append(value.lower())
        terms.extend(significant_terms(question, min_length=4))
        seen: set[str] = set()
        out: list[str] = []
        for term in terms:
            if term not in seen:
                seen.add(term)
                out.append(term)
        return out

    @staticmethod
    def _answer_focus_instruction(filter_payload: dict, answer_lang: str) -> str:
        material = (filter_payload.get("material") or "").strip()
        process = (filter_payload.get("process") or "").strip()
        if not material and not process:
            return ""
        if answer_lang == "ru":
            if material and process:
                return (
                    f"ФОКУС: отвечайте только о материале «{material}» и процессе «{process}» "
                    "с конкретными фактами из выдержек (цифры, условия, результаты)."
                )
            if material:
                return (
                    f"ФОКУС: отвечайте только о материале «{material}» с конкретными фактами "
                    "из выдержек (содержание, извлечение, условия, результаты)."
                )
            return (
                f"ФОКУС: отвечайте только о процессе «{process}» с конкретными фактами из выдержек."
            )
        if material and process:
            return (
                f"FOCUS: answer only about material '{material}' and process '{process}' "
                "with concrete facts from excerpts (numbers, conditions, outcomes)."
            )
        if material:
            return (
                f"FOCUS: answer only about material '{material}' with concrete facts from excerpts "
                "(grades, extraction, conditions, results) — not unrelated section titles."
            )
        return (
            f"FOCUS: answer only about process '{process}' with concrete facts from excerpts."
        )

    def _retrieval_limit(self, question: str) -> int:
        if is_technical_quantitative_question(question):
            base = RETRIEVAL_LIMIT_TECHNICAL
        else:
            base = RETRIEVAL_LIMIT
        ctx = resolve_context_tokens(self.settings)
        if ctx <= 8192:
            return min(base, 6)
        if ctx <= 32_768:
            return min(base, 12)
        return base

    def _append_graph_experiments_context(
        self,
        question: str,
        chunks: list[dict],
        filter_payload: dict | None,
    ) -> list[dict]:
        """Prepend graph experiment index for list-all-experiments questions."""
        if not requests_experiment_list(question):
            return chunks

        payload = dict(filter_payload or {})
        payload.update(self._infer_filters_from_question(question))

        material_terms = self._detect_material_terms(question)
        if material_terms and not payload.get("material"):
            payload["material"] = material_terms[0]

        if not payload:
            return chunks

        try:
            kwargs = {k: v for k, v in payload.items() if v is not None}
            result = self.graph_db.structured_search(limit=20, **kwargs)
        except Exception as exc:
            logger.warning("Graph experiment index failed: %s", exc)
            return chunks

        rows = result.get("experiments") or []
        if not rows:
            return chunks

        lines = [
            "INDEX OF MATCHING EXPERIMENTS FROM KNOWLEDGE GRAPH "
            "(use alongside numbered excerpts; cite excerpts for numeric values):"
        ]
        for row in rows[:18]:
            lines.append(
                f"- Material: {row.get('material')} | Process: {row.get('process') or row.get('regime')} "
                f"| Document: {row.get('document_title')} ({row.get('year') or 'n/d'}) "
                f"| Scope: {row.get('scope') or row.get('country') or 'n/d'}"
            )

        doc_id = str(rows[0].get("document_id") or "")
        synth = {
            "chunk_id": "graph-experiment-index",
            "text": "\n".join(lines),
            "document_id": doc_id,
            "title": rows[0].get("document_title"),
            "score": 1.0,
        }
        return [synth] + chunks

    @staticmethod
    def _detect_material_terms(question: str) -> list[str]:
        lower = question.lower()
        terms: list[str] = []
        markers = (
            ("золот", "gold"),
            ("серебр", "silver"),
            ("никел", "nickel"),
            ("мед", "copper"),
            ("мпг", "pgm"),
            ("platinum", "platinum"),
            ("au", "gold"),
            ("ag", "silver"),
        )
        for marker, canonical in markers:
            if marker in lower and canonical not in terms:
                terms.append(canonical)
        return terms
