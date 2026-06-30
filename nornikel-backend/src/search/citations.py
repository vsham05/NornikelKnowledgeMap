"""Grounded answer: extract cited facts from chunks, then format deterministically."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from search.query_processing import (
    TEMPORAL_QUERY_RE,
    YEAR_RE,
    is_name_question as _is_name_question_qp,
    significant_terms,
)

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[(\d+)\]")
_PERSON_TWO_RE = re.compile(
    r"\b([A-Z][a-z\u0400-\u04FF]{2,}\s+[A-Z][a-z\u0400-\u04FF]{2,})\b"
)
_PERSON_THREE_RE = re.compile(
    r"\b([A-Z][a-z\u0400-\u04FF]{2,}\s+"
    r"[A-Z][a-z\u0400-\u04FF]{3,}(?:ovich|evich|ovna|evna|ич|на)\s+"
    r"[A-Z][a-z\u0400-\u04FF]{2,})\b",
    re.IGNORECASE,
)

_LAST_NAME_STOP = frozenset({
    "Tree", "House", "World", "Council", "Centre", "Center", "Regions",
    "Landscape", "Grove", "Steel", "Life", "Love", "Park", "Affairs",
    "Society", "Foundation", "Institute", "Holding", "Office", "Federation",
    "Poetics", "Security", "Russian", "Creative", "Trade", "Film", "Federal",
    "Ethnic", "Presidential", "Foreign", "Media", "Geographical", "Regional",
    "Internet", "Development", "Down", "Upside", "Young", "Silk", "Mamayev",
    "Kurgan", "Volgograd", "Moscow", "National", "Peoples", "Countries",
    "Frontline", "Forest", "Ensemble", "Academy", "Presidium", "Board",
    "Session", "Festival", "Exposition", "Designers", "Capsule",
    "Mos", "Kino", "Film",
    "Economics", "Economic", "Industrial", "Organization", "Machine",
    "Learning", "Letters", "Theory", "Studies", "Modelling", "Modeling",
    "Psychology", "Software", "Product", "Transparency", "Capacities",
    "Fluctuation", "Detection", "References", "Statistical", "Political",
    "Demand", "Homogenous", "Applied", "Market", "Production",
})

_ROLE_HINTS = (
    "moderator", "soloist", "artist", "presenter", "journalist", "academician",
    "member", "organiser", "organizer", "author", "poet", "performed", "said",
    "noted", "people's artist", "people artist",
)


def is_name_question(question: str) -> bool:
    return _is_name_question_qp(question)


def _question_terms(question: str) -> list[str]:
    return significant_terms(question, min_length=4)


def facts_address_question(question: str, facts: list[dict[str, Any]]) -> bool:
    """Return False when extracted facts clearly fail to answer the question."""
    if not facts:
        return False

    claims = " ".join(fact["claim"] for fact in facts)
    claims_lower = claims.lower()
    question_lower = question.lower()

    if TEMPORAL_QUERY_RE.search(question) and not YEAR_RE.search(claims):
        return False

    if any(term in question_lower for term in ("harm", "damage", "overcharge")):
        if not any(term in claims_lower for term in ("harm", "damage", "overcharge", "%")):
            return False

    terms = _question_terms(question)
    if terms and not any(term in claims_lower for term in terms):
        return False

    return True


def extract_json_facts(text: str) -> list[dict[str, Any]]:
    """Parse {"facts": [...]} from LLM output."""
    if not text or not text.strip():
        return []

    content = text.strip()
    candidates: list[str] = [content]

    for pattern in (r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"):
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            candidates.insert(0, match.group(1).strip())

    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        candidates.append(content[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("facts"), list):
            return _normalize_facts(parsed["facts"])
        if isinstance(parsed, list):
            return _normalize_facts(parsed)

    logger.warning("Could not parse grounded facts JSON from LLM")
    return []


def _normalize_facts(raw_facts: list) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for item in raw_facts:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or item.get("text") or "").strip()
        if not claim:
            continue
        sources = item.get("sources") or item.get("source") or []
        if isinstance(sources, int):
            sources = [sources]
        if not isinstance(sources, list):
            continue
        clean_sources = sorted({
            int(s) for s in sources
            if isinstance(s, (int, float, str)) and str(s).isdigit()
        })
        if not clean_sources:
            continue
        facts.append({"claim": claim, "sources": clean_sources})
    return facts


def _is_likely_person(name: str) -> bool:
    parts = name.split()
    if len(parts) not in (2, 3):
        return False
    for part in parts:
        if len(part) < 3 or not part.replace("-", "").isalpha():
            return False
        if part in _LAST_NAME_STOP:
            return False
    if any(word in name for word in ("Birch", "Russia", "Russian")):
        return False
    if name.endswith("ovich") or name.endswith("evich"):
        return False
    return True


def _normalize_text(text: str) -> str:
    text = re.sub(r"[\uFFFD\u00AD\xa0]", " ", text)
    text = re.sub(r"(said|noted|shared|stated)([A-Z\u0400-\u04FF])", r"\1 \2", text, flags=re.I)
    text = re.sub(r"([a-z\u0400-\u04FF])(said|noted|shared|stated)\b", r"\1 \2", text, flags=re.I)
    text = re.sub(r"([a-z\u0400-\u04FF])(noted|said)\b", r"\1 \2", text, flags=re.I)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return re.sub(r"\s+", " ", text)


def _has_person_context(text: str, name: str) -> bool:
    if _role_for_name(text, name):
        return True
    escaped = re.escape(name)
    if re.search(rf"\b(?:said|stated)\s+{escaped}\b", text, re.I):
        return True
    if re.search(rf"\b{escaped}\s*,", text):
        return True
    if re.search(rf"\b{escaped}\s*\(", text):
        return True
    return False


def _iter_person_names(text: str):
    seen: set[str] = set()
    for pattern in (_PERSON_THREE_RE, _PERSON_TWO_RE):
        for match in pattern.finditer(text):
            name = re.sub(r"\s+", " ", match.group(1).strip())
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            yield name


def _role_for_name(text: str, name: str) -> str | None:
    idx = text.lower().find(name.lower())
    if idx == -1:
        return None
    window = text[max(0, idx - 80) : idx + len(name) + 120].lower()
    for hint in _ROLE_HINTS:
        if hint in window:
            return hint
    return None


def extract_person_facts_from_chunks(chunks: list[dict]) -> list[dict[str, Any]]:
    """Deterministic person extraction for name/who questions (no LLM hallucination)."""
    people: dict[str, dict[str, Any]] = {}

    for index, chunk in enumerate(chunks, start=1):
        text = _normalize_text(chunk.get("text") or "")
        for name in _iter_person_names(text):
            if not _is_likely_person(name):
                continue
            if not _has_person_context(text, name):
                continue
            if name not in people:
                role = _role_for_name(text, name)
                claim = f"{name}" + (f" — {role}" if role else "")
                people[name] = {"claim": claim, "sources": [index]}
            elif index not in people[name]["sources"]:
                people[name]["sources"].append(index)

    for entry in people.values():
        entry["sources"] = sorted(entry["sources"])

    return sorted(people.values(), key=lambda item: item["claim"])


def validate_facts(facts: list[dict[str, Any]], max_source: int) -> list[dict[str, Any]]:
    """Drop facts that cite non-existent excerpt numbers."""
    valid = []
    for fact in facts:
        sources = [s for s in fact["sources"] if 1 <= s <= max_source]
        if not sources:
            continue
        valid.append({"claim": fact["claim"], "sources": sources})
    return valid


def format_grounded_answer(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return (
            "The indexed excerpts do not contain enough information to answer this question."
        )

    lines: list[str] = []
    for index, fact in enumerate(facts, start=1):
        cites = "".join(f"[{s}]" for s in fact["sources"])
        lines.append(f"{index}. {fact['claim']} {cites}")
    return "\n".join(lines)


def citation_coverage(answer: str, max_source: int) -> float:
    """Fraction of answer sentences that include valid citations."""
    if not answer.strip() or max_source <= 0:
        return 0.0

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer) if s.strip()]
    if not sentences:
        return 0.0

    cited = 0
    for sentence in sentences:
        nums = [int(n) for n in _CITATION_RE.findall(sentence)]
        if nums and all(1 <= n <= max_source for n in nums):
            cited += 1
    return cited / len(sentences)


FACT_EXTRACTION_SYSTEM = """You extract facts ONLY from the numbered document excerpts provided.
Reply with JSON only: {"facts": [{"claim": "...", "sources": [1]}]}

Rules:
- Answer the user's specific question — not a tangential point from the excerpts.
- Each claim must directly help answer the question and be supported by cited excerpt number(s).
- Use exact years, numbers, names, and wording from the excerpts — do not invent or guess.
- For year/when questions: extract claims that name specific years or date ranges from the excerpts.
- For harm/damage questions: extract claims about economic harm, overcharges, or damage estimates.
- For people/name questions: one fact per person whose full name appears.
- One fact per key point. Keep claims short (one sentence).
- If excerpts cannot answer the question, return {"facts": []}."""

ANSWER_SYSTEM = """You are a precise research assistant answering from numbered document excerpts only.

Rules:
1. Read the QUESTION carefully — answer exactly what was asked (year, name, number, comparison, etc.).
2. Use ONLY facts stated in the excerpts. Never invent data.
3. Cite every factual claim with excerpt numbers like [1], [2].
4. Prefer specific numbers, years, and quotes from the excerpts over vague summaries.
5. If multiple excerpts conflict, mention the range and cite both.
6. If excerpts lack the exact answer, give the closest supported facts (e.g. a date range or estimate) and cite them. Only say "not enough information" if even partial facts are absent.
7. Keep answers concise: 1-4 sentences for simple questions; bullet list only when listing multiple items."""
