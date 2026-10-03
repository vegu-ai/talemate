"""How much character knowledge is out of sync: what a Repair would rebuild."""

from typing import TYPE_CHECKING

from pydantic import BaseModel

from talemate.agents.summarize.perceptions import (
    eligible_passage,
    never_analyzed,
    perception_staleness,
)
from talemate.instance import get_agent
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.perspectives import PerspectiveReadContext, message_sources
from talemate.knowledge.revision_refresh import turn_analyzes_revision
from talemate.knowledge.summaries import summary_repair_work

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = ["KnowledgeSync", "knowledge_sync"]


class KnowledgeSync(BaseModel):
    """Out-of-sync pieces: passages, and summary entries per layer (0 is the base)."""

    passages: int = 0
    summaries: int = 0
    summary_layers: dict[int, int] = {}

    @property
    def total(self) -> int:
        return self.passages + self.summaries


def _new_line(message) -> bool:
    """A line the next turn analyzes on its own."""
    if message.revision_state is None or message.revision_matches_baseline:
        return never_analyzed(message)
    return turn_analyzes_revision(message)


def knowledge_sync(scene: "Scene") -> KnowledgeSync | None:
    if not character_knowledge_enabled(scene):
        return None
    read = PerspectiveReadContext(scene)
    passages = sum(
        1
        for message in message_sources(scene)
        if eligible_passage(message)
        and message.knowledge is not None
        and not _new_line(message)
        and perception_staleness(scene, message, read=read) is not None
    )
    queued = get_agent("summarizer")._summary_dirty.get(scene, set())
    summarizer = get_agent("summarizer")
    layers: dict[int, int] = {}
    for layer, identity, names in summary_repair_work(scene):
        # a new entry already queued is built by the next turn
        if all(
            (layer, identity, name) in queued
            and summarizer._never_built(scene, layer, identity, name)
            for name in names
        ):
            continue
        layers[layer] = layers.get(layer, 0) + 1
    return KnowledgeSync(
        passages=passages, summaries=sum(layers.values()), summary_layers=layers
    )
