from typing import TYPE_CHECKING

import structlog

from talemate.agents.base import AgentAction, AgentActionConfig
from talemate.instance import get_agent
from talemate.knowledge.absence import (
    ABSENCE_LIMIT,
    ABSENCE_WINDOW,
    absence_facts,
    render_absence_lines,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Character

__all__ = ["CharacterKnowledgeMixin"]

log = structlog.get_logger("talemate.agents.conversation.knowledge")


class CharacterKnowledgeMixin:
    """
    What the speaking character knows, applied to the conversation prompt.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["character_knowledge"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=True,
            icon="mdi-head-lightbulb-outline",
            label="Character Knowledge",
            description="Build the prompt from the speaking character's point of view: drop what they were not present for, retrieve only what they know, and tell the model what they do not know. No extra requests.",
            config={
                "perspective_filter": AgentActionConfig(
                    type="bool",
                    label="Perspective filter",
                    description="Drop spans of the history the character was not present for (replaced by a one-line gap) and filter long term memory by their knowledge.",
                    value=True,
                ),
                "absence_block": AgentActionConfig(
                    type="bool",
                    label="Absence block",
                    description="List the recent facts the character does not know, so the model does not let them act on those.",
                    value=True,
                ),
                "absence_limit": AgentActionConfig(
                    type="number",
                    label="Absence block lines",
                    description="At most this many facts in the absence block.",
                    value=ABSENCE_LIMIT,
                    min=1,
                    max=20,
                    step=1,
                ),
                "absence_window": AgentActionConfig(
                    type="number",
                    label="Absence block window",
                    description="How many of the most recent facts are considered for the block.",
                    value=ABSENCE_WINDOW,
                    min=5,
                    max=200,
                    step=5,
                ),
            },
        )

    @property
    def character_knowledge_enabled(self) -> bool:
        return self.resolve_enabled("character_knowledge")

    @property
    def knowledge_perspective_filter(self) -> bool:
        return self.character_knowledge_enabled and self.resolve_config(
            "character_knowledge", "perspective_filter"
        )

    @property
    def knowledge_absence_block(self) -> bool:
        return self.character_knowledge_enabled and self.resolve_config(
            "character_knowledge", "absence_block"
        )

    @property
    def knowledge_absence_limit(self) -> int:
        return int(self.resolve_config("character_knowledge", "absence_limit"))

    @property
    def knowledge_absence_window(self) -> int:
        return int(self.resolve_config("character_knowledge", "absence_window"))

    def rag_knowledge_viewer(self, character: "Character | None") -> str | None:
        """
        The name every filter site uses (sheets, pins, the context history,
        retrieval and the analysis prompts), or None when the perspective
        filter is off: the shared record for every character.
        """
        if character is None or not self.knowledge_perspective_filter:
            return None
        return character.name

    async def knowledge_perspective(self, character: "Character | None") -> str | None:
        """Template access to `rag_knowledge_viewer` (templates await agent actions)."""
        return self.rag_knowledge_viewer(character)

    async def absence_block(self, character: "Character | None") -> list[str]:
        if character is None or not self.knowledge_absence_block:
            log.debug(
                "absence_block skipped",
                character=character.name if character else None,
                enabled=self.knowledge_absence_block,
            )
            return []
        dedupe = get_agent("summarizer").archive_fact_dedupe_distance
        facts = await absence_facts(
            self.scene,
            character.name,
            limit=self.knowledge_absence_limit,
            window=self.knowledge_absence_window,
            dedupe_distance=dedupe,
        )
        lines = render_absence_lines(facts)
        log.debug("absence_block", character=character.name, lines=len(lines))
        return lines
