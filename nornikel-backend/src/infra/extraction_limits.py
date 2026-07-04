"""Resolve extraction batch limits from active LLM provider/model."""

from __future__ import annotations

from infra.llm_runtime import get_effective_llm_provider, get_local_model, get_yandex_model
from infra.local_models import extraction_chars_for_local_model
from infra.yandex_models import extraction_chars_for_model
from settings import Settings


def resolve_extraction_max_chars(settings: Settings) -> int:
    if get_effective_llm_provider() == "yandex":
        return extraction_chars_for_model(
            get_yandex_model(),
            fallback=settings.llm_extraction_max_chars,
        )
    return extraction_chars_for_local_model(
        get_local_model(),
        fallback=settings.llm_extraction_max_chars,
    )
