from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.client.context import ClientContext
from talemate.context import RerunContext

from talemate.emit import wait_for_input

__all__ = [
    "CmdRerun",
    "CmdRerunWithDirection",
]

@register
class CmdRerun(TalemateCommand):
    """
    Command class for the 'rerun' command
    """

    name = "rerun"
    description = "Rerun the scene"
    aliases = ["rr"]

    async def run(self):
        nuke_repetition = self.args[0] if self.args else 0.0
        with ClientContext(nuke_repetition=nuke_repetition):
            await self.scene.rerun()
            
            
@register
class CmdRerunWithDirection(TalemateCommand):
    """
    Command class for the 'rerun_directed' command
    """

    name = "rerun_directed"
    description = "Rerun the scene with a direction"
    aliases = ["rrd"]
    
    label = "Directed Rerun"

    async def run(self):
        nuke_repetition = self.args[0] if self.args else 0.0
        method = self.args[1] if len(self.args) > 1 else "replace"
        
        
        
        if method not in ["replace", "edit"]:
            raise ValueError(f"Unknown method: {method}. Valid methods are 'replace' and 'edit'.")
        
        if method == "replace":
            hint = ""
        else:
            hint = " (subtle change to previous generation)"
        
        direction = await wait_for_input(f"Instructions for regeneration{hint}: ")
        
        with RerunContext(self.scene, direction=direction, method=method):
            with ClientContext(direction=direction, nuke_repetition=nuke_repetition):
                await self.scene.rerun()