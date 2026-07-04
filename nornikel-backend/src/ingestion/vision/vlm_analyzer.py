import base64
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from domain.dto.image import ImageDTO
from domain.enums import ImageType
from ingestion.parsers.pdf_table_vlm import normalize_vlm_table_markdown
from settings import Settings

logger = logging.getLogger(__name__)

TABLE_VLM_SYSTEM = (
    "You extract data tables from scientific PDF page images for a search index. "
    "Return ONLY a markdown pipe table (| col | col |) with a header row and separator row. "
    "Preserve every numeric value, unit, and column header exactly as shown. "
    "Do not summarize or omit rows. No prose, no code fences."
)

TABLE_VLM_USER = """Extract ALL data tables visible in this image.

Captions on the page: {title}

For each table, preserve every column header, unit, and numeric value exactly as printed.
If multiple tables are present, combine them in one markdown response separated by blank lines.
Output markdown pipe tables only (| col | col |), no prose."""


class VLMAnalyzer:
    """Vision-language extraction for figures and image-based tables."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._vlm_client: ChatOpenAI | None = None

    def _get_vlm_client(self) -> ChatOpenAI:
        if self._vlm_client is None:
            self._vlm_client = ChatOpenAI(
                model=self.settings.vlm_model,
                api_key=self.settings.vlm_api_key,
                base_url=self.settings.vlm_base_url,
                temperature=0.0,
                max_retries=2,
                request_timeout=180.0,
            )
            logger.info(
                "Initialized VLM for table OCR: %s @ %s",
                self.settings.vlm_model,
                self.settings.vlm_base_url,
            )
        return self._vlm_client

    async def extract_table_markdown(self, image_bytes: bytes, title: str) -> str:
        """OCR a table image into markdown suitable for RAG chunks."""
        if not image_bytes:
            return ""

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = TABLE_VLM_USER.format(title=title.strip())

        messages = [
            SystemMessage(content=TABLE_VLM_SYSTEM),
            HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ]
            ),
        ]

        try:
            client = self._get_vlm_client()
            response = await client.ainvoke(messages)
            raw = response.content if isinstance(response.content, str) else str(response.content)
            markdown = normalize_vlm_table_markdown(raw, title)
            if markdown and markdown.count("|") >= 6:
                logger.info(
                    "VLM table OCR OK (%s chars) for %r",
                    len(markdown),
                    title[:60],
                )
                return markdown
            logger.warning(
                "VLM table OCR returned no pipe-table for %r: %s",
                title[:60],
                (raw or "")[:120],
            )
            return ""
        except Exception as exc:
            logger.error("VLM table OCR failed for %r: %s", title[:60], exc)
            return ""

    async def analyze_image(self, image: ImageDTO, image_bytes: bytes) -> ImageDTO:
        """Analyze a figure and return an updated ImageDTO with description."""
        logger.info("Analyzing image: %s, type: %s", image.file_path, image.image_type)

        if image.image_type == ImageType.TABLE:
            markdown = await self.extract_table_markdown(
                image_bytes,
                image.caption or "Table",
            )
            if markdown:
                return image.model_copy(update={"ai_description": markdown})

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = self._get_analysis_prompt(image.image_type, image.caption)

        try:
            messages = [
                HumanMessage(
                    content=[
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ]
                )
            ]
            client = self._get_vlm_client()
            response = await client.ainvoke(messages)
            description = response.content if isinstance(response.content, str) else str(response.content)
            logger.info("Generated description: %s...", str(description)[:100])
            return image.model_copy(update={"ai_description": description})
        except Exception as exc:
            logger.error("VLM analysis failed: %s", exc)
            return image.model_copy(update={"ai_description": f"Analysis error: {exc}"})

    def _get_analysis_prompt(self, image_type: ImageType, caption: str | None) -> str:
        caption_text = f"\nCaption: {caption}" if caption else ""

        prompts = {
            ImageType.MICROSTRUCTURE: f"""
Analyze this materials micrograph:
1. Microstructure type (grains, dendrites, etc.)
2. Approximate feature size
3. Defects or second phases
4. Homogeneity

Structured answer in English.{caption_text}
""",
            ImageType.PLOT: f"""
Analyze this chart:
1. Axes labels and units
2. Trend shape
3. Key maxima/minima with values if readable
4. Quantitative readings

English, structured.{caption_text}
""",
            ImageType.SCHEME: f"""
Analyze this schematic:
1. Process or equipment shown
2. Main components and flows
3. Key parameters if labeled

Structured English.{caption_text}
""",
            ImageType.TABLE: f"""
Extract this table as a markdown pipe table with all rows and columns.
Preserve numbers and units exactly. No prose.{caption_text}
""",
            ImageType.OTHER: f"""
Describe this scientific figure: subject, labels, measurable values.
English, structured.{caption_text}
""",
        }
        return prompts.get(image_type, prompts[ImageType.OTHER])
