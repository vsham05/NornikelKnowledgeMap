"""Confidence scoring from retrieval scores + answer signals."""

from __future__ import annotations

import re
from typing import Literal

RetrievalMethod = Literal["vector", "keyword", "hybrid"]

# Cosine scores from mxbai-embed-large typically cluster between ~0.4 and ~0.75
# for good matches — rescale so user-facing confidence aligns with answer quality.
VECTOR_SCORE_FLOOR = 0.40
VECTOR_SCORE_CEILING = 0.75
DISPLAY_CONFIDENCE_MIN = 0.72
DISPLAY_CONFIDENCE_MAX = 0.94

HEDGE_PATTERNS = [
    r"not possible to determine",
    r"cannot determine",
    r"can't determine",
    r"unable to (?:answer|determine|conclude)",
    r"insufficient (?:information|context|data|evidence)",
    r"does not (?:contain|provide|address|include)",
    r"do not (?:contain|provide|address|include)",
    r"not enough information",
    r"no (?:specific|sufficient|direct) (?:information|details|data)",
    r"more information .{0,40} (?:needed|required|necessary)",
    r"what is missing",
    r"based on the (?:given |provided )?context,? it is not",
    r"the excerpts do not",
    r"context does not",
]

_CITATION_RE = re.compile(r"\[\d+\]")
_HEDGE_RE = re.compile("|".join(f"(?:{p})" for p in HEDGE_PATTERNS), re.IGNORECASE)


def _rescale_vector_score(raw: float) -> float:
    clamped = max(VECTOR_SCORE_FLOOR, min(VECTOR_SCORE_CEILING, raw))
    span = VECTOR_SCORE_CEILING - VECTOR_SCORE_FLOOR
    if span <= 0:
        return DISPLAY_CONFIDENCE_MAX
    ratio = (clamped - VECTOR_SCORE_FLOOR) / span
    return DISPLAY_CONFIDENCE_MIN + ratio * (DISPLAY_CONFIDENCE_MAX - DISPLAY_CONFIDENCE_MIN)


def retrieval_scores(chunks: list[dict], method: RetrievalMethod) -> list[float]:
    if not chunks:
        return []

    if method == "hybrid":
        raw_scores = [
            float(chunk["score"])
            for chunk in chunks[:3]
            if chunk.get("score") is not None
        ]
        if raw_scores:
            # final_score is already fused (RRF + lexical); map to display range
            return [min(DISPLAY_CONFIDENCE_MAX, DISPLAY_CONFIDENCE_MIN + s * 0.5) for s in raw_scores]
        return [0.75]

    if method == "vector":
        return [
            _rescale_vector_score(float(chunk["score"]))
            for chunk in chunks[:3]
            if chunk.get("score") is not None
        ]

    terms = [t for t in chunks[0].get("_query_terms", []) if t]
    if not terms:
        return [0.58]

    pseudo: list[float] = []
    for chunk in chunks[:3]:
        text = (chunk.get("text") or "").lower()
        hits = sum(1 for term in terms if term in text)
        pseudo.append(0.55 + 0.15 * (hits / len(terms)))
    return pseudo


def _citation_boost(answer: str) -> float:
    citations = len(_CITATION_RE.findall(answer))
    if citations >= 3:
        return 0.06
    if citations >= 1:
        return 0.04
    return 0.0


def compute_confidence(
    chunks: list[dict],
    method: RetrievalMethod,
    answer: str = "",
) -> float:
    """Map retrieval + answer signals to a user-facing 0–1 confidence score."""
    scores = retrieval_scores(chunks, method)
    if not scores:
        return 0.0

    confidence = sum(scores) / len(scores)

    if method == "keyword":
        confidence = min(confidence, 0.78)

    if len(chunks) >= 3:
        confidence = min(1.0, confidence + 0.03)

    confidence = min(1.0, confidence + _citation_boost(answer))
    confidence = apply_hedge_penalty(confidence, answer)

    return round(confidence, 3)


def apply_hedge_penalty(confidence: float, answer: str) -> float:
    """Lower confidence when the LLM signals the sources don't support an answer."""
    if confidence <= 0 or not answer.strip():
        return confidence

    if _HEDGE_RE.search(answer):
        return round(min(confidence, 0.58), 3)

    return confidence
