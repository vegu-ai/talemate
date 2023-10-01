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
        
        try:
            isodate.parse_duration(self.args[0])
        except isodate.ISO8601Error:
            self.emit("system", "Invalid duration")
            return
        
        try:
            msg = self.args[1]
        except IndexError:
            msg = iso8601_duration_to_human(self.args[0], suffix=" later")
                
        message = TimePassageMessage(ts=self.args[0], message=msg)
        emit('time', message)
        
        self.scene.push_history(message)
        self.scene.emit_status()