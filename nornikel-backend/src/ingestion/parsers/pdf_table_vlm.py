"""Render PDF regions and merge VLM-extracted table markdown into page chunks."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz

from ingestion.parsers.pdf_table_extract import (
    chunk_likely_missing_table_data,
    extract_tables_from_page,
    find_orphan_table_captions,
)

logger = logging.getLogger(__name__)

TABLE_BLOCK_RE = re.compile(r"\[TABLE\][\s\S]*?\[/TABLE\]", re.IGNORECASE)
MAX_VLM_TABLES_PER_DOCUMENT = 24
RENDER_DPI = 200


def render_page_region(page, region: tuple[float, float, float, float], *, dpi: int = RENDER_DPI) -> bytes:
    """Rasterize a PDF rectangle to PNG bytes for vision models."""
    x0, y0, x1, y1 = region
    clip = fitz.Rect(x0, y0, x1, y1)
    if clip.is_empty or clip.height < 8 or clip.width < 8:
        raise ValueError("Table render region too small")

    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    return pix.tobytes("png")


def render_region_from_file(
    file_path: Path,
    page_number: int,
    region: tuple[float, float, float, float],
    *,
    dpi: int = RENDER_DPI,
) -> bytes:
    doc = fitz.open(file_path)
    try:
        page = doc[page_number - 1]
        return render_page_region(page, region, dpi=dpi)
    finally:
        doc.close()


def normalize_vlm_table_markdown(raw: str, title: str) -> str:
    """Strip fences and keep a clean pipe-table body."""
    text = (raw or "").strip()
    if not text:
        return ""

    if "[TABLE]" in text.upper():
        match = TABLE_BLOCK_RE.search(text)
        if match:
            inner = match.group(0)
            inner = re.sub(r"^\[TABLE\]\s*", "", inner, flags=re.IGNORECASE)
            inner = re.sub(r"\s*\[/TABLE\]$", "", inner, flags=re.IGNORECASE).strip()
            lines = inner.split("\n")
            if lines and lines[0].lower().startswith("table "):
                body = "\n".join(lines[1:]).strip()
            else:
                body = inner
            if body.startswith("|"):
                return body
            text = body

    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""

    if not lines[0].startswith("|"):
        pipe_start = next((i for i, ln in enumerate(lines) if ln.startswith("|")), None)
        if pipe_start is not None:
            lines = lines[pipe_start:]

    if not lines or not lines[0].startswith("|"):
        return ""

    return "\n".join(lines)


def merge_table_into_chunk(existing: str, title: str, markdown: str) -> str:
    """Append a structured table block to page text."""
    md = normalize_vlm_table_markdown(markdown, title)
    if not md:
        return existing

    title_line = title.strip()
    if title_line.lower() in md.lower()[:120]:
        block = f"\n\n[TABLE]\n{title_line}\n{md}\n[/TABLE]"
    else:
        block = f"\n\n[TABLE]\n{title_line}\n{md}\n[/TABLE]"

    base = (existing or "").rstrip()
    if title_line in base and f"[TABLE]\n{title_line}" in base:
        return base
    return base + block


def collect_vlm_table_jobs(
    file_path: Path,
    document,
    *,
    max_jobs: int = MAX_VLM_TABLES_PER_DOCUMENT,
) -> list[dict]:
    """
    Pages/captions needing vision extraction.
    Returns dicts: page_number, chunk_index, region, title.
    Multiple captions on one page are merged into a single render region.
    """
    if file_path.suffix.lower() != ".pdf" or not file_path.is_file():
        return []

    raw_jobs: list[dict] = []
    doc = fitz.open(file_path)
    try:
        for chunk_index, chunk in enumerate(document.chunks):
            page_number = chunk.page_number
            if not page_number or page_number < 1 or page_number > doc.page_count:
                continue
            if not chunk_likely_missing_table_data(chunk.text or ""):
                continue

            page = doc[page_number - 1]
            extracted = extract_tables_from_page(page)
            orphans = find_orphan_table_captions(page, extracted)
            if not orphans:
                continue

            page_rect = page.rect
            titles = [title for _, title in orphans]
            y_start = min(region[1] for region, _ in orphans)
            y_end = float(page_rect.y1) - 4
            merged_region = (
                float(page_rect.x0),
                y_start,
                float(page_rect.x1),
                y_end,
            )
            raw_jobs.append(
                {
                    "page_number": page_number,
                    "chunk_index": chunk_index,
                    "region": merged_region,
                    "title": " | ".join(titles),
                }
            )
    finally:
        doc.close()

    # One vision call per page/chunk
    seen: set[tuple[int, int]] = set()
    jobs: list[dict] = []
    for job in raw_jobs:
        key = (job["page_number"], job["chunk_index"])
        if key in seen:
            continue
        seen.add(key)
        jobs.append(job)
        if len(jobs) >= max_jobs:
            logger.warning(
                "VLM table cap reached (%s); remaining image tables skipped",
                max_jobs,
            )
            break

    return jobs
