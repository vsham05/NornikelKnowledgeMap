"""Capped, sampled image extraction from PDFs."""

from __future__ import annotations

import hashlib

MAX_IMAGES_PER_DOCUMENT = 36
MAX_IMAGES_PER_PAGE = 2
MAX_IMAGE_SCAN_PAGES = 48
MIN_IMAGE_BYTES = 2_400


def image_page_indices(page_count: int) -> list[int]:
    """Pages to scan for figures — spread across the document, capped for speed."""
    if page_count <= 0:
        return []
    if page_count <= MAX_IMAGE_SCAN_PAGES:
        return list(range(page_count))
    step = max(1, page_count // MAX_IMAGE_SCAN_PAGES)
    return list(range(0, page_count, step))[:MAX_IMAGE_SCAN_PAGES]


def image_content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
