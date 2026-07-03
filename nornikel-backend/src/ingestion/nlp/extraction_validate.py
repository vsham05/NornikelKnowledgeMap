"""Reject LLM template echoes and generic placeholder entity names."""

from __future__ import annotations

import re

# Strings copied from prompts / JSON schemas — not real document entities.
_LLM_TEMPLATE_STRINGS = frozenset({
    "short label",
    "process or theme",
    "one grounded sentence",
    "linked process name if any",
    "canonical material name",
    "substance name",
    "organization name",
    "person name",
    "site name",
    "equipment name",
    "process name",
    "team name",
    "company name",
    "institute name",
    "facility name",
    "researcher name",
    "название материала",
    "название организации",
    "краткое описание",
    "example",
    "sample",
    "n/a",
    "na",
    "none",
    "unknown",
    "tbd",
    "todo",
})

_PLACEHOLDER_EQUIPMENT = frozenset({
    "equipment",
    "device",
    "unit",
    "apparatus",
    "machine",
    "tool",
    "оборудование",
    "устройство",
    "установка",
})

_PLACEHOLDER_PROCESS = frozenset({
    "process",
    "operation",
    "technology",
    "procedure",
    "method",
    "процесс",
    "операция",
    "технология",
    "метод",
})

_PLACEHOLDER_TOPIC = frozenset({
    "topic",
    "theme",
    "subject",
    "area",
    "тема",
    "направление",
})

_PLACEHOLDER_EXPERT_FIELDS = frozenset({
    "field",
    "discipline",
    "specialty",
    "area",
    "область",
    "специальность",
})


def normalize_entity_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip(" .;,"))


def is_llm_template_string(name: str) -> bool:
    n = normalize_entity_name(name).lower()
    if not n or len(n) < 2:
        return True
    if n in _LLM_TEMPLATE_STRINGS:
        return True
    if n.startswith("<") and n.endswith(">"):
        return True
    if "..." in n or n.endswith("…"):
        return True
    return False


def is_placeholder_equipment(name: str) -> bool:
    return normalize_entity_name(name).lower() in _PLACEHOLDER_EQUIPMENT


def is_placeholder_process(name: str) -> bool:
    return normalize_entity_name(name).lower() in _PLACEHOLDER_PROCESS


def is_placeholder_topic(name: str) -> bool:
    n = normalize_entity_name(name).lower()
    return not n or n in _PLACEHOLDER_TOPIC or is_llm_template_string(n)


def is_placeholder_expert_field(field: str | None) -> bool:
    if not field:
        return False
    return normalize_entity_name(field).lower() in _PLACEHOLDER_EXPERT_FIELDS
