import asyncio
import random

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import wait_for_input
from talemate.scene_message import DirectorMessage

__all__ = [
    "CmdAIDialogue",
    "CmdAIDialogueSelective",
    "CmdAIDialogueDirected",
]


@register
class CmdAIDialogue(TalemateCommand):
    """
    Command class for the 'ai_dialogue' command
    """

    name = "ai_dialogue"
    description = "Generate dialogue for an AI selected actor"
    aliases = ["dlg"]

    async def run(self):
        conversation_agent = self.scene.get_helper("conversation").agent

        actor = None

        # if there is only one npc in the scene, use that

        if len(self.scene.npc_character_names) == 1:
            actor = list(self.scene.get_npc_characters())[0].actor
        else:
            if conversation_agent.actions["natural_flow"].enabled:
                await conversation_agent.apply_natural_flow(force=True, npcs_only=True)
                character_name = self.scene.next_actor
                try:
                    actor = self.scene.get_character(character_name).actor
                except AttributeError:
                    return

                if actor.character.is_player:
                    actor = random.choice(list(self.scene.get_npc_characters())).actor
            else:
                # randomly select an actor
                actor = random.choice(list(self.scene.get_npc_characters())).actor

        if not actor:
            return

        messages = await actor.talk()

        self.scene.process_npc_dialogue(actor, messages)


@register
class CmdAIDialogueSelective(TalemateCommand):
    """
    Command class for the 'ai_dialogue_selective' command

    Will allow the player to select which npc dialogue will be generated
    for
    """

    name = "ai_dialogue_selective"

    description = "Generate dialogue for an AI selected actor"

    aliases = ["dlg_selective"]

    async def run(self):
        npc_name = self.args[0]

        character = self.scene.get_character(npc_name)

        if not character:
            self.emit("system_message", message=f"Character not found: {npc_name}")
            return

        actor = character.actor

        messages = await actor.talk()

        self.scene.process_npc_dialogue(actor, messages)


@register
class CmdAIDialogueDirected(TalemateCommand):
    """
    Command class for the 'ai_dialogue_directed' command

    Will allow the player to select which npc dialogue will be generated
    for
    """

    name = "ai_dialogue_directed"

    description = "Generate dialogue for an AI selected actor"

    aliases = ["dlg_directed"]

    async def run(self):
        npc_name = self.args[0]

        character = self.scene.get_character(npc_name)

        if not character:
            self.emit("system_message", message=f"Character not found: {npc_name}")
            return

        prefix = f'Director instructs {character.name}: "To progress the scene, i want you to'

        direction = await wait_for_input(prefix + "... (enter your instructions)")
        direction = f'{prefix} {direction}"'

        director_message = DirectorMessage(direction, source=character.name)

        self.emit("director", director_message, character=character)

        self.scene.push_history(director_message)

        actor = character.actor

        messages = await actor.talk()

        self.scene.process_npc_dialogue(actor, messages)
