"""Yandex AI Studio model catalog for ingestion / extraction.

Docs: https://yandex.cloud/en/docs/foundation-models/concepts/yandexgpt/models
AI Studio quickstart: https://aistudio.yandex.ru/docs/ru/ai-studio/quickstart/
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class YandexModelInfo:
    id: str
    label: str
    context_tokens: int
    extraction_chars: int
    tags: tuple[str, ...]
    moderation_risk: bool = False
    notes: str = ""


# Enterprise / open-weight models in AI Studio — preferred for scientific PDF extraction.
# Consumer YandexGPT Pro/Lite may refuse mining/metallurgy content ("не могу обсуждать").
YANDEX_MODELS: tuple[YandexModelInfo, ...] = (
    YandexModelInfo(
        id="qwen3-235b-a22b-fp8/latest",
        label="Qwen3 235B (recommended)",
        context_tokens=262_144,
        extraction_chars=64_000,
        tags=("extraction", "long_context", "structured"),
        notes="Best extraction quality on scientific PDFs; 262K context.",
    ),
    YandexModelInfo(
        id="deepseek-v4-flash",
        label="DeepSeek V4 Flash (fast long PDFs)",
        context_tokens=1_000_000,
        extraction_chars=96_000,
        tags=("extraction", "long_context", "very_long_pdf", "fast"),
        notes="Faster hybrid ingest for 400+ page PDFs; 1M context.",
    ),
    YandexModelInfo(
        id="gpt-oss-120b/latest",
        label="GPT-OSS 120B",
        context_tokens=131_072,
        extraction_chars=48_000,
        tags=("extraction", "reasoning"),
        notes="Strong reasoning; 131K context.",
    ),
    YandexModelInfo(
        id="gpt-oss-20b/latest",
        label="GPT-OSS 20B",
        context_tokens=131_072,
        extraction_chars=40_000,
        tags=("extraction", "fast"),
        notes="Faster/cheaper open model; 131K context.",
    ),
    YandexModelInfo(
        id="gemma-3-27b-it/latest",
        label="Gemma 3 27B IT",
        context_tokens=131_072,
        extraction_chars=40_000,
        tags=("extraction",),
        notes="Instruction-tuned Google open model.",
    ),
    YandexModelInfo(
        id="yandexgpt/rc",
        label="YandexGPT Pro 5.1 (rc)",
        context_tokens=32_768,
        extraction_chars=20_000,
        tags=("russian", "chat"),
        moderation_risk=True,
        notes="Native Russian; may refuse sensitive industrial topics.",
    ),
    YandexModelInfo(
        id="yandexgpt/latest",
        label="YandexGPT Pro 5",
        context_tokens=32_768,
        extraction_chars=20_000,
        tags=("russian", "chat"),
        moderation_risk=True,
        notes="General Pro model; document analysis but strict moderation.",
    ),
    YandexModelInfo(
        id="yandexgpt-lite/latest",
        label="YandexGPT Lite 5",
        context_tokens=32_768,
        extraction_chars=20_000,
        tags=("fast", "chat"),
        moderation_risk=True,
        notes="Fast/cheap; still subject to consumer-style refusals.",
    ),
)

_DEFAULT_EXTRACTION_MODEL = "qwen3-235b-a22b-fp8/latest"

_BY_ID: dict[str, YandexModelInfo] = {m.id: m for m in YANDEX_MODELS}


def default_yandex_extraction_model() -> str:
    return _DEFAULT_EXTRACTION_MODEL


def get_yandex_model_info(model_id: str) -> YandexModelInfo | None:
    return _BY_ID.get(model_id.strip())


def list_yandex_models() -> list[dict]:
    return [
        {
            "id": m.id,
            "label": m.label,
            "context_tokens": m.context_tokens,
            "extraction_chars": m.extraction_chars,
            "tags": list(m.tags),
            "moderation_risk": m.moderation_risk,
            "notes": m.notes,
            "recommended": m.id == _DEFAULT_EXTRACTION_MODEL,
        }
        for m in YANDEX_MODELS
    ]


def extraction_chars_for_model(model_id: str, *, fallback: int = 12_000) -> int:
    info = get_yandex_model_info(model_id)
    return info.extraction_chars if info else fallback
