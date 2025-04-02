import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import wait_for_input
from talemate.scene_message import NarratorMessage

__all__ = [
    "CmdNarrate",
    "CmdNarrateQ",
    "CmdNarrateProgress",
    "CmdNarrateProgressDirected",
    "CmdNarrateC",
]


@register
class CmdNarrate(TalemateCommand):
    """
    Command class for the 'narrate' command
    """

    name = "narrate"
    description = "Calls a narrator to narrate the scene"
    aliases = ["n"]

    async def run(self):
        narrator = self.scene.get_helper("narrator")

        if not narrator:
            self.system_message("No narrator found")
            return True

        narration = await narrator.agent.narrate_scene()
        message = NarratorMessage(narration, meta=narrator.action_to_meta("narrate_scene",{}))

        self.narrator_message(message)
        self.scene.push_history(message)


@register
class CmdNarrateQ(TalemateCommand):
    """
    Command class for the 'narrate_q' command
    """

    name = "narrate_q"
    description = "Will attempt to narrate using a specific question prompt"
    aliases = ["nq"]
    label = "Look at"

    async def run(self):
        narrator = self.scene.get_helper("narrator")

        if not narrator:
            self.system_message("No narrator found")
            return True

        if self.args:
            query = self.args[0]
            at_the_end = (
                (self.args[1].lower() == "true") if len(self.args) > 1 else False
            )
        else:
            query = await wait_for_input("Enter query: ")
            at_the_end = False

        narration = await narrator.agent.narrate_query(query, at_the_end=at_the_end)
        message = NarratorMessage(
            narration, meta=narrator.action_to_meta("narrate_query",{"query":query, "at_the_end":at_the_end})
        )

        self.narrator_message(message)
        self.scene.push_history(message)


@register
class CmdNarrateProgress(TalemateCommand):
    """
    Command class for the 'narrate_progress' command
    """

    name = "narrate_progress"
    description = "Calls a narrator to narrate the scene"
    aliases = ["np"]

    async def run(self):
        narrator = self.scene.get_helper("narrator")

        if not narrator:
            self.system_message("No narrator found")
            return True

        narration = await narrator.agent.progress_story()

        message = NarratorMessage(narration, meta=narrator.action_to_meta("progress_story",{}))

        self.narrator_message(message)
        self.scene.push_history(message)


@register
class CmdNarrateProgressDirected(TalemateCommand):
    """
    Command class for the 'narrate_progress_directed' command
    """

    name = "narrate_progress_directed"
    description = "Calls a narrator to narrate the scene"
    aliases = ["npd"]

    async def run(self):
        narrator = self.scene.get_helper("narrator")

        direction = await wait_for_input("Enter direction for the narrator: ")

        narration = await narrator.agent.progress_story(narrative_direction=direction)

        message = NarratorMessage(narration, meta=narrator.action_to_meta("progress_story",{"narrative_direction":direction}))

        self.narrator_message(message)
        self.scene.push_history(message)


@register
class CmdNarrateC(TalemateCommand):
    """
    Command class for the 'narrate_c' command
    """

    name = "narrate_c"
    description = "Calls a narrator to narrate a character"
    aliases = ["nc"]
    label = "Look at"

    async def run(self):
        narrator = self.scene.get_helper("narrator")

        if not narrator:
            self.system_message("No narrator found")
            return True

        if self.args:
            name = self.args[0]
        else:
            name = await wait_for_input("Enter character name: ")

        character = self.scene.get_character(name, partial=True)

        if not character:
            self.system_message(f"Character not found: {name}")
            return True

        narration = await narrator.agent.narrate_character(character)
        message = NarratorMessage(narration, meta=narrator.action_to_meta("narrate_character",{"character":character}))

        self.narrator_message(message)
        self.scene.push_history(message)


@register
class CmdNarrateDialogue(TalemateCommand):
    """
    Command class for the 'narrate_dialogue' command
    """

    name = "narrate_dialogue"
    description = "Calls a narrator to narrate a character"
    aliases = ["ndlg"]
    label = "Narrate dialogue"

    async def run(self):
        narrator = self.scene.get_helper("narrator")

        character_messages = self.scene.collect_messages("character", max_iterations=5)

        if not character_messages:
            self.system_message("No recent dialogue message found")
            return True

        character_message = character_messages[0]

        character_name = character_message.character_name

        character = self.scene.get_character(character_name)

        if not character:
            self.system_message(f"Character not found: {character_name}")
            return True

        narration = await narrator.agent.narrate_after_dialogue(character)
        message = NarratorMessage(
            narration, meta=narrator.action_to_meta("narrate_after_dialogue",{"character":character})
        )

        self.narrator_message(message)
        self.scene.push_history(message)
