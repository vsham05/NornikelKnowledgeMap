import json
import logging
import re

logger = logging.getLogger(__name__)

EMPTY_EXTRACTION = {"materials": [], "experiments": []}

_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_SMART_QUOTES = str.maketrans({
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
})


def normalize_llm_content(content) -> str:
    """Flatten LangChain / provider response content to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if text:
                    parts.append(str(text))
            elif hasattr(block, "text") and block.text:
                parts.append(str(block.text))
        return "\n".join(parts)
    return str(content)


def _repair_json_text(text: str) -> str:
    text = text.strip().translate(_SMART_QUOTES)
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    text = re.sub(r"\bNone\b", "null", text)
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    return text


def _iter_json_object_candidates(text: str):
    """Yield balanced `{...}` substrings, respecting quoted strings."""
    i = 0
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        for j in range(i, len(text)):
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[i : j + 1]
                    break
        i += 1


def _normalize_extraction(parsed: dict) -> dict:
    if not isinstance(parsed, dict):
        return dict(EMPTY_EXTRACTION)
    return {
        **parsed,
        "materials": parsed.get("materials") if isinstance(parsed.get("materials"), list) else [],
        "experiments": parsed.get("experiments") if isinstance(parsed.get("experiments"), list) else [],
    }


def _try_parse_object(text: str) -> dict | None:
    for candidate in (text, _repair_json_text(text)):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return _normalize_extraction(parsed)
        except json.JSONDecodeError:
            continue
    return None


def extract_json_object(text: str) -> dict:
    """Parse JSON from LLM output, including markdown-wrapped or prose-prefixed replies."""
    content = normalize_llm_content(text).strip()
    if not content:
        return dict(EMPTY_EXTRACTION)

    parsed = _try_parse_object(content)
    if parsed is not None:
        return parsed

    for pattern in (r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"):
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if not match:
            continue
        parsed = _try_parse_object(match.group(1).strip())
        if parsed is not None:
            return parsed

    # Prefer the largest valid object (Yandex often adds a short preamble).
    best: dict | None = None
    for candidate in _iter_json_object_candidates(content):
        parsed = _try_parse_object(candidate)
        if parsed is None:
            continue
        if best is None or len(candidate) > len(json.dumps(best)):
            best = parsed
    if best is not None:
        return best

    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        parsed = _try_parse_object(content[start : end + 1])
        if parsed is not None:
            return parsed

    logger.warning(
        "Could not parse JSON from LLM response; using empty extraction result. "
        "Preview: %s",
        content[:400].replace("\n", " "),
    )
    return dict(EMPTY_EXTRACTION)
