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
    r"сколько|процент|процентов|число|количество|сумм|средн|медиан)\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

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
    harm_related: bool
    content_terms: tuple[str, ...]


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


def extract_search_terms(query: str, *, limit: int = 12) -> list[str]:
    """Terms for Neo4j CONTAINS / sparse keyword retrieval."""
    terms = significant_terms(query)
    if len(terms) >= 2:
        return terms[:limit]

    # Fallback: keep Cyrillic/Latin tokens even if short
    extra = [t for t in tokenize(query, min_length=2) if not is_stopword(t)]
    merged: list[str] = []
    seen: set[str] = set()
    for t in terms + extra:
        if t not in seen:
            seen.add(t)
            merged.append(t)
    if merged:
        return merged[:limit]

    q = query.lower().strip()
    return [q[:60]] if q else []


def is_name_question(query: str) -> bool:
    return bool(NAME_QUERY_RE.search(query))


def query_harm_related(query: str) -> bool:
    lower = query.lower()
    return any(term in lower for term in HARM_TERMS)


def analyze_intent(query: str) -> QueryIntent:
    terms = tuple(significant_terms(query))
    return QueryIntent(
        original=query.strip(),
        language=detect_language(query),
        is_name=bool(NAME_QUERY_RE.search(query)),
        is_temporal=bool(TEMPORAL_QUERY_RE.search(query)),
        is_quantitative=bool(QUANT_QUERY_RE.search(query)),
        harm_related=query_harm_related(query),
        content_terms=terms,
    )


def keyword_search_string(query: str, extra_keywords: list[str] | None = None) -> str:
    """Build a keyword-focused string for sparse retrieval."""
    parts = list(significant_terms(query))
    for kw in extra_keywords or []:
        for token in tokenize(kw, min_length=2):
            if not is_stopword(token) and token not in parts:
                parts.append(token)
    return " ".join(parts[:12]) if parts else query.strip()
