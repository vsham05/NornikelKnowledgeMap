"""Normalize LLM extraction strings to the configured document language (RU/EN)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ingestion.nlp.extraction_language import (
    detect_document_language,
    extraction_language_instruction,
    resolve_extraction_language,
)
from ingestion.nlp.extraction_validate import contains_foreign_script
from infra.json_utils import extract_json_object

logger = logging.getLogger(__name__)

# Re-export for callers that import from this module.
__all__ = [
    "detect_document_language",
    "resolve_extraction_language",
    "extraction_language_instruction",
    "normalize_extraction_payload",
]

_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CHEMICAL_RE = re.compile(r"^(?:[A-Z][a-z]?\d*){1,6}$")

_SKIP_ENUM_VALUES = frozenset({
    "solid", "liquid", "gas", "powder", "slurry",
    "completed", "ongoing", "planned",
    "heat_treatment", "mechanical", "chemical", "thermomechanical", "other",
    "domestic", "international", "global",
    "plant", "mine", "smelter", "refinery", "laboratory", "site",
    "ore", "concentrate", "intermediate", "metal", "alloy", "compound", "waste", "reagent",
})

# Dict keys that hold canonical identifiers — never translate values at this key level only for keys themselves
_IDENTIFIER_KEYS = frozenset({
    "material_class", "state", "regime_type", "facility_type", "status", "category",
})


def _should_skip_translation(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or len(cleaned) < 3:
        return True
    if _SNAKE_CASE_RE.match(cleaned):
        return True
    if cleaned.lower() in _SKIP_ENUM_VALUES:
        return True
    if _CHEMICAL_RE.match(cleaned):
        return True
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return True
    return False


def _is_primarily_latin(text: str) -> bool:
    cyrillic = len(_CYRILLIC_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    return latin > cyrillic and latin >= 3


def _needs_translation(text: str, target_lang: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or _should_skip_translation(cleaned):
        return False
    if contains_foreign_script(cleaned):
        return True
    if target_lang == "ru" and _is_primarily_latin(cleaned):
        return True
    if target_lang == "en" and len(_CYRILLIC_RE.findall(cleaned)) > len(_LATIN_RE.findall(cleaned)):
        return True
    return False


def _collect_strings_to_translate(
    value: Any,
    target_lang: str,
    out: set[str],
    *,
    parent_key: str | None = None,
) -> None:
    if isinstance(value, str):
        if parent_key not in _IDENTIFIER_KEYS and _needs_translation(value, target_lang):
            out.add(value.strip())
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("source_text",):
                continue
            if key in ("properties", "measured_properties", "parameters") and isinstance(item, dict):
                for sub_key, sub_val in item.items():
                    if isinstance(sub_val, dict):
                        _collect_strings_to_translate(sub_val, target_lang, out, parent_key=None)
                    else:
                        _collect_strings_to_translate(sub_val, target_lang, out, parent_key=sub_key)
                continue
            _collect_strings_to_translate(item, target_lang, out, parent_key=key)
        return
    if isinstance(value, list):
        for item in value:
            _collect_strings_to_translate(item, target_lang, out, parent_key=parent_key)


def _apply_translations(value: Any, translations: dict[str, str]) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return translations.get(stripped, value)
    if isinstance(value, dict):
        return {key: _apply_translations(item, translations) for key, item in value.items()}
    if isinstance(value, list):
        return [_apply_translations(item, translations) for item in value]
    return value


async def _translate_strings_batch(
    strings: list[str],
    target_lang: str,
    llm_client: Any,
) -> dict[str, str]:
    if not strings:
        return {}

    lang_label = "Russian" if target_lang == "ru" else "English"
    payload = {"items": [{"id": i, "text": text} for i, text in enumerate(strings)]}
    prompt = f"""Translate each "text" field into {lang_label} for a scientific/engineering R&D knowledge graph.
Preserve technical meaning, numbers, and units. Use domain-appropriate terminology from the source field.
Keep chemical formulas (Fe2O3, H2SO4) and element symbols unchanged.

Return ONLY valid JSON in this exact shape:
{{"items": [{{"id": 0, "text": "..."}}, ...]}}

Input JSON:
{json.dumps(payload, ensure_ascii=False)}"""

    try:
        content = await llm_client.chat(
            user_message=prompt,
            system_message="You translate scientific extraction fields. Reply with JSON only.",
            temperature=0.0,
        )
        parsed = extract_json_object(content)
        items = parsed.get("items") if isinstance(parsed, dict) else None
        if not isinstance(items, list):
            logger.warning("Translation batch returned unexpected JSON shape")
            return {}

        out: dict[str, str] = {}
        for row in items:
            if not isinstance(row, dict):
                continue
            idx = row.get("id")
            translated = str(row.get("text") or "").strip()
            if isinstance(idx, int) and 0 <= idx < len(strings) and translated:
                out[strings[idx]] = translated
        return out
    except Exception as exc:
        logger.warning("LLM translation batch failed: %s", exc)
        return {}


async def normalize_extraction_payload(
    payload: Any,
    document_text: str,
    llm_client: Any,
    *,
    target_lang: str | None = None,
    fast_mode: bool = False,
) -> Any:
    """Translate foreign-script and cross-language strings to RU/EN — never drop records."""
    if payload is None:
        return payload

    lang = target_lang or detect_document_language(document_text)
    payload_root = payload

    if fast_mode:
        return payload_root

    to_translate: set[str] = set()
    _collect_strings_to_translate(payload_root, lang, to_translate)
    if not to_translate:
        return payload_root

    ordered = sorted(to_translate, key=len)
    translations: dict[str, str] = {}

    batch_size = 24
    for start in range(0, len(ordered), batch_size):
        batch = ordered[start : start + batch_size]
        translations.update(
            await _translate_strings_batch(batch, lang, llm_client)
        )

    if not translations:
        logger.warning(
            "Could not translate %s field(s) to %s; keeping originals",
            len(to_translate),
            lang,
        )
        return payload_root

    logger.info(
        "Translated %s/%s extraction strings to %s",
        len(translations),
        len(to_translate),
        lang,
    )
    return _apply_translations(payload_root, translations)
