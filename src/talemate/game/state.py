import asyncio
import copy
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal

import pydantic
import structlog

from talemate.context import active_scene
from talemate.events import GameStateChangedEvent
from talemate.instance import get_agent
from talemate.prompts.base import send_soon_outside_render
from talemate.util.data import coerce_forced_list
from talemate.util.path import get_path_parent, split_state_path

if TYPE_CHECKING:
    from talemate.agents.memory import MemoryAgent
    from talemate.tale_mate import Scene
    from talemate.agents.director import DirectorAgent

log = structlog.get_logger("game_state")


def game_state_leaves(variables: dict, prefix: str = "") -> dict[str, Any]:
    """
    Every leaf of the variables by its path ('a/b/c'). A nested dict is
    followed and is no leaf itself, so an empty dict has no leaves.
    """
    leaves = {}
    for key, value in variables.items():
        path = f"{prefix}/{key}" if prefix else str(key)
        if isinstance(value, dict):
            leaves.update(game_state_leaves(value, path))
        else:
            leaves[path] = value
    return leaves


def _same_value(a: Any, b: Any) -> bool:
    # type-strict: 1, 1.0 and True are different game state values
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same_value(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(map(_same_value, a, b))
    return a == b


def _leaves_under(variables: dict, keys: Iterable[str] | None) -> dict[str, Any]:
    if keys is None:
        subset = variables
    else:
        subset = {key: variables[key] for key in keys if key in variables}
    return copy.deepcopy(game_state_leaves(subset))


def _write_game_state(
    game_state: "GameState",
    scene: "Scene | None",
    write: Callable[[dict], Any],
    keys: Iterable[str] | None = None,
) -> Any:
    """
    The one write path of the game state variables. `write` changes the
    variables dict; `keys` names the top-level keys it can touch (None: any).
    A game_state.changed event goes out for each leaf path whose value
    changed, a removed path with value None. The events are sent in tasks,
    after a template render the write happens in, so no listener runs inside
    the writer's lock, render or websocket handler.
    """
    keys = None if keys is None else list(keys)
    before = _leaves_under(game_state.variables, keys)
    result = write(game_state.variables)
    after = _leaves_under(game_state.variables, keys)
    _send_changes(scene, before, after)
    return result


def _send_changes(
    scene: "Scene | None", before: dict[str, Any], after: dict[str, Any]
) -> None:
    changes = [
        (path, after.get(path), before.get(path))
        for path in {**before, **after}
        if not _same_value(before.get(path), after.get(path))
    ]
    if not changes or scene is None:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        log.warning(
            "game_state.changed not sent: no running event loop",
            paths=[path for path, _, _ in changes],
        )
        return
    for path, value, previous_value in changes:
        send_soon_outside_render(
            "game_state.changed",
            GameStateChangedEvent(
                scene=scene,
                event_type="game_state.changed",
                path=path,
                value=value,
                previous_value=previous_value,
            ),
        )


class Goal(pydantic.BaseModel):
    description: str
    id: int
    status: bool = False


class Instructions(pydantic.BaseModel):
    character: dict[str, str] = pydantic.Field(default_factory=dict)


class Ops(pydantic.BaseModel):
    run_on_start: bool = False
    always_direct: bool = False


class GameState(pydantic.BaseModel):
    ops: Ops = Ops()
    variables: dict[str, Any] = pydantic.Field(default_factory=dict)
    goals: list[Goal] = pydantic.Field(default_factory=list)
    instructions: Instructions = pydantic.Field(default_factory=Instructions)

    @property
    def director(self) -> "DirectorAgent":
        return get_agent("director")

    @property
    def memory(self) -> "MemoryAgent":
        return get_agent("memory")

    @property
    def scene(self) -> "Scene":
        return self.director.scene

    @property
    def game_won(self) -> bool:
        return self.variables.get("__game_won__") is True

    def __getitem__(self, key: str) -> Any:
        return self.get_var(key)

    def __setitem__(self, key: str, value: Any):
        self.set_var(key, value)

    def __delitem__(self, key: str):
        return self.unset_var(key)

    def __contains__(self, key: str) -> bool:
        return self.has_var(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.get_var(key, default=default)

    def pop(self, key: str, default: Any = None) -> Any:
        value = self.get_var(key, default=default)
        self.unset_var(key)
        return value

    def _scene(self) -> "Scene | None":
        # the scene this game state belongs to; a detached one sends no events
        scene = active_scene.get()
        if scene is None:
            try:
                scene = getattr(get_agent("director"), "scene", None)
            except KeyError:
                return None
        if scene is not None and getattr(scene, "game_state", None) is self:
            return scene
        return None

    def set_var(self, key: str, value: Any, commit: bool = False):
        _write_game_state(
            self, self._scene(), lambda variables: variables.update({key: value}), [key]
        )
        if commit:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self.memory.add(value, uid=f"game_state.{key}"))

    def has_var(self, key: str) -> bool:
        return key in self.variables

    def get_var(self, key: str, default: Any = None) -> Any:
        return self.variables.get(key, default)

    def get_or_set_var(self, key: str, value: Any, commit: bool = False) -> Any:
        if not self.has_var(key):
            self.set_var(key, value, commit=commit)
        return self.get_var(key)

    def unset_var(self, key: str):
        _write_game_state(
            self, self._scene(), lambda variables: variables.pop(key, None), [key]
        )


def set_game_state_value(
    scene: "Scene", path: str, value: Any, *, create: bool = True
) -> str:
    """
    Set the value at a path ('a/b/c') and return the path in its normalized
    form. With `create`, missing dicts on the way are made; without it, a
    missing parent raises ValueError. A segment that holds a value other
    than a dict raises ValueError.
    """
    parts = split_state_path(path)

    def write(variables: dict):
        parent, leaf_key = get_path_parent(variables, parts, create=create)
        if parent is None:
            raise ValueError(f"Game state path does not exist: {path}")
        parent[leaf_key] = value

    _write_game_state(scene.game_state, scene, write, parts[:1])
    return "/".join(parts)


def unset_game_state_value(scene: "Scene", path: str) -> Any:
    """Remove the value at a path and return it (None when there was none)."""
    parts = split_state_path(path)

    def write(variables: dict):
        parent, leaf_key = get_path_parent(variables, parts, create=False)
        if parent is None:
            return None
        return parent.pop(leaf_key, None)

    return _write_game_state(scene.game_state, scene, write, parts[:1])


def _deep_update(target: dict, source: dict):
    for key, value in source.items():
        if isinstance(value, dict) and not value:
            target[key] = {}
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def update_game_state(
    scene: "Scene", updates: dict | list[dict], *, merge: bool = True
) -> dict:
    """
    Apply update dicts to the variables, in order. With `merge`, nested dicts
    are merged and an empty dict clears its key; without it, each top-level
    key is replaced. Returns the variables.
    """
    if isinstance(updates, dict):
        updates = [updates]
    if not all(isinstance(update, dict) for update in updates):
        raise ValueError("Game state updates must be dicts")
    updates = copy.deepcopy(updates)

    def write(variables: dict):
        for update in updates:
            if merge:
                _deep_update(variables, update)
            else:
                variables.update(update)

    _write_game_state(
        scene.game_state, scene, write, {key for update in updates for key in update}
    )
    return scene.game_state.variables


def replace_game_state_variables(scene: "Scene", variables: dict) -> dict:
    """Replace all variables; each added, changed or removed leaf is a change."""

    def write(current: dict):
        current.clear()
        current.update(variables)

    _write_game_state(scene.game_state, scene, write)
    return scene.game_state.variables


def replace_game_state(scene: "Scene", game_state: GameState):
    """Take over another game state: its variables through the write path."""
    for field in GameState.model_fields:
        if field != "variables":
            setattr(scene.game_state, field, getattr(game_state, field))
    replace_game_state_variables(scene, game_state.variables)


GameStatePinTarget = Literal["debug", "control"]

# the Scene attribute holding each target's pinned paths
GAME_STATE_PIN_TARGETS: dict[GameStatePinTarget, str] = {
    "debug": "game_state_watch_paths",
    "control": "game_state_control_paths",
}


class GameStatePathSettings(pydantic.BaseModel):
    """
    How one pinned game state path is presented and limited in the control
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


def constrained_game_state_value(scene: "Scene", path: str, value):
    """
    The value a player may write at `path` under its pin settings: clamped
    and snapped onto a numeric grid, or refused with ValueError.
    """
    if scene.game_state_path_is_read_only(path):
        raise ValueError(f"Game state path is read only: {path}")

    settings = scene.game_state_path_settings.get(path)
    if not settings:
        return value

    if settings.choices:
        if not isinstance(value, str) or value not in settings.choices:
            raise ValueError(f"Value is not one of the choices for {path}: {value!r}")
        return value

    if settings.constrains_numbers:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Value must be a number for {path}: {value!r}")
        return settings.constrain(value)

    return value


def set_game_state_path_settings(
    scene: "Scene", path: str, settings: GameStatePathSettings, *, merge: bool = False
) -> dict:
    """
    Store the settings of a pinned path; default settings remove the entry.
    With `merge`, only the fields set on `settings` change, so naming one
    setting does not drop the others.
    """
    existing = scene.game_state_path_settings.get(path)
    if merge and existing:
        settings = GameStatePathSettings(
            **{
                **existing.model_dump(),
                **settings.model_dump(exclude_unset=True),
            }
        )
    if settings.is_default:
        scene.game_state_path_settings.pop(path, None)
    else:
        scene.game_state_path_settings[path] = settings
    return settings.model_dump(exclude_defaults=True)


def game_state_pin_paths(scene: "Scene", target: GameStatePinTarget) -> list[str]:
    return getattr(scene, GAME_STATE_PIN_TARGETS[target])


def set_game_state_paths(
    scene: "Scene", target: GameStatePinTarget, paths
) -> list[str]:
    """
    Replace the pinned paths of a target and drop the settings of paths no
    longer pinned anywhere.
    """
    attribute = GAME_STATE_PIN_TARGETS[target]
    setattr(scene, attribute, sorted(set(filter(None, paths))))
    scene.game_state_path_settings = prune_game_state_path_settings(
        scene.game_state_path_settings, scene.pinned_game_state_paths
    )
    return getattr(scene, attribute)


def pin_game_state_path(
    scene: "Scene",
    path: str,
    target: GameStatePinTarget,
    enabled: bool,
    settings: GameStatePathSettings | dict | None = None,
) -> list[str]:
    """
    Pin or unpin one path for a target; given settings are merged into the
    path's settings. Raises ValueError for an unknown target or unusable
    settings, before anything changes.
    """
    if target not in GAME_STATE_PIN_TARGETS:
        raise ValueError(f"Unknown game state pin target: {target}")
    if isinstance(settings, dict):
        settings = GameStatePathSettings(**settings)
    paths = set(game_state_pin_paths(scene, target))
    if enabled:
        paths.add(path)
    else:
        paths.discard(path)
    if settings is not None:
        set_game_state_path_settings(scene, path, settings, merge=True)
    return set_game_state_paths(scene, target, paths)
