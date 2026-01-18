"""
Intention of the story or a sub-scene. What are the expectations of the user and how do we meet them?

## Overarching Story Intent

What is the overarching intention of the story?

This is probably an abstract description of what type of experiences will be relayed by the story through individual scenes.

## Individual Scene Intent

What is the intention of the currently active scene?

Assumption: Carefully stating the intent of the scene (both in the context sent to the ai as well as enforced through certain parameters in talemate) can improve the general quality of the output.

The director agent can be informed on these to make adjustments to it's instructions and guidance to the actors and the narrator.
"""

from typing import TYPE_CHECKING

from .schema import (
    ScenePhase,
    SceneIntent,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "set_scene_phase",
]


async def set_scene_phase(
    scene: "Scene", scene_type_id: str, intent: str
) -> ScenePhase:
    """
    Set the scene phase.
    """

    scene_intent: SceneIntent = scene.intent_state

    if scene_type_id not in scene_intent.scene_types:
        raise ValueError(f"Invalid scene type: {scene_type_id}")

    scene_intent.phase = ScenePhase(
        scene_type=scene_type_id,
        intent=intent,
        start=scene.history[-1].id if scene.history else 0,
    )

    # Ensure UX stays in sync whenever scene phase/intention is updated.
    scene.emit_scene_intent()

    return scene_intent.phase
