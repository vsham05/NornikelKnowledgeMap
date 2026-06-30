"""Document deduplication: canonical URLs + SHA-256 content fingerprints."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from domain.dto.document import DocumentDTO

TRACKING_QUERY_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid",
})

DedupAction = Literal["create", "replace", "skip"]


@dataclass
class DedupDecision:
    action: DedupAction
    existing_id: str | None
    message: str


@dataclass
class IngestResult:
    document: DocumentDTO | None
    action: DedupAction
    document_id: str
    message: str

    @property
    def skipped(self) -> bool:
        return self.action == "skip"


def canonicalize_url(url: str) -> str:
    """Normalize URLs so http://site/a and http://site/a/ map to the same source."""
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")

    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_PARAMS
    ]
    query_pairs.sort()

    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        "",
        urlencode(query_pairs),
        "",
    ))


def normalize_text_for_hash(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip().lower())
    return collapsed


def hash_document_text(document: DocumentDTO) -> str:
    """SHA-256 fingerprint of extracted document text (before chunking boundaries vary)."""
    parts = [
        normalize_text_for_hash(chunk.text)
        for chunk in document.chunks
        if chunk.text and chunk.text.strip()
    ]
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_file_bytes(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
