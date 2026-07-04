"""Compress long chunks to query-relevant windows for the LLM context window."""

from __future__ import annotations

import re

from infra.llm_runtime import get_effective_llm_provider, get_local_model, get_yandex_model
from infra.local_models import context_tokens_for_local_model
from infra.yandex_models import get_yandex_model_info
from search.query_processing import YEAR_RE, significant_terms, extract_numeric_anchors, extract_search_terms
from settings import Settings

_WINDOW = 480
_MAX_CHUNK_CHARS = 2200
_RAG_RESERVED_TOKENS = 2500
_CHARS_PER_TOKEN = 3.2
_MIN_CHUNK_CHARS = 480
_CHUNK_OVERHEAD_CHARS = 72
_STAT_LINE_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:million|billion)?\s*(?:tonnes?|tons?|t/y|t/a|mt)\b",
    re.IGNORECASE,
)
_COMPRESSION_SYNONYMS: dict[str, tuple[str, ...]] = {
    "global production": ("worldwide", "produced worldwide", "world production"),
    "world production": ("worldwide", "produced worldwide", "global production"),
    "million tonnes": ("million tons", "million tonne", "mt"),
    "million tons": ("million tonnes", "million ton", "mt"),
}


def resolve_context_tokens(settings: Settings) -> int:
    """Active LLM context window (tokens)."""
    if get_effective_llm_provider() == "yandex":
        info = get_yandex_model_info(get_yandex_model())
        if info:
            return info.context_tokens
        return settings.llm_context_tokens

    from infra.local_models import get_local_model_info

    ctx = context_tokens_for_local_model(
        get_local_model(),
        fallback=settings.llm_context_tokens,
    )
    info = get_local_model_info(get_local_model())
    # Ollama often runs 8k num_ctx unless tuned — keep RAG inside a safe window.
    if info and info.tier in ("standard", "light"):
        ctx = min(ctx, 8192)
    return ctx


def resolve_rag_max_chars(settings: Settings) -> int:
    """Total excerpt budget for RAG prompts after reserving instructions + output."""
    ctx = resolve_context_tokens(settings)
    if ctx <= 8192:
        reserved = 3000
        chars_per_token = 2.7
    else:
        reserved = _RAG_RESERVED_TOKENS
        chars_per_token = _CHARS_PER_TOKEN
    budget_tokens = max(1200, ctx - reserved)
    return int(budget_tokens * chars_per_token)


def resolve_rag_chunk_max_chars(settings: Settings, chunk_count: int) -> int:
    """Per-chunk compression limit derived from model context."""
    total = resolve_rag_max_chars(settings)
    slots = max(1, min(chunk_count, 12))
    per = total // slots
    return max(_MIN_CHUNK_CHARS, min(_MAX_CHUNK_CHARS, per))


def _expand_compression_terms(query: str, terms: list[str]) -> list[str]:
    """Add semantic variants so compression windows match paraphrased facts."""
    lower_q = query.lower()
    out = list(terms)
    seen = {t.lower() for t in terms}
    for phrase, variants in _COMPRESSION_SYNONYMS.items():
        if phrase not in lower_q:
            continue
        for variant in variants:
            key = variant.lower()
            if key not in seen:
                seen.add(key)
                out.append(variant)
    return out


def _material_terms(terms: list[str]) -> list[str]:
    """Substance/process terms used to tie stats to the question subject."""
    skip = {
        "according", "paper", "page", "current", "what", "when", "where",
        "global", "production", "million", "tonnes", "tons", "tonne", "ton",
        "world", "worldwide", "about", "year", "years",
    }
    return [t for t in terms if len(t) >= 4 and t.lower() not in skip]


def _stat_line_positions(text: str, material_terms: list[str]) -> list[int]:
    """Character offsets of measurement lines likely answering quantitative questions."""
    lower = text.lower()
    positions: list[int] = []
    for match in _STAT_LINE_RE.finditer(text):
        ctx_start = max(0, match.start() - 140)
        ctx_end = min(len(text), match.end() + 140)
        ctx = lower[ctx_start:ctx_end]
        if not material_terms or any(term in ctx for term in material_terms):
            positions.append(match.start())
    return positions


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
    positions.extend(_stat_line_positions(text, _material_terms(terms)))
    return positions


def compress_chunk_for_query(
    text: str,
    query: str,
    max_chars: int = _MAX_CHUNK_CHARS,
    *,
    prefer_page_cited: bool = False,
) -> str:
    """Keep the most query-relevant span of a long chunk."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text

    terms = extract_search_terms(query, limit=16) or significant_terms(query)
    terms = _expand_compression_terms(query, terms)
    anchors = extract_numeric_anchors(query)
    for anchor in anchors:
        if anchor.lower() not in {t.lower() for t in terms}:
            terms.append(anchor.lower())
    if not terms:
        return text[:max_chars] + "…"

    material_terms = _material_terms(terms)
    stat_positions = _stat_line_positions(text, material_terms)
    positions = _find_windows(text, terms)
    if not positions and not stat_positions:
        return text[:max_chars] + "…"

    best_start = 0
    best_score = -1.0
    step = max(80, max_chars // 4)
    for start in range(0, max(1, len(text) - max_chars), step):
        window = text[start : start + max_chars].lower()
        term_hits = sum(1 for term in terms if term in window)
        stat_hits = sum(1 for pos in stat_positions if start <= pos < start + max_chars)
        score = term_hits + stat_hits * 4
        if prefer_page_cited and stat_hits:
            score += 2
        if score > best_score:
            best_score = score
            best_start = start

    anchor_pool = stat_positions or positions
    if anchor_pool:
        anchor = min(anchor_pool, key=lambda p: abs(p - best_start))
        best_start = max(0, anchor - _WINDOW)

    snippet = text[best_start : best_start + max_chars].strip()
    prefix = "…" if best_start > 0 else ""
    suffix = "…" if best_start + max_chars < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def compress_chunks(chunks: list[dict], query: str, *, max_chunk_chars: int | None = None) -> list[dict]:
    """Return chunks with text compressed in-place (copies dicts)."""
    cap = max_chunk_chars if max_chunk_chars is not None else _MAX_CHUNK_CHARS
    result = []
    for chunk in chunks:
        copy = dict(chunk)
        original = copy.get("text") or ""
        page_cited = "page" in (copy.get("retrieval_sources") or [])
        compressed = compress_chunk_for_query(
            original,
            query,
            max_chars=cap,
            prefer_page_cited=page_cited,
        )
        if page_cited and _STAT_LINE_RE.search(original) and not _STAT_LINE_RE.search(compressed):
            stat_pos = _stat_line_positions(original, _material_terms(
                _expand_compression_terms(
                    query,
                    extract_search_terms(query, limit=16) or significant_terms(query),
                )
            ))
            if stat_pos:
                anchor = stat_pos[0]
                best_start = max(0, anchor - _WINDOW)
                snippet = original[best_start : best_start + cap].strip()
                prefix = "…" if best_start > 0 else ""
                suffix = "…" if best_start + cap < len(original) else ""
                compressed = f"{prefix}{snippet}{suffix}"
        copy["text"] = compressed
        result.append(copy)
    return result


def _chunk_char_cost(chunk: dict) -> int:
    return len(chunk.get("text") or "") + _CHUNK_OVERHEAD_CHARS


def fit_chunks_to_context_budget(
    chunks: list[dict],
    query: str,
    *,
    max_total_chars: int,
    max_chunk_chars: int | None = None,
    settings: Settings | None = None,
) -> list[dict]:
    """Trim chunk count and text so assembled RAG context fits the LLM window."""
    if not chunks:
        return chunks

    per_chunk = max_chunk_chars
    if per_chunk is None and settings is not None:
        per_chunk = resolve_rag_chunk_max_chars(settings, len(chunks))
    if per_chunk is None:
        per_chunk = max(_MIN_CHUNK_CHARS, max_total_chars // max(1, len(chunks)))
    compressed = compress_chunks(chunks, query, max_chunk_chars=per_chunk)

    if sum(_chunk_char_cost(c) for c in compressed) <= max_total_chars:
        return compressed

    order = list(range(len(compressed)))
    drop: set[int] = set()
    for idx in sorted(order, key=lambda i: compressed[i].get("score") or 0):
        if len(compressed) - len(drop) <= 3:
            break
        drop.add(idx)
        kept = [compressed[i] for i in order if i not in drop]
        if sum(_chunk_char_cost(c) for c in kept) <= max_total_chars:
            return kept

    kept = [compressed[i] for i in order if i not in drop]
    if not kept:
        kept = compressed[:3]

    total = sum(_chunk_char_cost(c) for c in kept)
    if total <= max_total_chars:
        return kept

    ratio = max_total_chars / max(1, total)
    trimmed: list[dict] = []
    for chunk in kept:
        copy = dict(chunk)
        text = copy.get("text") or ""
        new_len = max(_MIN_CHUNK_CHARS, int(len(text) * ratio))
        if len(text) > new_len:
            page_cited = "page" in (copy.get("retrieval_sources") or [])
            copy["text"] = compress_chunk_for_query(
                text,
                query,
                max_chars=new_len,
                prefer_page_cited=page_cited,
            )
        trimmed.append(copy)
    return trimmed
