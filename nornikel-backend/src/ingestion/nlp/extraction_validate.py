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


# Modeling / methodology / property labels — not chemical or geological materials.
_CONCEPT_NOT_MATERIAL_RE = re.compile(
    r"(?:"
    r"model|simulation|simulat|methodolog|calibrat|integrat|efficien|stiffness|"
    r"modulus|equivalent|geometry|geometric|tectonic|fracture|fault|global|"
    r"computational|numerical|algorithm|workflow|framework|section|cross.?section|"
    r"модел|симуля|моделир|методик|калибр|интеграц|эффективн|жесткост|"
    r"модуль|эквивалент|геометри|тектонич|разлом|глобальн|вычислит|"
    r"численн|алгоритм|сечени|участк|брус|жёсткост|жестк"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_KEEP_AS_MATERIAL = frozenset({
    "rock", "soil", "clay", "sand", "gravel", "granite", "basalt", "limestone",
    "steel", "concrete", "water", "ice", "snow", "permafrost", "nickel", "copper",
    "iron", "ore", "гранит", "глина", "песок", "скала", "порода", "бетон", "сталь",
    "cement", "цемент",
})


def looks_like_concept_not_material(name: str) -> bool:
    """True when a label is a method, model, property, or workflow — not a substance."""
    cleaned = normalize_entity_name(name)
    if not cleaned or len(cleaned) < 2:
        return True
    lower = cleaned.lower()
    if lower in _KEEP_AS_MATERIAL:
        return False
    if _CONCEPT_NOT_MATERIAL_RE.search(cleaned):
        return True
    if re.search(
        r"(?:strength|density|pressure|stress|strain|stiffness|modulus|area)$",
        lower,
    ):
        return True
    if re.search(
        r"(?:прочност|плотност|напряжен|деформац|площад|жесткост|модуль)$",
        lower,
    ):
        return True
    return False


# --- Non-material routing: morphology + generic R&D vocabulary (not domain-specific) ---

_SUBSTANCE_NOUNS = frozenset({
    "ore", "concentrate", "tailings", "feed", "feedstock", "water", "gas",
    "reagent", "catalyst", "solvent", "powder", "sample", "specimen",
    "rock", "soil", "clay", "sand", "steel", "concrete",
    "руда", "концентрат", "хвосты", "реагент", "катализатор", "растворитель",
    "порошок", "образец", "проба", "вода", "газ", "скала", "порода", "глина",
    "песок", "сталь", "бетон",
}) | _KEEP_AS_MATERIAL

# Generic apparatus / instrument heads (lab + plant — not tied to one industry).
_APPARATUS_TERMS = frozenset({
    "reactor", "vessel", "tank", "pump", "filter", "compressor", "furnace", "boiler",
    "kiln", "column", "chamber", "module", "instrument", "apparatus", "device",
    "machine", "sensor", "detector", "probe", "rig", "burner", "motor", "turbine",
    "baffle", "partition", "roof", "vault", "shaft", "stack", "chimney", "stage",
    "реактор", "сосуд", "бак", "насос", "фильтр", "компрессор", "печь", "котел",
    "котёл", "колонна", "камера", "модуль", "прибор", "аппарат", "установка",
    "агрегат", "устройство", "машина", "датчик", "стенд", "горелка", "перегородка",
    "свод", "шахта", "конденсатор", "теплообменник",
})

_FACILITY_TERMS = frozenset({
    "plant", "site", "facility", "laboratory", "lab", "complex", "campus", "field",
    "завод", "лаборатория", "комплекс", "площадка", "объект", "цех",
})

_OPERATION_MORPHOLOGY_RE = re.compile(
    r"(?:"
    r"\b\w+(?:ing|tion|sion|ment|sis|ysis|ization|isation)\b|"
    r"\b[\w\u0400-\u04FF]+(?:ение|ания|ения|ание|ние|ция|овка|ировка|тие|ие)\b"
    r")",
    re.IGNORECASE | re.UNICODE,
)

# Standalone operation / activity nouns (not substances).
_PROCESS_ACTIVITY_NOUNS = frozenset({
    "mining", "extraction", "beneficiation", "enrichment", "closure", "processing",
    "smelting", "refining", "roasting", "leaching", "flotation", "grinding",
    "добыча", "обогащение", "обогащения", "закрытие", "переработка", "плавка",
    "флотация", "измельчение", "выщелачивание", "обжиг", "рафинирование",
})

_MATERIAL_HEAD_WORDS = frozenset({
    "отходы", "хвосты", "waste", "tailings", "residue", "residues", "slag", "шлак",
    "раствор", "solution", "cement", "цемент", "ore", "руда", "concentrate", "концентрат",
})

_YEAR_LABEL_RE = re.compile(
    r"^(?:"
    r"(?:19|20)\d{2}(?:\s*(?:year|yr|г\.?|год))?"
    r"|(?:19|20)\d{2}\s+год"
    r")$",
    re.IGNORECASE | re.UNICODE,
)

_SNAKE_CASE_PROPERTY_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")

_COMMON_PARAMETER_NAMES = frozenset({
    "temperature", "pressure", "density", "ph", "duration", "concentration",
    "viscosity", "conductivity", "hardness", "porosity", "moisture",
    "nickel_content", "copper_content", "iron_content", "recovery_rate",
    "yield_strength", "tensile_strength", "melting_point", "particle_size",
    "температура", "давление", "плотность", "концентрация", "прочность",
})

_CHEMICAL_FORMULA_RE = re.compile(
    r"^[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*|\([A-Z][a-z]?\d*\)\d*)+$"
)


def _looks_like_chemical_formula(name: str) -> bool:
    compact = re.sub(r"\s+", "", normalize_entity_name(name))
    if not compact or not re.search(r"\d", compact):
        return False
    return bool(_CHEMICAL_FORMULA_RE.match(compact))

_MINE_SITE_RE = re.compile(
    r"(?:"
    r"\bmine\b|\bdeposit\b|\bquarry\b|\bpit\b|\bfield\b|"
    r"\bрудник\b|\bкарьер\b|\bместорожд"
    r")",
    re.IGNORECASE | re.UNICODE,
)

_BUSINESS_CONNECTOR_RE = re.compile(r"[&+]")

_BUSINESS_SUFFIX_TERMS = frozenset({
    "associates", "associate", "group", "holdings", "partners", "consulting",
    "services", "corporation", "company", "limited", "resources", "mining",
    "metals", "platinum", "nickel", "international", "global", "american",
    "gmbh", "corp", "inc", "ltd", "plc",
})

_ORG_TICKER_RE = re.compile(r"^[A-Z]{2,5}$")

_OPERATION_LEAD_STEMS = (
    "cool", "heat", "dry", "test", "measur", "calibr", "analyz", "analys",
    "model", "simulat", "extract", "separ", "purif", "mix", "stir", "grind",
    "wash", "rinse", "monitor", "characteriz", "evaluat",
    "охлажд", "нагрев", "суш", "испыт", "измер", "калибр", "анализ",
    "моделир", "экстрак", "раздел", "очист", "смеш", "монитор",
)


def _tokenize_entity(name: str) -> list[str]:
    return re.findall(r"[\w\u0400-\u04FF]+", normalize_entity_name(name).lower())


def _term_match(word: str, vocabulary: frozenset[str], *, min_len: int = 3) -> bool:
    if len(word) < min_len:
        return False
    if word in vocabulary:
        return True
    for term in vocabulary:
        if len(term) < min_len:
            continue
        if word.startswith(term) or term.startswith(word):
            return True
        # Inflected forms (e.g. котле → котел, перегородки → перегородка).
        stem = min(len(word), len(term), max(4, min(len(term), len(word)) - 2))
        if stem >= 4 and word[:stem] == term[:stem]:
            return True
    return False


def _looks_like_operation(name: str) -> bool:
    cleaned = normalize_entity_name(name)
    if not cleaned:
        return False
    words = _tokenize_entity(cleaned)
    if words and words[0] in _MATERIAL_HEAD_WORDS:
        return False
    if _OPERATION_MORPHOLOGY_RE.search(cleaned):
        return True
    if not words:
        return False
    head = words[0]
    return any(head.startswith(stem) for stem in _OPERATION_LEAD_STEMS)


def _looks_like_apparatus(name: str) -> bool:
    words = _tokenize_entity(name)
    return any(_term_match(w, _APPARATUS_TERMS) for w in words)


def _looks_like_facility(name: str) -> bool:
    words = _tokenize_entity(name)
    if not words:
        return False
    if _MINE_SITE_RE.search(name):
        return True
    return any(_term_match(w, _FACILITY_TERMS) for w in words)


def looks_like_year_label(name: str) -> bool:
    cleaned = normalize_entity_name(name)
    if not cleaned:
        return False
    return bool(_YEAR_LABEL_RE.match(cleaned))


def looks_like_property_parameter(name: str) -> bool:
    """Schema / regime keys (nickel_content, temperature) — not graph entities."""
    cleaned = normalize_entity_name(name)
    if not cleaned or " " in cleaned:
        return False
    lower = cleaned.lower()
    if lower in _COMMON_PARAMETER_NAMES:
        return True
    if _SNAKE_CASE_PROPERTY_RE.match(lower):
        return True
    if lower.endswith("_content") or lower.endswith("_rate") or lower.endswith("_ratio"):
        return True
    return False


def _looks_like_process_activity(name: str) -> bool:
    words = _tokenize_entity(name)
    if not words:
        return False
    if words[0] in _MATERIAL_HEAD_WORDS:
        return False
    if len(words) == 1:
        return words[0] in _PROCESS_ACTIVITY_NOUNS
    return words[-1] in _PROCESS_ACTIVITY_NOUNS


def _looks_like_organization_brand(name: str) -> bool:
    cleaned = normalize_entity_name(name)
    if not cleaned or len(cleaned) < 2:
        return False
    if _looks_like_chemical_formula(cleaned):
        return False
    if cleaned.lower() in _SUBSTANCE_NOUNS:
        return False
    if _BUSINESS_CONNECTOR_RE.search(cleaned):
        return True
    words = _tokenize_entity(cleaned)
    if any(w in _BUSINESS_SUFFIX_TERMS for w in words):
        return True
    if _ORG_TICKER_RE.match(cleaned):
        return True
    # Lazy import — title_slide_extract already imports this module.
    from ingestion.parsers.title_slide_extract import looks_like_organization_name

    if looks_like_organization_name(cleaned):
        return True
    return False


def _looks_like_person_entity(name: str) -> bool:
    cleaned = normalize_entity_name(name)
    if not cleaned or looks_like_section_heading(cleaned):
        return False
    if _looks_like_chemical_formula(cleaned):
        return False
    words = _tokenize_entity(cleaned)
    if any(w in _BUSINESS_SUFFIX_TERMS for w in words):
        return False
    from ingestion.parsers.title_slide_extract import looks_like_author_name

    return looks_like_author_name(cleaned)


def classify_non_material_entity(name: str) -> str | None:
    """Return entity kind when label is not a substance, else None."""
    cleaned = normalize_entity_name(name)
    if not cleaned or len(cleaned) < 2:
        return None
    words = _tokenize_entity(cleaned)

    if cleaned.lower() in _SUBSTANCE_NOUNS or (
        len(words) == 1 and words[0] in _SUBSTANCE_NOUNS
    ):
        return None
    if cleaned.lower() in _KEEP_AS_MATERIAL:
        return None
    if _looks_like_chemical_formula(cleaned):
        return None

    if looks_like_year_label(cleaned):
        return "temporal"
    if looks_like_property_parameter(cleaned):
        return "parameter"
    if _looks_like_organization_brand(cleaned):
        return "organization"
    if _looks_like_person_entity(cleaned):
        return "person"

    if (
        _looks_like_operation(cleaned)
        or _looks_like_process_activity(cleaned)
        or looks_like_concept_not_material(cleaned)
    ):
        return "process"
    if _looks_like_facility(cleaned):
        return "facility"
    if _looks_like_apparatus(cleaned):
        return "equipment"
    return None


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
