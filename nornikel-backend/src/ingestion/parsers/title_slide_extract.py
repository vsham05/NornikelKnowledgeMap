"""Structural provenance extraction from document text (RU/EN).

Heuristics parse *layout* (labeled fields, numbered rosters, legal-entity
patterns). Semantic classification (person vs team) is done by the LLM.

Stop-word lists here are intentionally **generic** — slide boilerplate,
academic section headings, and legal/institution suffixes that apply to any
PDF or presentation. They must NOT list company names, project names, or
vocabulary from a specific document.
"""

from __future__ import annotations

import re

# Generic slide/document noise (EN + RU). Not course-, company-, or corpus-specific.
_GENERAL_NOISE_MARKERS = (
    "presentation", "презентация", "powerpoint", "microsoft", "slide", "slides",
    "figure", "fig.", "рис.", "таблица", "table", "chart", "diagram", "график",
    "copyright", "©", "confidential", "конфиденциаль",
    "abstract", "introduction", "conclusion", "references", "bibliography",
    "acknowledgement", "acknowledgment", "appendix",
    "аннотация", "введение", "заключение", "литература", "содержание",
    "contents", "agenda", "outline", "summary",
    "page ", "страница", "стр.",
)

# Generic institution / legal-form tokens. Not company or brand names.
_GENERAL_ORG_HINTS = (
    "institute", "university", "laboratory", "laborat", "academy", "college",
    "research", "department", "division", "faculty", "school", "hospital",
    "center", "centre", "foundation", "company", "corporation", "consortium",
    "институт", "университет", "лаборатор", "академ", "департамент",
    "факультет", "центр", "завод", "фгбу", "комбинат",
    "llc", "ltd", "inc", "corp", "gmbh", "ооо", "пао", "ао", "гмк",
)

# Latin: Julia Gershteyn, Dmitry V. Lyapinov
_LATIN_PERSON = re.compile(
    r"^[A-Z][a-zA-Z\-']+(?:\s+[A-Z]\.){0,2}\s+[A-Z][a-zA-Z\-']+$"
)
# Cyrillic: Д. В. Ляпинов, Ляпинов Дмитрий Васильевич
_CYRILLIC_PERSON = re.compile(
    r"^(?:"
    r"[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){1,3}"
    r"|[А-ЯЁ]\.\s*[А-ЯЁ]\.\s*[А-ЯЁ][а-яё\-]+"
    r")$",
    re.UNICODE,
)

# Numbered roster lines: "1. Ivanov Ivan Ivanovich – senior researcher"
_EXPERT_LIST_ITEM = re.compile(
    r"(?:\d+\.\s*)?"
    r"("
    r"[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){1,3}"
    r"|[A-Z][a-zA-Z\-']+(?:\s+[A-Z]\.){0,2}\s+[A-Z][a-zA-Z\-']+"
    r")\s*[–\-—]",
    re.UNICODE,
)

# Legal-entity / affiliation shapes (language-agnostic suffixes, not company names)
_OOO_ORG = re.compile(r"ООО\s*«[^»]+»", re.IGNORECASE | re.UNICODE)
_ORG_LINE = re.compile(
    r"(?:"
    r"(?:ПАО|ГМК|АО|ООО|LLC|Ltd\.?|Inc\.?|Corp\.?|GmbH|University|Institute|Laboratory|Лаборатория|Институт|ФГБУ)"
    r"|«[^»]{4,80}»"
    r")",
    re.IGNORECASE | re.UNICODE,
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip(" .;,"))


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    lower = (text or "").lower()
    return any(m in lower for m in markers)


def _has_non_name_noise(text: str) -> bool:
    if _contains_marker(text, _GENERAL_NOISE_MARKERS):
        return True
    lower = (text or "").lower()
    if "@" in text or "http" in lower or "www." in lower:
        return True
    if re.search(r"\d", text):
        return True
    return False


def looks_like_person_name(name: str) -> bool:
    """Name-shaped token suitable for provenance hints (not LLM classification)."""
    cleaned = _clean(name)
    if not cleaned or len(cleaned) < 4 or len(cleaned) > 80:
        return False
    if _has_non_name_noise(cleaned):
        return False
    if _contains_marker(cleaned, _GENERAL_ORG_HINTS):
        return False
    if _ORG_LINE.search(cleaned):
        return False
    return bool(_LATIN_PERSON.match(cleaned) or _CYRILLIC_PERSON.match(cleaned))


def looks_like_organization_name(name: str) -> bool:
    """Affiliation-shaped token for provenance hints / fallback team creation."""
    cleaned = _clean(name)
    if not cleaned or len(cleaned) < 4 or len(cleaned) > 200:
        return False
    if looks_like_person_name(cleaned):
        return False
    if _has_non_name_noise(cleaned):
        return False
    if _ORG_LINE.search(cleaned):
        return True
    if _contains_marker(cleaned, _GENERAL_ORG_HINTS):
        return True
    # Multi-word phrase that is not person-shaped
    return len(cleaned.split()) >= 2 and len(cleaned) >= 8


def _normalize_org_name(name: str) -> str:
    cleaned = _clean(name)
    match = _OOO_ORG.search(cleaned)
    if match:
        return _clean(match.group(0))
    return cleaned


def extract_listed_experts_from_text(text: str, limit: int = 12_000) -> list[str]:
    """Parse numbered expert rosters after an Experts / Эксперты heading."""
    sample = re.sub(r"\s+", " ", (text or "")[:limit])
    seen: set[str] = set()
    experts: list[str] = []

    def add(name: str) -> None:
        cleaned = _clean(name)
        if not looks_like_person_name(cleaned):
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        experts.append(cleaned)

    lower = sample.lower()
    start = lower.find("эксперт")
    if start < 0:
        start = lower.find("expert")
    window = sample[start:] if start >= 0 else sample

    for match in _EXPERT_LIST_ITEM.finditer(window):
        add(match.group(1))

    return experts[:25]


def extract_authors_from_text(text: str, limit: int = 4000) -> list[str]:
    """Pull names from labeled author fields and structured expert rosters only."""
    seen: set[str] = set()
    authors: list[str] = []
    sample = (text or "")[:limit]

    def add(name: str) -> None:
        cleaned = _clean(name)
        if not looks_like_person_name(cleaned):
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        authors.append(cleaned)

    for pattern in (
        r"(?:Авторы?|Authors?|Докладчик(?:и)?|Presenter(?:s)?)\s*:?\s*([^\n]+)",
        r"(?:Подготовил[аи]?|Prepared by)\s*:?\s*([^\n]+)",
    ):
        for match in re.finditer(pattern, sample, re.IGNORECASE):
            for part in re.split(r"[;,/]|(?:\s+and\s+)|\s{2,}", match.group(1)):
                add(part)

    for name in extract_listed_experts_from_text(text, limit):
        add(name)

    return authors[:20]


def extract_organizations_from_text(text: str, limit: int = 4000) -> list[str]:
    """Pull affiliations from labeled fields and legal-entity patterns."""
    seen: set[str] = set()
    orgs: list[str] = []
    sample = (text or "")[:limit]

    def add(name: str) -> None:
        cleaned = _normalize_org_name(name)
        if not looks_like_organization_name(cleaned):
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        orgs.append(cleaned)

    for pattern in (
        r"(?:Организация|Organization|Affiliation|Место работы|Учреждение)\s*:?\s*([^\n]+)",
        r"(ООО\s*«[^»]+»)",
        r"((?:ПАО|ГМК|АО)\s*«?[^»\n]{4,100}»?)",
        r"((?:Институт|Institute|University|Laboratory|Лаборатория)[^\n]{3,120})",
    ):
        for match in re.finditer(pattern, sample, re.IGNORECASE | re.UNICODE):
            add(match.group(1))

    for match in _OOO_ORG.finditer(sample):
        add(match.group(0))

    deduped: list[str] = []
    for org in sorted(orgs, key=len, reverse=True):
        lower = org.lower()
        if any(lower in existing.lower() and lower != existing.lower() for existing in deduped):
            continue
        deduped.append(org)

    return deduped[:5]


def merge_unique_names(existing: list[str], found: list[str]) -> list[str]:
    seen = {n.strip().lower() for n in existing if n}
    out = list(existing)
    for name in found:
        key = name.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(name.strip())
    return out
