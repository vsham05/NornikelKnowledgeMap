"""Hybrid retrieval: multi-query RRF + IDF-weighted rerank + per-document diversity."""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass, field

from search.query_processing import HARM_TERMS, YEAR_RE, QueryIntent, analyze_intent, significant_terms

from search.reranker import rerank_chunks

logger = logging.getLogger(__name__)

RRF_K = 60
RETRIEVAL_POOL = 80
PROPER_NOUN_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+|[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)+)\b"
)


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    document_id: str
    title: str | None = None
    vector_score: float | None = None
    rrf_score: float = 0.0
    lexical_score: float = 0.0
    name_score: float = 0.0
    final_score: float = 0.0
    retrieval_sources: list[str] = field(default_factory=list)

    def as_context_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "document_id": self.document_id,
            "title": self.title,
            "score": self.final_score,
            "vector_score": self.vector_score,
            "rrf_score": self.rrf_score,
            "retrieval_sources": list(self.retrieval_sources),
        }


def _chunk_key(chunk_id: str | None, text: str) -> str:
    if chunk_id:
        return str(chunk_id)
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    return digest[:32]


_UNIT_RE = re.compile(
    r"(?:мг/л|mg/l|мг/дм|mg/dm|ppm|%|°c|℃|м/ч|м³/ч|m3/h|мм/с|"
    r"т/год|t/y|t/a|usd|\$|руб|млн|million|billion|tonnes?|tonne|mt\b)",
    re.IGNORECASE,
)


def _numeric_density_score(text: str) -> float:
    """Boost passages with measurable technical values."""
    if not text.strip():
        return 0.0
    numbers = len(re.findall(r"\d+(?:[.,]\d+)?", text))
    units = len(_UNIT_RE.findall(text))
    score = min(1.0, numbers / 6) * 0.55 + min(1.0, units / 3) * 0.45
    return score


def _year_density_score(text: str) -> float:
    years = YEAR_RE.findall(text)
    if not years:
        return 0.0
    return min(1.0, len(years) / 4)


def _harm_damage_score(intent: QueryIntent, text: str) -> float:
    if not intent.harm_related:
        return 0.0
    lower = text.lower()
    hits = sum(1 for term in HARM_TERMS if term in lower)
    return min(1.0, hits / 3)


def _bibliography_penalty(text: str) -> float:
    """Down-rank reference lists and citation dumps."""
    lower = text.lower()
    head = lower[:400]
    penalty = 0.0
    if any(
        marker in head
        for marker in ("references", "bibliography", "литература", "библиограф", "источник")
    ):
        penalty += 0.25
    if lower.count("doi") >= 2 or lower.count("ssrn") >= 1:
        penalty += 0.35
    if len(YEAR_RE.findall(text)) > 8:
        penalty += 0.2
    return min(0.5, penalty)


def _toc_penalty(text: str) -> float:
    """Down-rank table-of-contents / heading-list chunks."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 4:
        return 0.0
    short_title_lines = sum(
        1
        for line in lines
        if len(line) < 55
        and 1 <= len(line.split()) <= 6
        and line[0].isupper()
        and not line.endswith(".")
    )
    if short_title_lines >= 3 and short_title_lines / len(lines) >= 0.45:
        return 0.35
    return 0.0


def _title_relevance_boost(intent: QueryIntent, chunk: RetrievedChunk) -> float:
    if not chunk.title:
        return 0.0
    title_lower = chunk.title.lower()
    hits = sum(1 for term in intent.content_terms if term in title_lower)
    return min(0.25, 0.08 * hits)


def _name_density_score(text: str) -> float:
    matches = PROPER_NOUN_RE.findall(text)
    if not matches:
        return 0.0
    return min(1.0, len(matches) / 5)


def _idf_weights(terms: list[str], corpus: list[str]) -> dict[str, float]:
    n = len(corpus) or 1
    weights: dict[str, float] = {}
    for term in terms:
        df = sum(1 for doc in corpus if term in doc)
        weights[term] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
    return weights


def _lexical_score(terms: list[str], text: str, idf: dict[str, float]) -> float:
    if not terms:
        return 0.0
    lower = text.lower()
    total_idf = sum(idf.get(t, 1.0) for t in terms) or 1.0
    hit_idf = sum(idf.get(t, 1.0) for t in terms if t in lower)
    return hit_idf / total_idf


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return scores


def _select_diverse(
    ranked: list[RetrievedChunk],
    limit: int,
    *,
    max_per_document: int = 2,
) -> list[RetrievedChunk]:
    """Prefer top scores while limiting chunks per document."""
    selected: list[RetrievedChunk] = []
    per_doc: dict[str, int] = {}

    for chunk in ranked:
        doc = chunk.document_id or "_"
        if per_doc.get(doc, 0) >= max_per_document:
            continue
        selected.append(chunk)
        per_doc[doc] = per_doc.get(doc, 0) + 1
        if len(selected) >= limit:
            return selected

    for chunk in ranked:
        if chunk in selected:
            continue
        selected.append(chunk)
        if len(selected) >= limit:
            break

    return selected


class HybridRetriever:
    """Dense (Qdrant) + keyword (Neo4j), multi-query RRF, IDF rerank, diversity."""

    def __init__(self, vector_db, graph_db, embedding_client):
        self.vector_db = vector_db
        self.graph_db = graph_db
        self.embedding_client = embedding_client

    async def retrieve(
        self,
        query: str,
        limit: int = 8,
        *,
        auxiliary_queries: list[str] | None = None,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
        max_per_document: int | None = None,
    ) -> list[RetrievedChunk]:
        intent = analyze_intent(query)
        terms = list(intent.content_terms) or significant_terms(query)

        queries = [query]
        for aux in auxiliary_queries or []:
            aux = (aux or "").strip()
            if aux and aux not in queries:
                queries.append(aux)

        pool: dict[str, RetrievedChunk] = {}
        all_rankings: list[list[str]] = []

        if intent.page_refs:
            page_hits = self.graph_db.get_chunks_by_pages(
                list(intent.page_refs),
                document_id=document_id,
                document_ids=document_ids,
            )
            page_ranking: list[str] = []
            for hit in page_hits:
                text = (hit.get("text") or "").strip()
                if not text:
                    continue
                key = _chunk_key(hit.get("id"), text)
                page_ranking.append(key)
                if key not in pool:
                    pool[key] = RetrievedChunk(
                        chunk_id=key,
                        text=text,
                        document_id=str(hit.get("document_id") or ""),
                        title=hit.get("title"),
                        retrieval_sources=["page"],
                    )
                elif "page" not in pool[key].retrieval_sources:
                    pool[key].retrieval_sources.append("page")
            if page_ranking:
                all_rankings.insert(0, page_ranking)

        for q in queries:
            vector_hits = await self._vector_hits(
                q, pool_size=RETRIEVAL_POOL, document_id=document_id, document_ids=document_ids
            )
            keyword_hits = self._keyword_hits(
                q, pool_size=RETRIEVAL_POOL, document_id=document_id, document_ids=document_ids
            )

            vector_ranking: list[str] = []
            for hit in vector_hits:
                key = _chunk_key(hit.get("chunk_id"), hit["text"])
                vector_ranking.append(key)
                if key not in pool:
                    pool[key] = RetrievedChunk(
                        chunk_id=key,
                        text=hit["text"],
                        document_id=hit["document_id"],
                        title=hit.get("title"),
                        vector_score=hit.get("score"),
                        retrieval_sources=["vector"],
                    )
                elif hit.get("score") and (
                    pool[key].vector_score is None
                    or hit["score"] > pool[key].vector_score
                ):
                    pool[key].vector_score = hit["score"]
                if "vector" not in pool[key].retrieval_sources:
                    pool[key].retrieval_sources.append("vector")

            keyword_ranking: list[str] = []
            for hit in keyword_hits:
                key = _chunk_key(hit.get("chunk_id"), hit["text"])
                keyword_ranking.append(key)
                if key in pool:
                    if "keyword" not in pool[key].retrieval_sources:
                        pool[key].retrieval_sources.append("keyword")
                    if not pool[key].title and hit.get("title"):
                        pool[key].title = hit["title"]
                else:
                    pool[key] = RetrievedChunk(
                        chunk_id=key,
                        text=hit["text"],
                        document_id=hit["document_id"],
                        title=hit.get("title"),
                        retrieval_sources=["keyword"],
                    )

            if vector_ranking:
                all_rankings.append(vector_ranking)
            if keyword_ranking:
                all_rankings.append(keyword_ranking)

        if not pool:
            return []

        rrf_scores = rrf_fuse(all_rankings) if all_rankings else {}
        corpus = [c.text.lower() for c in pool.values()]
        idf = _idf_weights(terms, corpus)

        for key, chunk in pool.items():
            chunk.rrf_score = rrf_scores.get(key, 0.0)
            chunk.lexical_score = _lexical_score(terms, chunk.text, idf)
            harm_score = _harm_damage_score(intent, chunk.text)
            year_score = _year_density_score(chunk.text) if intent.is_temporal else 0.0
            numeric_score = (
                _numeric_density_score(chunk.text)
                if intent.is_technical or intent.is_quantitative
                else 0.0
            )
            dual_source = 0.05 if len(chunk.retrieval_sources) > 1 else 0.0

            bib_penalty = _bibliography_penalty(chunk.text)
            toc_penalty = _toc_penalty(chunk.text)
            title_boost = _title_relevance_boost(intent, chunk)
            page_boost = 0.45 if "page" in chunk.retrieval_sources else 0.0

            if intent.is_name:
                chunk.name_score = _name_density_score(chunk.text)
                chunk.final_score = (
                    chunk.rrf_score
                    + 0.2 * chunk.lexical_score
                    + 0.3 * chunk.name_score
                    + 0.15 * harm_score
                    + 0.15 * year_score
                    + 0.2 * numeric_score
                    + title_boost
                    + page_boost
                    + dual_source
                    - bib_penalty
                    - toc_penalty
                )
            else:
                chunk.name_score = 0.0
                chunk.final_score = (
                    chunk.rrf_score
                    + 0.3 * chunk.lexical_score
                    + 0.2 * harm_score
                    + 0.2 * year_score
                    + 0.25 * numeric_score
                    + title_boost
                    + page_boost
                    + (0.1 if intent.is_quantitative and "%" in chunk.text else 0.0)
                    + dual_source
                    - bib_penalty
                    - toc_penalty
                )

        ranked = sorted(pool.values(), key=lambda c: c.final_score, reverse=True)
        ranked = rerank_chunks(query, ranked)
        per_doc_cap = max_per_document if max_per_document is not None else (
            limit if document_id else (4 if document_ids and len(document_ids) <= 3 else 2)
        )
        selected = _select_diverse(ranked, limit, max_per_document=per_doc_cap)

        logger.info(
            "Hybrid retrieval: queries=%s pool=%s -> top %s (intent temporal=%s harm=%s pages=%s)",
            len(queries),
            len(pool),
            len(selected),
            intent.is_temporal,
            intent.harm_related,
            list(intent.page_refs),
        )
        return selected

    async def _vector_hits(
        self,
        query: str,
        pool_size: int,
        *,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[dict]:
        try:
            embedding = await self.embedding_client.embed_query(query)
            similar = self.vector_db.search_similar_text(
                embedding,
                limit=pool_size,
                document_id=document_id,
                document_ids=document_ids,
            )
        except Exception as exc:
            logger.warning("Vector retrieval failed for %r: %s", query[:80], exc)
            return []

        hits = []
        for item in similar:
            payload = item.get("payload") or {}
            text = (payload.get("text") or "").strip()
            if not text:
                continue
            doc_id = str(payload.get("document_id") or "")
            title = None
            if doc_id:
                title = self.graph_db.get_document_title(doc_id)
            hits.append({
                "chunk_id": str(item.get("id")),
                "text": text,
                "document_id": doc_id,
                "title": title,
                "score": float(item.get("score") or 0.0),
            })
        return hits

    def _keyword_hits(
        self,
        query: str,
        pool_size: int,
        *,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[dict]:
        try:
            rows = self.graph_db.search_text_chunks(
                query,
                limit=pool_size,
                document_id=document_id,
                document_ids=document_ids,
            )
        except Exception as exc:
            logger.warning("Keyword retrieval failed: %s", exc)
            return []

        return [
            {
                "chunk_id": str(row.get("id") or ""),
                "text": (row.get("text") or "").strip(),
                "document_id": str(row.get("document_id") or ""),
                "title": row.get("title"),
            }
            for row in rows
            if row.get("text")
        ]
