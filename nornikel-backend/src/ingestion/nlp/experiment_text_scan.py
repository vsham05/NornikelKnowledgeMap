"""Heuristic experiment / computational-study detection for R&D documents."""

from __future__ import annotations

import re
from uuid import UUID, uuid4

from domain.dto.experiment import ExperimentDTO, RegimeDTO, RegimeParameterDTO
from domain.dto.material import MaterialDTO
from domain.dto.property_value import PropertyDTO, PropertyValueDTO
from domain.enums import MaterialClass, MaterialState, RegimeType
from ingestion.nlp.extraction_validate import is_llm_template_string, normalize_entity_name
from ingestion.parsers.pdf_table_extract import TABLE_BLOCK_RE

# (pattern, key, ru_title, en_title)
_EXPERIMENT_PHRASE_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        re.compile(r"верификационн\w*\s+модел", re.IGNORECASE | re.UNICODE),
        "verification_model",
        "верификационная модель",
        "verification model",
    ),
    (
        re.compile(r"расчетн\w*\s+(?:модел|схем|задач)", re.IGNORECASE | re.UNICODE),
        "computational_model",
        "расчетная модель",
        "computational model",
    ),
    (
        re.compile(r"численн\w*\s+(?:эксперимент|расчет|расчёт|моделир|исслед)", re.IGNORECASE | re.UNICODE),
        "numerical_experiment",
        "численный эксперимент",
        "numerical experiment",
    ),
    (
        re.compile(
            r"моделирование\s+(?:тектон|разлом|ослаблен|брус|конечн|упруг)",
            re.IGNORECASE | re.UNICODE,
        ),
        "geotechnical_simulation",
        "геотехническое моделирование",
        "geotechnical simulation",
    ),
    (
        re.compile(r"полев\w*\s+(?:испытан|эксперимент|исследован)", re.IGNORECASE | re.UNICODE),
        "field_experiment",
        "полевой эксперимент",
        "field experiment",
    ),
    (
        re.compile(r"лабораторн\w*\s+(?:испытан|эксперимент)", re.IGNORECASE | re.UNICODE),
        "laboratory_experiment",
        "лабораторный эксперимент",
        "laboratory experiment",
    ),
    (
        re.compile(r"статическ\w*\s+(?:расчет|расчёт|анализ|испытан)", re.IGNORECASE | re.UNICODE),
        "static_test",
        "статический расчет",
        "static analysis",
    ),
    (
        re.compile(r"динамическ\w*\s+(?:расчет|расчёт|анализ|испытан)", re.IGNORECASE | re.UNICODE),
        "dynamic_test",
        "динамический расчет",
        "dynamic analysis",
    ),
)

_INLINE_NUMERIC_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"(?:модуль\s+)?(?:упругости|Young(?:['']s)?(?:\s+modulus)?|E)\s*[=:]\s*([\d.,]+)\s*(MPa|GPa|kPa|Pa|МПа|ГПа)?",
            re.IGNORECASE | re.UNICODE,
        ),
        "elastic_modulus",
        "MPa",
    ),
    (
        re.compile(
            r"(?:коэфф\.?\s+)?(?:Пуассона|Poisson(?:['']s)?|ν)\s*[=:]\s*([\d.,]+)",
            re.IGNORECASE | re.UNICODE,
        ),
        "poisson_ratio",
        "",
    ),
    (
        re.compile(
            r"(?:плотност\w*|density)\s*[=:]\s*([\d.,]+)\s*(kg/m3|kg/m³|g/cm3|g/cm³)?",
            re.IGNORECASE | re.UNICODE,
        ),
        "density",
        "kg/m3",
    ),
)

_HEADER_PROP_MAP: dict[str, tuple[str, str]] = {
    "e": ("elastic_modulus", "MPa"),
    "e mpa": ("elastic_modulus", "MPa"),
    "e, mpa": ("elastic_modulus", "MPa"),
    "e (mpa)": ("elastic_modulus", "MPa"),
    "young's modulus": ("elastic_modulus", "MPa"),
    "youngs modulus": ("elastic_modulus", "MPa"),
    "модуль упругости": ("elastic_modulus", "MPa"),
    "модуль e": ("elastic_modulus", "MPa"),
    "ν": ("poisson_ratio", ""),
    "nu": ("poisson_ratio", ""),
    "v": ("poisson_ratio", ""),
    "poisson ratio": ("poisson_ratio", ""),
    "коэффициент пуассона": ("poisson_ratio", ""),
    "пуассона": ("poisson_ratio", ""),
    "density": ("density", "kg/m3"),
    "плотность": ("density", "kg/m3"),
    "g": ("shear_modulus", "MPa"),
    "shear modulus": ("shear_modulus", "MPa"),
    "модуль сдвига": ("shear_modulus", "MPa"),
}

_ZONE_HEADER_HINTS = (
    "zone", "зона", "material", "материал", "участок", "region", "область", "element", "элемент",
)


def _normalize_header(header: str) -> str:
    return re.sub(r"\s+", " ", (header or "").strip().lower())


def _parse_number(raw: str) -> float | int | str:
    cleaned = (raw or "").strip().replace(",", ".")
    if not cleaned:
        return cleaned
    try:
        val = float(cleaned)
        return int(val) if val.is_integer() else val
    except ValueError:
        return cleaned


def looks_like_experiment_label(name: str) -> bool:
    cleaned = normalize_entity_name(name)
    if not cleaned or len(cleaned) < 6:
        return False
    if is_llm_template_string(cleaned):
        return False
    lower = cleaned.lower()
    hints = (
        "model", "simulation", "experiment", "study", "analysis", "verification",
        "calculation", "computational", "numerical", "test", "run", "case",
        "модел", "эксперимент", "расчет", "расчёт", "верификац", "численн",
        "испытан", "исследован", "анализ", "схем",
    )
    return any(h in lower for h in hints)


def experiment_fingerprint(exp: ExperimentDTO) -> str:
    name = (exp.regime.name or "").lower().strip()
    params = sorted(
        f"{k}={getattr(exp.regime.parameters[k].value, 'value', '')}"
        for k in exp.regime.parameters
        if k != "status"
    )
    measured = sorted(
        f"{k}={getattr(exp.measured_properties[k].value, 'value', '')}"
        for k in exp.measured_properties
    )
    return f"{name}|{'|'.join(params)}|{'|'.join(measured)}"


def merge_experiments(existing: list[ExperimentDTO], new_items: list[ExperimentDTO]) -> list[ExperimentDTO]:
    seen = {experiment_fingerprint(exp) for exp in existing}
    merged = list(existing)
    for exp in new_items:
        fp = experiment_fingerprint(exp)
        if fp in seen:
            continue
        seen.add(fp)
        merged.append(exp)
    return merged


def find_experiment_phrases_in_text(
    text: str,
    target_lang: str = "ru",
) -> list[tuple[str, str, str, dict[str, RegimeParameterDTO]]]:
    """Return (key, title, source, parameters) for phrase + inline numeric hits."""
    if not text.strip():
        return []

    hits: list[tuple[str, str, str, dict[str, RegimeParameterDTO]]] = []
    seen: set[str] = set()

    inline_params: dict[str, RegimeParameterDTO] = {}
    for pattern, prop_name, default_unit in _INLINE_NUMERIC_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        val = _parse_number(match.group(1))
        unit = (match.group(2) if match.lastindex and match.lastindex >= 2 else None) or default_unit
        inline_params[prop_name] = RegimeParameterDTO(
            name=prop_name,
            value=PropertyValueDTO(value=val, unit=unit or None, source_text=match.group(0)),
        )

    for pattern, key, ru, en in _EXPERIMENT_PHRASE_PATTERNS:
        if not pattern.search(text):
            continue
        if key in seen:
            continue
        seen.add(key)
        title = en if target_lang == "en" else ru
        hits.append((key, title, "phrase", dict(inline_params)))

    if inline_params and not hits:
        title = "Численные параметры модели" if target_lang == "ru" else "Model numeric parameters"
        hits.append(("inline_parameters", title, "inline", inline_params))

    return hits


def _header_to_property(header: str) -> tuple[str, str] | None:
    norm = _normalize_header(header)
    if norm in _HEADER_PROP_MAP:
        return _HEADER_PROP_MAP[norm]
    if "e" == norm or norm.endswith(", mpa") or "модул" in norm and "упруг" in norm:
        return ("elastic_modulus", "MPa")
    if "пуассон" in norm or norm in {"ν", "nu"}:
        return ("poisson_ratio", "")
    if "плотност" in norm or "density" in norm:
        return ("density", "kg/m3")
    return None


def _is_zone_header(header: str) -> bool:
    norm = _normalize_header(header)
    return any(h in norm for h in _ZONE_HEADER_HINTS)


def _pick_material_id(materials: list[MaterialDTO], label: str, document_id: UUID) -> UUID:
    hay = label.lower()
    for mat in materials:
        if mat.name.lower() in hay or hay in mat.name.lower():
            return mat.id
        for alias in mat.aliases:
            if alias.lower() in hay or hay in alias.lower():
                return mat.id
    if materials:
        return materials[0].id
    fallback = MaterialDTO(
        id=uuid4(),
        name=label[:80] or "model domain",
        material_class=MaterialClass.OTHER,
        state=MaterialState.SOLID,
        properties={},
        source_document_id=document_id,
    )
    materials.append(fallback)
    return fallback.id


def build_experiment(
    *,
    document_id: UUID,
    material_id: UUID,
    title: str,
    summary: str = "",
    parameters: dict[str, RegimeParameterDTO] | None = None,
    measured: dict[str, PropertyDTO] | None = None,
    source: str = "backfill",
) -> ExperimentDTO:
    params = dict(parameters or {})
    exp = ExperimentDTO(
        id=uuid4(),
        material_id=material_id,
        regime=RegimeDTO(
            regime_type=RegimeType.OTHER,
            name=title[:120],
            parameters=params,
            description=(summary or title)[:500],
        ),
        measured_properties=measured or {},
        conclusions=[(summary or title)[:500]] if (summary or title) else [],
        document_id=document_id,
    )
    return exp


def experiments_from_table_blocks(
    text: str,
    document_id: UUID,
    materials: list[MaterialDTO],
    *,
    table_title: str | None = None,
) -> list[ExperimentDTO]:
    """One experiment per numeric table row (FEM parameter tables, lab results)."""
    results: list[ExperimentDTO] = []
    for match in TABLE_BLOCK_RE.finditer(text):
        block = match.group(0)
        lines = [
            line.strip()
            for line in block.splitlines()
            if line.strip() and not line.strip().upper().startswith("[TABLE")
        ]
        md_rows = [line for line in lines if line.startswith("|")]
        if len(md_rows) < 3:
            continue
        caption = ""
        if lines and not lines[0].startswith("|"):
            caption = lines[0]

        headers = [_normalize_header(c) for c in md_rows[0].strip("|").split("|")]
        zone_idx = next((i for i, h in enumerate(headers) if _is_zone_header(h)), 0)

        prop_cols: list[tuple[int, str, str]] = []
        for idx, header in enumerate(headers):
            if idx == zone_idx:
                continue
            mapped = _header_to_property(header)
            if mapped:
                prop_cols.append((idx, mapped[0], mapped[1]))

        if not prop_cols:
            continue

        for row in md_rows[2:]:
            cells = [c.strip() for c in row.strip("|").split("|")]
            if len(cells) < len(headers):
                cells += [""] * (len(headers) - len(cells))
            zone_label = cells[zone_idx].strip() if zone_idx < len(cells) else ""
            if not zone_label:
                zone_label = caption or table_title or "Table row"

            measured: dict[str, PropertyDTO] = {}
            params: dict[str, RegimeParameterDTO] = {}
            has_number = False
            for col_idx, prop_name, unit in prop_cols:
                if col_idx >= len(cells):
                    continue
                raw_val = cells[col_idx].strip()
                if not raw_val or not re.search(r"\d", raw_val):
                    continue
                has_number = True
                val = _parse_number(raw_val)
                measured[prop_name] = PropertyDTO(
                    name=prop_name,
                    category="mechanical",
                    value=PropertyValueDTO(value=val, unit=unit or None, source_text=row.strip()),
                    aliases=[],
                )
                params[prop_name] = RegimeParameterDTO(
                    name=prop_name,
                    value=PropertyValueDTO(value=val, unit=unit or None, source_text=row.strip()),
                )

            if not has_number:
                continue

            title = zone_label
            if caption and caption.lower() not in title.lower():
                title = f"{caption}: {zone_label}"

            material_id = _pick_material_id(materials, zone_label, document_id)
            results.append(
                build_experiment(
                    document_id=document_id,
                    material_id=material_id,
                    title=title[:120],
                    summary=row.strip()[:500],
                    parameters=params,
                    measured=measured,
                    source="table_row",
                )
            )
    return results


def experiments_from_text_phrases(
    text: str,
    document_id: UUID,
    materials: list[MaterialDTO],
    target_lang: str = "ru",
) -> list[ExperimentDTO]:
    results: list[ExperimentDTO] = []
    for key, title, source, params in find_experiment_phrases_in_text(text, target_lang):
        material_id = _pick_material_id(materials, title, document_id)
        measured = {
            name: PropertyDTO(
                name=name,
                category="mechanical",
                value=p.value,
                aliases=[],
            )
            for name, p in params.items()
            if name != "source"
        }
        results.append(
            build_experiment(
                document_id=document_id,
                material_id=material_id,
                title=title,
                summary=title,
                parameters={k: v for k, v in params.items() if k != "source"},
                measured=measured,
                source=source,
            )
        )
    return results


def experiments_from_section_titles(
    chunks: list,
    document_id: UUID,
    materials: list[MaterialDTO],
) -> list[ExperimentDTO]:
    results: list[ExperimentDTO] = []
    seen: set[str] = set()
    for chunk in chunks:
        title = str(getattr(chunk, "section_title", None) or "").strip()
        if not title or not looks_like_experiment_label(title):
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        material_id = _pick_material_id(materials, title, document_id)
        results.append(
            build_experiment(
                document_id=document_id,
                material_id=material_id,
                title=title,
                summary=title,
                source="section_title",
            )
        )
    return results
