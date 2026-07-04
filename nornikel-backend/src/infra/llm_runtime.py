"""Runtime LLM provider selection (local Ollama vs Yandex Cloud)."""

from __future__ import annotations

import threading
from typing import Literal

from infra.yandex_models import default_yandex_extraction_model
from infra.local_models import default_local_extraction_model

LLMProvider = Literal["local", "yandex"]

_lock = threading.Lock()
_provider: LLMProvider = "local"
_yandex_model: str | None = None
_local_model: str | None = None


def get_llm_provider() -> LLMProvider:
    with _lock:
        return _provider


def get_effective_llm_provider() -> LLMProvider:
    """Global provider, or per-document override set during ingest."""
    from infra.ingest_context import get_ingest_provider

    override = get_ingest_provider()
    if override is not None:
        return override
    return get_llm_provider()


def get_yandex_model() -> str:
    with _lock:
        return _yandex_model or default_yandex_extraction_model()


def get_local_model() -> str:
    with _lock:
        if _local_model:
            return _local_model
        from settings import get_settings
        return get_settings().llm_model


def set_local_model(model_id: str) -> str:
    cleaned = model_id.strip()
    if not cleaned:
        raise ValueError("Local Ollama model id is required")
    with _lock:
        global _local_model
        _local_model = cleaned
        return _local_model


def set_yandex_model(model_id: str) -> str:
    cleaned = model_id.strip()
    if not cleaned:
        raise ValueError("Yandex model id is required")
    with _lock:
        global _yandex_model
        _yandex_model = cleaned
        return _yandex_model


def set_llm_provider(provider: str) -> LLMProvider:
    normalized = provider.strip().lower()
    if normalized not in ("local", "yandex"):
        raise ValueError(f"Unsupported LLM provider: {provider}")
    with _lock:
        global _provider
        _provider = normalized  # type: ignore[assignment]
        return _provider


def init_llm_provider_from_settings(default: str) -> LLMProvider:
    try:
        return set_llm_provider(default)
    except ValueError:
        return set_llm_provider("local")


def init_yandex_model_from_settings(model: str) -> str:
    try:
        return set_yandex_model(model or default_yandex_extraction_model())
    except ValueError:
        return set_yandex_model(default_yandex_extraction_model())


def init_local_model_from_settings(model: str) -> str:
    try:
        return set_local_model(model or default_local_extraction_model())
    except ValueError:
        return set_local_model(default_local_extraction_model())
