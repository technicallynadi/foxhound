"""Robust JSON parser for LLM outputs.

Handles common issues: markdown fences, extra text before/after JSON,
trailing commas, and mixed text+JSON responses.
"""

from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict | list | None:
    """Extract a JSON object or array from text that may contain extra content.

    Handles:
    - ```json ... ``` fences
    - Extra text before/after the JSON
    - Trailing text after closing } or ]
    """
    if not text:
        return None

    # Strip markdown fences
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find a JSON object { ... }
    obj_match = re.search(r"\{[\s\S]*\}", cleaned)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError:
            pass

    # Try to find a JSON array [ ... ]
    arr_match = re.search(r"\[[\s\S]*\]", cleaned)
    if arr_match:
        try:
            return json.loads(arr_match.group(0))
        except json.JSONDecodeError:
            pass

    return None
