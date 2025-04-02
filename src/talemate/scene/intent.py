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
    SceneType,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene