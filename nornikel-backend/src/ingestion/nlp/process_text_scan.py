"""Heuristic process detection for R&D documents (geotech, FEM, lab, metallurgy)."""

from __future__ import annotations

import re
from uuid import uuid4

from domain.entity_glossary import canonical_entity_key, find_glossary_terms_in_text
from domain.entity_glossary import PROCESS_GLOSSARY_KEYS
from ingestion.nlp.extraction_validate import (
    is_llm_template_string,
    is_placeholder_process,
    looks_like_concept_not_material,
    normalize_entity_name,
)

# (regex, canonical_key, ru_label, en_label)
_PROCESS_PHRASE_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        re.compile(
            r"метод\s+конечн(?:ых|ого|ой)\s+элемент\w*|"
            r"мкэ|mkэ|finite\s+element(?:\s+method)?|\bfem\b",
            re.IGNORECASE | re.UNICODE,
        ),
        "finite_element_method",
        "метод конечных элементов",
        "finite element method",
    ),
    (
        re.compile(
            r"связ(?:и|ь)\s+конечн(?:ой|ых)\s+ж[её]сткост",
            re.IGNORECASE | re.UNICODE,
        ),
        "finite_stiffness_links",
        "связи конечной жесткости",
        "finite stiffness links",
    ),
    (
        re.compile(
            r"численн(?:ое|ые|ая|ый)?\s+(?:моделир|расч|исслед|анализ)",
            re.IGNORECASE | re.UNICODE,
        ),
        "numerical_modeling",
        "численное моделирование",
        "numerical modeling",
    ),
    (
        re.compile(
            r"моделир(?:ование|овани)?\s+(?:тектон|разлом|геотех|скал|пород|брус|конструкц)",
            re.IGNORECASE | re.UNICODE,
        ),
        "geotechnical_modeling",
        "моделирование геотехнических систем",
        "geotechnical modeling",
    ),
    (
        re.compile(
            r"верификационн(?:ая|ое|ые|ый)?\s+модел",
            re.IGNORECASE | re.UNICODE,
        ),
        "verification_modeling",
        "верификационное моделирование",
        "verification modeling",
    ),
    (
        re.compile(
            r"\bcfd\b|вычислительн(?:ая|ые|ое|ый)?\s+гидродинамик",
            re.IGNORECASE | re.UNICODE,
        ),
        "cfd_simulation",
        "CFD-моделирование",
        "CFD simulation",
    ),
    (
        re.compile(
            r"полев(?:ые|ое|ая|ой)?\s+(?:испытан|исследован|наблюден|работ)",
            re.IGNORECASE | re.UNICODE,
        ),
        "field_testing",
        "полевые испытания",
        "field testing",
    ),
    (
        re.compile(
            r"лабораторн(?:ые|ое|ая|ой)?\s+(?:испытан|исследован|эксперимент)",
            re.IGNORECASE | re.UNICODE,
        ),
        "laboratory_testing",
        "лабораторные испытания",
        "laboratory testing",
    ),
    (
        re.compile(
            r"геотехнич(?:еск(?:ие|ое|ая|ий)|ески)\s+(?:расч|модел|исслед)",
            re.IGNORECASE | re.UNICODE,
        ),
        "geotechnical_analysis",
        "геотехнический анализ",
        "geotechnical analysis",
    ),
    (
        re.compile(
            r"калибров(?:ка|ки|очн)?\s+модел",
            re.IGNORECASE | re.UNICODE,
        ),
        "model_calibration",
        "калибровка модели",
        "model calibration",
    ),
    (
        re.compile(
            r"статическ(?:ий|ая|ое|ие)\s+(?:расч|анализ)",
            re.IGNORECASE | re.UNICODE,
        ),
        "static_analysis",
        "статический расчет",
        "static analysis",
    ),
    (
        re.compile(
            r"охлажден(?:ие|ия|ию|ии)?\s+(?:печ|реактор|котел|котёл|установк)",
            re.IGNORECASE | re.UNICODE,
        ),
        "furnace_cooling",
        "охлаждение печи",
        "furnace cooling",
    ),
    (
        re.compile(
            r"динамическ(?:ий|ая|ое|ие)\s+(?:расч|анализ|модел)",
            re.IGNORECASE | re.UNICODE,
        ),
        "dynamic_analysis",
        "динамический расчет",
        "dynamic analysis",
    ),
)


def looks_like_process_label(name: str) -> bool:
    cleaned = normalize_entity_name(name)
    if not cleaned or len(cleaned) < 4:
        return False
    if is_llm_template_string(cleaned) or is_placeholder_process(cleaned):
        return False
    lower = cleaned.lower()
    if lower in {"base", "other", "unknown", "none"}:
        return False
    if looks_like_concept_not_material(cleaned):
        return True
    process_hints = (
        "simulation", "modeling", "modelling", "analysis", "calibration",
        "testing", "experiment", "survey", "monitoring", "drilling",
        "sampling", "leaching", "flotation", "smelting", "refining",
        "finite", "element", "stiffness", "fem", "cfd",
        "моделир", "расчет", "расчёт", "анализ", "испытан", "исследован",
        "выщелач", "флотац", "плавк", "рафинир", "обогащ", "бурени",
        "отбор", "мониторинг", "калибров", "метод", "элемент", "мкэ", "жесткост",
    )
    return any(h in lower for h in process_hints)


def find_process_phrases_in_text(
    text: str,
    target_lang: str = "ru",
) -> list[tuple[str, str, str]]:
    """Return (canonical_key, display_name, source) hits from regex + glossary."""
    if not text.strip():
        return []

    hits: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def add(key: str, display: str, source: str, *, trusted: bool = False) -> None:
        norm_key = canonical_entity_key(key) or key.lower()
        if not norm_key or norm_key in seen:
            return
        if not trusted and not looks_like_process_label(display):
            return
        seen.add(norm_key)
        hits.append((norm_key, display, source))

    for pattern, key, ru, en in _PROCESS_PHRASE_PATTERNS:
        if pattern.search(text):
            display = en if target_lang == "en" else ru
            add(key, display, "phrase", trusted=True)

    for key, ru, en in find_glossary_terms_in_text(text, PROCESS_GLOSSARY_KEYS):
        display = en if target_lang == "en" else ru
        add(key, display or en or ru, "glossary", trusted=True)

    return hits


def append_process_record(
    processes: list[dict],
    *,
    name: str,
    document_id: str,
    canonical_key: str | None = None,
    source: str = "backfill",
) -> bool:
    display = normalize_entity_name(name)
    if is_llm_template_string(display) or is_placeholder_process(display):
        return False
    if not canonical_key and not looks_like_process_label(display):
        return False
    key = canonical_key or canonical_entity_key(display)
    if not key:
        return False
    seen = {
        str(p.get("canonical_key") or canonical_entity_key(str(p.get("name") or ""))).lower()
        for p in processes
    }
    if key.lower() in seen:
        return False
    processes.append({
        "id": str(uuid4()),
        "name": display,
        "canonical_key": key,
        "aliases": [],
        "materials": [],
        "document_id": document_id,
        "source": source,
    })
    return True
