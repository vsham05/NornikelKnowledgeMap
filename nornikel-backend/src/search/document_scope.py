"""Scope RAG to the right document(s) to prevent cross-document hallucination."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from search.query_processing import tokenize

ScopeMode = Literal["single", "multi", "explicit", "aggregate"]

_COMPARISON_RE = re.compile(
    r"\b("
    r"compare|comparison|versus|vs\.?|difference|differences|between|"
    r"both\s+documents|each\s+other|"
    r"сравн|разниц|отличи|между|оба\s+документ"
    r")\b",
    re.IGNORECASE,
)

_AGGREGATE_RE = re.compile(
    r"\b("
    r"all\s+documents|every\s+document|each\s+document|across\s+all|"
    r"all\s+reports|all\s+articles|all\s+sources|every\s+report|"
    r"все\s+документ|каждом\s+документ|по\s+всем\s+документ|всех\s+документ"
    r")\b",
    re.IGNORECASE,
)

AMBIGUITY_SCORE_RATIO = 0.88

_TITLE_STOP = frozenset({
    "the", "and", "for", "from", "with", "about", "article", "report", "study",
    "документ", "статья", "отчет", "отчёт", "материал",
})


@dataclass(frozen=True)
class DocumentScope:
    mode: ScopeMode
    primary_document_id: str | None
    primary_title: str | None
    document_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class DocumentCandidate:
    document_id: str
    title: str | None
    score: float


@dataclass(frozen=True)
class DisambiguationResult:
    ambiguous: bool
    candidates: tuple[DocumentCandidate, ...]


def _title_terms(title: str) -> list[str]:
    terms = [
        t for t in tokenize(title, min_length=3)
        if t not in _TITLE_STOP and len(t) >= 3
    ]
    return terms[:8]


def document_title_in_query(question: str, title: str | None) -> bool:
    if not title or not title.strip():
        return False
    q_lower = question.lower()
    terms = _title_terms(title)
    if not terms:
        return False
    hits = [t for t in terms if t in q_lower]
    if len(hits) >= 2:
        return True
    if len(hits) == 1 and len(hits[0]) >= 5:
        return True
    # Full short title substring (e.g. "Birch")
    compact = re.sub(r"\s+", " ", title.lower().strip())
    if len(compact) >= 4 and compact in q_lower:
        return True
    return False


def query_requests_comparison(question: str) -> bool:
    return bool(_COMPARISON_RE.search(question))


def query_requests_aggregate(question: str) -> bool:
    return bool(_AGGREGATE_RE.search(question))


def detect_disambiguation(
    ranked: list[tuple[str, float, str | None]],
    *,
    forced_document_id: str | None = None,
    comparison: bool = False,
    aggregate: bool = False,
) -> DisambiguationResult:
    """True when top documents score too close to auto-pick safely."""
    candidates = tuple(
        DocumentCandidate(doc_id, title, score)
        for doc_id, score, title in ranked[:4]
    )
    if forced_document_id or comparison or aggregate or len(ranked) < 2:
        return DisambiguationResult(False, candidates)

    top_score = ranked[0][1]
    second_score = ranked[1][1]
    if top_score <= 0:
        return DisambiguationResult(False, candidates)

    if second_score / top_score >= AMBIGUITY_SCORE_RATIO:
        return DisambiguationResult(True, candidates)
    return DisambiguationResult(False, candidates)


def _document_catalog(chunks: list[dict]) -> dict[str, str | None]:
    catalog: dict[str, str | None] = {}
    for chunk in chunks:
        doc_id = str(chunk.get("document_id") or "").strip()
        if not doc_id:
            continue
        if doc_id not in catalog or not catalog[doc_id]:
            catalog[doc_id] = chunk.get("title")
    return catalog


def find_explicit_documents(
    question: str,
    chunks: list[dict],
    *,
    all_documents: list[dict] | None = None,
) -> list[str]:
    catalog = _document_catalog(chunks)
    if all_documents:
        for doc in all_documents:
            doc_id = str(doc.get("id") or doc.get("document_id") or "").strip()
            title = doc.get("title")
            if doc_id and title and doc_id not in catalog:
                catalog[doc_id] = title

    matched: list[str] = []
    for doc_id, title in catalog.items():
        if document_title_in_query(question, title):
            matched.append(doc_id)
    return matched


def aggregate_document_scores(chunks: list[dict]) -> list[tuple[str, float, str | None]]:
    scores: dict[str, float] = {}
    titles: dict[str, str | None] = {}
    for chunk in chunks:
        doc_id = str(chunk.get("document_id") or "").strip()
        if not doc_id:
            continue
        scores[doc_id] = scores.get(doc_id, 0.0) + float(chunk.get("score") or 0.0)
        if chunk.get("title"):
            titles[doc_id] = chunk["title"]
    return sorted(
        [(doc_id, score, titles.get(doc_id)) for doc_id, score in scores.items()],
        key=lambda item: item[1],
        reverse=True,
    )


def resolve_document_scope(
    question: str,
    chunks: list[dict],
    *,
    all_documents: list[dict] | None = None,
    forced_document_id: str | None = None,
) -> DocumentScope:
    if forced_document_id:
        title = None
        if all_documents:
            for doc in all_documents:
                if str(doc.get("id") or "") == forced_document_id:
                    title = doc.get("title")
                    break
        if not title:
            title = _document_catalog(chunks).get(forced_document_id)
        return DocumentScope(
            "explicit",
            forced_document_id,
            title,
            (forced_document_id,),
            "user_filter",
        )

    if not chunks and not all_documents:
        return DocumentScope("single", None, None, (), "empty")

    if query_requests_aggregate(question) and all_documents:
        doc_ids = tuple(
            str(doc.get("id") or "")
            for doc in all_documents
            if doc.get("id")
        )
        if doc_ids:
            return DocumentScope("aggregate", None, None, doc_ids, "aggregate_query")

    explicit = find_explicit_documents(question, chunks, all_documents=all_documents)
    if len(explicit) == 1:
        doc_id = explicit[0]
        title = _document_catalog(chunks).get(doc_id)
        if not title and all_documents:
            for doc in all_documents:
                if str(doc.get("id") or "") == doc_id:
                    title = doc.get("title")
                    break
        return DocumentScope("explicit", doc_id, title, (doc_id,), "title_in_query")
    if len(explicit) > 1:
        return DocumentScope("multi", None, None, tuple(explicit), "multiple_titles_in_query")

    ranked = aggregate_document_scores(chunks)
    if not ranked:
        return DocumentScope("single", None, None, (), "no_document_ids")

    if query_requests_comparison(question):
        return DocumentScope(
            "multi",
            ranked[0][0],
            ranked[0][2],
            tuple(doc_id for doc_id, _, _ in ranked),
            "comparison_query",
        )

    if len(ranked) == 1:
        doc_id, _, title = ranked[0]
        return DocumentScope("single", doc_id, title, (doc_id,), "only_one_document")

    # Default: one primary document — avoids blending unrelated corpora.
    doc_id, _, title = ranked[0]
    return DocumentScope("single", doc_id, title, (doc_id,), "primary_relevance")


def filter_chunks_to_documents(chunks: list[dict], document_ids: set[str]) -> list[dict]:
    if not document_ids:
        return chunks
    return [
        chunk
        for chunk in chunks
        if str(chunk.get("document_id") or "") in document_ids
    ]


def group_chunks_by_document(chunks: list[dict]) -> list[tuple[str | None, str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    titles: dict[str, str | None] = {}
    for chunk in chunks:
        doc_id = str(chunk.get("document_id") or "_unknown")
        groups.setdefault(doc_id, []).append(chunk)
        if chunk.get("title"):
            titles[doc_id] = chunk["title"]

    ranked = sorted(
        groups.items(),
        key=lambda item: max(float(c.get("score") or 0.0) for c in item[1]),
        reverse=True,
    )
    return [(titles.get(doc_id), doc_id, group) for doc_id, group in ranked]


def scope_instruction(scope: DocumentScope, answer_lang: str) -> str:
    if scope.mode == "single" and scope.primary_title:
        if answer_lang == "ru":
            return (
                f"Используй ТОЛЬКО документ «{scope.primary_title}». "
                "Не добавляй факты из других документов."
            )
        return (
            f"Use ONLY the document \"{scope.primary_title}\". "
            "Do not add facts from any other document."
        )

    if scope.mode == "explicit" and scope.primary_title:
        if answer_lang == "ru":
            return (
                f"Вопрос относится к документу «{scope.primary_title}». "
                "Отвечай только по нему."
            )
        return (
            f"The question targets the document \"{scope.primary_title}\". "
            "Answer from that document only."
        )

    if scope.mode == "multi":
        if answer_lang == "ru":
            return (
                "Сопоставь несколько документов. Отвечай по каждому отдельно. "
                "Никогда не смешивай факты из разных документов в одном предложении. "
                "Указывай название документа перед каждым блоком фактов."
            )
        return (
            "Multiple documents apply. Answer per document in separate sentences or bullets. "
            "NEVER merge facts from different documents into one sentence. "
            "Name the source document before each block of facts."
        )

    if scope.mode == "aggregate":
        if answer_lang == "ru":
            return (
                "Ответь по каждому документу отдельным блоком. "
                "Не объединяй факты из разных документов."
            )
        return (
            "Answer with a separate block per document. "
            "Do not merge facts across documents."
        )

    if answer_lang == "ru":
        return "Не смешивай факты из разных документов в одном ответе."
    return "Do not mix facts from different documents in one answer."
