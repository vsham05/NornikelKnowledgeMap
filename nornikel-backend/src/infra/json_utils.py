import json
import logging
import re

logger = logging.getLogger(__name__)

EMPTY_EXTRACTION = {"materials": [], "experiments": []}


def extract_json_object(text: str) -> dict:
    """Parse JSON from LLM output, including markdown-wrapped or prose-prefixed replies."""
    if not text or not text.strip():
        return dict(EMPTY_EXTRACTION)

    content = text.strip()

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    for pattern in (r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"):
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(content[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse JSON from LLM response; using empty extraction result")
    return dict(EMPTY_EXTRACTION)
