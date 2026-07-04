from fastapi import APIRouter, Form, HTTPException
import logging

from domain.dto.query import UserQueryDTO
from infra.llm_client import is_context_overflow
from search.rag_service import RAGService
from settings import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _result_payload(query: str, result) -> dict:
    return {
        "query": query,
        "answer": result.answer_text,
        "document_ids": [str(doc_id) for doc_id in result.document_ids],
        "experiment_ids": [str(eid) for eid in result.experiment_ids],
        "confidence": result.confidence,
        "sources": [s.model_dump() for s in result.sources],
        "needs_disambiguation": result.needs_disambiguation,
        "document_candidates": [c.model_dump() for c in result.document_candidates],
        "retrieval_scope": result.retrieval_scope.model_dump(),
    }


def _block_search_during_ingest() -> None:
    from api.routers.ingestion import has_active_ingest

    if has_active_ingest():
        raise HTTPException(
            status_code=503,
            detail=(
                "Document ingestion is in progress. Wait until processing finishes "
                "before asking questions — the LLM is reserved for indexing."
            ),
        )


async def _run_rag(query: UserQueryDTO):
    _block_search_during_ingest()
    settings = get_settings()
    rag_service = RAGService(settings)
    try:
        result = await rag_service.answer_question(query)
    except Exception as exc:
        logger.exception("RAG search failed: %s", exc)
        lang = "ru" if any("\u0400" <= c <= "\u04FF" for c in (query.text or "")) else "en"
        msg = str(exc).lower()
        if is_context_overflow(exc):
            if lang == "ru":
                answer = (
                    "Контекст модели переполнен. Сузьте запрос, выберите один документ "
                    "в фильтре или переключитесь на модель с большим контекстом."
                )
            else:
                answer = (
                    "The model context window was exceeded. Try a narrower query, "
                    "select one document in the filter, or switch to a larger-context model."
                )
        elif "timeout" in msg or "timed out" in msg or "connection" in msg:
            if lang == "ru":
                answer = (
                    "LLM не ответил вовремя. Проверьте, что Ollama запущен, "
                    "или переключитесь на Yandex Cloud в переключателе модели."
                )
            else:
                answer = (
                    "The LLM timed out. Check that Ollama is running, "
                    "or switch to Yandex Cloud in the model switcher."
                )
        else:
            if lang == "ru":
                answer = (
                    "Не удалось сформировать ответ. Проверьте LLM (Ollama/Yandex) "
                    "и попробуйте сузить запрос или выбрать один документ."
                )
            else:
                answer = (
                    "Could not generate an answer. Check that the LLM (Ollama/Yandex) "
                    "is running, then try a narrower query or pick one document."
                )
        return {
            "query": query.text or "",
            "answer": answer,
            "document_ids": [],
            "experiment_ids": [],
            "confidence": 0.0,
            "sources": [],
            "needs_disambiguation": False,
            "document_candidates": [],
            "retrieval_scope": {
                "mode": "full_corpus",
                "filter_document_ids": [],
                "filter_document_titles": [],
                "filters_applied": {},
                "graph_match_count": 0,
            },
        }
    return _result_payload(query.text or "", result)


@router.post("/search")
async def search(query: str = Form(...)):
    """Текстовый поиск с генерацией ответа через RAG."""
    return await _run_rag(UserQueryDTO(text=query))


@router.post("/search/json")
async def search_json(body: UserQueryDTO):
    """RAG search with JSON body (for Next.js frontend)."""
    if not body.text:
        return {
            "query": "",
            "answer": "Query text is required.",
            "document_ids": [],
            "confidence": 0,
            "sources": [],
            "needs_disambiguation": False,
            "document_candidates": [],
        }
    return await _run_rag(body)