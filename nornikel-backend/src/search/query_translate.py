"""Cross-lingual RAG: translate RU questions to EN for retrieval and answers back to RU."""

from __future__ import annotations

import logging
import re

from search.query_processing import CYRILLIC_RE, detect_language

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[\d+\]")

TRANSLATE_QUESTION_SYSTEM = """You translate Russian technical questions into English for document search.
The knowledge base covers mining, metallurgy, geotechnics, and R&D reports (mixed RU/EN).

Rules:
- Output ONLY the English translation — no quotes, labels, or explanation.
- Preserve ALL numbers, units (mg/L, %, °C), chemical symbols, and proper names exactly.
- Keep the same information need (processes, materials, parameters, years, locations)."""

TRANSLATE_ANSWER_SYSTEM = """You translate an English R&D answer into Russian for the end user.

Rules:
- Output ONLY the Russian translation.
- Preserve citation markers like [1], [2], [3] exactly in place — do not renumber or remove them.
- Preserve numbers, units, chemical formulas, and standard Latin abbreviations (pH, HPAL, FEM).
- Use formal technical Russian (mining / metallurgy / engineering).
- Do not add facts that were not in the English answer."""


def should_use_translate_pipeline(question: str, *, enabled: bool = True) -> bool:
    """True when we should run RU→EN retrieval + EN answer → RU output."""
    if not enabled:
        return False
    if not (question or "").strip():
        return False
    return detect_language(question) in ("ru", "mixed")


async def translate_question_to_english(llm_client, question: str) -> str | None:
    """Translate a Russian user question to English for embedding / LLM retrieval."""
    cleaned = (question or "").strip()
    if not cleaned or not CYRILLIC_RE.search(cleaned):
        return None
    try:
        raw = await llm_client.chat(
            user_message=f"RUSSIAN QUESTION:\n{cleaned}",
            system_message=TRANSLATE_QUESTION_SYSTEM,
            temperature=0.0,
            max_tokens=512,
        )
        translated = (raw or "").strip().strip('"').strip("'")
        if translated and len(translated) >= 3:
            logger.info("RU→EN question translation: %r", translated[:100])
            return translated
    except Exception as exc:
        logger.warning("Question translation failed: %s", exc)
    return None


async def translate_answer_to_russian(
    llm_client,
    answer_en: str,
    original_question: str,
) -> str:
    """Translate grounded English answer to Russian; preserve [n] citations."""
    text = (answer_en or "").strip()
    if not text:
        return text
    if CYRILLIC_RE.search(text) and not re.search(r"[a-zA-Z]{4,}", text):
        return text
    try:
        raw = await llm_client.chat(
            user_message=(
                f"ORIGINAL RUSSIAN QUESTION:\n{original_question.strip()}\n\n"
                f"ENGLISH ANSWER TO TRANSLATE:\n{text}"
            ),
            system_message=TRANSLATE_ANSWER_SYSTEM,
            temperature=0.0,
            max_tokens=2048,
        )
        translated = (raw or "").strip()
        if translated:
            if _citation_count(text) and _citation_count(translated) < _citation_count(text):
                logger.warning("Answer translation dropped citations — using English answer")
                return text
            logger.info("EN→RU answer translation: %s chars", len(translated))
            return translated
    except Exception as exc:
        logger.warning("Answer translation failed (%s); returning English answer", exc)
    return text


def _citation_count(text: str) -> int:
    return len(_CITATION_RE.findall(text or ""))
