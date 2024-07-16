from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional, TypeVar, Union

import pydantic

from talemate.instance import get_agent
from talemate.world_state import InsertionMode, Reinforcement
from talemate.world_state.templates.base import Template, register

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "StateReinforcement",
]


class GeneratedStateReinforcement(pydantic.BaseModel):
    query: str
    reinforcement: "Reinforcement"
    character: str
    template: "StateReinforcement"


@register("state_reinforcement")
class StateReinforcement(Template):
    name: str
    query: str
    state_type: str = "npc"
    insert: InsertionMode = InsertionMode.sequential
    instructions: str | None = None
    description: str | None = None
    interval: int = 10
    auto_create: bool = False
    template_type: str = "state_reinforcement"

    @pydantic.field_serializer("insert")
    def serialize_insert(self, value: InsertionMode, _info) -> str:
        return value.value

    async def generate(
        self,
        scene: "Scene",
        character_name: str = None,
        run_immediately: bool = False,
    ) -> GeneratedStateReinforcement:
        """
        Applies a state reinforcement template to a specific character, if provided.

        Arguments:
            template: The StateReinforcementTemplate object defining the reinforcement details. Can also be a string representing the template name.
            character_name: Optional; the name of the character to apply the template to.
            run_immediately: Whether to run the reinforcement immediately after applying.

        Returns:
            A Reinforcement object if the template is applied, or None if the reinforcement already exists.

        Raises:
            ValueError: If a character name is required but not provided.
        """

        if not character_name and self.state_type in ["npc", "character", "player"]:
            raise ValueError("Character name required for this template type.")

        world_state = scene.world_state
        world_state_agent = get_agent("world_state")
        question = self.formatted("query", scene, character_name=character_name)
        instructions = self.formatted(
            "instructions", scene, character_name=character_name
        )

        reinforcement = await world_state.add_reinforcement(
            question,
            character_name,
            instructions,
            self.interval,
            insert=self.insert,
        )

        if run_immediately:
            await world_state_agent.update_reinforcement(question, character_name)

        return GeneratedStateReinforcement(
            query=question,
            reinforcement=reinforcement,
            character=character_name,
            template=self,
        )
