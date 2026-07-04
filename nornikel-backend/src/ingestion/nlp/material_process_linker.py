"""Infer Material -> Process links from LLM hints, text, taxonomy, and name overlap."""

from __future__ import annotations

import re

from domain.dto.material import MaterialDTO
from domain.enums import MaterialProcessStage
from domain.material_taxonomy import get_material_taxonomy

_TOKEN_STOP = frozenset({
    "and", "the", "of", "for", "raw", "materials", "material", "ore", "metal",
})

_STAGE_KEYWORDS: dict[MaterialProcessStage, tuple[str, ...]] = {
    MaterialProcessStage.FEEDSTOCK: ("mining", "beneficiation", "flotation", "heap", "leaching"),
    MaterialProcessStage.BENEFICIATION: ("beneficiation", "flotation", "concentrate"),
    MaterialProcessStage.PROCESSING: (
        "pyrometallurgy", "smelting", "roasting", "leaching", "hydro", "electrowinning",
    ),
    MaterialProcessStage.PRODUCT: ("refining", "electrowinning"),
    MaterialProcessStage.ENGINEERING: ("water", "treatment", "recycling", "waste"),
}

_NAME_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("catholyte", ("electrowinning", "electro")),
    ("anolyte", ("electrowinning", "electro")),
    ("matte", ("pyrometallurgy", "smelting")),
    ("slag", ("pyrometallurgy", "smelting")),
    ("gypsum", ("leaching", "hydro", "waste", "water", "recycling")),
    ("sulfate", ("electrowinning", "refining", "nickel", "cobalt")),
    ("nickel", ("nickel", "refining", "electrowinning", "cobalt")),
    ("copper", ("copper", "smelting", "refining")),
    ("rom", ("mining", "beneficiation", "heap", "leaching")),
    ("concentrate", ("flotation", "beneficiation", "smelting")),
)


def _material_terms(mat: MaterialDTO) -> set[str]:
    terms: set[str] = set()
    for field in [mat.name, *(mat.aliases or [])]:
        for part in re.split(r"[\s\-/,]+", str(field).lower()):
            part = part.strip()
            if len(part) >= 3 and part not in _TOKEN_STOP:
                terms.add(part)
    return terms


def _process_names(proc: dict) -> list[str]:
    names = [str(proc.get("name") or "").lower()]
    names.extend(str(a).lower() for a in proc.get("aliases") or [] if a)
    return [n for n in names if n]


def _score_material_process(
    mat: MaterialDTO,
    proc: dict,
    text_lower: str,
) -> float:
    score = 0.0
    pnames = _process_names(proc)
    if not pnames:
        return 0.0

    terms = _material_terms(mat)
    mn = mat.name.lower()

    for t in terms:
        if any(t in pn for pn in pnames):
            score += 2.5

    if any(pn in mn or mn in pn for pn in pnames):
        score += 3.0

    for pname in pnames:
        pos = 0
        while True:
            idx = text_lower.find(pname, pos)
            if idx < 0:
                break
            window = text_lower[max(0, idx - 450) : idx + len(pname) + 450]
            if any(t in window for t in terms):
                score += 2.0
                break
            pos = idx + 1

    try:
        stage = get_material_taxonomy().get_stage(mat.material_class)
    except Exception:
        stage = MaterialProcessStage.OTHER

    for kw in _STAGE_KEYWORDS.get(stage, ()):
        if any(kw in pn for pn in pnames):
            score += 1.2

    for hint, kws in _NAME_HINTS:
        if hint in mn or hint in terms:
            if any(any(k in pn for pn in pnames) for k in kws):
                score += 2.0

    return score


def build_material_process_links(
    materials: list[MaterialDTO],
    processes: list[dict],
    text: str,
) -> list[dict]:
    """Return PROCESSED_IN link specs: material_name + process_id."""
    links: list[dict] = []
    seen: set[tuple[str, str]] = set()
    text_lower = (text or "").lower()

    mat_by_key: dict[str, MaterialDTO] = {}
    for mat in materials:
        mat_by_key[mat.name.lower()] = mat
        for alias in mat.aliases or []:
            mat_by_key[str(alias).lower()] = mat

    def add(mat_name: str, process_id: str) -> None:
        key = mat_name.strip().lower()
        if key not in mat_by_key:
            return
        pair = (mat_by_key[key].name.lower(), process_id)
        if pair in seen:
            return
        seen.add(pair)
        links.append({
            "material_name": mat_by_key[key].name,
            "process_id": process_id,
        })

    # 1) LLM per-process material lists + substring / co-occurrence
    for proc in processes:
        proc_id = proc["id"]
        pnames = _process_names(proc)
        for raw_mat in proc.get("materials") or []:
            add(str(raw_mat).strip(), proc_id)

        for mat in materials:
            mn = mat.name.lower()
            if (mn, proc_id) in seen:
                continue
            terms = _material_terms(mat)
            matched = False
            for pn in pnames:
                if mn in pn or pn in mn or any(t in pn for t in terms):
                    add(mn, proc_id)
                    matched = True
                    break
            if matched:
                continue
            for pn in pnames:
                pos = 0
                while True:
                    idx = text_lower.find(pn, pos)
                    if idx < 0:
                        break
                    window = text_lower[max(0, idx - 450) : idx + len(pn) + 450]
                    if mn in window or any(t in window for t in terms):
                        add(mn, proc_id)
                        break
                    pos = idx + 1
                if (mn, proc_id) in seen:
                    break

    linked = {lnk["material_name"].lower() for lnk in links}

    # 2) Best-scoring process for still-unlinked materials
    for mat in materials:
        if mat.name.lower() in linked:
            continue
        best_proc: dict | None = None
        best_score = 0.0
        for proc in processes:
            s = _score_material_process(mat, proc, text_lower)
            if s > best_score:
                best_score = s
                best_proc = proc
        if best_proc and best_score >= 2.0:
            add(mat.name, best_proc["id"])
            linked.add(mat.name.lower())

    # 3) Inherit from name-related material (e.g. copper matte -> matte's process)
    proc_by_mat = {lnk["material_name"].lower(): lnk["process_id"] for lnk in links}
    for mat in materials:
        if mat.name.lower() in proc_by_mat:
            continue
        mn = mat.name.lower()
        for other_name, proc_id in list(proc_by_mat.items()):
            if other_name == mn:
                continue
            if other_name in mn or mn in other_name:
                add(mat.name, proc_id)
                proc_by_mat[mat.name.lower()] = proc_id
                break

    # 4) Last resort: one process link for anything still orphan (same class bucket)
    if processes:
        for mat in materials:
            if mat.name.lower() in {lnk["material_name"].lower() for lnk in links}:
                continue
            best_proc = max(
                processes,
                key=lambda p: _score_material_process(mat, p, text_lower),
            )
            if _score_material_process(mat, best_proc, text_lower) > 0:
                add(mat.name, best_proc["id"])

    return links
