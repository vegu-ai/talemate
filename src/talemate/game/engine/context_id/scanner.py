"""
Context ID scanner for parsing arbitrary text and extracting context IDs.
"""

import re
from typing import TYPE_CHECKING
import pydantic
import contextvars
import structlog
from .base import ContextIDItem, context_id_item_from_string


if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "ContextIDScanResult",
    "scan_text_for_context_ids",
]

log = structlog.get_logger("talemate.game.engine.context_id.scanner")

context_id_scan_state = contextvars.ContextVar("context_id_scan_state", default=None)


class OpenContextIDScanCollector:
    """Context ID scanner collector."""

    def __init__(self):
        self.context_ids = set()

    def __enter__(self):
        self.token = context_id_scan_state.set(self)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        context_id_scan_state.reset(self.token)


class ContextIDScanResult(pydantic.BaseModel):
    """Result of scanning text for context IDs."""

    resolved: list[ContextIDItem] = pydantic.Field(default_factory=list)
    unresolved: list[str] = pydantic.Field(default_factory=list)


async def scan_text_for_context_ids(text: str, scene: "Scene") -> ContextIDScanResult:
    """
    Scan text for context IDs in backtick-fenced format and resolve them.

    Looks for patterns like `context_type.path:id` or `context_type:path.id`.

    Args:
        text: The text to scan
        scene: The scene context for resolving context IDs

    Returns:
        ContextIDScanResult with resolved and unresolved context IDs
    """
    # Pattern to match backtick-fenced context IDs
    # Matches `word.word:id with spaces` or `word:id.with.spaces` patterns
    # Allows spaces in the ID part after the colon separator
    pattern = r"`([a-zA-Z_][a-zA-Z0-9_.]*:[^`]+)`"

    matches = re.findall(pattern, text)
    resolved = []
    unresolved = []

    for context_id_str in matches:
        try:
            context_id_item = await context_id_item_from_string(context_id_str, scene)
            if context_id_item:
                resolved.append(context_id_item)
            else:
                unresolved.append(context_id_str)
        except Exception:
            unresolved.append(context_id_str)

    state = context_id_scan_state.get()
    if state:
        for context_id_item in resolved:
            state.context_ids.add(str(context_id_item.context_id))

        log.debug("Context ID scan state", context_ids=state.context_ids)

    return ContextIDScanResult(resolved=resolved, unresolved=unresolved)
