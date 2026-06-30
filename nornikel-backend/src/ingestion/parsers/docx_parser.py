import logging
from pathlib import Path
from uuid import uuid4

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT

from domain.dto.document import DocumentDTO, DocumentChunkDTO
from domain.dto.image import ImageDTO
from domain.enums import DocumentType, ImageType

logger = logging.getLogger(__name__)


class DOCXParser:
    """Парсер DOCX документов."""
    
    def parse(self, file_path: Path) -> DocumentDTO:
        """Парсит DOCX файл."""
        logger.info(f"Parsing DOCX: {file_path}")
        
        doc = Document(file_path)
        
        # Извлекаем текст с сохранением структуры
        chunks = []
        current_chunk_text = []
        current_section = None
        chunk_index = 0
        
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            
            # Определяем заголовки
            if para.style.name.startswith("Heading"):
                # Сохраняем предыдущий чанк
                if current_chunk_text:
                    chunk = DocumentChunkDTO(
                        id=uuid4(),
                        document_id=uuid4(),
                        text="\n".join(current_chunk_text),
                        chunk_index=chunk_index,
                        section_title=current_section
                    )
                    chunks.append(chunk)
                    chunk_index += 1
                    current_chunk_text = []
                
                current_section = text
            else:
                current_chunk_text.append(text)
                
                # Разбиваем на чанки по ~5 параграфов
                if len(current_chunk_text) >= 5:
                    chunk = DocumentChunkDTO(
                        id=uuid4(),
                        document_id=uuid4(),
                        text="\n".join(current_chunk_text),
                        chunk_index=chunk_index,
                        section_title=current_section
                    )
                    chunks.append(chunk)
                    chunk_index += 1
                    current_chunk_text = []
        
        # Последний чанк
        if current_chunk_text:
            chunk = DocumentChunkDTO(
                id=uuid4(),
                document_id=uuid4(),
                text="\n".join(current_chunk_text),
                chunk_index=chunk_index,
                section_title=current_section
            )
            chunks.append(chunk)
        
        # Извлекаем изображения
        images = []
        for rel_id, rel in doc.part.rels.items():
            if "image" in rel.reltype:
                image_part = rel.target_part
                image_bytes = image_part.blob
                image_ext = image_part.content_type.split("/")[-1]
                
                image_filename = f"{file_path.stem}_{rel_id}.{image_ext}"
                image_path = f"images/{image_filename}"
                
                # Пытаемся найти подпись
                caption = self._find_caption_for_image(doc, rel_id)
                
                image = ImageDTO(
                    id=uuid4(),
                    document_id=uuid4(),
                    image_type=self._guess_image_type(caption),
                    file_path=image_path,
                    caption=caption,
                    ai_description=""
                )
                images.append(image)
        
        # Создаем DocumentDTO
        document = DocumentDTO(
            id=uuid4(),
            title=file_path.stem,
            document_type=DocumentType.REPORT,
            file_path=str(file_path),
            chunks=chunks,
            images=images
        )
        
        # Обновляем document_id
        for chunk in chunks:
            chunk.document_id = document.id
        for image in images:
            image.document_id = document.id
        
        logger.info(f"Parsed: {len(chunks)} chunks, {len(images)} images")
        return document
    
    def _find_caption_for_image(self, doc: Document, rel_id: str) -> str | None:
        """Ищет подпись к изображению."""
        # Упрощенная реализация — ищем "Рис." в параграфах
        for para in doc.paragraphs:
            text = para.text.strip()
            if any(keyword in text.lower() for keyword in ["рис.", "figure", "fig."]):
                return text
        return None
    
    def _guess_image_type(self, caption: str | None) -> ImageType:
        """Угадывает тип изображения."""
        if not caption:
            return ImageType.OTHER
        
        caption_lower = caption.lower()
        
        if any(word in caption_lower for word in ["микроструктур", "microstructure", "sem", "tem"]):
            return ImageType.MICROSTRUCTURE
        elif any(word in caption_lower for word in ["график", "зависимост", "plot"]):
            return ImageType.PLOT
        elif any(word in caption_lower for word in ["схем", "диаграмм", "scheme"]):
            return ImageType.SCHEME
        
        return ImageType.OTHER