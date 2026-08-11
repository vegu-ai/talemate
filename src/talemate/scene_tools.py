from typing import Literal

import pydantic

__all__ = [
    "SceneToolAction",
    "SCENE_TOOL_ACTIONS",
]


class SceneToolAction(pydantic.BaseModel):
    id: str
    section: Literal["narrator", "actor", "director", "visual"]
    label: str
    per_character: bool = False
    # a per-character action that also works without a target renders one
    # extra entry with no character bound to it
    include_unbound: bool = False


SCENE_TOOL_ACTIONS: list[SceneToolAction] = [
    SceneToolAction(
        id="narrator.progress",
        section="narrator",
        label="Progress Story",
    ),
    SceneToolAction(
        id="narrator.narrate_environment",
        section="narrator",
        label="Narrate Environment",
    ),
    SceneToolAction(
        id="narrator.look_at_scene",
        section="narrator",
        label="Look at Scene",
    ),
    SceneToolAction(
        id="narrator.look_at_character",
        section="narrator",
        label="Look at Character",
        per_character=True,
    ),
    SceneToolAction(
        id="conversation.request_actor_action",
        section="actor",
        label="Actor Action",
        per_character=True,
        include_unbound=True,
    ),
    SceneToolAction(
        id="director.request_dynamic_choices",
        section="director",
        label="Generate dynamic actions",
    ),
    SceneToolAction(
        id="director.scene_direction_turn",
        section="director",
        label="Scene direction turn",
    ),
    SceneToolAction(
        id="visual.visualize_environment_card",
        section="visual",
        label="Visualize Scene (Card)",
    ),
    SceneToolAction(
        id="visual.visualize_environment_background",
        section="visual",
        label="Visualize Scene (Background)",
    ),
    SceneToolAction(
        id="visual.visualize_character_card",
        section="visual",
        label="Visualize Character (Card)",
        per_character=True,
    ),
    SceneToolAction(
        id="visual.visualize_character_portrait",
        section="visual",
        label="Visualize Character (Portrait)",
        per_character=True,
    ),
]
