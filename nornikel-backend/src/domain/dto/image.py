from uuid import UUID
from pydantic import BaseModel, Field

from domain.enums import ImageType


class ImageDTO(BaseModel):
    """Изображение из документа."""
    id: UUID
    document_id: UUID
    image_type: ImageType
    file_path: str = Field(..., description="Путь к файлу в хранилище")
    caption: str | None = Field(None, description="Подпись из документа")
    ai_description: str = Field(..., description="Описание от VLM")
    visual_embedding: list[float] | None = Field(None, description="CLIP-вектор")
    linked_text_chunk_id: UUID | None = Field(None, description="Связанный чанк текста")
    page_number: int | None = None
    
    class Config:
        frozen = False