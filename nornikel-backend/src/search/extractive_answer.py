"""Fallback answers built directly from embedding-retrieved passages (no LLM)."""

from __future__ import annotations

import re

_NUMERIC_SENTENCE = re.compile(
    r"[^.!?]*\d+(?:[.,]\d+)?[^.!?]*[.!?]",
    re.UNICODE,
)


def extractive_answer_from_chunks(
    question: str,
    chunks: list[dict],
    *,
    answer_lang: str = "en",
    max_passages: int = 4,
) -> str:
    """
    Surface the best embedding/keyword hits when the LLM is unavailable.
    RAG still uses embeddings for retrieval; this step skips generation.
    """
    if not chunks:
        return ""

    header = (
        "**Ответ на основе семантического поиска (эмбеддинги Qdrant):**\n\n"
        if answer_lang == "ru"
        else "**Answer from semantic search (Qdrant embeddings):**\n\n"
    )

    question_lower = question.lower()
    terms = [
        t.lower()
        for t in re.findall(r"[\w\u0400-\u04FF]+", question_lower)
        if len(t) >= 4
    ][:12]

    lines: list[str] = [header]
    used = 0

    for idx, chunk in enumerate(chunks, start=1):
        if used >= max_passages:
            break
        text = (chunk.get("text") or "").strip()
        if not text:
            continue

        title = chunk.get("title") or "Document"
        sources = chunk.get("retrieval_sources") or []
        via = "embedding + keyword" if len(sources) > 1 else (
            "embedding" if "vector" in sources else "keyword"
        )
        score = chunk.get("score")
        score_txt = f" · score {score:.2f}" if isinstance(score, (int, float)) else ""

        snippet = _best_snippet(text, terms, question)
        lines.append(f"**[{idx}]** ({title}{score_txt}, {via})\n{snippet}\n")
        used += 1

    if used == 0:
        return ""

    footer = (
        "\n_Сформировано из найденных фрагментов без LLM. Для связного ответа проверьте Ollama/Yandex._"
        if answer_lang == "ru"
        else "\n_Assembled from retrieved passages without LLM synthesis. Check Ollama/Yandex for a fluent answer._"
    )
    lines.append(footer)
    return "\n".join(lines)


def _best_snippet(text: str, terms: list[str], question: str) -> str:
    """Prefer sentences with numbers and query term overlap."""
    sentences = _NUMERIC_SENTENCE.findall(text)
    if not sentences:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

    if sentences:
        scored: list[tuple[float, str]] = []
        for sent in sentences:
            lower = sent.lower()
            term_hits = sum(1 for t in terms if t in lower)
            has_number = 1.0 if re.search(r"\d", sent) else 0.0
            scored.append((term_hits + has_number * 2, sent.strip()))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] > 0:
            top = [s for _, s in scored[:3]]
            return " ".join(top)[:900]

    cap = 700
    if len(text) <= cap:
        return text
    return text[:cap].rstrip() + "…"
