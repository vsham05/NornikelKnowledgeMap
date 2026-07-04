"""Yandex API reachability — auto-fallback to local Ollama when unusable."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from settings import Settings

logger = logging.getLogger(__name__)

_PROBE_TTL_SEC = 120.0

_yandex_usable: bool | None = None
_yandex_checked_at: float = 0.0
_yandex_unusable_reason: str = ""

_YANDEX_FAILURE_MARKERS = (
    "401",
    "403",
    "unauthorized",
    "unauthenticated",
    "invalid api key",
    "api key",
    "permission denied",
    "forbidden",
    "connection error",
    "connect error",
    "connection refused",
    "name or service not known",
    "failed to resolve",
    "server misbehaving",
    "timeout",
    "timed out",
    "ssl",
    "certificate",
    "502",
    "503",
    "504",
    "bad gateway",
    "service unavailable",
    "rate limit",
    "too many requests",
    "quota",
    "billing",
    "folder_id",
    "resource not found",
    "not found",
)


def yandex_credentials_configured(settings: Settings) -> bool:
    return bool((settings.yandex_api_key or "").strip() and (settings.yandex_folder_id or "").strip())


def yandex_unusable_reason() -> str:
    return _yandex_unusable_reason


def mark_yandex_unusable(reason: str) -> None:
    global _yandex_usable, _yandex_unusable_reason, _yandex_checked_at
    cleaned = (reason or "unknown error").strip()[:240]
    if _yandex_usable is not False:
        logger.warning("Yandex API marked unusable — routing to local LLM (%s)", cleaned)
    _yandex_usable = False
    _yandex_unusable_reason = cleaned
    _yandex_checked_at = time.monotonic()


def mark_yandex_usable() -> None:
    global _yandex_usable, _yandex_unusable_reason, _yandex_checked_at
    _yandex_usable = True
    _yandex_unusable_reason = ""
    _yandex_checked_at = time.monotonic()


def yandex_usable_cached() -> bool:
    """Fast sync check for routing (optimistic until probe or call fails)."""
    if _yandex_usable is False:
        return False
    if _yandex_usable is True:
        return True
    return True


def is_yandex_failure(exc: BaseException) -> bool:
    """True when the error indicates Yandex API is unavailable or misconfigured."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in _YANDEX_FAILURE_MARKERS)


async def check_yandex_api(settings: Settings, *, force: bool = False) -> bool:
    """
    Probe Yandex OpenAI-compatible API. Result cached for _PROBE_TTL_SEC.
    Returns False when keys missing or API unreachable.
    """
    global _yandex_usable, _yandex_checked_at

    if not yandex_credentials_configured(settings):
        mark_yandex_unusable("YANDEX_API_KEY or YANDEX_FOLDER_ID not set")
        return False

    now = time.monotonic()
    if (
        not force
        and _yandex_usable is not None
        and now - _yandex_checked_at < _PROBE_TTL_SEC
    ):
        return _yandex_usable

    url = f"{settings.yandex_base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Api-Key {settings.yandex_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 200:
            mark_yandex_usable()
            logger.info("Yandex API probe OK")
            return True
        mark_yandex_unusable(f"HTTP {response.status_code}: {response.text[:120]}")
        return False
    except Exception as exc:
        if is_yandex_failure(exc):
            mark_yandex_unusable(str(exc))
            return False
        mark_yandex_unusable(str(exc))
        return False
