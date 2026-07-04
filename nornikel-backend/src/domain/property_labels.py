"""Human-readable property labels (Russian or English)."""

from __future__ import annotations

from domain.ontology import get_ontology

_EXTRA_LABELS_RU: dict[str, str] = {
    "nickel_content": "Содержание никеля",
    "cobalt_content": "Содержание кобальта",
    "copper_content": "Содержание меди",
    "iron_content": "Содержание железа",
    "magnesium_content": "Содержание магния",
    "total_content": "Общее содержание",
    "nickel_extraction": "Извлечение никеля",
    "cobalt_extraction": "Извлечение кобальта",
    "magnesium_extraction": "Извлечение магния",
    "copper_extraction": "Извлечение меди",
    "recovery_rate": "Степень извлечения",
    "extraction_rate": "Степень извлечения",
    "yield": "Выход",
    "density": "Плотность",
    "ph": "pH",
    "temperature": "Температура",
    "concentration": "Концентрация",
    "flow_rate": "Расход",
}

_EXTRA_LABELS_EN: dict[str, str] = {
    "nickel_content": "Nickel content",
    "cobalt_content": "Cobalt content",
    "copper_content": "Copper content",
    "iron_content": "Iron content",
    "magnesium_content": "Magnesium content",
    "total_content": "Total content",
    "nickel_extraction": "Nickel extraction",
    "cobalt_extraction": "Cobalt extraction",
    "magnesium_extraction": "Magnesium extraction",
    "copper_extraction": "Copper extraction",
    "recovery_rate": "Recovery rate",
    "extraction_rate": "Extraction rate",
    "yield": "Yield",
    "density": "Density",
    "ph": "pH",
    "temperature": "Temperature",
    "concentration": "Concentration",
    "flow_rate": "Flow rate",
}


def _title_case_key(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("_") if part)


def property_display_label(canonical_name: str, *, lang: str = "en") -> str:
    """Display label for a property canonical_name in the requested language."""
    name = (canonical_name or "").strip()
    target = (lang or "en").strip().lower()
    if target not in ("ru", "en"):
        target = "en"

    if not name:
        return "Measured parameter" if target == "en" else "Измеряемый параметр"

    if target == "en":
        if name in _EXTRA_LABELS_EN:
            return _EXTRA_LABELS_EN[name]
        return _title_case_key(name)

    if name in _EXTRA_LABELS_RU:
        return _EXTRA_LABELS_RU[name]
    schema = get_ontology().get_property_schema(name)
    if schema and schema.label:
        return schema.label
    return name.replace("_", " ")
