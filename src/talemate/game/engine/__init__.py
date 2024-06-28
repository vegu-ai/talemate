import os
from typing import TYPE_CHECKING

import nest_asyncio
import structlog
from RestrictedPython import compile_restricted, safe_globals
from RestrictedPython.Eval import default_guarded_getitem, default_guarded_getiter
from RestrictedPython.Guards import guarded_iter_unpack_sequence, safer_getattr

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

from talemate.prompts.base import PrependTemplateDirectories, Prompt

from talemate.game.scope import OpenScopedContext, GameInstructionScope
import talemate.game.engine.api.exceptions as api_exceptions

log = structlog.get_logger("talemate.game.engine")
nest_asyncio.apply()

DEV_MODE = True


def compile_scene_module(module_code: str, **kwargs):
    # Compile the module code using RestrictedPython
    compiled_code = compile_restricted(
        module_code, filename="<scene instructions>", mode="exec"
    )

    # Create a restricted globals dictionary
    restricted_globals = safe_globals.copy()
    safe_locals = {}

    # Add custom variables, functions, or objects to the restricted globals
    restricted_globals.update(kwargs)
    restricted_globals["__name__"] = "__main__"
    restricted_globals["__metaclass__"] = type
    restricted_globals["_getiter_"] = default_guarded_getiter
    restricted_globals["_getitem_"] = default_guarded_getitem
    restricted_globals["_iter_unpack_sequence_"] = guarded_iter_unpack_sequence
    restricted_globals["getattr"] = safer_getattr
    restricted_globals["_write_"] = lambda x: x
    restricted_globals["hasattr"] = hasattr
    restricted_globals["exceptions"] = api_exceptions

    # Execute the compiled code with the restricted globals
    exec(compiled_code, restricted_globals, safe_locals)
    
    return safe_locals.get("game")


class GameInstructionsMixin:
    """
    Game instructions mixin for director agent.

    This allows Talemate scenarios to hook into the python api for more sophisticated
    gameplate mechanics and direct exposure to AI functionality.
    """

    @property
    def scene_module_path(self):
        return os.path.join(self.scene.save_dir, "game.py")

    async def scene_has_instructions(self, scene: "Scene") -> bool:
        """Returns True if the scene has instructions."""
        return await self.scene_has_module(
            scene
        ) or await self.scene_has_template_instructions(scene)

    async def run_scene_instructions(self, scene: "Scene"):
        """
        runs the game/__init__.py of the scene
        """

        if await self.scene_has_module(scene):
            await self.run_scene_module(scene)
        else:
            return await self.run_scene_template_instructions(scene)

    # SCENE TEMPLATE INSTRUCTIONS SUPPORT

    async def scene_has_template_instructions(self, scene: "Scene") -> bool:
        """Returns True if the scene has an instructions template."""
        instructions_template_path = os.path.join(
            scene.template_dir, "instructions.jinja2"
        )
        return os.path.exists(instructions_template_path)

    async def run_scene_template_instructions(self, scene: "Scene"):
        client = self.client
        game_state = scene.game_state

        if not await self.scene_has_template_instructions(self.scene):
            return

        log.info("Running scene instructions from jinja2 template", scene=scene)
        with PrependTemplateDirectories([scene.template_dir]):
            prompt = Prompt.get(
                "instructions",
                {
                    "scene": scene,
                    "max_tokens": client.max_token_length,
                    "game_state": game_state,
                },
            )

            prompt.client = client
            instructions = prompt.render().strip()
            log.info(
                "Initialized game state instructions",
                scene=scene,
                instructions=instructions,
            )
            return instructions

    # SCENE PYTHON INSTRUCTIONS SUPPORT

    async def run_scene_module(self, scene: "Scene"):
        """
        runs the game/__init__.py of the scene
        """

        if not await self.scene_has_module(scene):
            return

        await self.load_scene_module(scene)

        log.info("Running scene instructions from python module", scene=scene)

        with OpenScopedContext(self.scene, self.client):
            with PrependTemplateDirectories(self.scene.template_dir):
                scene._module()

        if DEV_MODE:
            # delete the module so it can be reloaded
            # on the next run
            del scene._module

    async def load_scene_module(self, scene: "Scene"):
        """
        loads the game.py of the scene
        """

        if not await self.scene_has_module(scene):
            return

        if hasattr(scene, "_module"):
            log.warning("Scene already has a module loaded")
            return

        # file path to the game/__init__.py file of the scene
        module_path = self.scene_module_path

        # read thje file into _module property
        with open(module_path, "r") as f:
            module_code = f.read()
            scene._module = GameInstructionScope(
                director=self,
                log=log,
                scene=scene,
                module_function=compile_scene_module(module_code),
            )

    async def scene_has_module(self, scene: "Scene"):
        """
        checks if the scene has a game.py
        """

        return os.path.exists(self.scene_module_path)
