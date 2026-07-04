"""Document language detection and LLM prompt instructions (no LLM client imports)."""

from __future__ import annotations

import re

_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)


def detect_document_language(text: str) -> str:
    """Pick Russian or English from document text."""
    sample = (text or "")[:12_000]
    cyrillic = len(_CYRILLIC_RE.findall(sample))
    latin = len(_LATIN_RE.findall(sample))
    if cyrillic > max(latin * 0.25, 40):
        return "ru"
    return "en"


def resolve_extraction_language(document_text: str, configured: str = "auto") -> str:
    """Use configured language (ru/en) or auto-detect from text."""
    lang = (configured or "auto").strip().lower()
    if lang in ("ru", "en"):
        return lang
    return detect_document_language(document_text)


def extraction_language_instruction(target_lang: str) -> str:
    """Prompt line: display strings follow document language."""
    if target_lang == "ru":
        return (
            "Все строки для отображения (name, aliases, descriptions, выводы) — "
            "на русском языке, как в исходном тексте. Не смешивай русский и английский в одной строке."
        )
    return (
        "Write ALL display strings (names, aliases, descriptions, conclusions) in English, "
        "matching the source text. Do not mix Russian and English in one label."
    )
