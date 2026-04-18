"""
Robust JSON extraction from LLM responses.

LLMs (especially after rate-limit retries) may return:
- Bare JSON
- JSON wrapped in ```json ... ``` fences
- JSON preceded/followed by explanatory text
- Empty fences with no content  (```json\n```)
- Truncated JSON (token limit hit mid-output)
"""

from __future__ import annotations

import json
import re
import logging

logger = logging.getLogger(__name__)


def extract_json_object(text: str) -> str:
    """
    Return the first complete JSON object or array found in *text*.
    Strips markdown fences, skips any prose before the JSON.
    Raises ValueError if nothing parseable is found.
    """
    text = text.strip()
    if not text:
        raise ValueError("LLM returned an empty response")

    # 1. Strip markdown code fences (```json ... ``` or ``` ... ```)
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        inner = fence_match.group(1).strip()
        if inner:
            text = inner
        # else: fence had no content — fall through to search below

    # 2. If after fence-stripping the text starts with { or [, use it directly
    text = text.strip()
    if text and text[0] in ("{", "["):
        return text

    # 3. Scan for the first { or [ and return from there
    for start_char in ("{", "["):
        idx = text.find(start_char)
        if idx >= 0:
            candidate = text[idx:]
            if candidate:
                return candidate

    raise ValueError(
        f"No JSON object or array found in LLM response "
        f"(first 300 chars): {text[:300]!r}"
    )


def parse_json_object(text: str) -> dict:
    """Extract and parse a JSON *object* from an LLM response."""
    raw = extract_json_object(text)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Last-ditch: try to repair by truncating at last complete field
        result = _repair_and_load(raw)
    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object, got {type(result).__name__}")
    return result


def parse_json_array(text: str) -> list:
    """Extract and parse a JSON *array* from an LLM response."""
    raw = extract_json_object(text)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = _repair_and_load(raw)

    if isinstance(result, list):
        return result

    if isinstance(result, dict):
        # 1. Try common wrapper keys first
        for key in ("strategies", "companies", "results", "data", "items", "array", "list", "entries", "output"):
            if key in result and isinstance(result[key], list):
                return result[key]

        # 2. Find any value that is a non-empty list
        for val in result.values():
            if isinstance(val, list) and val:
                return val

        # 3. Numeric-keyed dict {"0": {...}, "1": {...}} → reconstruct list
        if all(k.isdigit() for k in result.keys()):
            return [result[k] for k in sorted(result.keys(), key=int)]

        # 4. Single-item dict whose value is a dict → wrap in list
        if len(result) == 1:
            only = next(iter(result.values()))
            if isinstance(only, dict):
                return [only]

        raise ValueError(f"Expected JSON array, got object with keys: {list(result.keys())}")

    raise ValueError(f"Expected JSON array, got {type(result).__name__}")


def _repair_and_load(text: str):
    """
    Attempt to salvage truncated JSON (token limit hit mid-output).
    Handles both truncated arrays and truncated objects.
    """
    text = text.strip()
    if not text:
        raise json.JSONDecodeError("Empty input", text, 0)

    is_array = text.startswith("[")
    is_object = text.startswith("{")

    if not (is_array or is_object):
        raise json.JSONDecodeError("Cannot parse or repair JSON", text, 0)

    depth_brace = 0
    depth_bracket = 0
    in_string = False
    escape_next = False
    last_complete_obj_end = -1  # last `}` that closed a top-level object

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace -= 1
            if is_array and depth_brace == 0 and depth_bracket == 1:
                last_complete_obj_end = i
            elif is_object and depth_brace == 0:
                last_complete_obj_end = i
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket -= 1

    if last_complete_obj_end > 0:
        if is_array:
            repaired = text[: last_complete_obj_end + 1] + "]"
            result = json.loads(repaired)
            logger.warning("Repaired truncated JSON array — kept %d entries", len(result))
            return result
        else:
            repaired = text[: last_complete_obj_end + 1]
            result = json.loads(repaired)
            logger.warning("Repaired truncated JSON object")
            return result

    raise json.JSONDecodeError("Cannot parse or repair JSON", text, 0)
