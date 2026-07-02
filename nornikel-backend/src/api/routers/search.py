from fastapi import APIRouter, Form

from domain.dto.query import UserQueryDTO
from search.rag_service import RAGService
from settings import get_settings

router = APIRouter()


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


async def _run_rag(query: UserQueryDTO):
    settings = get_settings()
    rag_service = RAGService(settings)
    result = await rag_service.answer_question(query)
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