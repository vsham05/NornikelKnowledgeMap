"""RU↔EN canonical keys for materials, processes, and graph deduplication."""

from __future__ import annotations

import re
import unicodedata

# canonical_key -> (ru_display, en_display)
_ENTRIES: dict[str, tuple[str, str]] = {
    "nickel": ("никель", "nickel"),
    "copper": ("медь", "copper"),
    "cobalt": ("кобальт", "cobalt"),
    "iron": ("железо", "iron"),
    "zinc": ("цинк", "zinc"),
    "magnesium": ("магний", "magnesium"),
    "manganese": ("марганец", "manganese"),
    "aluminum": ("алюминий", "aluminum"),
    "gold": ("золото", "gold"),
    "silver": ("серебро", "silver"),
    "platinum": ("платина", "platinum"),
    "palladium": ("палладий", "palladium"),
    "sulfur": ("сера", "sulfur"),
    "gypsum": ("гипс", "gypsum"),
    "limonite": ("лимонит", "limonite"),
    "matte": ("матт", "matte"),
    "slag": ("шлак", "slag"),
    "concentrate": ("концентрат", "concentrate"),
    "ore": ("руда", "ore"),
    "hydrochloric_acid": ("соляная кислота", "hydrochloric acid"),
    "sulfuric_acid": ("серная кислота", "sulfuric acid"),
    "h2so4": ("серная кислота", "H2SO4"),
    "hcl": ("соляная кислота", "HCl"),
    "beneficiation": ("обогащение", "beneficiation"),
    "flotation": ("флотация", "flotation"),
    "leaching": ("выщелачивание", "leaching"),
    "heap_leaching": ("кучное выщелачивание", "heap leaching"),
    "hpal": ("автоклавное выщелачивание", "HPAL"),
    "hydrometallurgy": ("гидрометаллургия", "hydrometallurgy"),
    "hydrometallurgical_processing": (
        "гидрометаллургическая переработка",
        "hydrometallurgical processing",
    ),
    "pyrometallurgy": ("пирометаллургия", "pyrometallurgy"),
    "roasting": ("обжиг", "roasting"),
    "smelting": ("плавка", "smelting"),
    "refining": ("рафинирование", "refining"),
    "electrorefining": ("электрорафинирование", "electrorefining"),
    "electrolytic_refining": ("электролитическое рафинирование", "electrolytic refining"),
    "electrowinning": ("электроосаждение", "electrowinning"),
    "precipitation": ("осаждение", "precipitation"),
    "oxidation": ("окисление", "oxidation"),
    "autoclave_oxidation": ("автоклавное окисление", "autoclave oxidation"),
    "carbonyl_nickel": ("карбонильный никель", "carbonyl nickel"),
    "precious_metals": ("драгоценные металлы", "precious metals"),
    "ore_raw_material": ("рудное сырье", "ore raw material"),
    "magnesium_chloride": ("хлорид магния", "magnesium chloride"),
    "limonite_ore": ("лимонитовая руда", "limonite ore"),
    "fe2o3": ("Fe2O3", "Fe2O3"),
    "coral_bay": ("coral bay", "Coral Bay"),
    "zinc_removal": ("удаление цинка", "zinc removal"),
    "de_zn": ("de-zn", "De-Zn"),
    "finite_element_method": ("метод конечных элементов", "finite element method"),
    "finite_stiffness_links": ("связи конечной жесткости", "finite stiffness links"),
    "numerical_modeling": ("численное моделирование", "numerical modeling"),
    "geotechnical_modeling": ("геотехническое моделирование", "geotechnical modeling"),
    "verification_modeling": ("верификационное моделирование", "verification modeling"),
    "cfd_simulation": ("CFD-моделирование", "CFD simulation"),
    "field_testing": ("полевые испытания", "field testing"),
    "laboratory_testing": ("лабораторные испытания", "laboratory testing"),
    "geotechnical_analysis": ("геотехнический анализ", "geotechnical analysis"),
    "model_calibration": ("калибровка модели", "model calibration"),
    "static_analysis": ("статический расчет", "static analysis"),
    "dynamic_analysis": ("динамический расчет", "dynamic analysis"),
    "fem_simulation": ("МКЭ-моделирование", "FEM simulation"),
    "structural_analysis": ("расчет конструкций", "structural analysis"),
    "rock_mechanics_testing": ("испытания механики горных пород", "rock mechanics testing"),
}

_LOOKUP: dict[str, str] = {}


def _normalize_token(text: str) -> str:
    raw = unicodedata.normalize("NFKC", (text or "").strip().lower())
    raw = raw.replace("ё", "е")
    raw = re.sub(r"[_\-]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _build_lookup() -> None:
    if _LOOKUP:
        return
    for key, (ru, en) in _ENTRIES.items():
        for variant in (key, ru, en):
            norm = _normalize_token(variant)
            if norm:
                _LOOKUP[norm] = key


def canonical_entity_key(name: str) -> str:
    """Stable ASCII key for dedup / resolution."""
    _build_lookup()
    norm = _normalize_token(name)
    if not norm:
        return ""
    if norm in _LOOKUP:
        return _LOOKUP[norm]
    return re.sub(r"\s+", "_", norm)


def to_display_lang(name: str, lang: str) -> str:
    """Map a known term to the target display language."""
    _build_lookup()
    norm = _normalize_token(name)
    if not norm:
        return name
    key = _LOOKUP.get(norm)
    if not key:
        return name.strip()
    ru, en = _ENTRIES[key]
    if lang == "en":
        return en
    return ru


def glossary_translate(name: str, target_lang: str) -> str:
    """Return glossary translation if known, else original."""
    mapped = to_display_lang(name, target_lang)
    return mapped if mapped != name.strip() else name.strip()


# Glossary keys that denote metallurgical processes (for text backfill).
PROCESS_GLOSSARY_KEYS: frozenset[str] = frozenset({
    "beneficiation",
    "flotation",
    "leaching",
    "heap_leaching",
    "hpal",
    "hydrometallurgy",
    "hydrometallurgical_processing",
    "pyrometallurgy",
    "roasting",
    "smelting",
    "refining",
    "electrorefining",
    "electrolytic_refining",
    "electrowinning",
    "precipitation",
    "oxidation",
    "autoclave_oxidation",
    "zinc_removal",
    "de_zn",
    "finite_element_method",
    "finite_stiffness_links",
    "numerical_modeling",
    "geotechnical_modeling",
    "verification_modeling",
    "cfd_simulation",
    "field_testing",
    "laboratory_testing",
    "geotechnical_analysis",
    "model_calibration",
    "static_analysis",
    "dynamic_analysis",
    "fem_simulation",
    "structural_analysis",
    "rock_mechanics_testing",
})

FACILITY_GLOSSARY_KEYS: frozenset[str] = frozenset({
    "coral_bay",
})


def find_glossary_terms_in_text(
    text: str,
    keys: frozenset[str],
) -> list[tuple[str, str, str]]:
    """Return (canonical_key, ru, en) for glossary entries found in *text*."""
    _build_lookup()
    if not text.strip():
        return []
    haystack_lower = text.lower()
    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for key in keys:
        if key not in _ENTRIES:
            continue
        ru, en = _ENTRIES[key]
        variants = {key.replace("_", " "), ru, en, key}
        hit = False
        for variant in variants:
            token = (variant or "").strip().lower()
            if token and token in haystack_lower:
                hit = True
                break
        if hit and key not in seen:
            seen.add(key)
            found.append((key, ru, en))
    return found


def apply_glossary_to_value(value: object, target_lang: str) -> object:
    """Recursively apply glossary to string fields in extraction JSON."""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return value
        return glossary_translate(stripped, target_lang)
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            if key in ("source_text",):
                out[key] = item
            elif key in ("properties", "measured_properties", "parameters") and isinstance(item, dict):
                out[key] = {
                    pk: apply_glossary_to_value(pv, target_lang) if pk != "source_text" else pv
                    for pk, pv in item.items()
                }
            else:
                out[key] = apply_glossary_to_value(item, target_lang)
        return out
    if isinstance(value, list):
        return [apply_glossary_to_value(item, target_lang) for item in value]
    return value
