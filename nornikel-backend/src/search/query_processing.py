"""Query tokenization and intent analysis — English + Russian (Cyrillic)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Snowball-style English stopwords
ENGLISH_STOPWORDS = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any",
    "are", "aren't", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "can't", "could", "couldn't", "did", "didn't",
    "do", "does", "doesn't", "doing", "don't", "down", "during", "each", "few", "for",
    "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having",
    "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "if", "in",
    "into", "is", "isn't", "it", "its", "itself", "me", "more", "most", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "our", "ours",
    "ourselves", "out", "over", "own", "same", "she", "should", "so", "some", "such",
    "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "were", "what", "when", "where", "which", "while", "who", "whom",
    "why", "with", "would", "you", "your", "yours", "yourself",
})

# Common Russian function words (search engines / IR style)
RUSSIAN_STOPWORDS = frozenset({
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все",
    "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по",
    "только", "ее", "мне", "было", "вот", "от", "меня", "еще", "ещё", "нет", "о", "об",
    "из", "ему", "теперь", "когда", "даже", "ну", "ли", "если", "уже", "или", "ни",
    "быть", "был", "него", "до", "вас", "опять", "уж", "вам", "ведь", "там", "потом",
    "себя", "ничего", "ей", "может", "они", "тут", "где", "есть", "надо", "ней", "для",
    "мы", "тебя", "им", "их", "чем", "при", "без", "раз", "тоже", "также", "это",
    "эта", "эти", "этот", "этого", "этом", "того", "том", "тем", "чтобы", "который",
    "которая", "которые", "которых", "которой", "были", "будет", "будут", "была",
    "можно", "очень", "более", "менее", "после", "перед", "между", "через", "под",
    "над", "при", "про", "где", "куда", "откуда", "здесь", "там", "тут", "кто", "что",
    "какой", "какая", "какие", "какое", "сколько", "почему", "зачем", "как", "ли",
})

STOPWORDS = ENGLISH_STOPWORDS | RUSSIAN_STOPWORDS

TOKEN_RE = re.compile(r"[a-zA-Z\u0400-\u04FF0-9]{2,}")
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

NAME_QUERY_RE = re.compile(
    r"\b(name|names|who|people|person|persons|"
    r"имя|имена|имен|фамили|фамилия|фамилии|кто|люди|человек|персон|упомянут|упомянута|упомянуты)\b",
    re.IGNORECASE,
)
TEMPORAL_QUERY_RE = re.compile(
    r"\b(year|years|when|date|period|duration|timeline|how\s+long|"
    r"год|года|году|годы|лет|когда|дата|период|срок|длительность)\b",
    re.IGNORECASE,
)
QUANT_QUERY_RE = re.compile(
    r"\b(how\s+many|how\s+much|percent|percentage|number|count|total|average|median|rate|"
    r"сколько|процент|процентов|число|количество|сумм|средн|медиан|показател)\b",
    re.IGNORECASE,
)
TECHNICAL_QUANT_RE = re.compile(
    r"(?:"
    r"мг/л|mg/l|мг/дм|mg/dm|ppm|г/л|g/l|"
    r"≤|≥|<|>|"
    r"\bph\b|ph\s*range|concentration|retention\s+time|"
    r"de-?zn|zinc\s+removal|coral\s+bay|"
    r"оптимальн|скорост\w*\s+поток|технико-эконом|"
    r"распределени|содержани|извлечен|концентрац|"
    r"сухой\s+остаток|обессолив|католит|электроэкстракц|"
    r"штейн|шлак|мпг|pgm|precious|"
    r"flow\s+rate|desalination|electrowinning|catholyte"
    r")",
    re.IGNORECASE,
)
LIST_EXPERIMENTS_RE = re.compile(
    r"(?:"
    r"покажите\s+все|все\s+эксперимент|все\s+публикац|"
    r"list\s+all|show\s+all\s+experiment"
    r")",
    re.IGNORECASE,
)
NUMERIC_ANCHOR_RE = re.compile(
    r"[\d]+(?:[.,]\d+)?(?:\s*[-–—]\s*[\d]+(?:[.,]\d+)?)?"
    r"(?:\s*(?:мг/л|mg/l|мг/дм³?|mg/dm³?|%|°c|℃|м/ч|м³/ч|m3/h|мм/с))?",
    re.IGNORECASE,
)
CHEM_SYMBOL_RE = re.compile(
    r"\b(?:Ca|Mg|Na|Ni|Cu|Au|Ag|Fe|Al|Zn|Co|SO4|Cl|H2SO4|pH|"
    r"сульфат|хлорид|никел|мед|золот|серебр)\w*\b",
    re.IGNORECASE,
)
PROPER_NOUN_PHRASE_RE = re.compile(
    r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b"
)
CYRILLIC_PROPER_NOUN_RE = re.compile(
    r"(?<![а-яёА-ЯЁ])([А-ЯЁ][а-яё]{2,}(?:\s+[А-ЯЁ][а-яё]{2,}){0,3})(?![а-яёА-ЯЁ])"
)
HYPHEN_TERM_RE = re.compile(r"\b[A-Za-z]+(?:-[A-Za-z0-9]+)+\b")
TECH_SHORT_TERMS = frozenset({
    "ph", "zn", "ni", "cu", "au", "ag", "fe", "al", "co", "mg", "na", "ca",
    "hpal", "hcl", "h2so4", "ppm",
})
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
PAGE_REF_RE = re.compile(
    r"(?:\bpage|\bpages|\bp\.|\bpp\.|\bстр\.?|\bстраниц(?:а|е|ы)?)\s*[#:]?\s*(\d{1,4})\b",
    re.IGNORECASE,
)
SPELLING_VARIANTS: dict[str, str] = {
    "sulphuric": "sulfuric",
    "sulphur": "sulfur",
    "sulphate": "sulfate",
    "aluminium": "aluminum",
    "artefact": "artifact",
}

HARM_TERMS = (
    "harm", "damage", "overcharge", "hurt", "loss",
    "вред", "ущерб", "убыт", "переплат", "затрат", "потер", "убытк",
)


@dataclass(frozen=True)
class QueryIntent:
    original: str
    language: str  # "ru", "en", or "mixed"
    is_name: bool
    is_temporal: bool
    is_quantitative: bool
    is_technical: bool
    wants_experiment_list: bool
    harm_related: bool
    content_terms: tuple[str, ...]
    numeric_anchors: tuple[str, ...]
    page_refs: tuple[int, ...]


def detect_language(text: str) -> str:
    """Rough language tag for answer routing."""
    if not text.strip():
        return "en"
    cyr = len(CYRILLIC_RE.findall(text))
    lat = len(re.findall(r"[a-zA-Z]", text))
    if cyr > lat and cyr >= 3:
        return "ru"
    if cyr > 0 and lat > 0:
        return "mixed"
    return "en"


def resolve_answer_language(question: str) -> str:
    """Answer language must match the question: 'en' or 'ru' only."""
    lang = detect_language(question)
    if lang == "ru":
        return "ru"
    if lang == "mixed":
        cyr = len(CYRILLIC_RE.findall(question))
        lat = len(re.findall(r"[a-zA-Z]", question))
        return "ru" if cyr > lat else "en"
    return "en"


def answer_language_instruction(lang: str) -> str:
    """Hard constraint prepended to LLM prompts."""
    if lang == "ru":
        return (
            "ОБЯЗАТЕЛЬНО: весь ответ только на русском языке, "
            "даже если фрагменты на английском. Не используй английский в ответе."
        )
    return (
        "MANDATORY: Write your ENTIRE answer in English only, "
        "even if the excerpts are in Russian. Do not use Russian in the answer."
    )


def is_stopword(token: str) -> bool:
    return token.lower() in STOPWORDS


def tokenize(text: str, *, min_length: int = 2) -> list[str]:
    return [
        token
        for token in TOKEN_RE.findall(text.lower())
        if len(token) >= min_length
    ]


def significant_terms(query: str, *, min_length: int = 2) -> list[str]:
    """Content-bearing terms for lexical / keyword search (stopwords removed)."""
    lang = detect_language(query)
    min_len = 2 if lang in ("ru", "mixed") else 3

    seen: set[str] = set()
    terms: list[str] = []
    for token in tokenize(query, min_length=min_len):
        if len(token) < max(min_length, min_len):
            continue
        if is_stopword(token):
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)

    if terms:
        return terms

    fallback = query.lower().strip()[:48]
    return [fallback] if fallback else []


def extract_search_terms(query: str, *, limit: int = 16) -> list[str]:
    """Terms for Neo4j CONTAINS / sparse keyword retrieval."""
    terms = significant_terms(query, min_length=2)
    seen = set(t.lower() for t in terms)

    def push(value: str) -> None:
        v = value.strip().lower()
        if not v or v in seen:
            return
        seen.add(v)
        terms.append(v)

    for match in PROPER_NOUN_PHRASE_RE.finditer(query):
        push(match.group(0))
        for part in match.group(0).split():
            if len(part) >= 3:
                push(part)

    for match in CYRILLIC_PROPER_NOUN_RE.finditer(query):
        push(match.group(1))
        for part in match.group(1).split():
            if len(part) >= 3:
                push(part)

    for match in HYPHEN_TERM_RE.finditer(query):
        push(match.group(0))
        for part in re.split(r"[-/]", match.group(0)):
            if len(part) >= 2:
                push(part)

    for match in CHEM_SYMBOL_RE.finditer(query):
        push(match.group(0))

    if re.search(r"\bph\b", query, re.IGNORECASE):
        push("ph")

    for token in tokenize(query, min_length=2):
        if token in TECH_SHORT_TERMS:
            push(token)

    def finalize(raw_terms: list[str]) -> list[str]:
        expanded = expand_spelling_variants(raw_terms)
        expanded = expand_russian_morphology(expanded)
        expanded = expand_glossary_bilingual(query, expanded)
        deduped: list[str] = []
        seen3: set[str] = set()
        for t in expanded:
            key = t.lower()
            if key not in seen3:
                seen3.add(key)
                deduped.append(t)
        return deduped[:limit]

    if len(terms) >= 2:
        return finalize(terms)

    extra = [t for t in tokenize(query, min_length=2) if not is_stopword(t)]
    merged: list[str] = []
    seen2: set[str] = set()
    for t in terms + extra:
        key = t.lower()
        if key not in seen2:
            seen2.add(key)
            merged.append(t)
    if merged:
        return finalize(merged)

    q = query.lower().strip()
    return finalize([q[:60]]) if q else []


def is_name_question(query: str) -> bool:
    return bool(NAME_QUERY_RE.search(query))


def query_harm_related(query: str) -> bool:
    lower = query.lower()
    return any(term in lower for term in HARM_TERMS)


def extract_page_refs(query: str) -> list[int]:
    """Page numbers explicitly cited in the question (e.g. 'Page 228')."""
    pages: list[int] = []
    seen: set[int] = set()
    for match in PAGE_REF_RE.finditer(query):
        try:
            page = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if page <= 0 or page in seen:
            continue
        seen.add(page)
        pages.append(page)
    return pages[:8]


def expand_spelling_variants(terms: list[str]) -> list[str]:
    """Add US/UK spelling variants so keyword search hits both forms."""
    out = list(terms)
    seen = {t.lower() for t in terms}
    for term in terms:
        alt = SPELLING_VARIANTS.get(term.lower())
        if alt and alt not in seen:
            seen.add(alt)
            out.append(alt)
    return out


def _russian_prefix_stems(token: str) -> list[str]:
    """Prefix stems catch inflected forms (обогащение/обогащения/обогащению)."""
    if not CYRILLIC_RE.search(token):
        return []
    t = token.lower().replace("ё", "е")
    if len(t) < 5:
        return []
    stems: list[str] = []
    for n in (4, 5, 6):
        if len(t) >= n + 2:
            stem = t[:n]
            if stem not in stems:
                stems.append(stem)
    return stems


def expand_russian_morphology(terms: list[str]) -> list[str]:
    """Add Cyrillic prefix stems for Neo4j CONTAINS keyword recall."""
    out = list(terms)
    seen = {t.lower() for t in terms}
    for term in terms:
        for stem in _russian_prefix_stems(term):
            if stem not in seen:
                seen.add(stem)
                out.append(stem)
    return out


def expand_glossary_bilingual(query: str, terms: list[str]) -> list[str]:
    """Add RU+EN glossary aliases when the query mentions a known domain term."""
    from domain.entity_glossary import _ENTRIES, find_glossary_terms_in_text

    out = list(terms)
    seen = {t.lower() for t in terms}
    for _key, ru, en in find_glossary_terms_in_text(query, frozenset(_ENTRIES.keys())):
        for variant in (ru, en):
            for piece in re.split(r"[\s/\-]+", variant):
                v = piece.strip().lower()
                if len(v) >= 2 and v not in seen:
                    seen.add(v)
                    out.append(v)
            phrase = variant.strip().lower()
            if len(phrase) >= 4 and phrase not in seen:
                seen.add(phrase)
                out.append(phrase)
    return out


def term_matches_text(term: str, text_lower: str) -> bool:
    """Lexical hit: exact token or Russian prefix stem."""
    if not term or not text_lower:
        return False
    if term in text_lower:
        return True
    for stem in _russian_prefix_stems(term):
        if stem in text_lower:
            return True
    return False


def extract_numeric_anchors(query: str) -> list[str]:
    """Numbers, ranges, and units from the question for retrieval anchoring."""
    anchors: list[str] = []
    seen: set[str] = set()
    for match in NUMERIC_ANCHOR_RE.finditer(query):
        token = match.group(0).strip()
        if token and token not in seen:
            seen.add(token)
            anchors.append(token)
    for match in CHEM_SYMBOL_RE.finditer(query):
        token = match.group(0).strip()
        key = token.lower()
        if key not in seen:
            seen.add(key)
            anchors.append(token)
    return anchors[:16]


def is_technical_quantitative_question(query: str) -> bool:
    if not query.strip():
        return False
    if TECHNICAL_QUANT_RE.search(query):
        return True
    if QUANT_QUERY_RE.search(query) and re.search(r"\d", query):
        return True
    if LIST_EXPERIMENTS_RE.search(query):
        return True
    anchors = extract_numeric_anchors(query)
    return len(anchors) >= 2 and len(significant_terms(query)) >= 5


def requests_experiment_list(query: str) -> bool:
    return bool(LIST_EXPERIMENTS_RE.search(query))


def analyze_intent(query: str) -> QueryIntent:
    terms = tuple(extract_search_terms(query, limit=16))
    anchors = tuple(extract_numeric_anchors(query))
    pages = tuple(extract_page_refs(query))
    technical = is_technical_quantitative_question(query)
    return QueryIntent(
        original=query.strip(),
        language=detect_language(query),
        is_name=bool(NAME_QUERY_RE.search(query)),
        is_temporal=bool(TEMPORAL_QUERY_RE.search(query)),
        is_quantitative=bool(QUANT_QUERY_RE.search(query)) or technical or bool(pages),
        is_technical=technical,
        wants_experiment_list=requests_experiment_list(query),
        harm_related=query_harm_related(query),
        content_terms=terms,
        numeric_anchors=anchors,
        page_refs=pages,
    )


def keyword_search_string(query: str, extra_keywords: list[str] | None = None) -> str:
    """Build a keyword-focused string for sparse retrieval."""
    parts = list(extract_search_terms(query, limit=14))
    for kw in extra_keywords or []:
        for token in tokenize(kw, min_length=2):
            if not is_stopword(token) and token not in parts:
                parts.append(token)
    return " ".join(parts[:12]) if parts else query.strip()
