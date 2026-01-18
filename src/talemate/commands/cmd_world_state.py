from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import emit, wait_for_input
from talemate.instance import get_agent

__all__ = [
    "CmdAddReinforcement",
    "CmdRemoveReinforcement",
    "CmdUpdateReinforcements",
    "CmdCheckPinConditions",
    "CmdApplyWorldStateTemplate",
    "CmdDetermineCharacterDevelopment",
]


@register
class CmdAddReinforcement(TalemateCommand):
    """
    Will attempt to create an actual character from a currently non
    tracked character in the scene, by name.

    Once persisted this character can then participate in the scene.
    """

    name = "add_reinforcement"
    description = "Add a reinforcement to the world state"
    aliases = ["ws_ar"]

    async def run(self):
        scene = self.scene

        world_state = scene.world_state

        if not len(self.args):
            question = await wait_for_input("Ask reinforcement question")
        else:
            question = self.args[0]

        await world_state.add_reinforcement(question)


@register
class CmdRemoveReinforcement(TalemateCommand):
    """
    Will attempt to create an actual character from a currently non
    tracked character in the scene, by name.

    Once persisted this character can then participate in the scene.
    """

    name = "remove_reinforcement"
    description = "Remove a reinforcement from the world state"
    aliases = ["ws_rr"]

    async def run(self):
        scene = self.scene

        world_state = scene.world_state

        if not len(self.args):
            question = await wait_for_input("Ask reinforcement question")
        else:
            question = self.args[0]

        idx, reinforcement = await world_state.find_reinforcement(question)

        if idx is None:
            raise ValueError(f"Reinforcement {question} not found.")

        await world_state.remove_reinforcement(idx)


@register
class CmdUpdateReinforcements(TalemateCommand):
    """
    Will attempt to create an actual character from a currently non
    tracked character in the scene, by name.

    Once persisted this character can then participate in the scene.
    """

    name = "update_reinforcements"
    description = "Update the reinforcements in the world state"
    aliases = ["ws_ur"]

    async def run(self):
        world_state = get_agent("world_state")

        await world_state.update_reinforcements(force=True)


@register
class CmdCheckPinConditions(TalemateCommand):
    """
    Will attempt to create an actual character from a currently non
    tracked character in the scene, by name.

    Once persisted this character can then participate in the scene.
    """

    name = "check_pin_conditions"
    description = "Check the pin conditions in the world state"
    aliases = ["ws_cpc"]

    async def run(self):
        world_state = get_agent("world_state")
        await world_state.check_pin_conditions()


@register
class CmdApplyWorldStateTemplate(TalemateCommand):
    """
    Will apply a world state template setting up
    automatic state tracking.
    """

    name = "apply_world_state_template"
    description = "Apply a world state template, creating an auto state reinforcement."
    aliases = ["ws_awst"]
    label = "Add state"

    async def run(self):
        scene = self.scene

        if not len(self.args):
            raise ValueError("No template name provided.")

        template_name = self.args[0]
        template_type = self.args[1] if len(self.args) > 1 else None

        character_name = self.args[2] if len(self.args) > 2 else None

        templates = await self.scene.world_state_manager.get_templates()

        try:
            template = getattr(templates, template_type)[template_name]
        except KeyError:
            raise ValueError(f"Template {template_name} not found.")

        reinforcement = (
            await scene.world_state_manager.apply_template_state_reinforcement(
                template, character_name=character_name, run_immediately=True
            )
        )

        response_data = {
            "template_name": template_name,
            "template_type": template_type,
            "reinforcement": reinforcement.model_dump() if reinforcement else None,
            "character_name": character_name,
        }

        if reinforcement is None:
            emit(
                "status",
                message="State already tracked.",
                status="info",
                data=response_data,
            )
        else:
            emit(
                "status",
                message="Auto state added.",
                status="success",
                data=response_data,
            )


@register
class CmdDetermineCharacterDevelopment(TalemateCommand):
    """
    Will analyze whether or not the specified character has had
    some major development in the story.
    """

    name = "determine_character_development"
    description = "Determine the development of a character"
    aliases = ["ws_dcd"]

    async def run(self):
        scene = self.scene

        world_state = get_agent("world_state")

        if not len(self.args):
            raise ValueError("No character name provided.")

        character_name = self.args[0]

        character = scene.get_character(character_name)

        if not character:
            raise ValueError(f"Character {character_name} not found.")

        await world_state.determine_character_development(character)
        # updates = await creator.update_character_sheet(character, instructions)
