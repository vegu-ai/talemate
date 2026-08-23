from decimal import Decimal
from typing import Any, Literal

import pydantic
import structlog

from talemate.util.data import coerce_forced_list

from talemate.world_state import WorldState
from talemate.game.state import GameState


__all__ = [
    "GameStatePathSettings",
    "load_game_state_path_settings",
    "prune_game_state_path_settings",
    "SceneType",
    "ScenePhase",
    "SceneIntent",
    "SceneState",
    "ScenePerspectives",
    "PerspectiveRole",
]


log = structlog.get_logger("talemate.scene.schema")

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


class GameStatePathSettings(pydantic.BaseModel):
    """
    How one pinned game state path is presented and limited in the knob
    toolbar and in Debug Vars.
    """

    label: str | None = None
    description: str | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: int | float | None = None
    slider: bool = False
    choices: list[str] = pydantic.Field(default_factory=list)
    read_only: bool = False
    order: int | None = None

    @pydantic.field_validator("label", "description")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @pydantic.field_validator("choices", mode="before")
    @classmethod
    def repair_forced_list_choices(cls, value):
        # a force-mode delta can leave an int-keyed dict where this list was,
        # and the whole settings entry is dropped if it fails to validate
        converted, was_forced = coerce_forced_list(value)
        return converted if was_forced else value

    @pydantic.field_validator("choices")
    @classmethod
    def validate_choices(cls, value: list[str]) -> list[str]:
        return [choice.strip() for choice in value if choice and choice.strip()]

    @pydantic.field_validator("step")
    @classmethod
    def validate_step(cls, value: int | float | None) -> int | float | None:
        if value is not None and value <= 0:
            raise ValueError("step must be greater than zero")
        return value

    @pydantic.model_validator(mode="after")
    def validate_bounds(self) -> "GameStatePathSettings":
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum must not be greater than maximum")
        return self

    @property
    def is_default(self) -> bool:
        return not self.model_dump(exclude_defaults=True)

    @property
    def constrains_numbers(self) -> bool:
        return (
            self.minimum is not None
            or self.maximum is not None
            or self.step is not None
        )

    def _snap(self, value: int | float) -> int | float:
        base = self.minimum if self.minimum is not None else 0
        snapped = base + round((value - base) / self.step) * self.step
        # binary floats make a stepped value drift; the grid is only ever as
        # fine as the step and the offset it is measured from
        decimals = max(
            -Decimal(str(base)).as_tuple().exponent,
            -Decimal(str(self.step)).as_tuple().exponent,
            0,
        )
        return round(snapped, decimals)

    @property
    def _grid_is_fractional(self) -> bool:
        return any(
            bound is not None and not float(bound).is_integer()
            for bound in (self.minimum, self.maximum, self.step)
        )

    def constrain(self, value: int | float) -> int | float:
        constrained = value
        if self.step is not None:
            constrained = self._snap(constrained)
        if self.minimum is not None:
            constrained = max(constrained, self.minimum)
        if self.maximum is not None:
            constrained = min(constrained, self.maximum)
        # the type follows the grid rather than the input: every value on an
        # integral grid is an integer, whatever was typed to reach it
        if float(constrained).is_integer() and not self._grid_is_fractional:
            return int(constrained)
        return float(constrained)


def load_game_state_path_settings(
    data: Any, pinned_paths: set[str]
) -> dict[str, "GameStatePathSettings"]:
    if not isinstance(data, dict):
        return {}

    settings_map: dict[str, GameStatePathSettings] = {}
    for path, raw in data.items():
        if path not in pinned_paths or not isinstance(raw, dict):
            continue
        try:
            settings = GameStatePathSettings(**raw)
        except pydantic.ValidationError as exc:
            log.warning(
                "Dropping unusable game state path settings", path=path, error=str(exc)
            )
            continue
        if not settings.is_default:
            settings_map[path] = settings

    return settings_map


def prune_game_state_path_settings(
    settings_map: dict[str, "GameStatePathSettings"], pinned_paths: set[str]
) -> dict[str, "GameStatePathSettings"]:
    return {
        path: settings
        for path, settings in settings_map.items()
        if path in pinned_paths and not settings.is_default
    }


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
