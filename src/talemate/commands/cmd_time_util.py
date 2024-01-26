"""
Commands to manage scene timescale
"""

import asyncio
import logging

import isodate

import talemate.instance as instance
from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.emit import wait_for_input

__all__ = [
    "CmdAdvanceTime",
]


@register
class CmdAdvanceTime(TalemateCommand):
    """
    Command class for the 'advance_time' command
    """

    name = "advance_time"
    description = "Advance the scene time by a given amount (expects iso8601 duration))"
    aliases = ["time_a"]

    async def run(self):
        if not self.args:
            self.emit("system", "You must specify an amount of time to advance")
            return

        narrator = instance.get_agent("narrator")
        narration_prompt = None

        # if narrator has narrate_time_passage action enabled ask the user
        # for a prompt to guide the narration

        if (
            narrator.actions["narrate_time_passage"].enabled
            and narrator.actions["narrate_time_passage"].config["ask_for_prompt"].value
        ):
            narration_prompt = await wait_for_input(
                "Enter a prompt to guide the time passage narration (or leave blank): "
            )

            if not narration_prompt.strip():
                narration_prompt = None

        world_state = instance.get_agent("world_state")
        await world_state.advance_time(self.args[0], narration_prompt)
