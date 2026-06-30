import logging
from pathlib import Path
from uuid import uuid4

import fitz  

from domain.dto.document import DocumentDTO, DocumentChunkDTO
from domain.dto.image import ImageDTO
from domain.enums import DocumentType, ImageType

logger = logging.getLogger(__name__)


class PDFParser:
    """Парсер PDF документов с извлечением текста и изображений."""
    
    def parse(self, file_path: Path) -> DocumentDTO:
        """Парсит PDF файл."""
        logger.info(f"Parsing PDF: {file_path}")
        
        doc = fitz.open(file_path)
        
        # Метаданные
        metadata = doc.metadata
        title = metadata.get("title", file_path.stem)
        authors = [metadata.get("author", "")] if metadata.get("author") else []
        year = self._extract_year(metadata)
        
        # Извлекаем текст постранично
        chunks = []
        for page_num, page in enumerate(doc):
            text = page.get_text("text")
            
            if text.strip():
                chunk = DocumentChunkDTO(
                    id=uuid4(),
                    document_id=uuid4(),  # Обновится позже
                    text=text,
                    chunk_index=page_num,
                    page_number=page_num + 1,
                    section_title=self._detect_section_title(text)
                )
                chunks.append(chunk)
        
        # Извлекаем изображения
        images = []
        for page_num, page in enumerate(doc):
            image_list = page.get_images(full=True)
            
            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]
                
                try:
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]
                    
                    # Имя файла
                    image_filename = f"{file_path.stem}_p{page_num}_i{img_index}.{image_ext}"
                    image_path = f"images/{image_filename}"
                    
                    # Пытаемся найти подпись (caption) рядом с изображением
                    caption = self._find_image_caption(page, img_index)
                    
                    image = ImageDTO(
                        id=uuid4(),
                        document_id=uuid4(),  # Обновится позже
                        image_type=self._guess_image_type(caption),
                        file_path=image_path,
                        caption=caption,
                        ai_description="",  # Заполнит VLM
                        page_number=page_num + 1
                    )
                    images.append(image)
                    
                except Exception as e:
                    logger.warning(f"Failed to extract image {img_index} on page {page_num}: {e}")
        
        doc.close()
        
        # Создаем DocumentDTO
        document = DocumentDTO(
            id=uuid4(),
            title=title,
            document_type=DocumentType.ARTICLE,
            authors=authors,
            year=year,
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
    
    def _extract_year(self, metadata: dict) -> int | None:
        """Извлекает год из метаданных."""
        creation_date = metadata.get("creationDate", "")
        if creation_date and len(creation_date) >= 4:
            try:
                # Формат D:YYYYMMDD...
                year_str = creation_date[2:6] if creation_date.startswith("D:") else creation_date[:4]
                return int(year_str)
            except:
                pass
        return None
    
    def _detect_section_title(self, text: str) -> str | None:
        """Пытается определить заголовок секции (EN/RU)."""
        lines = text.split("\n")
        for line in lines[:3]:
            line = line.strip()
            if not line or len(line) > 100:
                continue
            if line.isupper():
                return line
            if line.startswith(("1.", "2.", "3.", "I.", "II.")):
                return line
            lower = line.lower()
            if lower in (
                "введение", "заключение", "результаты", "обсуждение", "методы",
                "материалы", "литература", "аннотация", "abstract", "introduction",
                "conclusion", "references",
            ):
                return line
        return None
    
    def _find_image_caption(self, page, img_index: int) -> str | None:
        """Ищет подпись к изображению."""
        # Простая эвристика: ищем текст "Рис. X" или "Figure X" рядом
        text = page.get_text("text")
        lines = text.split("\n")
        
        for i, line in enumerate(lines):
            if any(keyword in line.lower() for keyword in ["рис.", "figure", "fig.", "фиг."]):
                # Проверяем, что это рядом с изображением (в пределах 5 строк)
                if abs(i - img_index) < 5:
                    return line.strip()
        return None
    
    def _guess_image_type(self, caption: str | None) -> ImageType:
        """Угадывает тип изображения по подписи."""
        if not caption:
            return ImageType.OTHER
        
        caption_lower = caption.lower()
        
        if any(word in caption_lower for word in ["микроструктур", "microstructure", "sem", "tem", "оптик"]):
            return ImageType.MICROSTRUCTURE
        elif any(word in caption_lower for word in ["график", "зависимост", "plot", "figure", "крив"]):
            return ImageType.PLOT
        elif any(word in caption_lower for word in ["схем", "диаграмм", "scheme", "diagram"]):
            return ImageType.SCHEME
        elif any(word in caption_lower for word in ["табл", "table"]):
            return ImageType.TABLE
        
        return ImageType.OTHER