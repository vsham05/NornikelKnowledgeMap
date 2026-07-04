"""Normalize uploaded filenames into human-readable document titles."""

from __future__ import annotations

import re
from pathlib import Path


def humanize_upload_title(filename_or_stem: str) -> str:
    """Turn ``1_My_Report.docx`` into ``1 My Report`` for display/storage."""
    raw = (filename_or_stem or "").strip()
    if not raw:
        return ""
    stem = Path(raw).stem if "." in raw else raw
    title = re.sub(r"_+", " ", stem.strip())
    title = re.sub(r"\s+", " ", title).strip()
    return title[:300]
