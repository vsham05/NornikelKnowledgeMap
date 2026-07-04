"""Chunk batching and merging for fast long-document ingestion."""

from __future__ import annotations

import re

from domain.dto.document import DocumentChunkDTO

LONG_DOC_PAGE_THRESHOLD = 35
# Fits ~3k tokens of body text inside an 8192-token local model after ontology prompt overhead.
DEFAULT_EXTRACTION_TEXT_CHARS = 12_000
MAX_EXTRACTION_BATCHES = 24
EMBED_MERGE_TARGET_CHARS = 1_400
EMBED_MERGE_MAX_CHUNKS = 150

_NUMERIC_UNIT_RE = re.compile(
    r"(?:\d+(?:[.,]\d+)?|"
    r"ph|mg/l|ppm|kpa|mpa|°c|℃|min|hours?|g/l|%|"
    r"million|billion|tonnes?|tonne|mt|t/y|t/a|pa\b|g/l)",
    re.IGNORECASE,
)


def _chunk_priority(text: str) -> float:
    """Boost table and measurement-dense passages when thinning embeddings."""
    base = _numeric_richness(text)
    if "[TABLE]" in text:
        base += 1.5
    return base


def _numeric_richness(text: str) -> float:
    """Score how measurement-dense a passage is (for keeping hackathon-critical facts)."""
    if not text.strip():
        return 0.0
    hits = len(_NUMERIC_UNIT_RE.findall(text))
    return min(3.0, hits / 4.0)


def _prioritize_chunks_for_limit(
    chunks: list[DocumentChunkDTO],
    max_chunks: int,
) -> list[DocumentChunkDTO]:
    """Keep stratified coverage + numeric-rich pages when thinning for Qdrant."""
    n = len(chunks)
    if n <= max_chunks:
        return chunks

    must_keep: set[int] = {0, n - 1}
    ranked = sorted(range(n), key=lambda i: _chunk_priority(chunks[i].text or ""), reverse=True)
    for idx in ranked[: max(6, max_chunks // 4)]:
        must_keep.add(idx)

    stride = max(1, n // max(1, max_chunks - len(must_keep)))
    for i in range(0, n, stride):
        must_keep.add(i)

    selected = sorted(must_keep)[:max_chunks]
    if len(selected) < max_chunks:
        for i in range(n):
            if i not in must_keep:
                selected.append(i)
            if len(selected) >= max_chunks:
                break
        selected = sorted(set(selected))[:max_chunks]

    return [chunks[i] for i in selected]


def stratified_document_text(
    chunks: list[DocumentChunkDTO],
    *,
    max_chars: int,
    sample_points: int = 32,
) -> str:
    """Sample text across a long document (start/middle/end + evenly spaced pages)."""
    usable = [c for c in chunks if c.text and c.text.strip()]
    if not usable:
        return ""

    if len(usable) <= 12:
        parts: list[str] = []
        total = 0
        for chunk in usable:
            piece = chunk.text.strip()
            parts.append(piece)
            total += len(piece)
            if total >= max_chars:
                break
        return "\n\n".join(parts)[:max_chars]

    n = len(usable)
    indices: set[int] = {0, 1, 2, max(0, n - 2), n - 1}
    for i in range(sample_points):
        frac = i / max(sample_points - 1, 1)
        indices.add(min(n - 1, int(n * frac)))

    parts: list[str] = []
    total = 0
    for idx in sorted(indices):
        chunk = usable[idx]
        page = chunk.page_number
        header = f"[page {page}]\n" if page else ""
        piece = chunk.text.strip()
        block = f"{header}{piece}"
        parts.append(block)
        total += len(block)
        if total >= max_chars:
            break
    return "\n\n".join(parts)[:max_chars]


def _chunk_char_len(chunk: DocumentChunkDTO) -> int:
    return len((chunk.text or "").strip())


def _split_oversized_chunk(
    chunk: DocumentChunkDTO,
    max_text_chars: int,
) -> list[DocumentChunkDTO]:
    text = (chunk.text or "").strip()
    if len(text) <= max_text_chars:
        return [chunk]
    parts: list[DocumentChunkDTO] = []
    for start in range(0, len(text), max_text_chars):
        parts.append(
            DocumentChunkDTO(
                id=chunk.id,
                document_id=chunk.document_id,
                text=text[start : start + max_text_chars],
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
            )
        )
    return parts


def _thin_batches(
    batches: list[list[DocumentChunkDTO]],
    max_batches: int,
) -> list[list[DocumentChunkDTO]]:
    if max_batches <= 0 or max_batches >= len(batches):
        return batches
    if max_batches <= 0:
        return []
    if max_batches == 1:
        return [batches[len(batches) // 2]]

    scored: list[tuple[int, float]] = []
    for i, batch in enumerate(batches):
        text = "\n".join((c.text or "") for c in batch)
        scored.append((i, _chunk_priority(text)))

    must_keep: set[int] = {0, len(batches) - 1}
    for idx, _ in sorted(scored, key=lambda row: row[1], reverse=True)[: max(2, max_batches // 3)]:
        must_keep.add(idx)

    step = max(1, (len(batches) - 1) // max(1, max_batches - len(must_keep)))
    for i in range(0, len(batches), step):
        must_keep.add(min(len(batches) - 1, i))

    selected = sorted(must_keep)[:max_batches]
    return [batches[i] for i in selected]


def build_extraction_batches(
    chunks: list[DocumentChunkDTO],
    *,
    max_text_chars: int = DEFAULT_EXTRACTION_TEXT_CHARS,
    max_batches: int = MAX_EXTRACTION_BATCHES,
) -> list[list[DocumentChunkDTO]]:
    """Group page chunks into LLM batches that fit the model context window."""
    usable = [c for c in chunks if c.text and c.text.strip()]
    if not usable:
        return []

    expanded: list[DocumentChunkDTO] = []
    for chunk in usable:
        expanded.extend(_split_oversized_chunk(chunk, max_text_chars))

    batches: list[list[DocumentChunkDTO]] = []
    current: list[DocumentChunkDTO] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            batches.append(current)
            current = []
            current_len = 0

    for chunk in expanded:
        piece_len = _chunk_char_len(chunk)
        if current and current_len + piece_len + 2 > max_text_chars:
            flush()
        current.append(chunk)
        current_len += piece_len + (2 if current_len else 0)

    flush()
    return _thin_batches(batches, max_batches)


def merge_chunks_for_embedding(
    chunks: list[DocumentChunkDTO],
    *,
    target_chars: int = EMBED_MERGE_TARGET_CHARS,
    max_chunks: int = EMBED_MERGE_MAX_CHUNKS,
) -> list[DocumentChunkDTO]:
    """Merge page-level chunks into fewer, larger chunks for vector indexing."""
    usable = [c for c in chunks if c.text and c.text.strip()]
    if len(usable) <= 80:
        return usable

    merged: list[DocumentChunkDTO] = []
    buf_text: list[str] = []
    buf_start = usable[0]
    buf_len = 0

    def flush() -> None:
        nonlocal buf_text, buf_start, buf_len
        if not buf_text:
            return
        merged.append(
            DocumentChunkDTO(
                id=buf_start.id,
                document_id=buf_start.document_id,
                text="\n\n".join(buf_text),
                chunk_index=len(merged),
                page_number=buf_start.page_number,
                section_title=buf_start.section_title,
            )
        )
        buf_text = []
        buf_len = 0

    for chunk in usable:
        piece = chunk.text.strip()
        if not piece:
            continue
        if not buf_text:
            buf_start = chunk
        next_len = buf_len + len(piece) + (2 if buf_text else 0)
        if buf_text and next_len > target_chars:
            flush()
            buf_start = chunk
            buf_len = 0
        buf_text.append(piece)
        buf_len += len(piece) + (2 if len(buf_text) > 1 else 0)

    flush()

    if len(merged) > max_chunks and max_chunks > 0:
        return _prioritize_chunks_for_limit(merged, max_chunks)

    return merged
