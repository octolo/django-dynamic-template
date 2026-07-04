"""Parse :class:`~dynamic_template.models.DynamicTemplateVariant` shortcut arguments."""

from __future__ import annotations

import json
from typing import Any


def _coerce_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
        return int(raw)
    try:
        return float(raw)
    except ValueError:
        pass
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        return raw[1:-1]
    return raw


def parse_variant_arguments(raw: str) -> dict[str, Any]:
    """
    Turn variant ``arguments`` text into a render-context dict.

    Supports JSON objects or space-separated tokens like the ``dyntpl`` tag::

        woman
        woman=true debug
        {"woman": true, "title": "Hello"}
    """
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Arguments JSON must be an object.")
        return parsed

    result: dict[str, Any] = {}
    for token in text.split():
        if "=" in token:
            key, _, val = token.partition("=")
            key = key.strip()
            if not key:
                raise ValueError(f"Invalid argument token {token!r}.")
            result[key] = _coerce_value(val.strip())
        else:
            result[token] = True
    return result
