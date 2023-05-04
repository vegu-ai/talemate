import asyncio

from talemate.commands.base import TalemateCommand
from talemate.commands.manager import register
from talemate.exceptions import RestartSceneLoop


@register
class CmdSetEnvironmentToScene(TalemateCommand):
    """
    Command class for the 'setenv_scene' command
    """

    name = "setenv_scene"
    description = "Changes the scene environment to `scene` making it playable"
    aliases = [""]

    async def run(self):
        await asyncio.sleep(0)
        
        player_character = self.scene.get_player_character()
        
        if not player_character:
            self.system_message("No player character found")
            return True
        
        self.scene.set_environment("scene")
        
        self.system_message(f"Game mode")
        
        raise RestartSceneLoop()
    
        
        
@register
class CmdSetEnvironmentToCreative(TalemateCommand):
    """
    Command class for the 'setenv_scene' command
    """

    name = "setenv_creative"
    description = "Changes the scene environment to `creative` making it editable"
    aliases = [""]

    async def run(self):
        
        await asyncio.sleep(0)
        self.scene.set_environment("creative")
        
        raise RestartSceneLoop()
