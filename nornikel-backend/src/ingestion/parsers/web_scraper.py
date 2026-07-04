import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import httpx
from selectolax.parser import HTMLParser

from domain.dto.document import DocumentDTO, DocumentChunkDTO
from domain.dto.image import ImageDTO
from domain.enums import DocumentType, ImageType

logger = logging.getLogger(__name__)

_PAYWALL_HINT = (
    "This publisher requires a subscription or institutional login. "
    "Download the PDF (e.g. via your university library) and use Upload PDF/DOCX instead."
)

_AUTH_REDIRECT_MARKERS = (
    "idp.",
    "/authorize",
    "/login",
    "cas.",
    "shibboleth",
    "sso.",
    "signin",
    "sign-in",
)


class PaywalledContentError(Exception):
    """Page is behind a publisher paywall or login wall."""


def _is_auth_redirect(url: str) -> bool:
    lower = url.lower()
    return any(marker in lower for marker in _AUTH_REDIRECT_MARKERS)


def _paywall_message(original_url: str) -> str:
    host = urlparse(original_url).netloc.lower()
    if "nature.com" in host:
        return (
            f"Nature.com blocked automated access to {original_url} (subscription/login required). "
            + _PAYWALL_HINT
        )
    return f"Access to {original_url} requires login or a paid subscription. " + _PAYWALL_HINT


def _looks_like_login_page(html: str) -> bool:
    lower = html.lower()
    if "idp.nature.com" in lower or "springer nature" in lower and "sign in" in lower:
        return True
    if "sign in" in lower and ("password" in lower or "institutional access" in lower):
        return len(html) < 80_000
    return False


class WebScraper:
    """Парсер веб-страниц с извлечением текста и изображений."""
    
    def __init__(self, use_playwright: bool = False):
        """
        Args:
            use_playwright: Использовать Playwright для JS-рендеринга
                           (нужно для SPA, динамических сайтов)
        """
        self.use_playwright = use_playwright
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
    
    async def scrape(self, url: str) -> DocumentDTO:
        """Скрапит веб-страницу и возвращает DocumentDTO."""
        logger.info(f"Scraping URL: {url}")
        
        # 1. Загружаем HTML (with open-access mirror fallback for paywalled DOIs)
        try:
            html = await self._fetch_html(url)
        except PaywalledContentError:
            fallback = await self._open_access_fallback(url)
            if not fallback:
                raise
            logger.info(f"Paywalled URL; trying open-access mirror: {fallback}")
            html = await self._fetch_html(fallback)
        
        # 2. Парсим HTML
        parser = HTMLParser(html)
        
        # 3. Извлекаем метаданные
        title = self._extract_title(parser, url)
        authors = self._extract_authors(parser)
        year = self._extract_year(parser)
        
        # 4. Извлекаем основной текст с структурой
        chunks = self._extract_text_chunks(parser, url)
        if not chunks:
            raise RuntimeError(
                f"No readable text extracted from {url}. "
                "The page may be JavaScript-only, paywalled, or use an unsupported layout — "
                "try Upload PDF/DOCX or enable Playwright (use_playwright=true)."
            )
        
        # 5. Извлекаем изображения
        images = self._extract_images(parser, url)
        
        # 6. Создаем DocumentDTO
        document = DocumentDTO(
            id=uuid4(),
            title=title,
            document_type=DocumentType.ARTICLE,
            authors=authors,
            year=year,
            file_path=url,
            chunks=chunks,
            images=images
        )
        
        # Обновляем document_id
        for chunk in chunks:
            chunk.document_id = document.id
        for image in images:
            image.document_id = document.id
        
        logger.info(f"Scraped: {len(chunks)} chunks, {len(images)} images")
        return document
    
    async def _fetch_html(self, url: str) -> str:
        """Загружает HTML страницы."""
        if self.use_playwright:
            return await self._fetch_with_playwright(url)
        return await self._fetch_with_httpx(url)

    async def _fetch_with_httpx(self, url: str) -> str:
        """HTTP fetch with paywall / auth-redirect detection."""
        try:
            response = await self.client.get(url, follow_redirects=False)
        except httpx.RequestError as exc:
            raise RuntimeError(f"Could not reach {url}: {exc}") from exc

        if response.status_code in (300, 301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            if location and _is_auth_redirect(location):
                raise PaywalledContentError(_paywall_message(url))
            response = await self.client.get(url, follow_redirects=True)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"HTTP {exc.response.status_code} when fetching {url}"
            ) from exc

        final_url = str(response.url)
        if _is_auth_redirect(final_url):
            raise PaywalledContentError(_paywall_message(url))

        html = response.text
        if _looks_like_login_page(html):
            raise PaywalledContentError(_paywall_message(url))
        return html

    async def _open_access_fallback(self, url: str) -> str | None:
        """Try Europe PMC / PMC for open-access full text of a DOI-based article."""
        doi = self._doi_from_url(url)
        if not doi:
            return None
        api = (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query=DOI:{doi}&format=json&resultType=core&pageSize=1"
        )
        try:
            response = await self.client.get(api, follow_redirects=True)
            response.raise_for_status()
            results = response.json().get("resultList", {}).get("result", [])
            if not results:
                return None
            for entry in results[0].get("fullTextUrlList", {}).get("fullTextUrl", []):
                if entry.get("availability") in ("Open access", "Free"):
                    mirror = entry.get("url")
                    if mirror:
                        return mirror
        except Exception as exc:
            logger.warning(f"Europe PMC lookup failed for DOI {doi}: {exc}")
        return None

    @staticmethod
    def _doi_from_url(url: str) -> str | None:
        host = urlparse(url).netloc.lower()
        path = urlparse(url).path
        if "nature.com" in host:
            match = re.search(r"/articles/([^/?#]+)", path)
            if match:
                return f"10.1038/{match.group(1)}"
        match = re.search(r"10\.\d{4,9}/[^\s?#]+", url)
        return match.group(0) if match else None
    
    async def _fetch_with_playwright(self, url: str) -> str:
        """Загружает HTML с JS-рендерингом через Playwright."""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle")
                final_url = page.url
                if _is_auth_redirect(final_url):
                    await browser.close()
                    raise PaywalledContentError(_paywall_message(url))
                html = await page.content()
                await browser.close()
                if _looks_like_login_page(html):
                    raise PaywalledContentError(_paywall_message(url))
                return html
        except ImportError:
            logger.warning("Playwright not installed, falling back to httpx")
            return await self._fetch_with_httpx(url)
    
    def _extract_title(self, parser: HTMLParser, url: str) -> str:
        """Извлекает заголовок страницы."""
        # Пробуем <title>
        title_tag = parser.css_first("title")
        if title_tag:
            title = title_tag.text(strip=True)
            if title:
                return title
        
        # Пробуем <h1>
        h1_tag = parser.css_first("h1")
        if h1_tag:
            title = h1_tag.text(strip=True)
            if title:
                return title
        
        # Пробуем Open Graph
        og_title = parser.css_first('meta[property="og:title"]')
        if og_title:
            title = og_title.attributes.get("content", "")
            if title:
                return title
        
        # Fallback — URL
        return urlparse(url).path
    
    def _extract_authors(self, parser: HTMLParser) -> list[str]:
        """Извлекает авторов."""
        authors = []
        
        # Пробуем meta tags
        for meta in parser.css('meta[name="author"], meta[property="article:author"]'):
            author = meta.attributes.get("content", "")
            if author:
                authors.append(author)
        
        # Пробуем <address> или <span class="author">
        for elem in parser.css("address, .author, .byline"):
            text = elem.text(strip=True)
            if text and len(text) < 200:
                authors.append(text)
        
        return list(set(authors))  # Убираем дубликаты
    
    def _extract_year(self, parser: HTMLParser) -> int | None:
        """Извлекает год публикации."""
        # Пробуем meta tags
        for meta in parser.css('meta[property="article:published_time"], meta[name="date"]'):
            date_str = meta.attributes.get("content", "")
            if date_str:
                # Парсим дату (формат ISO 8601 или другой)
                match = re.search(r"(\d{4})", date_str)
                if match:
                    return int(match.group(1))
        
        # Пробуем <time> tag
        time_tag = parser.css_first("time[datetime]")
        if time_tag:
            datetime_str = time_tag.attributes.get("datetime", "")
            match = re.search(r"(\d{4})", datetime_str)
            if match:
                return int(match.group(1))
        
        return None
    
    def _extract_text_chunks(self, parser: HTMLParser, base_url: str) -> list[DocumentChunkDTO]:
        """Извлекает текст с сохранением структуры."""
        chunks = []
        chunk_index = 0
        current_section = None
        
        # Удаляем ненужные элементы
        for elem in parser.css("script, style, nav, footer, header, aside, .ads, .sidebar"):
            elem.decompose()
        
        # Ищем основной контент (prefer article body over full-page <main> wrappers)
        main_content = (
            parser.css_first("article") or
            parser.css_first("#abs, .abstract-content, [itemprop='articleBody']") or
            parser.css_first("main") or
            parser.css_first('[role="main"]') or
            parser.css_first(".content, .post, .entry") or
            parser.body
        )
        
        if not main_content:
            logger.warning("Could not find main content")
            return chunks

        # Academic pages: pull abstract early so sidebar noise does not bury it
        abstract_text = self._extract_abstract_text(parser)
        if abstract_text:
            chunks.append(
                DocumentChunkDTO(
                    id=uuid4(),
                    document_id=uuid4(),
                    text=abstract_text,
                    chunk_index=0,
                    section_title="Abstract",
                )
            )
            chunk_index = 1

        # Обходим элементы
        current_text = []

        for elem in main_content.css("h1, h2, h3, h4, h5, h6, p, li, table, blockquote"):
            tag = elem.tag

            # Заголовки — начинаем новый чанк
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                # Сохраняем предыдущий чанк
                if current_text:
                    chunk = DocumentChunkDTO(
                        id=uuid4(),
                        document_id=uuid4(),
                        text="\n".join(current_text),
                        chunk_index=chunk_index,
                        section_title=current_section
                    )
                    chunks.append(chunk)
                    chunk_index += 1
                    current_text = []

                current_section = elem.text(strip=True)

            # Параграфы, списки и цитаты (arXiv abstract, pull quotes)
            elif tag in ("p", "li", "blockquote"):
                text = elem.text(strip=True)
                if text:
                    if abstract_text and tag == "blockquote" and text == abstract_text:
                        continue
                    current_text.append(text)

            # Таблицы
            elif tag == "table":
                table_text = self._extract_table_text(elem)
                if table_text:
                    current_text.append(table_text)

            # Разбиваем на чанки по ~5 параграфов
            if len(current_text) >= 5:
                chunk = DocumentChunkDTO(
                    id=uuid4(),
                    document_id=uuid4(),
                    text="\n".join(current_text),
                    chunk_index=chunk_index,
                    section_title=current_section
                )
                chunks.append(chunk)
                chunk_index += 1
                current_text = []

        # Последний чанк
        if current_text:
            chunk = DocumentChunkDTO(
                id=uuid4(),
                document_id=uuid4(),
                text="\n".join(current_text),
                chunk_index=chunk_index,
                section_title=current_section
            )
            chunks.append(chunk)

        return chunks

    @staticmethod
    def _extract_abstract_text(parser: HTMLParser) -> str | None:
        """Best-effort abstract for scholarly pages (arXiv, publishers, meta tags)."""
        for selector in (
            "blockquote.abstract",
            "#abs blockquote",
            ".abstract",
            "[itemprop='description']",
            'meta[name="description"]',
            'meta[property="og:description"]',
        ):
            node = parser.css_first(selector)
            if not node:
                continue
            if node.tag == "meta":
                text = (node.attributes.get("content") or "").strip()
            else:
                text = node.text(strip=True)
            if len(text) >= 80:
                return text
        return None
    
    def _extract_table_text(self, table_elem) -> str:
        """Извлекает текст из HTML таблицы."""
        rows = []
        
        for row in table_elem.css("tr"):
            cells = []
            for cell in row.css("th, td"):
                text = cell.text(strip=True)
                cells.append(text)
            if cells:
                rows.append(" | ".join(cells))
        
        return "\n".join(rows) if rows else ""
    
    def _extract_images(self, parser: HTMLParser, base_url: str) -> list[ImageDTO]:
        """Извлекает изображения с контекстом."""
        images = []
        
        for img_elem in parser.css("img"):
            # Получаем src
            src = img_elem.attributes.get("src", "")
            if not src:
                continue
            
            # Делаем URL абсолютным
            full_url = urljoin(base_url, src)
            
            # Пропускаем маленькие иконки, логотипы
            width = img_elem.attributes.get("width", "")
            height = img_elem.attributes.get("height", "")
            if width and height:
                try:
                    if int(width) < 100 or int(height) < 100:
                        continue
                except ValueError:
                    pass
            
            # Получаем alt text
            alt = img_elem.attributes.get("alt", "")
            
            # Ищем подпись (figcaption или ближайший текст)
            caption = self._find_image_caption(img_elem)
            
            # Определяем тип изображения
            image_type = self._guess_image_type(alt, caption)
            
            # Создаем ImageDTO
            image = ImageDTO(
                id=uuid4(),
                document_id=uuid4(),
                image_type=image_type,
                file_path=full_url,  # URL изображения
                caption=caption or alt,
                ai_description="",  # Заполнит VLM
                page_number=None  # Для веба нет страниц
            )
            
            images.append(image)
        
        return images
    
    def _find_image_caption(self, img_elem) -> str | None:
        """Ищет подпись к изображению."""
        # Пробуем <figcaption>
        parent = img_elem.parent
        if parent and parent.tag == "figure":
            figcaption = parent.css_first("figcaption")
            if figcaption:
                return figcaption.text(strip=True)
        
        # Пробуем ближайший <p> или <div> с классом caption
        for sibling in img_elem.parent.css("p, div"):
            classes = sibling.attributes.get("class", "")
            if "caption" in classes.lower():
                return sibling.text(strip=True)
        
        return None
    
    def _guess_image_type(self, alt: str, caption: str | None) -> ImageType:
        """Угадывает тип изображения по alt и caption."""
        text = f"{alt} {caption or ''}".lower()
        
        if any(word in text for word in ["микроструктур", "microstructure", "sem", "tem", "оптик"]):
            return ImageType.MICROSTRUCTURE
        elif any(word in text for word in ["график", "зависимост", "plot", "figure", "крив"]):
            return ImageType.PLOT
        elif any(word in text for word in ["схем", "диаграмм", "scheme", "diagram"]):
            return ImageType.SCHEME
        elif any(word in text for word in ["табл", "table"]):
            return ImageType.TABLE
        
        return ImageType.OTHER
    
    async def close(self):
        """Закрывает HTTP клиент."""
        await self.client.aclose()