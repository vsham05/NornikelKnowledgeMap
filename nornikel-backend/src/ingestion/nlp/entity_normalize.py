"""Normalize messy LLM extraction output before Pydantic validation."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from domain.dto.property_value import PropertyValueDTO
from domain.enums import MaterialClass, MaterialState
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

    return PropertyValueDTO(
        value=raw_value,
        unit=prop_data.get("unit"),
        value_min=float(value_min) if value_min is not None else None,
        value_max=float(value_max) if value_max is not None else None,
        conditions=prop_data.get("conditions") or {},
        source_document_id=document_id,
        source_page=source_page,
        source_text=prop_data.get("source_text"),
        confidence=confidence,
    )


__all__ = [
    "coerce_material_class",
    "coerce_material_state",
    "coerce_property_value",
    "split_compound_field",
    "MaterialClass",
    "MaterialState",
]
