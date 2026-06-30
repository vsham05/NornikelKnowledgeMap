"""Centralized query tokenization and intent analysis (Snowball English stopwords)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Standard English stopwords (Snowball / search-engine style). No domain-specific hacks.
ENGLISH_STOPWORDS = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any",
    "are", "aren't", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "can't", "could", "couldn't", "did", "didn't",
    "do", "does", "doesn't", "doing", "don't", "down", "during", "each", "few", "for",
    "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having",
    "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself", "him",
    "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in",
    "into", "is", "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most",
    "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only",
    "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some",
    "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very",
    "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what",
    "what's", "when", "when's", "where", "where's", "which", "while", "who", "who's",
    "whom", "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd",
    "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves",
})

TOKEN_RE = re.compile(r"[a-zA-Z0-9\u0400-\u04FF]{3,}")
NAME_QUERY_RE = re.compile(r"\b(name|names|who|people|person|persons)\b", re.IGNORECASE)
TEMPORAL_QUERY_RE = re.compile(
    r"\b(year|years|when|date|period|duration|timeline|how\s+long)\b", re.IGNORECASE
)
QUANT_QUERY_RE = re.compile(
    r"\b(how\s+many|how\s+much|percent|percentage|number|count|total|average|median|rate)\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


@dataclass(frozen=True)
class QueryIntent:
    original: str
    is_name: bool
    is_temporal: bool
    is_quantitative: bool
    harm_related: bool
    content_terms: tuple[str, ...]


def tokenize(text: str, *, min_length: int = 3) -> list[str]:
    return [
        token
        for token in TOKEN_RE.findall(text.lower())
        if len(token) >= min_length
    ]


def significant_terms(query: str, *, min_length: int = 3) -> list[str]:
    """Content-bearing terms for lexical/BM25 scoring (stopwords removed)."""
    seen: set[str] = set()
    terms: list[str] = []
    for token in tokenize(query, min_length=min_length):
        if token in ENGLISH_STOPWORDS:
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
    if terms:
        return terms
    fallback = query.lower().strip()[:48]
    return [fallback] if fallback else []


def is_name_question(query: str) -> bool:
    return bool(NAME_QUERY_RE.search(query))


def analyze_intent(query: str) -> QueryIntent:
    lower = query.lower()
    terms = tuple(significant_terms(query))
    return QueryIntent(
        original=query.strip(),
        is_name=bool(NAME_QUERY_RE.search(query)),
        is_temporal=bool(TEMPORAL_QUERY_RE.search(query)),
        is_quantitative=bool(QUANT_QUERY_RE.search(query)),
        harm_related=any(w in lower for w in ("harm", "damage", "overcharge", "hurt", "loss")),
        content_terms=terms,
    )


def keyword_search_string(query: str, extra_keywords: list[str] | None = None) -> str:
    """Build a keyword-focused string for sparse retrieval."""
    parts = list(significant_terms(query))
    for kw in extra_keywords or []:
        for token in tokenize(kw, min_length=3):
            if token not in ENGLISH_STOPWORDS and token not in parts:
                parts.append(token)
    return " ".join(parts[:12]) if parts else query.strip()
