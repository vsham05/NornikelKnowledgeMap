"""Structured PDF table extraction — preserves rows/columns for RAG and entity extraction."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MIN_TABLE_QUALITY = 0.42
MIN_MARKDOWN_CHARS = 16
FIND_TABLE_STRATEGIES = ("lines", "text", "explicit")

TABLE_CAPTION_RE = re.compile(
    r"^(?:table\s+\d+|fig(?:ure)?\.\s*\d+|таблица\s+\d+).{0,160}$",
    re.IGNORECASE,
)
TABLE_CAPTION_INLINE_RE = re.compile(
    r"^table\s+(\d+[\w\-\.]*)[\.\:\s]+(.+)$",
    re.IGNORECASE,
)
TABLE_HINT_RE = re.compile(
    r"\b(?:table\s*\d+|таблица\s*\d+|tabular)\b",
    re.IGNORECASE,
)
TABLE_BLOCK_RE = re.compile(r"\[TABLE\][\s\S]*?\[/TABLE\]", re.IGNORECASE)
GARBAGE_CELL_RE = re.compile(r"^(?:col\d+|&lt;br&gt;|<br\s*/?>|)$", re.IGNORECASE)
HTML_ARTIFACT_RE = re.compile(r"&(?:lt|gt|amp|#\d+|#x[0-9a-f]+);|<br\s*/?>", re.IGNORECASE)
NUMERIC_CELL_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class ExtractedTable:
    bbox: tuple[float, float, float, float]
    markdown: str
    title: str | None = None
    quality: float = 0.0


def _rect_tuple(bbox) -> tuple[float, float, float, float]:
    if hasattr(bbox, "x0"):
        return (float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1))
    parts = tuple(float(v) for v in bbox)
    if len(parts) != 4:
        return (0.0, 0.0, 0.0, 0.0)
    return parts  # type: ignore[return-value]


def _union_bbox(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _normalize_cell(val) -> str:
    if val is None:
        return ""
    text = html.unescape(str(val))
    text = html.unescape(text)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
    text = HTML_ARTIFACT_RE.sub(" ", text)
    text = text.replace("\u00ad", "")  # soft hyphen
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def _grid_to_markdown(grid: list[list]) -> str:
    rows = [[_normalize_cell(c) for c in row] for row in grid]
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return ""

    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]

    lines: list[str] = []
    header = norm[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in norm[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _table_quality_score(grid: list[list] | None, markdown: str = "") -> float:
    """Score 0–1; reject garbled Col1/br artifacts and empty grids."""
    if not grid:
        return 0.0

    rows = [[_normalize_cell(c) for c in row] for row in grid]
    rows = [r for r in rows if any(c for c in r)]
    if len(rows) < 2:
        return 0.0

    width = max(len(r) for r in rows)
    if width < 2:
        return 0.0

    total_cells = sum(len(r) for r in rows)
    filled = 0
    garbage = 0
    numeric = 0
    for row in rows:
        for cell in row:
            if not cell:
                continue
            if GARBAGE_CELL_RE.match(cell) or HTML_ARTIFACT_RE.search(cell):
                garbage += 1
                continue
            filled += 1
            if NUMERIC_CELL_RE.search(cell):
                numeric += 1

    if filled < 4:
        return 0.0

    filled_ratio = filled / max(1, total_cells)
    garbage_ratio = garbage / max(1, total_cells)
    numeric_bonus = min(0.15, numeric / max(1, filled) * 0.15)
    size_bonus = min(0.12, len(rows) / 12 * 0.12)

    score = filled_ratio * 0.72 + size_bonus + numeric_bonus - garbage_ratio * 0.65
    if garbage_ratio > 0.35:
        score *= 0.45
    if markdown and HTML_ARTIFACT_RE.search(markdown):
        score *= 0.55
    return max(0.0, min(1.0, score))


def _table_to_markdown(table) -> tuple[str, list[list] | None]:
    grid = None
    if hasattr(table, "extract"):
        try:
            grid = table.extract()
        except Exception:
            grid = None

    if grid:
        md = _grid_to_markdown(grid)
        if md:
            return md, grid

    if hasattr(table, "to_markdown"):
        try:
            md = table.to_markdown(clean=True)
        except TypeError:
            md = table.to_markdown()
        if md and str(md).strip():
            return str(md).strip(), grid

    return "", grid


def _bbox_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1.0, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1.0, (bx1 - bx0) * (by1 - by0))
    return inter / min(area_a, area_b)


def _dedupe_tables(
    tables: list[ExtractedTable],
    overlap_threshold: float = 0.50,
) -> list[ExtractedTable]:
    ranked = sorted(tables, key=lambda t: (t.quality, len(t.markdown)), reverse=True)
    kept: list[ExtractedTable] = []
    for table in ranked:
        if any(_bbox_overlap(table.bbox, other.bbox) >= overlap_threshold for other in kept):
            continue
        kept.append(table)
    return sorted(kept, key=lambda t: t.bbox[1])


def _line_center_in_bbox(
    line_bbox: tuple[float, float, float, float],
    table_bbox: tuple[float, float, float, float],
    *,
    margin: float = 3.0,
) -> bool:
    lx0, ly0, lx1, ly1 = line_bbox
    cx = (lx0 + lx1) / 2.0
    cy = (ly0 + ly1) / 2.0
    x0, y0, x1, y1 = table_bbox
    return (x0 - margin) <= cx <= (x1 + margin) and (y0 - margin) <= cy <= (y1 + margin)


def _iter_page_lines(page) -> list[tuple[tuple[float, float, float, float], str]]:
    lines: list[tuple[tuple[float, float, float, float], str]] = []
    try:
        page_dict = page.get_text("dict") or {}
        for block in page_dict.get("blocks", []):
            if block.get("type") not in (0, None):
                continue
            for line in block.get("lines", []):
                bbox = tuple(line.get("bbox", (0.0, 0.0, 0.0, 0.0)))
                text = "".join(span.get("text", "") for span in line.get("spans", []))
                text = _normalize_cell(text)
                if text:
                    lines.append((bbox, text))
    except Exception as exc:
        logger.debug("Page line iteration failed: %s", exc)
    return lines


def _guess_table_title(page, bbox: tuple[float, float, float, float]) -> str | None:
    x0, y0, _, _ = bbox
    candidates: list[tuple[float, str]] = []
    for line_bbox, text in _iter_page_lines(page):
        ly1 = line_bbox[3]
        if ly1 > y0 or y0 - ly1 > 80:
            continue
        if len(text) > 180:
            continue
        if TABLE_CAPTION_RE.match(text) or text.lower().startswith("table "):
            candidates.append((y0 - ly1, text))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _find_captions(page) -> list[tuple[tuple[float, float, float, float], str]]:
    captions: list[tuple[tuple[float, float, float, float], str]] = []
    for bbox, text in _iter_page_lines(page):
        if TABLE_CAPTION_INLINE_RE.match(text) or TABLE_CAPTION_RE.match(text):
            captions.append((bbox, text))
    return sorted(captions, key=lambda item: item[0][1])


def _caption_regions(
    page,
    captions: list[tuple[tuple[float, float, float, float], str]],
) -> list[tuple[tuple[float, float, float, float], str]]:
    if not captions:
        return []

    page_rect = page.rect
    page_bottom = float(page_rect.y1)
    page_left = float(page_rect.x0)
    page_right = float(page_rect.x1)
    regions: list[tuple[tuple[float, float, float, float], str]] = []

    for idx, (bbox, title) in enumerate(captions):
        y_start = bbox[3] + 2
        y_end = captions[idx + 1][0][1] - 2 if idx + 1 < len(captions) else page_bottom - 4
        if y_end - y_start < 18:
            continue
        region = (page_left, y_start, page_right, y_end)
        regions.append((region, title))
    return regions


def _words_in_region(page, region: tuple[float, float, float, float]) -> list[tuple]:
    x0, y0, x1, y1 = region
    words = page.get_text("words") or []
    selected: list[tuple] = []
    for word in words:
        if len(word) < 5:
            continue
        wx0, wy0, wx1, wy1, text = word[0], word[1], word[2], word[3], word[4]
        if wy1 < y0 or wy0 > y1:
            continue
        if wx1 < x0 or wx0 > x1:
            continue
        if _normalize_cell(text):
            selected.append(word)
    return selected


def _cluster_positions(values: list[float], tolerance: float) -> list[float]:
    if not values:
        return []
    values = sorted(values)
    clusters: list[list[float]] = [[values[0]]]
    for val in values[1:]:
        if val - clusters[-1][-1] <= tolerance:
            clusters[-1].append(val)
        else:
            clusters.append([val])
    return [sum(group) / len(group) for group in clusters]


def _assign_column(x_mid: float, columns: list[float], tolerance: float) -> int:
    if not columns:
        return 0
    best_idx = 0
    best_dist = abs(x_mid - columns[0])
    for idx, col in enumerate(columns[1:], start=1):
        dist = abs(x_mid - col)
        if dist < best_dist:
            best_dist = dist
            best_idx = idx
    if best_dist > tolerance * 2.5:
        return -1
    return best_idx


def _words_to_grid(words: list[tuple], *, y_tolerance: float = 4.0, x_tolerance: float = 14.0) -> list[list[str]]:
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w[1], w[0]))
    line_groups: list[list[tuple]] = []
    current: list[tuple] = []
    current_y: float | None = None

    for word in sorted_words:
        y0 = float(word[1])
        if current_y is None or abs(y0 - current_y) <= y_tolerance:
            current.append(word)
            current_y = y0 if current_y is None else (current_y + y0) / 2.0
        else:
            line_groups.append(current)
            current = [word]
            current_y = y0
    if current:
        line_groups.append(current)

    col_centers = _cluster_positions(
        [((float(w[0]) + float(w[2])) / 2.0) for w in sorted_words],
        x_tolerance,
    )
    if len(col_centers) < 2:
        col_centers = _cluster_positions(
            [float(w[0]) for w in sorted_words],
            x_tolerance,
        )

    width = max(2, len(col_centers))
    grid: list[list[str]] = []

    for group in line_groups:
        row = [""] * width
        for word in sorted(group, key=lambda w: w[0]):
            text = _normalize_cell(word[4])
            if not text:
                continue
            x_mid = (float(word[0]) + float(word[2])) / 2.0
            col = _assign_column(x_mid, col_centers, x_tolerance)
            if col < 0:
                col = min(width - 1, max(0, int((x_mid - col_centers[0]) / max(x_tolerance, 1))))
            if row[col]:
                row[col] = f"{row[col]} {text}".strip()
            else:
                row[col] = text
        if any(row):
            grid.append(row)
    return grid


def _grid_bbox(words: list[tuple]) -> tuple[float, float, float, float]:
    if not words:
        return (0.0, 0.0, 0.0, 0.0)
    x0 = min(float(w[0]) for w in words)
    y0 = min(float(w[1]) for w in words)
    x1 = max(float(w[2]) for w in words)
    y1 = max(float(w[3]) for w in words)
    return (x0, y0, x1, y1)


def _parse_spaced_text_row(line: str) -> list[str] | None:
    line = _normalize_cell(line)
    if not line or len(line) < 2:
        return None
    if line.lower().startswith("alta free library"):
        return None
    parts = [p.strip() for p in re.split(r"\s{2,}|\t", line) if p.strip()]
    if len(parts) >= 2:
        return parts
    if len(re.findall(r"\d+(?:\.\d+)?", line)) >= 3:
        parts = line.split()
        if len(parts) >= 3:
            return parts
    return None


def _extract_plaintext_table_block(lines: list[str], title: str) -> ExtractedTable | None:
    rows: list[list[str]] = []
    for line in lines:
        parsed = _parse_spaced_text_row(line)
        if parsed:
            rows.append(parsed)
    if len(rows) < 2:
        return None
    md = _grid_to_markdown(rows)
    score = _table_quality_score(rows, md)
    if score < MIN_TABLE_QUALITY or len(md) < MIN_MARKDOWN_CHARS:
        return None
    return ExtractedTable(
        bbox=(0.0, 0.0, 0.0, 0.0),
        markdown=md,
        title=title,
        quality=score,
    )


def _region_covered(region: tuple[float, float, float, float], tables: list[ExtractedTable]) -> bool:
    rx0, ry0, rx1, ry1 = region
    region_area = max(1.0, (rx1 - rx0) * (ry1 - ry0))
    for table in tables:
        overlap = _bbox_overlap(table.bbox, region)
        if overlap >= 0.25:
            return True
        tx0, ty0, tx1, ty1 = table.bbox
        inter_y = max(0.0, min(ry1, ty1) - max(ry0, ty0))
        if inter_y / max(1.0, ry1 - ry0) > 0.35:
            return True
    return False


def _extract_find_tables(page) -> list[ExtractedTable]:
    found: list[ExtractedTable] = []
    for strategy in FIND_TABLE_STRATEGIES:
        try:
            finder = page.find_tables(strategy=strategy)
        except Exception as exc:
            logger.debug("find_tables(%s) failed: %s", strategy, exc)
            continue

        for table in getattr(finder, "tables", None) or []:
            try:
                markdown, grid = _table_to_markdown(table)
                score = _table_quality_score(grid, markdown)
                if score < MIN_TABLE_QUALITY or len(markdown.strip()) < MIN_MARKDOWN_CHARS:
                    continue
                bbox = _rect_tuple(table.bbox)
                title = _guess_table_title(page, bbox)
                found.append(
                    ExtractedTable(
                        bbox=bbox,
                        markdown=markdown,
                        title=title,
                        quality=score,
                    )
                )
            except Exception as exc:
                logger.debug("Table markdown failed (%s): %s", strategy, exc)
    return found


def _extract_caption_region_tables(page, existing: list[ExtractedTable]) -> list[ExtractedTable]:
    captions = _find_captions(page)
    if not captions:
        return []

    extracted: list[ExtractedTable] = []
    for region, title in _caption_regions(page, captions):
        if _region_covered(region, existing + extracted):
            continue

        words = _words_in_region(page, region)
        if len(words) < 6:
            continue

        grid = _words_to_grid(words)
        markdown = _grid_to_markdown(grid)
        score = _table_quality_score(grid, markdown)
        if score < MIN_TABLE_QUALITY or len(markdown.strip()) < MIN_MARKDOWN_CHARS:
            continue

        bbox = _grid_bbox(words)
        extracted.append(
            ExtractedTable(
                bbox=bbox,
                markdown=markdown,
                title=title,
                quality=score,
            )
        )
    return extracted


def _extract_plaintext_caption_tables(page, existing: list[ExtractedTable]) -> list[ExtractedTable]:
    text = _normalize_cell(page.get_text("text") or "")
    if not text or not TABLE_HINT_RE.search(text):
        return []

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    caption_indices: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if TABLE_CAPTION_INLINE_RE.match(line) or TABLE_CAPTION_RE.match(line):
            caption_indices.append((idx, line))

    if not caption_indices:
        return []

    extracted: list[ExtractedTable] = []
    for pos, (start_idx, title) in enumerate(caption_indices):
        end_idx = caption_indices[pos + 1][0] if pos + 1 < len(caption_indices) else len(lines)
        body = lines[start_idx + 1 : end_idx]
        if len(body) < 2:
            continue
        if any(t.title == title for t in existing + extracted):
            continue
        table = _extract_plaintext_table_block(body, title)
        if table:
            extracted.append(table)
    return extracted


def _page_likely_has_table(page) -> bool:
    """Cheap pre-check — skip slow extraction on prose-only pages."""
    try:
        quick = (page.get_text("text") or "")[:6000]
    except Exception:
        return False
    if not quick.strip():
        return False
    if TABLE_HINT_RE.search(quick):
        return True
    lines = [ln.strip() for ln in quick.split("\n") if ln.strip()]
    if len(lines) < 3:
        return False
    numeric_rows = sum(
        1
        for ln in lines[:50]
        if len(re.findall(r"\d+(?:\.\d+)?", ln)) >= 3
        and (len(re.findall(r"\s{2,}|\t", ln)) >= 2 or len(ln.split()) >= 4)
    )
    return numeric_rows >= 2


def extract_tables_from_page(page) -> list[ExtractedTable]:
    """Detect tables using find_tables + caption-region word grids + plain-text fallbacks."""
    if not _page_likely_has_table(page):
        return []

    found = _extract_find_tables(page)
    found.extend(_extract_caption_region_tables(page, found))
    found.extend(_extract_plaintext_caption_tables(page, found))

    deduped = _dedupe_tables(found)
    if deduped:
        logger.debug(
            "Extracted %s table(s) on page (qualities: %s)",
            len(deduped),
            [round(t.quality, 2) for t in deduped],
        )
    else:
        captions = _find_captions(page)
        if captions:
            logger.warning(
                "Table caption(s) found but no quality grid extracted (%s)",
                [title[:80] for _, title in captions[:4]],
            )
    return deduped


def find_orphan_table_captions(
    page,
    extracted: list[ExtractedTable],
) -> list[tuple[tuple[float, float, float, float], str]]:
    """Captions whose body region is not covered by a quality text/table extraction."""
    captions = _find_captions(page)
    if not captions:
        return []

    orphans: list[tuple[tuple[float, float, float, float], str]] = []
    for region, title in _caption_regions(page, captions):
        if _region_covered(region, extracted):
            continue
        orphans.append((region, title))
    return orphans


def chunk_likely_missing_table_data(chunk_text: str) -> bool:
    """True when the page mentions tables but has no usable structured [TABLE] block."""
    text = chunk_text or ""
    if not TABLE_HINT_RE.search(text):
        return False
    for match in TABLE_BLOCK_RE.finditer(text):
        block = match.group(0)
        if block.count("|") >= 6 and "---" in block:
            return False
    return True


def extract_text_outside_tables(page, tables: list[ExtractedTable]) -> str:
    """Body text excluding table regions to avoid duplicated jumbled columns."""
    if not tables:
        return ""

    bboxes = [t.bbox for t in tables if t.bbox != (0.0, 0.0, 0.0, 0.0)]
    if not bboxes:
        return _normalize_cell(page.get_text("text") or "")

    lines_out: list[str] = []
    seen_caption_titles = {t.title for t in tables if t.title}
    try:
        for line_bbox, text in _iter_page_lines(page):
            if any(_line_center_in_bbox(line_bbox, bbox) for bbox in bboxes):
                continue
            if text in seen_caption_titles:
                continue
            lines_out.append(text)
    except Exception as exc:
        logger.debug("Text outside tables failed: %s", exc)
        return ""

    return "\n".join(lines_out)


def merge_page_text_and_tables(page, tables: list[ExtractedTable]) -> str:
    """Combine prose and structured tables in reading order."""
    if not tables:
        return ""

    tables = sorted(tables, key=lambda t: (t.bbox[1], t.title or ""))
    body = extract_text_outside_tables(page, tables)

    parts: list[str] = []
    if body.strip():
        parts.append(body.strip())

    for table in tables:
        block_lines = ["[TABLE]"]
        if table.title:
            block_lines.append(table.title)
        block_lines.append(table.markdown)
        block_lines.append("[/TABLE]")
        parts.append("\n".join(block_lines))

    return "\n\n".join(parts)
