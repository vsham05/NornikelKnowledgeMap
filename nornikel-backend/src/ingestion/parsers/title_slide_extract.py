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
# Cyrillic: Д. В. Ляпинов, Ляпинов Дмитрий Васильевич, Иванов И. О.
_CYRILLIC_PERSON = re.compile(
    r"^(?:"
    r"[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){1,3}"
    r"|[А-ЯЁ]\.\s*[А-ЯЁ]\.\s*[А-ЯЁ][а-яё\-]+"
    r"|[А-ЯЁ][а-яё\-]+\s+[А-ЯЁ]\.\s*(?:[А-ЯЁ]\.\s*)?"
    r")$",
    re.UNICODE,
)

_ROLE_WORDS = (
    "researcher", "scientist", "engineer", "manager", "director", "specialist",
    "consultant", "professor", "associate", "assistant", "coordinator",
    "исследователь", "инженер", "менеджер", "директор", "специалист",
    "консультант", "профессор", "ассистент", "руководитель", "эксперт",
    "senior", "junior", "lead", "head", "chief", "principal",
)

_PERSON_DELIMITERS = re.compile(r"[;,/]|(?:\s+and\s+)|(?:\s+и\s+)|\s{2,}", re.IGNORECASE)

# Numbered roster lines: "1. Ivanov Ivan Ivanovich – senior researcher"
_EXPERT_LIST_ITEM = re.compile(
    r"(?:\d+\.\s*)?"
    r"("
    r"[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){1,3}"
    r"|[A-Z][a-zA-Z\-']+(?:\s+[A-Z]\.){0,2}\s+[A-Z][a-zA-Z\-']+"
    r")\s*[–\-—]",
    re.UNICODE,
)

# Require an explicit roster heading — not bare "expert" inside body text ("expertise", etc.)
_EXPERT_SECTION_HEADING = re.compile(
    r"(?:^|\n)\s*(?:"
    r"Experts?(?:\s+of\s+the\s+project)?"
    r"|Эксперты?(?:\s+проекта)?"
    r"|Список\s+экспертов"
    r"|Project\s+team"
    r"|Team\s+members?"
    r"|Команда(?:\s+проекта)?"
    r"|Участники(?:\s+проекта)?"
    r")\s*[:：]?\s*(?:\n|$)",
    re.IGNORECASE | re.UNICODE,
)

# Numbered roster without role dash: "1. Ivanov Ivan Ivanovich"
_NUMBERED_PERSON_LINE = re.compile(
    r"(?m)^\s*\d+\.\s*"
    r"("
    r"[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){1,3}"
    r"|[A-Z][a-zA-Z\-']+(?:\s+[A-Z]\.){0,2}\s+[A-Z][a-zA-Z\-']+"
    r")\s*$",
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


from ingestion.nlp.extraction_validate import contains_domain_entity_term, looks_like_section_heading


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


def looks_like_job_title(name: str) -> bool:
    """Reject role labels mis-tagged as person names."""
    lower = (name or "").lower()
    tokens = re.sub(r"[^\w\s]", " ", lower).split()
    if not tokens:
        return False
    role_hits = sum(1 for t in tokens if t in _ROLE_WORDS)
    return role_hits >= 1 and role_hits >= len(tokens) - 1


def split_person_name_line(line: str) -> list[str]:
    """Split author metadata lines into individual name candidates."""
    out: list[str] = []
    for part in _PERSON_DELIMITERS.split(line or ""):
        cleaned = _clean(part)
        if cleaned:
            out.append(cleaned)
    return out


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
    if contains_domain_entity_term(cleaned):
        return False
    if looks_like_job_title(cleaned):
        return False
    return bool(_LATIN_PERSON.match(cleaned) or _CYRILLIC_PERSON.match(cleaned))


_AUTHOR_INITIALS_LATIN = re.compile(
    r"^[A-Z]\.\s*(?:[A-Z]\.\s*)?[A-Z][a-zA-Z\-']+(?:\s+[A-Z][a-zA-Z\-']+)?$"
)
_LAST_COMMA_FIRST = re.compile(
    r"^[A-Z][a-zA-Z\-']+,\s+[A-Z][a-zA-Z\-'.]+(?:\s+[A-Z][a-zA-Z\-'.]+)?$"
)
_PAGE_HEADER_SKIP = re.compile(
    r"^(?:abstract|introduction|references|figure|table|page\s+\d+|страница\s+\d+|\d+\s*$|"
    r"contents|appendix|overview|summary|discussion|conclusion|acknowledgement)",
    re.IGNORECASE,
)
_AUTHOR_LINE_HINT = re.compile(
    r"\b(?:and|&|и)\b|,"
)


def normalize_person_name(name: str) -> str:
    """Normalize 'Last, First M.' → 'First M. Last' for downstream matching."""
    cleaned = _clean(name)
    if _LAST_COMMA_FIRST.match(cleaned):
        last, rest = cleaned.split(",", 1)
        parts = rest.strip().split()
        if parts:
            return _clean(f"{' '.join(parts)} {last.strip()}")
    return cleaned


def looks_like_author_name(name: str) -> bool:
    """Person name incl. academic initials (D. V. Surname) for author/expert lists."""
    cleaned = normalize_person_name(name)
    if looks_like_section_heading(cleaned):
        return False
    if looks_like_person_name(cleaned):
        return True
    if not cleaned or len(cleaned) < 4 or len(cleaned) > 80:
        return False
    if _has_non_name_noise(cleaned):
        return False
    if _contains_marker(cleaned, _GENERAL_ORG_HINTS):
        return False
    if _ORG_LINE.search(cleaned):
        return False
    if looks_like_job_title(cleaned):
        return False
    return bool(_AUTHOR_INITIALS_LATIN.match(cleaned) or _CYRILLIC_PERSON.match(cleaned))


def looks_like_affiliation_name(name: str) -> bool:
    """Institute / university labels mis-tagged as people."""
    cleaned = _clean(name)
    if not cleaned:
        return False
    if looks_like_organization_name(cleaned):
        return True
    lower = cleaned.lower()
    return any(
        hint in lower
        for hint in (
            "institute", "university", "laboratory", "department",
            "институт", "университет", "лаборатор",
        )
    )


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
    return False


def _normalize_org_name(name: str) -> str:
    cleaned = _clean(name)
    match = _OOO_ORG.search(cleaned)
    if match:
        return _clean(match.group(0))
    return cleaned


def extract_listed_experts_from_text(text: str, limit: int = 200_000) -> list[str]:
    """Parse numbered expert rosters after an Experts / Эксперты heading."""
    sample = (text or "")[:limit]
    heading = _EXPERT_SECTION_HEADING.search(sample)
    if not heading:
        return []

    window = sample[heading.end() : heading.end() + 8_000]
    seen: set[str] = set()
    experts: list[str] = []

    def add(name: str) -> None:
        cleaned = normalize_person_name(name)
        if not looks_like_author_name(cleaned):
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        experts.append(cleaned)

    for match in _EXPERT_LIST_ITEM.finditer(window):
        add(match.group(1))

    for match in _NUMBERED_PERSON_LINE.finditer(window):
        add(match.group(1))

    return experts[:80]


def extract_authors_from_page_header(text: str, *, header_chars: int = 1_400) -> list[str]:
    """Pull author names from the top of a proceedings / paper page."""
    sample = (text or "")[:header_chars]
    if not sample.strip():
        return []

    seen: set[str] = set()
    authors: list[str] = []

    def add(name: str) -> None:
        cleaned = normalize_person_name(name)
        if not looks_like_author_name(cleaned):
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        authors.append(cleaned)

    for pattern in (
        r"(?:Authors?|Author|By|Докладчик(?:и)?|Presenter(?:s)?)\s*:?\s*([^\n]+)",
        r"(?:Авторы?)\s*:?\s*([^\n]+)",
    ):
        for match in re.finditer(pattern, sample, re.IGNORECASE | re.UNICODE):
            for part in split_person_name_line(match.group(1)):
                add(part)

    lines = [ln.strip() for ln in sample.splitlines() if ln.strip()]
    for i, line in enumerate(lines[:8]):
        if len(line) > 100 or _PAGE_HEADER_SKIP.match(line):
            continue
        if looks_like_section_heading(line):
            continue
        if line.isupper() and len(line.split()) >= 3:
            continue
        if re.search(r"\d{4}", line) and len(line) < 50:
            continue
        # Single author line followed by affiliation (common in proceedings)
        if 2 <= len(line.split()) <= 4 and looks_like_author_name(line):
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            if looks_like_affiliation_name(next_line) or looks_like_organization_name(next_line):
                add(line)
                continue
        # Author lists with commas / "and"
        if not _AUTHOR_LINE_HINT.search(line):
            continue
        for part in split_person_name_line(line):
            add(part)

    return authors[:6]


def extract_authors_from_document_chunks(
    chunks: list,
    *,
    header_chars: int = 1_400,
    max_authors: int = 80,
    max_chunks: int | None = None,
) -> list[str]:
    """Harvest paper authors from per-page headers (conference proceedings)."""
    seen: set[str] = set()
    authors: list[str] = []
    scan = chunks[:max_chunks] if max_chunks is not None else chunks

    for chunk in scan:
        text = getattr(chunk, "text", None) or (chunk if isinstance(chunk, str) else "")
        for name in extract_authors_from_page_header(str(text), header_chars=header_chars):
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            authors.append(name)
            if max_authors > 0 and len(authors) >= max_authors:
                return authors

    return authors


def extract_authors_from_text(text: str, limit: int = 4000) -> list[str]:
    """Pull names from labeled author fields, bare metadata, and expert rosters."""
    seen: set[str] = set()
    authors: list[str] = []
    sample = (text or "")[:limit]

    def add(name: str) -> None:
        cleaned = normalize_person_name(name)
        if not looks_like_author_name(cleaned):
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
            for part in split_person_name_line(match.group(1)):
                add(part)

    # Bare metadata author line without "Authors:" label
    if not authors and sample.strip() and len(sample) < 400:
        for part in split_person_name_line(sample):
            add(part)

    for name in extract_listed_experts_from_text(text, limit):
        add(name)

    return authors[:80]


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
