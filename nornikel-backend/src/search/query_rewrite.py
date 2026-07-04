"""LLM query rewrite for better retrieval recall."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from search.query_processing import (
    extract_numeric_anchors,
    extract_search_terms,
    keyword_search_string,
    significant_terms,
)

logger = logging.getLogger(__name__)

REWRITE_SYSTEM = """You help search a scientific and engineering R&D document knowledge base (Russian and English).
Given a user question, produce search terms that will retrieve passages with NUMERIC data.

Reply with JSON only:
{"search_query": "one concise sentence for semantic search", "keywords": ["term1", "term2"]}

Rules:
- search_query: rephrase the information need clearly (processes, materials, geography, years).
- keywords: 6-12 important words/phrases — include ALL numbers, units (мг/л, %, м/ч), chemical symbols (Ca, Mg, Ni, Au), and technical terms from the question.
- Keep Russian keywords in Cyrillic; English in Latin script.
- Do not answer the question — only optimize retrieval.
- Preserve numeric thresholds and ranges exactly (e.g. 200–300 мг/л, ≤1000 мг/дм³)."""

_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


@dataclass(frozen=True)
class RewrittenQuery:
    original: str
    search_query: str
    keywords: tuple[str, ...]


def should_skip_llm_rewrite(question: str) -> bool:
    """
    Skip the rewrite LLM call — hybrid embedding+keyword retrieval handles long queries.
    Only very short/vague questions get an LLM rewrite.
    """
    q = question.strip()
    if len(q) < 28:
        return False
    return True


def _heuristic_rewrite(question: str) -> RewrittenQuery:
    terms = extract_search_terms(question, limit=14)
    anchors = extract_numeric_anchors(question)
    extra = [a for a in anchors if a.lower() not in {t.lower() for t in terms}]
    keywords = tuple((terms + extra)[:12])
    search = question.strip()
    if keywords:
        search = f"{question.strip()} — ключевые термины: {', '.join(keywords[:10])}"
    return RewrittenQuery(
        original=question.strip(),
        search_query=search,
        keywords=keywords or tuple(terms[:10]),
    )


def _parse_rewrite_json(text: str, fallback: str) -> RewrittenQuery | None:
    import json

    for match in _JSON_RE.finditer(text):
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        search_query = str(data.get("search_query") or "").strip()
        raw_kw = data.get("keywords") or []
        keywords = tuple(
            str(k).strip()
            for k in raw_kw
            if isinstance(k, str) and k.strip()
        )[:10]
        if search_query:
            return RewrittenQuery(
                original=fallback.strip(),
                search_query=search_query,
                keywords=keywords or tuple(significant_terms(fallback)),
            )
    return None


async def rewrite_query_for_retrieval(llm_client, question: str) -> RewrittenQuery:
    """Rewrite user question into retrieval-optimized queries (LLM with heuristic fallback)."""
    question = (question or "").strip()
    if not question:
        return _heuristic_rewrite("")

    if should_skip_llm_rewrite(question):
        logger.info("Query rewrite: heuristic (embedding retrieval handles this query)")
        return _heuristic_rewrite(question)

    try:
        raw = await llm_client.chat(
            user_message=f"USER QUESTION:\n{question}",
            system_message=REWRITE_SYSTEM,
            temperature=0.0,
        )
        parsed = _parse_rewrite_json(raw, question)
        if parsed:
            logger.info(
                "Query rewrite: search_query=%r keywords=%s",
                parsed.search_query[:80],
                list(parsed.keywords)[:6],
            )
            return parsed
    except Exception as exc:
        logger.warning("Query rewrite failed, using heuristic: %s", exc)

    return _heuristic_rewrite(question)


def auxiliary_retrieval_queries(rewritten: RewrittenQuery) -> list[str]:
    """Distinct queries for multi-query RRF (original always retrieved separately)."""
    queries: list[str] = []
    if rewritten.search_query and rewritten.search_query != rewritten.original:
        queries.append(rewritten.search_query)
    kw_string = keyword_search_string(rewritten.original, list(rewritten.keywords))
    if kw_string and kw_string not in queries and kw_string != rewritten.original:
        queries.append(kw_string)
    return queries
