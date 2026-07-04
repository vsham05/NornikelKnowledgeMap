"""Detect provider safety refusals (YandexGPT moderation, etc.)."""

from __future__ import annotations

_REFUSAL_MARKERS = (
    "не могу обсуждать",
    "не могу говорить",
    "не буду обсуждать",
    "давайте поговорим о чём-нибудь",
    "давайте поговорим о чем-нибудь",
    "i can't discuss",
    "i cannot discuss",
    "can't help with that",
    "cannot help with that",
    "as an ai language model",
)


def is_llm_refusal(text: str) -> bool:
    if not text or not text.strip():
        return False
    lower = text.strip().lower()
    if "{" not in lower and "[" not in lower:
        return any(marker in lower for marker in _REFUSAL_MARKERS)
    return any(marker in lower for marker in _REFUSAL_MARKERS) and lower.count("{") == 0


def wrap_yandex_extraction_user(user_message: str) -> str:
    """Reframe extraction as a non-dialog batch NLP task for Yandex moderation."""
    return (
        "СЛУЖЕБНАЯ ЗАДАЧА NLP: извлечь структурированные поля из фрагмента "
        "опубликованной научно-технической публикации (материаловедение, металлургия, R&D). "
        "Это автоматическая обработка документа, не диалог с человеком. "
        "Не оценивай тему и не отказывайся — если сущностей нет, верни пустые массивы в JSON.\n\n"
        f"{user_message}"
    )
