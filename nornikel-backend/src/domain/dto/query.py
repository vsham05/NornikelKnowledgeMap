from uuid import UUID
from pydantic import BaseModel, Field


class DocumentCandidateDTO(BaseModel):
    document_id: str
    title: str | None = None
    score: float = 0.0


class StructuredFiltersDTO(BaseModel):
    """Multi-parameter filters for mining/metallurgy R&D queries."""
    material: str | None = Field(None, description="Material or substance name")
    material_class: str | None = Field(
        None,
        description="Process-material class: ore, concentrate, intermediate, metal, alloy, solution, …",
    )
    process: str | None = Field(None, description="Process: leaching, electrowinning, …")
    geography: str | None = Field(
        None, description="domestic | international | country name (Russia, CN, …)"
    )
    year_from: int | None = Field(None, ge=1900, le=2100)
    year_to: int | None = Field(None, ge=1900, le=2100)
    property_name: str | None = Field(None, description="Measured property or parameter")
    value_min: float | None = None
    value_max: float | None = None


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
    structured: StructuredFiltersDTO = Field(
        default_factory=StructuredFiltersDTO,
        description="Structured multi-parameter filters",
    )


class RetrievalScopeDTO(BaseModel):
    """How retrieval was scoped for this answer."""
    mode: str = Field(
        "full_corpus",
        description="full_corpus | explicit_document | structured_filters | structured_fallback",
    )
    filter_document_ids: list[str] = Field(default_factory=list)
    filter_document_titles: list[str] = Field(default_factory=list)
    filters_applied: dict = Field(default_factory=dict)
    graph_match_count: int = 0


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
    retrieval_scope: RetrievalScopeDTO = Field(
        default_factory=RetrievalScopeDTO,
        description="Whether chunk retrieval was scoped by structured filters",
    )

    class Config:
        frozen = False
