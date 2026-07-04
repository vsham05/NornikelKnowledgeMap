import logging
import re
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import fitz  

from domain.dto.document import DocumentDTO, DocumentChunkDTO
from domain.dto.image import ImageDTO
from domain.enums import DocumentType, ImageType

from ingestion.parsers.title_slide_extract import (
    extract_authors_from_page_header,
    extract_authors_from_text,
    extract_organizations_from_text,
    looks_like_author_name,
    merge_unique_names,
    normalize_person_name,
    split_person_name_line,
)
from ingestion.parsers.image_extract import (
    MAX_IMAGES_PER_DOCUMENT,
    MAX_IMAGES_PER_PAGE,
    MIN_IMAGE_BYTES,
    image_content_hash,
    image_page_indices,
)
from ingestion.parsers.pdf_table_extract import (
    extract_tables_from_page,
    merge_page_text_and_tables,
)

logger = logging.getLogger(__name__)


def peek_pdf_page_count(file_path: Path) -> int:
    """Fast page count without full text extraction — used for hybrid LLM routing."""
    doc = fitz.open(file_path)
    try:
        return doc.page_count
    finally:
        doc.close()


class PDFParser:

    def __init__(self) -> None:
        # (ImageDTO, bytes, file_extension) populated by parse()
        self._last_image_payloads: list[tuple[ImageDTO, bytes, str]] = []

    @property
    def last_image_payloads(self) -> list[tuple[ImageDTO, bytes, str]]:
        return self._last_image_payloads
    def parse(
        self,
        file_path: Path,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> DocumentDTO:
        """Парсит PDF файл."""
        logger.info(f"Parsing PDF: {file_path}")

        self._last_image_payloads = []

        doc = fitz.open(file_path)
        total_pages = doc.page_count
        
        # Метаданные
        metadata = doc.metadata
        title = metadata.get("title", file_path.stem)
        authors = self._extract_authors(metadata, doc)
        organizations = self._extract_organizations(metadata, doc)
        year = self._extract_year(metadata)
        
        # Извлекаем текст постранично
        chunks = []
        for page_num, page in enumerate(doc):
            if on_page_progress and (page_num == 0 or (page_num + 1) % 3 == 0):
                on_page_progress(page_num + 1, total_pages)
            text = self._extract_page_text(page)
            
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
        
        # Figures: sampled pages, deduped embedded images (stored for MinIO during ingest)
        images: list[ImageDTO] = []
        seen_xrefs: set[int] = set()
        seen_hashes: set[str] = set()
        scan_pages = set(image_page_indices(doc.page_count))
        for page_num in sorted(scan_pages):
            if len(images) >= MAX_IMAGES_PER_DOCUMENT:
                break
            page = doc[page_num]
            page_caption = self._primary_figure_caption(page)
            page_candidates: list[tuple[int, bytes, str, int]] = []

            for img_info in page.get_images(full=True):
                xref = img_info[0]
                if xref in seen_xrefs:
                    continue
                try:
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    if len(image_bytes) < MIN_IMAGE_BYTES:
                        continue
                    digest = image_content_hash(image_bytes)
                    if digest in seen_hashes:
                        continue
                    image_ext = base_image.get("ext") or "png"
                    page_candidates.append(
                        (xref, image_bytes, image_ext, len(image_bytes))
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to extract image xref %s on page %s: %s",
                        xref,
                        page_num + 1,
                        e,
                    )

            page_candidates.sort(key=lambda item: item[3], reverse=True)
            for idx, (xref, image_bytes, image_ext, _) in enumerate(
                page_candidates[:MAX_IMAGES_PER_PAGE]
            ):
                if len(images) >= MAX_IMAGES_PER_DOCUMENT:
                    break
                seen_xrefs.add(xref)
                seen_hashes.add(image_content_hash(image_bytes))
                caption = page_caption if idx == 0 else None
                image = ImageDTO(
                    id=uuid4(),
                    document_id=uuid4(),
                    image_type=self._guess_image_type(caption),
                    file_path="",
                    caption=caption,
                    ai_description="",
                    page_number=page_num + 1,
                )
                images.append(image)
                self._last_image_payloads.append((image, image_bytes, image_ext))

        if len(scan_pages) < doc.page_count and images:
            logger.info(
                "Sampled figures from %s/%s pages (%s images, cap %s)",
                len(scan_pages),
                doc.page_count,
                len(images),
                MAX_IMAGES_PER_DOCUMENT,
            )
        
        if on_page_progress:
            on_page_progress(total_pages, total_pages)

        doc.close()
        
        # Создаем DocumentDTO
        document = DocumentDTO(
            id=uuid4(),
            title=title,
            document_type=DocumentType.ARTICLE,
            authors=authors,
            organizations=organizations,
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
        
        logger.info(
            "Parsed: %s chunks, %s images, %s author(s), %s org(s)",
            len(chunks),
            len(images),
            len(authors),
            len(organizations),
        )
        return document

    def _intro_text(self, doc: fitz.Document, max_pages: int = 4, max_chars: int = 12_000) -> str:
        parts: list[str] = []
        total = 0
        for page_num in range(min(doc.page_count, max_pages)):
            piece = (doc[page_num].get_text("text") or "").strip()
            if not piece:
                continue
            parts.append(piece)
            total += len(piece)
            if total >= max_chars:
                break
        return "\n\n".join(parts)[:max_chars]

    def _extract_authors(self, metadata: dict, doc: fitz.Document) -> list[str]:
        """Collect author names from PDF metadata and opening slides."""
        authors: list[str] = []

        author_raw = metadata.get("author") or metadata.get("authors") or ""
        if isinstance(author_raw, str) and author_raw.strip():
            for part in split_person_name_line(author_raw):
                if looks_like_author_name(part):
                    authors = merge_unique_names(authors, [normalize_person_name(part)])
            authors = merge_unique_names(
                authors, extract_authors_from_text(author_raw, 500)
            )

        intro = self._intro_text(doc)
        if intro:
            authors = merge_unique_names(authors, extract_authors_from_text(intro, 12_000))

        authors = merge_unique_names(authors, self._extract_proceedings_authors(doc))

        return authors[:80]

    def _extract_proceedings_authors(self, doc: fitz.Document) -> list[str]:
        """Scan page headers for paper authors (conference proceedings)."""
        authors: list[str] = []
        scan_limit = min(doc.page_count, 48)
        for page_num in range(scan_limit):
            text = (doc[page_num].get_text("text") or "").strip()
            if not text:
                continue
            authors = merge_unique_names(
                authors, extract_authors_from_page_header(text)
            )
            if len(authors) >= 80:
                break
        return authors

    def _extract_organizations(self, metadata: dict, doc: fitz.Document) -> list[str]:
        """Collect institute / company names from PDF metadata and opening slides."""
        orgs: list[str] = []
        meta_bits = " ".join(
            str(metadata.get(k) or "")
            for k in ("subject", "keywords", "producer", "creator", "title")
        )
        if meta_bits.strip():
            orgs = merge_unique_names([], extract_organizations_from_text(meta_bits, 2000))

        intro = self._intro_text(doc)
        if intro:
            orgs = merge_unique_names(orgs, extract_organizations_from_text(intro, 12_000))

        return orgs[:5]

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
    
    def _extract_page_text(self, page) -> str:
        """Plain text with quality-gated structured tables and fallbacks."""
        tables = extract_tables_from_page(page)
        if tables:
            structured = merge_page_text_and_tables(page, tables)
            if "[TABLE]" in structured and len(structured.strip()) >= 20:
                return structured

        text = (page.get_text("text") or "").strip()
        if len(text) >= 40:
            return text

        block_parts: list[str] = []
        try:
            for block in page.get_text("blocks") or []:
                if not isinstance(block, (list, tuple)) or len(block) < 5:
                    continue
                if len(block) >= 7 and block[6] not in (0, None):
                    continue
                piece = (block[4] or "").strip()
                if piece:
                    block_parts.append(piece)
        except Exception:
            block_parts = []

        if block_parts:
            joined = "\n".join(block_parts).strip()
            if len(joined) > len(text):
                text = joined

        if len(text) >= 40:
            return text

        dict_parts: list[str] = []
        try:
            page_dict = page.get_text("dict") or {}
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    line_text = "".join(
                        span.get("text", "") for span in line.get("spans", [])
                    ).strip()
                    if line_text:
                        dict_parts.append(line_text)
        except Exception:
            dict_parts = []

        if dict_parts:
            joined = "\n".join(dict_parts).strip()
            if len(joined) > len(text):
                text = joined

        return text
    
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
    
    def _primary_figure_caption(self, page) -> str | None:
        """Best-effort figure caption for the page (assigned to the main image only)."""
        for line in (page.get_text("text") or "").split("\n"):
            cleaned = line.strip()
            if not cleaned:
                continue
            lower = cleaned.lower()
            if any(keyword in lower for keyword in ("рис.", "figure", "fig.", "фиг.")):
                return cleaned
        return None

    def _guess_image_type(self, caption: str | None) -> ImageType:
        """Guess image type from caption — avoid treating 'Figure 3' references as plots."""
        if not caption:
            return ImageType.OTHER

        caption_lower = caption.lower()

        if any(word in caption_lower for word in ["микроструктур", "microstructure", "sem", "tem", "оптик"]):
            return ImageType.MICROSTRUCTURE
        if any(word in caption_lower for word in ["график", "зависимост", "chart", "graph", "крив"]):
            return ImageType.PLOT
        if any(word in caption_lower for word in ["схем", "диаграмм", "scheme", "diagram", "flowsheet"]):
            return ImageType.SCHEME
        if any(word in caption_lower for word in ["табл", "table"]):
            return ImageType.TABLE

        return ImageType.OTHER