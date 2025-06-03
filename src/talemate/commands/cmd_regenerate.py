from talemate.client.context import ClientContext
from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.context import RegenerationContext
from talemate.emit import wait_for_input
from talemate.regenerate import regenerate

__all__ = [
    "CmdRegenerate",
    "CmdRegenerateWithDirection",
]


@register
class CmdRegenerate(TalemateCommand):
    """
    Command class for the 'regenerate' command
    """

    name = "regenerate"
    description = "Regenerate the scene"
    aliases = ["rr"]

    async def run(self):
        nuke_repetition = self.args[0] if self.args else 0.0
        with ClientContext(nuke_repetition=nuke_repetition):
            await regenerate(self.scene, -1)


@register
class CmdRegenerateWithDirection(TalemateCommand):
    """
    Command class for the 'regenerate_directed' command
    """

    name = "regenerate_directed"
    description = "Regenerate the scene with a direction"
    aliases = ["rrd"]

    label = "Directed Regenerate"

    async def run(self):
        nuke_repetition = self.args[0] if self.args else 0.0
        method = self.args[1] if len(self.args) > 1 else "replace"

        if method not in ["replace", "edit"]:
            raise ValueError(
                f"Unknown method: {method}. Valid methods are 'replace' and 'edit'."
            )

        if method == "replace":
            hint = ""
        else:
            hint = " (subtle change to previous generation)"

        direction = await wait_for_input(f"Instructions for regeneration{hint}: ")

        with RegenerationContext(self.scene, direction=direction, method=method):
            with ClientContext(direction=direction, nuke_repetition=nuke_repetition):
                await regenerate(self.scene, -1)
