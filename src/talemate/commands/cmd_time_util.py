"""
Commands to manage scene timescale
"""

import asyncio
import logging

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.prompts.base import set_default_sectioning_handler
from talemate.scene_message import TimePassageMessage
from talemate.util import iso8601_duration_to_human
from talemate.emit import wait_for_input, emit
import talemate.instance as instance
import isodate

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
        
        
        world_state = instance.get_agent("world_state")
        await world_state.advance_time(self.args[0])