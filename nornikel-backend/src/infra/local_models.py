"""Ollama model catalog — tiered limits targeting ~90% of Yandex Qwen3-235B extraction quality.

Yandex reference (qwen3-235b-a22b-fp8): 262K ctx, 64K extraction chars.
Local tiers scale context + batch size; use qwen2.5:32b-instruct for best parity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_YANDEX_REF_EXTRACTION_CHARS = 64_000


@dataclass(frozen=True, slots=True)
class LocalModelInfo:
    id: str
    label: str
    tier: str  # light | standard | premium
    context_tokens: int
    extraction_chars: int
    max_output_tokens: int
    enricher_multipass: int
    extraction_batches: int
    notes: str = ""
    recommended: bool = False


LOCAL_MODELS: tuple[LocalModelInfo, ...] = (
    LocalModelInfo(
        id="qwen2.5:32b-instruct",
        label="Qwen2.5 32B (best local parity)",
        tier="premium",
        context_tokens=131_072,
        extraction_chars=56_000,
        max_output_tokens=16_384,
        enricher_multipass=0,
        extraction_batches=0,
        notes="~85–90% of Yandex Qwen3-235B on long PDFs; needs 24GB+ VRAM.",
        recommended=True,
    ),
    LocalModelInfo(
        id="qwen3:32b",
        label="Qwen3 32B",
        tier="premium",
        context_tokens=131_072,
        extraction_chars=56_000,
        max_output_tokens=16_384,
        enricher_multipass=0,
        extraction_batches=0,
        notes="Strong structured JSON; same tier as Qwen2.5 32B.",
    ),
    LocalModelInfo(
        id="deepseek-r1:32b",
        label="DeepSeek R1 32B",
        tier="premium",
        context_tokens=131_072,
        extraction_chars=52_000,
        max_output_tokens=16_384,
        enricher_multipass=0,
        extraction_batches=0,
        notes="Reasoning-heavy; slightly smaller safe context window.",
    ),
    LocalModelInfo(
        id="qwen2.5:14b-instruct",
        label="Qwen2.5 14B (recommended balance)",
        tier="standard",
        context_tokens=32_768,
        extraction_chars=28_000,
        max_output_tokens=12_288,
        enricher_multipass=0,
        extraction_batches=0,
        notes="~70–80% of Yandex on typical hardware (16GB VRAM).",
    ),
    LocalModelInfo(
        id="qwen3:14b",
        label="Qwen3 14B",
        tier="standard",
        context_tokens=32_768,
        extraction_chars=28_000,
        max_output_tokens=12_288,
        enricher_multipass=0,
        extraction_batches=0,
        notes="Good mid-tier extraction model.",
    ),
    LocalModelInfo(
        id="qwen2.5:7b-instruct",
        label="Qwen2.5 7B (fast, lower recall)",
        tier="light",
        context_tokens=8_192,
        extraction_chars=12_000,
        max_output_tokens=8_192,
        enricher_multipass=0,
        extraction_batches=0,
        notes="Full-coverage ingest; 14B+ recommended for Yandex-like recall.",
    ),
)

_DEFAULT_LOCAL_MODEL = "qwen2.5:14b-instruct"
_BY_ID: dict[str, LocalModelInfo] = {m.id: m for m in LOCAL_MODELS}
_TIER_BILINEAR = re.compile(r"(\d+)\s*b", re.IGNORECASE)


def default_local_extraction_model() -> str:
    return _DEFAULT_LOCAL_MODEL


def _normalize_model_key(model_id: str) -> str:
    return (model_id or "").strip().lower().replace("_", "-")


def get_local_model_info(model_id: str) -> LocalModelInfo | None:
    key = _normalize_model_key(model_id)
    if key in _BY_ID:
        return _BY_ID[key]
    if ":" not in key:
        colon = re.sub(r"-(\d+b)-", r":\1-", key, count=1)
        if colon in _BY_ID:
            return _BY_ID[colon]
    if ":" in key:
        hyphen = key.replace(":", "-", 1)
        if hyphen in _BY_ID:
            return _BY_ID[hyphen]
    return None


def infer_tier_from_name(model_id: str) -> str:
    match = _TIER_BILINEAR.search(model_id or "")
    if not match:
        return "light"
    params = int(match.group(1))
    if params >= 30:
        return "premium"
    if params >= 12:
        return "standard"
    return "light"


def resolve_local_model_tier(model_id: str) -> str:
    info = get_local_model_info(model_id)
    if info:
        return info.tier
    return infer_tier_from_name(model_id)


def extraction_chars_for_local_model(model_id: str, *, fallback: int = 12_000) -> int:
    info = get_local_model_info(model_id)
    if info:
        return info.extraction_chars
    tier = infer_tier_from_name(model_id)
    if tier == "premium":
        return 56_000
    if tier == "standard":
        return 28_000
    return fallback


def context_tokens_for_local_model(model_id: str, *, fallback: int = 8192) -> int:
    info = get_local_model_info(model_id)
    if info:
        return info.context_tokens
    tier = infer_tier_from_name(model_id)
    if tier == "premium":
        return 131_072
    if tier == "standard":
        return 32_768
    return fallback


def local_ingest_profile(model_id: str) -> dict:
    info = get_local_model_info(model_id)
    tier = info.tier if info else infer_tier_from_name(model_id)
    extraction_chars = info.extraction_chars if info else extraction_chars_for_local_model(model_id)
    context_tokens = info.context_tokens if info else context_tokens_for_local_model(model_id)
    max_output = info.max_output_tokens if info else 8192
    multipass = info.enricher_multipass if info else 0
    batches = info.extraction_batches if info else 0
    return {
        "tier": tier,
        "extraction_chars": extraction_chars,
        "context_tokens": context_tokens,
        "max_output_tokens": max_output,
        "enricher_multipass": multipass,
        "extraction_batches": batches,
        "yandex_char_parity": round(extraction_chars / _YANDEX_REF_EXTRACTION_CHARS, 2),
        "high_capability": tier in ("standard", "premium"),
    }


def is_high_capability_local(model_id: str) -> bool:
    return resolve_local_model_tier(model_id) in ("standard", "premium")


def local_enricher_concurrency(model_id: str, *, configured: int = 0) -> int:
    """Parallel enricher passes — keep low on 7B to avoid Ollama OOM."""
    if configured > 0:
        return configured
    tier = resolve_local_model_tier(model_id)
    if tier == "premium":
        return 4
    if tier == "standard":
        return 3
    return 2


def local_extraction_concurrency(model_id: str, *, configured: int = 8) -> int:
    """Parallel entity-extraction batches for local Ollama."""
    tier = resolve_local_model_tier(model_id)
    tier_cap = 4 if tier == "premium" else 3 if tier == "standard" else 2
    return min(configured, tier_cap)


def list_local_models() -> list[dict]:
    return [
        {
            "id": m.id,
            "label": m.label,
            "tier": m.tier,
            "context_tokens": m.context_tokens,
            "extraction_chars": m.extraction_chars,
            "max_output_tokens": m.max_output_tokens,
            "enricher_multipass": m.enricher_multipass,
            "extraction_batches": m.extraction_batches,
            "yandex_char_parity": round(m.extraction_chars / _YANDEX_REF_EXTRACTION_CHARS, 2),
            "notes": m.notes,
            "recommended": m.recommended,
        }
        for m in LOCAL_MODELS
    ]
