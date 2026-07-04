"""Normalize messy LLM extraction output before Pydantic validation."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from domain.dto.property_value import PropertyValueDTO
from domain.enums import MaterialClass, MaterialState, RegimeType
from domain.material_taxonomy import coerce_material_class

_RANGE_RE = re.compile(
    r"^\s*([<>]?\s*[\d.]+)\s*[-–—~to]+\s*([<>]?\s*[\d.]+)\s*$",
    re.IGNORECASE,
)
_COMPOUND_SEP = re.compile(r"[|/,;]+")
_ELLIPSIS = re.compile(r"[.…]{2,}$")


def split_compound_field(value: str | None) -> list[str]:
    """Split pipe/comma-separated LLM fields into individual entity names."""
    if not value or not str(value).strip():
        return []
    text = _ELLIPSIS.sub("", str(value).strip())
    parts: list[str] = []
    for piece in _COMPOUND_SEP.split(text):
        name = piece.strip().strip(".")
        if not name:
            continue
        if len(name) < 2 and not (len(name) == 1 and name.isalpha()):
            continue
        parts.append(name)
    return parts if parts else [text.strip()]


def coerce_material_state(raw: str | None) -> MaterialState:
    if not raw:
        return MaterialState.SOLID
    key = str(raw).strip().lower()
    if key in MaterialState._value2member_map_:
        return MaterialState(key)
    for part in key.split("|"):
        part = part.strip()
        if part in MaterialState._value2member_map_:
            return MaterialState(part)
    return MaterialState.SOLID


_REGIME_TYPE_ALIASES: dict[str, RegimeType] = {
    "leaching": RegimeType.CHEMICAL,
    "heap_leaching": RegimeType.CHEMICAL,
    "heap leaching": RegimeType.CHEMICAL,
    "hydrometallurgy": RegimeType.CHEMICAL,
    "hydro": RegimeType.CHEMICAL,
    "electrowinning": RegimeType.CHEMICAL,
    "electrorefining": RegimeType.CHEMICAL,
    "refining": RegimeType.CHEMICAL,
    "roasting": RegimeType.HEAT_TREATMENT,
    "smelting": RegimeType.HEAT_TREATMENT,
    "pyrometallurgy": RegimeType.HEAT_TREATMENT,
    "pyro": RegimeType.HEAT_TREATMENT,
    "flotation": RegimeType.MECHANICAL,
    "beneficiation": RegimeType.MECHANICAL,
    "grinding": RegimeType.MECHANICAL,
    "crushing": RegimeType.MECHANICAL,
    "milling": RegimeType.MECHANICAL,
    "mining": RegimeType.MECHANICAL,
    "heat": RegimeType.HEAT_TREATMENT,
    "heat treatment": RegimeType.HEAT_TREATMENT,
    "annealing": RegimeType.HEAT_TREATMENT,
    "quenching": RegimeType.HEAT_TREATMENT,
    "tempering": RegimeType.HEAT_TREATMENT,
    "forging": RegimeType.THERMOMECHANICAL,
    "rolling": RegimeType.THERMOMECHANICAL,
    "extrusion": RegimeType.THERMOMECHANICAL,
}


def coerce_regime_type(raw: str | None, *, name: str | None = None, description: str | None = None) -> RegimeType:
    """Map free-text / process names to a valid RegimeType."""
    candidates: list[str] = []
    if raw:
        candidates.append(str(raw).strip().lower())
    if name:
        candidates.append(str(name).strip().lower())
    if description:
        candidates.append(str(description).strip().lower())

    for candidate in candidates:
        if not candidate:
            continue
        normalized = candidate.replace(" ", "_").replace("-", "_")
        if normalized in RegimeType._value2member_map_:
            return RegimeType(normalized)
        for part in candidate.replace("_", " ").split("|"):
            part = part.strip()
            if part in RegimeType._value2member_map_:
                return RegimeType(part)
        if normalized in _REGIME_TYPE_ALIASES:
            return _REGIME_TYPE_ALIASES[normalized]
        for alias, regime in _REGIME_TYPE_ALIASES.items():
            if alias in normalized or normalized in alias:
                return regime

    blob = " ".join(candidates)
    if any(k in blob for k in ("leach", "hydro", "electro", "refin", "acid", "alkali")):
        return RegimeType.CHEMICAL
    if any(k in blob for k in ("smelt", "roast", "pyro", "furnace", "temperature")):
        return RegimeType.HEAT_TREATMENT
    if any(k in blob for k in ("grind", "crush", "float", "mill", "beneficiat")):
        return RegimeType.MECHANICAL
    return RegimeType.OTHER


def _try_parse_float(text: str) -> float | None:
    cleaned = text.strip().replace(",", ".")
    if not cleaned or cleaned in {"-", "—", "–"}:
        return None
    if cleaned[0] in "<>":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_range_string(text: str) -> tuple[float | None, float | None]:
    match = _RANGE_RE.match(text.strip())
    if not match:
        return None, None
    lo = _try_parse_float(match.group(1))
    hi = _try_parse_float(match.group(2))
    return lo, hi


def _normalize_composition(raw: dict[Any, Any]) -> dict[str, float | str]:
    out: dict[str, float | str] = {}
    for key, val in raw.items():
        if val is None:
            continue
        if isinstance(val, (int, float)):
            out[str(key)] = float(val)
            continue
        if isinstance(val, str):
            lo, hi = _parse_range_string(val)
            if lo is not None and hi is not None:
                out[str(key)] = f"{lo}–{hi}"
            else:
                parsed = _try_parse_float(val)
                out[str(key)] = parsed if parsed is not None else val.strip()
            continue
        out[str(key)] = str(val)
    return out


def coerce_property_value(
    prop_data: dict | None,
    *,
    document_id: UUID | None,
    source_page: int | None,
    confidence: float = 0.9,
) -> PropertyValueDTO | None:
    """Build PropertyValueDTO from LLM JSON, skipping empty or invalid entries."""
    if not prop_data or not isinstance(prop_data, dict):
        return None

    value_min = prop_data.get("value_min")
    value_max = prop_data.get("value_max")
    if isinstance(value_min, str):
        value_min = _try_parse_float(value_min)
    if isinstance(value_max, str):
        value_max = _try_parse_float(value_max)

    raw_value = prop_data.get("value")

    if isinstance(raw_value, str):
        lo, hi = _parse_range_string(raw_value)
        if lo is not None and hi is not None:
            value_min = value_min if value_min is not None else lo
            value_max = value_max if value_max is not None else hi
            raw_value = None

    if isinstance(raw_value, dict):
        raw_value = _normalize_composition(raw_value)
        if not raw_value:
            return None

    if raw_value is None:
        if value_min is not None and value_max is not None:
            raw_value = (float(value_min) + float(value_max)) / 2
        elif value_min is not None:
            raw_value = float(value_min)
        elif value_max is not None:
            raw_value = float(value_max)
        elif prop_data.get("source_text"):
            raw_value = str(prop_data["source_text"])
        else:
            return None

    conditions_raw = prop_data.get("conditions")
    conditions: dict[str, Any] = {}
    if isinstance(conditions_raw, dict):
        for key, val in conditions_raw.items():
            if isinstance(val, (str, int, float, bool)):
                conditions[str(key)] = val

    return PropertyValueDTO(
        value=raw_value,
        unit=prop_data.get("unit"),
        value_min=float(value_min) if value_min is not None else None,
        value_max=float(value_max) if value_max is not None else None,
        conditions=conditions,
        source_document_id=document_id,
        source_page=source_page,
        source_text=prop_data.get("source_text"),
        confidence=confidence,
    )


__all__ = [
    "coerce_material_class",
    "coerce_material_state",
    "coerce_property_value",
    "coerce_regime_type",
    "split_compound_field",
    "MaterialClass",
    "MaterialState",
    "RegimeType",
]
