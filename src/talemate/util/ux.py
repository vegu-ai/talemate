from __future__ import annotations

import json
from typing import Any

from talemate.game.engine.ux.schema import UXChoice

__all__ = [
    "json_load_maybe",
    "normalize_choices",
]


def json_load_maybe(value: str) -> Any:
    """
    Attempts to parse a string as JSON. Returns the parsed value if successful,
    otherwise returns the original string.
    """
    try:
        return json.loads(value)
    except Exception:
        return value


def normalize_choices(raw: Any) -> list[UXChoice]:
    """
    Normalizes various input formats into a list of UXChoice objects.

    Accepts:
    - list[str]
    - list[dict]
    - dict[label->value]
    - JSON string for any of the above
    - newline-separated string
    """
    if raw is None:
        return []

    if isinstance(raw, str):
        stripped = raw.strip()
        loaded = json_load_maybe(stripped)
        if isinstance(loaded, str) and loaded == stripped:
            # newline separated list
            lines = [ln.strip() for ln in raw.splitlines()]
            lines = [ln for ln in lines if ln]
            return [
                UXChoice(id=f"choice_{i}", label=label, value=label)
                for i, label in enumerate(lines)
            ]
        raw = loaded

    if isinstance(raw, dict):
        items = list(raw.items())
        return [
            UXChoice(
                id=f"choice_{i}",
                label=str(label),
                value=value,
            )
            for i, (label, value) in enumerate(items)
        ]

    if isinstance(raw, list):
        result: list[UXChoice] = []
        for i, item in enumerate(raw):
            if isinstance(item, UXChoice):
                result.append(item)
                continue
            if isinstance(item, str):
                result.append(UXChoice(id=f"choice_{i}", label=item, value=item))
                continue
            if isinstance(item, dict):
                # tolerate minimal dicts with just label/value
                if "id" not in item:
                    item = {**item, "id": f"choice_{i}"}
                if "label" not in item:
                    # if {<label>: <value>} is embedded as dict item
                    # Check if there are exactly 2 keys: "id" and one other key
                    if len(item.keys()) == 2 and "id" in item:
                        k = next(iter([k for k in item.keys() if k != "id"]), None)
                        if k is not None:
                            item = {
                                "id": item["id"],
                                "label": str(k),
                                "value": item.get(k),
                            }
                result.append(UXChoice(**item))
                continue

            # fallback: stringify
            result.append(UXChoice(id=f"choice_{i}", label=str(item), value=item))
        return result

    # fallback: single value
    return [UXChoice(id="choice_0", label=str(raw), value=raw)]
