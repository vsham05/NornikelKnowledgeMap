"""Per-ingest flags (provider override, disable local fallback on Yandex API)."""

from __future__ import annotations

import contextvars
from typing import Literal

IngestLLMProvider = Literal["local", "yandex"]

_yandex_only: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "ingest_yandex_only", default=False
)
_ingest_provider: contextvars.ContextVar[IngestLLMProvider | None] = contextvars.ContextVar(
    "ingest_llm_provider", default=None
)


def set_ingest_yandex_only(enabled: bool) -> contextvars.Token:
    return _yandex_only.set(enabled)


def reset_ingest_yandex_only(token: contextvars.Token) -> None:
    _yandex_only.reset(token)


def ingest_yandex_only() -> bool:
    return _yandex_only.get()


def set_ingest_provider(provider: IngestLLMProvider) -> contextvars.Token:
    return _ingest_provider.set(provider)


def reset_ingest_provider(token: contextvars.Token) -> None:
    _ingest_provider.reset(token)


def get_ingest_provider() -> IngestLLMProvider | None:
    return _ingest_provider.get()
