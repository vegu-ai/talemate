import json
from typing import Literal

import yaml

__all__ = [
    "strip_call_blocks",
]


def strip_call_blocks(response: str, schema_format: Literal["json", "yaml"]) -> str:
    """
    Remove fenced code blocks that hold focal function calls from the visible
    response text, leaving any other fenced blocks (code examples etc.) intact.
    """
    parts = response.split("```")
    kept: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            kept.append(part)
            continue
        block = part.strip()
        if block.startswith(schema_format):
            block = block[len(schema_format) :].strip()
        if _is_call_payload(block, schema_format):
            continue
        kept.append(f"```{part}```")
    return "".join(kept).strip()


def _is_call_payload(block: str, schema_format: Literal["json", "yaml"]) -> bool:
    try:
        if schema_format == "yaml":
            data = yaml.safe_load(block)
        else:
            data = json.loads(block)
    except Exception:
        return False
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        return False
    return all(
        isinstance(item, dict) and ("function" in item or "name" in item)
        for item in data
    )
