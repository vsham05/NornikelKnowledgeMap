"""Compress long chunks to query-relevant windows for the LLM context window."""

from __future__ import annotations

import re

from search.query_processing import YEAR_RE, significant_terms

_WINDOW = 420
_MAX_CHUNK_CHARS = 1400


def _find_windows(text: str, terms: list[str]) -> list[int]:
    lower = text.lower()
    positions: list[int] = []
    for term in terms:
        start = 0
        while True:
            idx = lower.find(term, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + len(term)
    for match in YEAR_RE.finditer(text):
        positions.append(match.start())
    return positions


def compress_chunk_for_query(text: str, query: str, max_chars: int = _MAX_CHUNK_CHARS) -> str:
    """Keep the most query-relevant span of a long chunk."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text

    terms = significant_terms(query)
    if not terms:
        return text[:max_chars] + "…"

    positions = _find_windows(text, terms)
    if not positions:
        return text[:max_chars] + "…"

    best_start = 0
    best_hits = -1
    step = max(80, max_chars // 4)
    for start in range(0, max(1, len(text) - max_chars), step):
        window = text[start : start + max_chars].lower()
        hits = sum(1 for term in terms if term in window)
        if hits > best_hits:
            best_hits = hits
            best_start = start

    # Fine-tune: center on nearest term hit
    if positions:
        anchor = min(positions, key=lambda p: abs(p - best_start))
        best_start = max(0, anchor - _WINDOW)

    snippet = text[best_start : best_start + max_chars].strip()
    prefix = "…" if best_start > 0 else ""
    suffix = "…" if best_start + max_chars < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def compress_chunks(chunks: list[dict], query: str) -> list[dict]:
    """Return chunks with text compressed in-place (copies dicts)."""
    result = []
    for chunk in chunks:
        copy = dict(chunk)
        copy["text"] = compress_chunk_for_query(copy.get("text") or "", query)
        result.append(copy)
    return result
