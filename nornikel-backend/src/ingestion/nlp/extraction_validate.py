"""Reject LLM template echoes and generic placeholder entity names."""

from __future__ import annotations

import re

# Strings copied from prompts / JSON schemas — not real document entities.
_LLM_TEMPLATE_STRINGS = frozenset({
    "short label",
    "process or theme",
    "one grounded sentence",
    "linked process name if any",
    "canonical material name",
    "substance name",
    "organization name",
    "person name",
    "site name",
    "equipment name",
    "process name",
    "team name",
    "company name",
    "institute name",
    "facility name",
    "researcher name",
    "название материала",
    "название организации",
    "краткое описание",
    "example",
    "sample",
    "n/a",
    "na",
    "none",
    "unknown",
    "tbd",
    "todo",
})

_PLACEHOLDER_EQUIPMENT = frozenset({
    "equipment",
    "device",
    "unit",
    "apparatus",
    "machine",
    "tool",
    "оборудование",
    "устройство",
    "установка",
})

_PLACEHOLDER_PROCESS = frozenset({
    "process",
    "operation",
    "technology",
    "procedure",
    "method",
    "процесс",
    "операция",
    "технология",
    "метод",
})

_PLACEHOLDER_TOPIC = frozenset({
    "topic",
    "theme",
    "subject",
    "area",
    "тема",
    "направление",
})

_PLACEHOLDER_EXPERT_FIELDS = frozenset({
    "field",
    "discipline",
    "specialty",
    "area",
    "область",
    "специальность",
})

# CJK / Japanese / Korean — common LLM hallucination (e.g. Qwen on RU/EN mining PDFs).
_FOREIGN_SCRIPT_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]"
)


def contains_foreign_script(text: str) -> bool:
    """True when text includes Chinese/Japanese/Korean characters."""
    return bool(_FOREIGN_SCRIPT_RE.search(text or ""))


def has_foreign_script_hallucination(*texts: str | None) -> bool:
    """True when any string still contains CJK after normalization (informational)."""
    return any(text and contains_foreign_script(text) for text in texts)


# Title-case pairs like "Copper Matte" match person regex but are materials/processes.
_DOMAIN_NON_PERSON_WORDS = frozenset({
    "nickel", "copper", "iron", "zinc", "cobalt", "gold", "silver", "platinum",
    "magnesium", "manganese", "aluminum", "aluminium", "lead", "tin", "chromium",
    "matte", "slag", "gypsum", "sulfate", "sulphate", "chloride", "hydroxide",
    "catholyte", "anolyte", "electrolyte", "concentrate", "tailings", "ore",
    "leaching", "flotation", "electrowinning", "refining", "smelting", "roasting",
    "crusher", "reactor", "furnace", "circuit", "heap", "treatment", "removal",
    "water", "mine", "plant", "mill", "cell", "tank", "pump", "filter",
    "institute", "university", "laboratory", "department", "division", "company",
    "norilsk", "nornickel", "monchegorsk", "zapolyarny",
    "mining", "metallurgy", "metallurgical", "hydrometallurgy", "pyrometallurgy",
    # Section headings / TOC labels misread as "First Last" person names
    "facility", "facilities", "auxiliary", "site", "condition", "conditions",
    "project", "information", "management", "equipment", "procurement",
    "overview", "summary", "introduction", "conclusion", "abstract", "contents",
    "appendix", "section", "chapter", "maintenance", "construction", "design",
    "engineering", "performance", "evaluation", "assessment", "background",
    "objective", "scope", "schedule", "safety", "environmental", "inventory",
    "supply", "control", "monitoring", "system", "systems", "operation",
    "operations", "processing", "precipitation", "extraction", "recovery",
    "pressure", "high", "low", "acid", "alkaline", "neutral", "waste",
    "disposal", "storage", "handling", "transport", "logistics", "procurement",
    "commissioning", "startup", "shutdown", "reagent", "reagents", "catalyst",
    "никель", "медь", "железо", "цинк", "шлак", "гипс", "руда", "концентрат",
    "институт", "университет", "лаборатория", "завод", "комбинат", "рудник",
    "объект", "площадка", "проект", "оборудование", "процесс", "установка",
})


_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)


def pick_monolingual_label(name: str, target_lang: str) -> str:
    """Resolve mixed labels like 'католит - Catholyte' to one language."""
    cleaned = normalize_entity_name(name)
    if not cleaned:
        return cleaned
    for sep in (" - ", " – ", " — ", ": ", " / "):
        if sep not in cleaned:
            continue
        left, right = [part.strip() for part in cleaned.split(sep, 1)]
        if not left or not right:
            continue
        left_cyr = bool(_CYRILLIC_RE.search(left))
        right_cyr = bool(_CYRILLIC_RE.search(right))
        if left_cyr == right_cyr:
            continue
        if target_lang == "ru":
            return left if left_cyr else right
        return right if not right_cyr else left
    return cleaned


def normalize_entity_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip(" .;,"))


def is_llm_template_string(name: str) -> bool:
    n = normalize_entity_name(name).lower()
    if not n or len(n) < 2:
        return True
    if n in _LLM_TEMPLATE_STRINGS:
        return True
    if n.startswith("<") and n.endswith(">"):
        return True
    if "..." in n or n.endswith("…"):
        return True
    return False


def is_placeholder_equipment(name: str) -> bool:
    return normalize_entity_name(name).lower() in _PLACEHOLDER_EQUIPMENT


def is_placeholder_process(name: str) -> bool:
    return normalize_entity_name(name).lower() in _PLACEHOLDER_PROCESS


def is_placeholder_topic(name: str) -> bool:
    n = normalize_entity_name(name).lower()
    return not n or n in _PLACEHOLDER_TOPIC or is_llm_template_string(n)


def is_placeholder_expert_field(field: str | None) -> bool:
    if not field:
        return False
    return normalize_entity_name(field).lower() in _PLACEHOLDER_EXPERT_FIELDS


def contains_domain_entity_term(name: str) -> bool:
    """True when the token looks like material/process/org vocabulary, not a person."""
    words = re.findall(r"[\w\u0400-\u04FF]+", normalize_entity_name(name).lower())
    return any(word in _DOMAIN_NON_PERSON_WORDS for word in words)


def looks_like_section_heading(name: str) -> bool:
    """TOC / slide section titles (e.g. 'Auxiliary Facility') — not people."""
    cleaned = normalize_entity_name(name)
    if not cleaned:
        return True
    lower = cleaned.lower()
    words = re.findall(r"[\w\u0400-\u04FF]+", lower)
    if not words:
        return True
    # Author lists: "Chris Fleming and Joe Ferron", "Smith, J."
    if re.search(r"\b(?:and|&|и)\b", lower) or "," in cleaned:
        return False
    if any(word in _DOMAIN_NON_PERSON_WORDS for word in words):
        return True
    if cleaned.isupper() and len(words) >= 2:
        return True
    if len(words) >= 4 and not any(len(w) <= 2 for w in words):
        return True
    heading_suffixes = (
        "facility", "facilities", "equipment", "information", "management",
        "condition", "conditions", "overview", "summary", "appendix",
        "procurement", "commissioning", "operations", "processing",
    )
    if words[-1] in heading_suffixes:
        return True
    return False


def is_blocklisted_entity_name(name: str, blocklist: set[str], *, exact: bool = False) -> bool:
    key = normalize_entity_name(name).lower()
    if not key:
        return True
    if key in blocklist:
        return True
    if exact:
        return False
    return any(
        key == item or key in item or item in key
        for item in blocklist
        if len(item) >= 4
    )
