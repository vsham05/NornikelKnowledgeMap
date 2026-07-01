"""Rerank retrieved chunks (cross-encoder when available, lexical fallback)."""

from __future__ import annotations

import logging
import math
import re
from typing import TYPE_CHECKING

from search.query_processing import significant_terms

if TYPE_CHECKING:
    from search.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

_CROSS_ENCODER = None
_CROSS_ENCODER_FAILED = False

_BIGRAM_RE = re.compile(r"[a-zA-Z\u0400-\u04FF]{3,}")


def _idf_weights(terms: list[str], corpus: list[str]) -> dict[str, float]:
    n = len(corpus) or 1
    weights: dict[str, float] = {}
    for term in terms:
        df = sum(1 for doc in corpus if term in doc)
        weights[term] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
    return weights


def _lexical_rerank_score(query: str, text: str, idf: dict[str, float]) -> float:
    terms = significant_terms(query)
    if not terms:
        return 0.0
    lower = text.lower()
    total_idf = sum(idf.get(t, 1.0) for t in terms) or 1.0
    hit_idf = sum(idf.get(t, 1.0) for t in terms if t in lower)
    coverage = hit_idf / total_idf

    # Phrase / bigram overlap from query
    query_tokens = _BIGRAM_RE.findall(query.lower())
    bigram_hits = 0
    for i in range(len(query_tokens) - 1):
        phrase = f"{query_tokens[i]} {query_tokens[i + 1]}"
        if phrase in lower:
            bigram_hits += 1
    bigram_score = min(1.0, bigram_hits / max(1, len(query_tokens) - 1))

    return 0.72 * coverage + 0.28 * bigram_score


def _load_cross_encoder():
    global _CROSS_ENCODER, _CROSS_ENCODER_FAILED
    if _CROSS_ENCODER_FAILED:
        return None
    if _CROSS_ENCODER is not None:
        return _CROSS_ENCODER
    try:
        from sentence_transformers import CrossEncoder

        _CROSS_ENCODER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        logger.info("Loaded cross-encoder reranker: ms-marco-MiniLM-L-6-v2")
        return _CROSS_ENCODER
    except Exception as exc:
        _CROSS_ENCODER_FAILED = True
        logger.info("Cross-encoder unavailable (%s); using lexical reranker", exc)
        return None


def rerank_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    *,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Rerank chunks by query–passage relevance before diversity selection."""
    if not chunks:
        return []

    model = _load_cross_encoder()
    corpus = [c.text.lower() for c in chunks]
    terms = significant_terms(query)
    idf = _idf_weights(terms, corpus)

    if model is not None:
        pairs = [(query, chunk.text[:512]) for chunk in chunks]
        try:
            ce_scores = model.predict(pairs)
            for chunk, ce_score in zip(chunks, ce_scores):
                lex = _lexical_rerank_score(query, chunk.text, idf)
                chunk.final_score = (
                    0.55 * float(ce_score)
                    + 0.25 * chunk.final_score
                    + 0.20 * lex
                )
        except Exception as exc:
            logger.warning("Cross-encoder predict failed: %s", exc)
            for chunk in chunks:
                lex = _lexical_rerank_score(query, chunk.text, idf)
                chunk.final_score = 0.6 * chunk.final_score + 0.4 * lex
    else:
        for chunk in chunks:
            lex = _lexical_rerank_score(query, chunk.text, idf)
            chunk.final_score = 0.55 * chunk.final_score + 0.45 * lex

    ranked = sorted(chunks, key=lambda c: c.final_score, reverse=True)
    if top_k is not None:
        return ranked[:top_k]
    return ranked
