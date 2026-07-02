from typing import Literal

import pydantic

from talemate.world_state import WorldState
from talemate.game.state import GameState


__all__ = [
    "SceneType",
    "ScenePhase",
    "SceneIntent",
    "SceneState",
    "ScenePerspectives",
    "PerspectiveRole",
]


PerspectiveRole = Literal["default", "player", "other", "narrator"]


class ScenePerspectives(pydantic.BaseModel):
    """
    Narrative perspective / tense configuration for a scene.

    `default` is the scene-wide perspective shown in ambient prompt context.
    The other three are speaker-specific overrides: when a prompt is generated
    on behalf of the player character, an NPC, or the narrator, the matching
    field is preferred over `default`. Empty overrides fall back to `default`.
    """

    default: str = ""
    player: str = ""
    other: str = ""
    narrator: str = ""

    def for_role(self, role: PerspectiveRole | str | None) -> str:
        default = (self.default or "").strip()
        if not role or role == "default":
            return default
        value = getattr(self, role, None)
        if value and value.strip():
            return value.strip()
        return default


def make_default_types() -> list["SceneType"]:
    return {
        "roleplay": SceneType(
            id="roleplay",
            name="Roleplay",
            description="Freeform dialogue between one or more characters with occasional narration.",
        )
    }


def make_default_phase() -> "ScenePhase":
    default_type = make_default_types().get("roleplay")
    return ScenePhase(scene_type=default_type.id)


class SceneType(pydantic.BaseModel):
    id: str
    name: str
    description: str
    instructions: str | None = None
    instruction_template: str | None = None


class ScenePhase(pydantic.BaseModel):
    scene_type: str
    intent: str | None = None


class SceneDirectionConfig(pydantic.BaseModel):
    always_on: bool = False
    run_immediately: bool = False


class SceneIntent(pydantic.BaseModel):
    scene_types: dict[str, SceneType] | None = pydantic.Field(
        default_factory=make_default_types
    )
    intent: str | None = None
    instructions: str | None = None
    instruction_template: str | None = None
    direction: SceneDirectionConfig = pydantic.Field(
        default_factory=SceneDirectionConfig
    )
    phase: ScenePhase | None = pydantic.Field(default_factory=make_default_phase)
    start: int = 0

    @property
    def current_scene_type(self) -> SceneType:
        return self.scene_types[self.phase.scene_type]

    @property
    def active(self) -> bool:
        return self.intent or self.phase

    def get_scene_type(self, scene_type_id: str) -> SceneType:
        return self.scene_types[scene_type_id]

    def reset(self):
        self.phase = make_default_phase()
        self.start = 0


class SceneState(pydantic.BaseModel):
    world_state: "WorldState | None" = None
    game_state: "GameState | None" = None
    agent_state: dict | None = None
    intent_state: SceneIntent | None = None

    def model_dump(self, **kwargs):
        return super().model_dump(exclude_none=True)
