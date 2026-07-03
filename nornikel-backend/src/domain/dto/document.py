from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from domain.enums import DocumentType


class DocumentChunkDTO(BaseModel):
    """Часть документа (чанк)."""
    id: UUID
    document_id: UUID
    text: str
    chunk_index: int = Field(..., description="Порядковый номер чанка")
    page_number: int | None = None
    section_title: str | None = None
    
    class Config:
        frozen = False
    


class DocumentDTO(BaseModel):
    """Документ (статья, отчет и т.д.)."""
    id: UUID
    title: str
    document_type: DocumentType
    authors: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(
        default_factory=list,
        description="Research institutes / companies from title page or metadata",
    )
    year: int | None = None
    file_path: str = Field(..., description="Путь к файлу в хранилище")
    content_hash: str | None = Field(None, description="SHA-256 of normalized extracted text")
    canonical_source: str | None = Field(None, description="Canonical URL or stable source id")
    file_hash: str | None = Field(None, description="SHA-256 of raw file bytes")
    chunks: list[DocumentChunkDTO] = Field(default_factory=list)
    images: list["ImageDTO"] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        frozen = False


# Forward reference для ImageDTO
from domain.dto.image import ImageDTO
DocumentDTO.model_rebuild()