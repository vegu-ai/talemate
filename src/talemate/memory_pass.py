"""What Refine memories with AI gave a character for one reply."""

from typing import Literal

import pydantic

__all__ = [
    "MemoryKind",
    "MemoryPassItem",
    "MemoryPassResult",
    "memory_pass_item",
]

MemoryKind = Literal[
    "story", "summary", "world", "character", "disclosure", "insight", "note"
]

CHARACTER_SHEET_TYPES = ("base_attribute", "details", "description")


class MemoryPassItem(pydantic.BaseModel):
    text: str
    # the text as retrieved, when the pass rewrote it
    retrieved: str | None = None
    kind: MemoryKind = "note"
    # the character or item the memory is about, when its source names one
    subject: str | None = None
    # chosen, but left out of the reply because its scene history already
    # holds the message
    in_scene: bool = False
    # the scene message a character's view of a message stands for
    _message_id: str | None = pydantic.PrivateAttr(default=None)


class MemoryPassResult(pydantic.BaseModel):
    # none: the pass answered that nothing should reach the reply;
    # fallback: its answer could not be read, so the candidates were kept as retrieved
    status: Literal["kept", "none", "fallback"]
    candidates: int
    kept: list[MemoryPassItem] = pydantic.Field(default_factory=list)
    dropped: list[MemoryPassItem] = pydantic.Field(default_factory=list)

    def without_messages(self, message_ids: set[str]) -> "MemoryPassResult":
        """
        The result as the reply's prompt received it: a kept view of a
        message already in the reply's history moves to `dropped`.
        """
        in_scene = [item for item in self.kept if item._message_id in message_ids]
        if not in_scene:
            return self
        return self.model_copy(
            update={
                "kept": [
                    item for item in self.kept if item._message_id not in message_ids
                ],
                "dropped": [
                    item.model_copy(update={"in_scene": True}) for item in in_scene
                ]
                + self.dropped,
            }
        )


def _kind_and_subject(meta) -> tuple[MemoryKind, str | None]:
    if not isinstance(meta, dict):
        # AI-assisted retrieval answers are plain strings
        return "insight", None
    typ = meta.get("typ")
    if typ == "history":
        if meta.get("knowledge_kind") in ("message", "intro"):
            return "story", None
        return "summary", None
    if typ == "disclosure":
        return "disclosure", None
    if typ in CHARACTER_SHEET_TYPES:
        return "character", meta.get("character")
    if typ == "world_state":
        return "world", meta.get("character") or meta.get("item")
    return "note", None


def memory_pass_item(candidate, text: str | None = None) -> MemoryPassItem:
    retrieved = str(candidate).strip()
    kept = (text or "").strip() or retrieved
    meta = getattr(candidate, "meta", None)
    kind, subject = _kind_and_subject(meta)
    item = MemoryPassItem(
        text=kept,
        retrieved=retrieved if kept != retrieved else None,
        kind=kind,
        subject=subject,
    )
    if isinstance(meta, dict) and meta.get("knowledge_kind") == "message":
        item._message_id = str(meta.get("knowledge_id"))
    return item
