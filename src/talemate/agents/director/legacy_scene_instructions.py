from typing import TYPE_CHECKING
import structlog
from talemate.agents.base import (
    set_processing,
)
from talemate.game.engine import GameInstructionsMixin
import talemate.emit.async_signals
from talemate.events import GameLoopActorIterEvent, SceneStateEvent

log = structlog.get_logger("talemate.agents.conversation.legacy_scene_instructions")

class LegacySceneInstructionsMixin(
    GameInstructionsMixin,
):
    """
    Legacy support for scoped api instructions in scenes.
    
    This is being replaced by node based in structions, but kept for backwards compatibility.
    
    THIS WILL BE DEPRECATED IN THE FUTURE.
    """
    
    # signal connect
    
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("game_loop_actor_iter").connect(self.LSI_on_player_dialog)
        talemate.emit.async_signals.get("scene_init").connect(self.LSI_on_scene_init)
        
    async def LSI_on_scene_init(self, event: SceneStateEvent):
        """
        LEGACY: If game state instructions specify to be run at the start of the game loop
        we will run them here.
        """

        if not self.enabled:
            if await self.scene_has_instructions(self.scene):
                self.is_enabled = True
            else:
                return

        if not await self.scene_has_instructions(self.scene):
            return

        if not self.scene.game_state.ops.run_on_start:
            return

        log.info("on_game_loop_start - running game state instructions")
        await self.LSI_run_gamestate_instructions()

    async def LSI_on_player_dialog(self, event: GameLoopActorIterEvent):
        if not self.enabled:
            return

        if not await self.scene_has_instructions(self.scene):
            return

        if not event.actor.character.is_player:
            return
        
        log.warning(f"LSI_on_player_dialog is being DEPRECATED. Please use the new node based instructions. Support for this will be removed in the future.")

        if event.game_loop.had_passive_narration:
            log.debug(
                "director.on_player_dialog",
                skip=True,
                had_passive_narration=event.game_loop.had_passive_narration,
            )
            return

        event.game_loop.had_passive_narration = await self.LSI_direct()

    async def LSI_direct(self) -> bool:
        # no character, see if there are NPC characters at all
        # if not we always want to direct narration
        always_direct = (
            not self.scene.npc_character_names
            or self.scene.game_state.ops.always_direct
        )
        
        log.warning(f"LSI_direct is being DEPRECATED. Please use the new node based instructions. Support for this will be removed in the future.", always_direct=always_direct)

        next_direct = self.next_direct_scene

        TURNS = 5

        if (
            next_direct % TURNS != 0
            or next_direct == 0
        ):
            if not always_direct:
                log.info("direct", skip=True, next_direct=next_direct)
                self.next_direct_scene += 1
                return False

        self.next_direct_scene = 0
        await self.LSI_direct_scene()
        return True

    @set_processing
    async def LSI_run_gamestate_instructions(self):
        """
        Run game state instructions, if they exist.
        """

        if not await self.scene_has_instructions(self.scene):
            return

        await self.LSI_direct_scene()

    @set_processing
    async def LSI_direct_scene(self):
        """
        LEGACY: Direct the scene based scoped api scene instructions.
        This is being replaced by node based instructions, but kept for 
        backwards compatibility.
        """
        log.warning(f"Direct python scene instructions are being DEPRECATED. Please use the new node based instructions. Support for this will be removed in the future.")
        await self.run_scene_instructions(self.scene)