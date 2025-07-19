from __future__ import annotations

import talemate.client as client
from talemate.agents.base import Agent, set_processing
from talemate.agents.registry import register
from talemate.agents.memory.rag import MemoryRAGMixin
from talemate.prompts import Prompt

from .assistant import AssistantMixin
from .character import CharacterCreatorMixin
from .scenario import ScenarioCreatorMixin

from talemate.agents.base import AgentAction

import talemate.agents.creator.nodes  # noqa: F401


@register()
class CreatorAgent(
    CharacterCreatorMixin,
    ScenarioCreatorMixin,
    AssistantMixin,
    MemoryRAGMixin,
    Agent,
):
    """
    Creates characters and scenarios and other fun stuff!
    """

    agent_type = "creator"
    verbose_name = "Creator"

    @classmethod
    def init_actions(cls) -> dict[str, AgentAction]:
        actions = {}
        MemoryRAGMixin.add_actions(actions)
        AssistantMixin.add_actions(actions)
        return actions

    def __init__(
        self,
        client: client.ClientBase | None = None,
        **kwargs,
    ):
        self.client = client
        self.actions = CreatorAgent.init_actions()

    @set_processing
    async def generate_title(self, text: str):
        title = await Prompt.request(
            "creator.generate-title",
            self.client,
            "create_short",
            vars={
                "text": text,
            },
        )
        return title
