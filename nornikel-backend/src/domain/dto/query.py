from uuid import UUID
from pydantic import BaseModel, Field


class DocumentCandidateDTO(BaseModel):
    document_id: str
    title: str | None = None
    score: float = 0.0


class UserQueryDTO(BaseModel):
    """Запрос пользователя."""
    text: str | None = Field(None, description="Текстовый запрос")
    document_id: str | None = Field(
        None, description="Optional: search only within this document"
    )
    image_path: str | None = Field(None, description="Путь к изображению для визуального поиска")
    filters: dict[str, str] = Field(
        default_factory=dict,
        description="Фильтры: {material: 'Ti-6Al-4V', property: 'прочность'}"
    )


class SourceExcerptDTO(BaseModel):
    """A numbered excerpt passed to the LLM as context (matches [1], [2], … in answers)."""
    index: int = Field(..., ge=1)
    text: str
    document_id: str
    title: str | None = None
    score: float | None = None


class SearchResultDTO(BaseModel):
    """Результат поиска."""
    experiment_ids: list[UUID] = Field(default_factory=list)
    document_ids: list[UUID] = Field(default_factory=list)
    image_ids: list[UUID] = Field(default_factory=list)
    answer_text: str | None = Field(None, description="Синтезированный ответ")
    confidence: float = Field(
        0.0, ge=0, le=1, description="Confidence score from retrieval relevance and answer support"
    )
    sources: list[SourceExcerptDTO] = Field(
        default_factory=list,
        description="Numbered excerpts used to generate the answer",
    )
    needs_disambiguation: bool = Field(
        False,
        description="True when the user should pick which document to search",
    )
    document_candidates: list[DocumentCandidateDTO] = Field(
        default_factory=list,
        description="Top document options when needs_disambiguation is true",
    )
    
    class Config:
        frozen = False