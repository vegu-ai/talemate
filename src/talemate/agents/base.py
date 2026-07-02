from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import json
from inspect import signature
import re
import traceback
from abc import ABC
from functools import wraps
from typing import Awaitable, Callable, Literal
import uuid
import pydantic
from pydantic import ConfigDict
import structlog
from typing import TYPE_CHECKING

import talemate.emit.async_signals
import talemate.instance as instance
import talemate.util as util
from talemate.agents.context import ActiveAgent, active_agent
from talemate.emit import emit
from talemate.events import GameLoopStartEvent
from talemate.context import active_scene
from talemate.ux.schema import Action, Column, Note
from talemate.config import get_config, Config
import talemate.config.schema as config_schema
from talemate.client.context import (
    ClientContext,
)
from talemate.scene_agent_settings import UNSET
from talemate.game.engine.nodes.core import GraphState
from talemate.game.engine.nodes.registry import get_nodes_by_base_type, get_node
from talemate.game.engine.nodes.run import FunctionWrapper

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

__all__ = [
    "Agent",
    "AgentAction",
    "AgentActionConditional",
    "AgentActionConfig",
    "AgentDetail",
    "AgentEmission",
    "AgentTemplateEmission",
    "set_processing",
    "store_context_state",
]

log = structlog.get_logger("talemate.agents.base")


class AgentActionConditional(pydantic.BaseModel):
    attribute: str
    value: int | float | str | bool | list[int | float | str | bool] | None = None


class AgentActionNote(Note):
    pass


class AgentActionConfig(pydantic.BaseModel):
    type: Literal[
        "autocomplete",
        "blob",
        "bool",
        "flags",
        "number",
        "text",
        "vector2",
        "weights",
        "wstemplate",
        "password",
        "unified_api_key",
    ]
    label: str
    description: str = ""
    value: int | float | str | bool | list | dict | None = None
    default_value: int | float | str | bool | None = None
    max: int | float | None = None
    min: int | float | None = None
    step: int | float | None = None
    graduations: list[dict[str, int | float]] | None = None
    scope: str = "global"
    choices: (
        list[dict[str, str | int | float | bool | list[int | float | bool]]] | None
    ) = None
    note: AgentActionNote | None = None
    expensive: bool = False
    quick_toggle: bool = False
    condition: AgentActionConditional | None = None
    title: str | None = None
    value_migration: Callable | None = pydantic.Field(default=None, exclude=True)
    columns: list[Column] | None = None

    note_on_value: dict[str | int | float | bool, AgentActionNote] = pydantic.Field(
        default_factory=dict
    )
    save_on_change: bool = False
    scene_overridable: bool = True

    wstemplate_type: (
        Literal[
            "state_reinforcement",
            "character_attribute",
            "character_detail",
            "spices",
            "writing_style",
            "visual_style",
            "agent_persona",
            "scene_type",
        ]
        | None
    ) = None
    wstemplate_filter: dict[str, str] | None = None

    @pydantic.field_validator("note", mode="before")
    @classmethod
    def validate_note(cls, v):
        if isinstance(v, str):
            return AgentActionNote(text=v)
        return v

    @pydantic.model_validator(mode="after")
    def ensure_note_is_object(self):
        if isinstance(self.note, str):
            self.note = AgentActionNote(text=self.note)
        return self

    @pydantic.field_serializer("note")
    def serialize_note(self, v):
        if isinstance(v, str):
            return AgentActionNote(text=v)
        return v

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AgentAction(pydantic.BaseModel):
    enabled: bool = True
    label: str
    description: str = ""
    warning: str = ""
    config: dict[str, AgentActionConfig] | None = None
    condition: AgentActionConditional | None = None
    container: bool = False
    icon: str | None = None
    can_be_disabled: bool = False
    quick_toggle: bool = False
    experimental: bool = False
    subtitle: str | None = None
    tools: list[Action] = pydantic.Field(default_factory=list)

    # When set, marks this action as a child of another action — used by the
    # frontend to visually group dynamic children under their registry tab.
    parent_key: str | None = None

    # When set, the frontend renders the registry-management UI for this
    # action using the named component (e.g. "TTSOpenAICompatibleBackends").
    # Falls back to the generic ``DynamicAgentRegistry`` component when None.
    # Only meaningful on actions that are themselves dynamic registries.
    dynamic_registry_component: str | None = None

    enabled_scene_overridable: bool = False

    @pydantic.model_validator(mode="after")
    def _enabled_scene_overridable_requires_can_be_disabled(self):
        # An enable-flag override only makes sense when the global enable
        # flag is itself togglable. Without can_be_disabled the global UI
        # never exposes an Enable checkbox, so a scene-level override has
        # nothing to override.
        if self.enabled_scene_overridable and not self.can_be_disabled:
            raise ValueError(
                f"AgentAction {self.label!r}: enabled_scene_overridable=True "
                "requires can_be_disabled=True"
            )
        return self


# ---------------------------------------------------------------------------
# Dynamic action registries
# ---------------------------------------------------------------------------
#
# An AgentAction whose config contains a reserved field named
# ``dynamic_children`` (an AgentActionConfig of type "blob") is treated as a
# *registry*. The blob holds a JSON-encoded list of ``{"slug": ..., "label":
# ...}`` entries; one synthesized child AgentAction per entry is installed
# onto ``self.actions`` at config-load time via the agent-supplied factory.
#
# This lets agents expose user-managed lists of named configurations
# (TTS OpenAI-compatible backends, future per-instance integrations, etc.)
# without changes to AgentActionConfig schema or the save/load pipeline.

DYNAMIC_CHILDREN_FIELD = "dynamic_children"


def optimize_prompt_caching_action() -> AgentAction:
    """Reusable per-agent action for prompt caching optimization override."""
    return AgentAction(
        enabled=True,
        label="Prompt Caching",
        config={
            "optimize_prompt_caching": AgentActionConfig(
                type="text",
                label="Optimize for Prompt Caching",
                description="Place volatile context (long-term memory, dynamic notes) after the scene history for better prompt caching on API backends. May confuse weaker models. 'Auto' defers to the client setting.",
                value="auto",
                choices=[
                    {"label": "Auto (use client setting)", "value": "auto"},
                    {"label": "On", "value": "on"},
                    {"label": "Off", "value": "off"},
                ],
                scene_overridable=False,
            ),
        },
    )


class AgentDetail(pydantic.BaseModel):
    value: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str = "grey"
    hidden: bool = False


class DynamicInstruction(pydantic.BaseModel):
    title: str
    content: str

    def __str__(self) -> str:
        if not self.content:
            return ""

        return "\n".join(
            [f"<|SECTION:{self.title}|>", self.content, "<|CLOSE_SECTION|>"]
        )


def args_and_kwargs_to_dict(
    fn, args: list, kwargs: dict, filter: list[str] = None
) -> dict:
    """
    Takes a list of arguments and a dict of keyword arguments and returns
    a dict mapping parameter names to their values.

    Args:
        fn: The function whose parameters we want to map
        args: List of positional arguments
        kwargs: Dictionary of keyword arguments
        filter: List of parameter names to include in the result, if None all parameters are included

    Returns:
        Dict mapping parameter names to their values
    """
    sig = signature(fn)
    bound_args = sig.bind(*args, **kwargs)
    bound_args.apply_defaults()
    rv = dict(bound_args.arguments)
    rv.pop("self", None)

    if filter:
        for key in list(rv.keys()):
            if key not in filter:
                rv.pop(key)

    return rv


class store_context_state:
    """
    Flag to store a function's arguments in the agent's context state.

    Any arguments passed to the function will be stored in the agent's context

    If no arguments are passed, all arguments will be stored.

    Keyword arguments can be passed to store additional values in the context state.
    """

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __call__(self, fn):
        fn.store_context_state = self.args
        fn.store_context_state_kwargs = self.kwargs
        return fn


def _agent_action_override_kwargs(agent_type: str, action_name: str) -> dict:
    """ClientContext kwargs for any per-action override on ``{agent_type}.{action_name}``; empty when none applies."""
    config = get_config()
    override = config.agent_actions.overrides.get(f"{agent_type}.{action_name}")
    if override is None:
        return {}

    kwargs: dict = {}
    if override.disable_reasoning:
        kwargs["disable_reasoning"] = True
    return kwargs


# When True (set by a background dispatcher around asyncio.create_task), a
# @set_processing action skips its foreground "busy" status emit. The action
# still establishes its normal client/agent context, but status is left to
# set_background_processing() so the work reports as "busy_bg" rather than
# blocking-looking "busy". Default False keeps every other call unchanged.
background_processing: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "agent_background_processing", default=False
)


def set_processing(fn):
    """
    decorator that emits the agent status as processing while the function
    is running.

    Done via a try - final block to ensure the status is reset even if
    the function fails.
    """

    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        # In background mode the foreground "busy" emit is suppressed; status is
        # owned by set_background_processing() so the action reports "busy_bg".
        is_background = background_processing.get()
        with ClientContext():
            scene = active_scene.get()

            if scene:
                scene.continue_actions()

            with ActiveAgent(self, fn, args, kwargs) as active_agent_context:
                try:
                    action_name = fn.__name__
                    if action_name == "delegate":
                        action_name = args[0].__name__

                    self._current_action = action_name
                    if not is_background:
                        await self.emit_status(processing=True)

                    # Now pass the complete args list
                    if getattr(fn, "store_context_state", None) is not None:
                        all_args = args_and_kwargs_to_dict(
                            fn,
                            [self] + list(args),
                            kwargs,
                            getattr(fn, "store_context_state", []),
                        )
                        if getattr(fn, "store_context_state_kwargs", None) is not None:
                            all_args.update(
                                getattr(fn, "store_context_state_kwargs", {})
                            )

                        all_args[f"fn_{fn.__name__}"] = True

                        active_agent_context.state_params = all_args

                        self.set_context_states(**all_args)

                    override_kwargs = _agent_action_override_kwargs(
                        self.agent_type, action_name
                    )
                    override_ctx = (
                        ClientContext(**override_kwargs)
                        if override_kwargs
                        else contextlib.nullcontext()
                    )
                    with override_ctx:
                        return await fn(self, *args, **kwargs)
                finally:
                    try:
                        self._current_action = None
                        if not is_background:
                            await self.emit_status(processing=False)
                    except RuntimeError as exc:
                        # not sure why this happens
                        # some concurrency error?
                        log.error("error emitting agent status", exc=exc)

    return wrapper


class Agent(ABC):
    """
    Base agent class, defines a role
    """

    agent_type = "agent"
    verbose_name = None
    set_processing = set_processing
    requires_llm_client = True
    websocket_handler = None
    essential = True
    ready_check_error = None

    # Debounce tracking for emit_status
    _emit_status_debounce_task: asyncio.Task | None = None

    _current_action: str | None = None

    @classmethod
    def init_actions(
        cls, actions: dict[str, AgentAction] | None = None
    ) -> dict[str, AgentAction]:
        if actions is None:
            actions = {}

        return actions

    @classmethod
    def config_options(cls, agent=None):
        config_options = {
            "client": [
                name for name, client in instance.client_instances() if client.enabled
            ],
            "enabled": agent.enabled if agent else True,
            "has_toggle": agent.has_toggle if agent else False,
            "experimental": agent.experimental if agent else False,
            "requires_llm_client": cls.requires_llm_client,
            "scene_overrides": cls._scene_overrides_payload(agent),
        }
        actions = getattr(agent, "actions", None)

        if actions:
            config_options["actions"] = {k: v.model_dump() for k, v in actions.items()}
        else:
            config_options["actions"] = {}

        return config_options

    @classmethod
    def _scene_overrides_payload(cls, agent) -> dict:
        """Sparse override dict for THIS agent from the active scene, if any.

        Empty dict means: no scene loaded, or no overrides set for this
        agent. The frontend uses this to populate the Scene tab in the
        AgentModal.
        """
        if not agent:
            return {}
        overrides = agent.scene_overrides()
        if overrides is None:
            return {}
        agent_override = overrides.agents.get(agent.agent_type)
        if not agent_override:
            return {}
        return agent_override.model_dump(exclude_none=True)

    @classmethod
    async def init_nodes(cls, scene: "Scene", state: GraphState):
        log.debug(f"{cls.agent_type}.init_nodes")

        if not cls.websocket_handler:
            return

        cls.websocket_handler.clear_sub_handlers()

        for node_cls in get_nodes_by_base_type("agents/AgentWebsocketHandler"):
            _node = node_cls()
            handler_name = _node.get_property("name")
            agent_type = _node.get_property("agent")
            if agent_type != cls.agent_type:
                continue

            async def handler_fn(router, data: dict, captured_node=_node):
                agent = instance.get_agent(cls.agent_type)

                async def wrapped_agent_action(agent: "Agent", *args, **kwargs):
                    state: GraphState = scene.nodegraph_state
                    node = get_node(captured_node.registry)()
                    fn = FunctionWrapper(node, node, state)
                    try:
                        await fn(websocket_router=router, data=data)
                    except Exception as e:
                        log.error(
                            "Error in agent action",
                            agent=cls.agent_type,
                            error=traceback.format_exc(),
                        )
                        emit(
                            "status",
                            message=f"Error in agent action: {e}",
                            status="error",
                        )

                # Set name before decoration so @wraps copies it to wrapper
                wrapped_agent_action.__name__ = f"{cls.agent_type}_{handler_name}"
                wrapped_agent_action = cls.set_processing(wrapped_agent_action)
                # Also set on wrapper in case @wraps didn't copy it properly
                wrapped_agent_action.__name__ = f"{cls.agent_type}_{handler_name}"
                asyncio.create_task(wrapped_agent_action(agent))

            cls.websocket_handler.register_sub_handler(handler_name, handler_fn)
            log.debug(
                f"{cls.agent_type}.init_nodes.websocket_handler",
                handler_name=handler_name,
            )

    @property
    def config(self) -> Config:
        return get_config()

    @property
    def agent_details(self):
        if hasattr(self, "client"):
            if self.client:
                return self.client.name
        return None

    @property
    def ready(self):
        if not self.requires_llm_client:
            return True

        if not hasattr(self, "client"):
            return False

        if not getattr(self.client, "enabled", True):
            return False

        if self.client and self.client.current_status in ["error", "warning"]:
            return False

        return self.client is not None

    @property
    def status(self):
        if not self.enabled:
            return "disabled"

        if not self.ready:
            return "uninitialized"

        if getattr(self, "processing", 0) > 0:
            return "busy"

        if getattr(self, "processing_bg", 0) > 0:
            return "busy_bg"

        return "idle"

    @property
    def enabled(self):
        # by default, agents are enabled, an agent class that
        # is disableable should override this property
        return True

    @property
    def disable(self):
        # by default, agents are enabled, an agent class that
        # is disableable should override this property to
        # disable the agent
        pass

    @property
    def has_toggle(self):
        # by default, agents do not have toggles to enable / disable
        # an agent class that is disableable should override this property
        return False

    @property
    def experimental(self):
        # by default, agents are not experimental, an agent class that
        # is experimental should override this property
        return False

    @property
    def meta(self):
        meta = {
            "essential": self.essential,
            "current_action": self._current_action,
        }

        return meta

    @property
    def sanitized_action_config(self):
        if not getattr(self, "actions", None):
            return {}

        return {k: v.model_dump() for k, v in self.actions.items()}

    # scene state

    def context_fingerprint(self, extra: list[str] = None) -> str | None:
        active_agent_context = active_agent.get()

        if not active_agent_context:
            return None

        if self.scene.history:
            fingerprint = f"{self.scene.history[-1].fingerprint}-{active_agent_context.first.fingerprint}"
        else:
            fingerprint = f"START-{active_agent_context.first.fingerprint}"

        if extra:
            for extra_key in extra:
                fingerprint += f"-{hash(extra_key)}"

        return fingerprint

    def get_scene_state(self, key: str, default=None):
        agent_state = self.scene.agent_state.get(self.agent_type, {})
        return agent_state.get(key, default)

    def set_scene_states(self, **kwargs):
        agent_state = self.scene.agent_state.get(self.agent_type, {})
        for key, value in kwargs.items():
            agent_state[key] = value
        self.scene.agent_state[self.agent_type] = agent_state

    def dump_scene_state(self):
        return self.scene.agent_state.get(self.agent_type, {})

    # active agent context state

    def get_context_state(self, key: str, default=None):
        key = f"{self.agent_type}__{key}"
        try:
            return active_agent.get().state.get(key, default)
        except AttributeError:
            log.warning("get_context_state error", agent=self.agent_type, key=key)
            return default

    def set_context_states(self, **kwargs):
        try:
            items = {f"{self.agent_type}__{k}": v for k, v in kwargs.items()}
            active_agent.get().state.update(items)
            log.debug(
                "set_context_states",
                agent=self.agent_type,
                state=active_agent.get().state,
            )
        except AttributeError:
            log.error("set_context_states error", agent=self.agent_type, kwargs=kwargs)

    def dump_context_state(self):
        try:
            return active_agent.get().state
        except AttributeError:
            return {}

    ###

    async def _handle_ready_check(self, fut: asyncio.Future):
        callback_failure = getattr(self, "on_ready_check_failure", None)
        if fut.cancelled():
            if callback_failure:
                await callback_failure()
            return

        if fut.exception():
            exc = fut.exception()
            self.ready_check_error = exc
            log.error("agent ready check error", agent=self.agent_type, exc=exc)
            if callback_failure:
                await callback_failure(exc)
            return

        callback = getattr(self, "on_ready_check_success", None)
        result = fut.result()
        if callback:
            await callback(result)

    async def setup_check(self):
        """Per-status-tick auto-setup hook.

        Called once per status tick by ``agent_ready_checks`` for *every*
        live agent slot — including agents whose ``enabled`` flag is False.
        Overrides must therefore be safe to invoke when the agent is
        disabled (e.g. they can still flip ``is_enabled`` on themselves
        when an external precondition is met, as TTSAgent does when a
        client reports a freshly loaded TTS model).
        """
        return False

    async def ready_check(self, task: asyncio.Task = None):
        self.ready_check_error = None
        if task:
            task.add_done_callback(
                lambda fut: asyncio.create_task(self._handle_ready_check(fut))
            )
            return
        return True

    # ------------------------------------------------------------------
    # Dynamic action registries
    # ------------------------------------------------------------------

    def is_dynamic_registry(self, action_key: str) -> bool:
        """Return True if the named action is a dynamic-children registry."""
        actions = getattr(self, "actions", None) or {}
        action = actions.get(action_key)
        return bool(
            action and action.config and DYNAMIC_CHILDREN_FIELD in action.config
        )

    def dynamic_registry_keys(self) -> list[str]:
        actions = getattr(self, "actions", None) or {}
        return [k for k in actions if self.is_dynamic_registry(k)]

    def dynamic_children_entries(self, registry_key: str) -> list[dict]:
        """Return parsed [{slug, label}, ...] from the registry's blob value."""
        if not self.is_dynamic_registry(registry_key):
            return []
        raw = self.actions[registry_key].config[DYNAMIC_CHILDREN_FIELD].value or "[]"
        try:
            entries = json.loads(raw)
        except (TypeError, ValueError):
            log.warning(
                "dynamic registry blob is not valid JSON",
                agent=self.agent_type,
                registry_key=registry_key,
            )
            return []
        return [e for e in entries if isinstance(e, dict) and e.get("slug")]

    def dynamic_child_slugs(self, registry_key: str) -> list[str]:
        return [e["slug"] for e in self.dynamic_children_entries(registry_key)]

    def _write_dynamic_children_entries(
        self, registry_key: str, entries: list[dict]
    ) -> None:
        self.actions[registry_key].config[DYNAMIC_CHILDREN_FIELD].value = json.dumps(
            entries
        )

    def dynamic_action_factory(
        self, registry_key: str, slug: str, label: str
    ) -> "AgentAction":
        """Subclasses override to produce a per-child AgentAction definition.

        The returned action MUST have ``parent_key=registry_key`` set so the
        frontend can group it under its registry tab.
        """
        raise NotImplementedError(
            f"{type(self).__name__} declared dynamic registry '{registry_key}' "
            "but did not implement dynamic_action_factory()"
        )

    def install_dynamic_children(self, registry_key: str) -> None:
        """Synthesize per-child actions from the registry's stored entries.

        Idempotent. Existing entries with matching slugs are left alone so that
        in-memory state (e.g., applied config values) survives re-installation.
        Stale child entries (slugs no longer in the registry) are removed.
        """
        if not self.is_dynamic_registry(registry_key):
            return

        entries = self.dynamic_children_entries(registry_key)
        slugs = {e["slug"] for e in entries}

        for entry in entries:
            slug = entry["slug"]
            label = entry.get("label") or slug
            if slug in self.actions:
                continue
            child = self.dynamic_action_factory(registry_key, slug, label)
            child.parent_key = registry_key
            self.actions[slug] = child

        # Drop synthesized children that are no longer registered.
        for action_key in list(self.actions.keys()):
            action = self.actions[action_key]
            if action.parent_key == registry_key and action_key not in slugs:
                del self.actions[action_key]

    # Lifecycle hooks — subclasses override as needed.
    #
    # These run *synchronously* immediately after the agent's in-memory
    # registry state mutates. Use them only for in-memory updates (refreshing
    # choices, purging cached data, etc.). For I/O-bound cleanup (e.g.,
    # persisting external state to disk), override
    # ``persist_dynamic_external_state`` instead — it's awaited by the
    # websocket plugin after the sync hook fires.
    def on_dynamic_child_added(self, registry_key: str, slug: str, label: str) -> None:
        return None

    def on_dynamic_child_removed(self, registry_key: str, slug: str) -> None:
        return None

    def on_dynamic_child_renamed(
        self, registry_key: str, slug: str, label: str
    ) -> None:
        return None

    async def persist_dynamic_external_state(self, registry_key: str) -> None:
        """Persist any external state mutated by sync lifecycle hooks.

        Default: no-op. TTSAgent overrides to flush its voice library after
        a backend purge, for example. Called by the agent-config websocket
        plugin after register/unregister so failures surface to the UI.
        """
        return None

    def reserved_slugs_for_registry(self, registry_key: str) -> set[str]:
        """Slugs the agent considers reserved for this registry.

        Subclasses may override to prevent registration of slugs that would
        collide with existing static action keys, dispatch identifiers, etc.

        Scope: the framework itself only enforces *intra-registry* slug
        uniqueness (no two children of the same registry share a slug).
        Cross-action collisions (with static action keys, other registries,
        runtime dispatch tables) are the agent's responsibility to declare
        here.
        """
        return set()

    # Mutation helpers.
    def register_dynamic_child(self, registry_key: str, slug: str, label: str) -> None:
        if not self.is_dynamic_registry(registry_key):
            raise ValueError(f"'{registry_key}' is not a dynamic registry")
        if not slug:
            raise ValueError("slug is required")
        if slug in self.reserved_slugs_for_registry(registry_key):
            raise ValueError(f"slug '{slug}' is reserved")
        entries = self.dynamic_children_entries(registry_key)
        if any(e["slug"] == slug for e in entries):
            raise ValueError(f"a child with slug '{slug}' already exists")
        entries.append({"slug": slug, "label": label or slug})
        self._write_dynamic_children_entries(registry_key, entries)
        self.install_dynamic_children(registry_key)
        self.on_dynamic_child_added(registry_key, slug, label or slug)

    def unregister_dynamic_child(self, registry_key: str, slug: str) -> None:
        if not self.is_dynamic_registry(registry_key):
            raise ValueError(f"'{registry_key}' is not a dynamic registry")
        entries = self.dynamic_children_entries(registry_key)
        if not any(e["slug"] == slug for e in entries):
            return
        entries = [e for e in entries if e["slug"] != slug]
        self._write_dynamic_children_entries(registry_key, entries)
        self.install_dynamic_children(registry_key)
        self.on_dynamic_child_removed(registry_key, slug)

    def rename_dynamic_child_label(
        self, registry_key: str, slug: str, label: str
    ) -> None:
        if not self.is_dynamic_registry(registry_key):
            raise ValueError(f"'{registry_key}' is not a dynamic registry")
        entries = self.dynamic_children_entries(registry_key)
        for entry in entries:
            if entry["slug"] == slug:
                entry["label"] = label or slug
                break
        else:
            return
        self._write_dynamic_children_entries(registry_key, entries)
        if slug in self.actions:
            self.actions[slug].label = label or slug
        self.on_dynamic_child_renamed(registry_key, slug, label or slug)

    # Resolver helpers — used by agents that dispatch via name-prefixed methods.
    def dynamic_attr(self, registry_key: str, slug: str, name: str, default=None):
        """Resolve a property-like helper for a dynamic child.

        Looks up ``self._<registry_key>_<name>`` and invokes it with the
        child slug. Returns ``default`` if the helper is missing.
        """
        fn = getattr(self, f"_{registry_key}_{name}", None)
        if fn is None:
            return default
        return fn(slug)

    def dynamic_method(self, registry_key: str, slug: str, name: str, default=None):
        """Resolve a callable helper for a dynamic child.

        Returns a partial that pre-binds the slug, so callers can invoke it
        the same way they would invoke a static per-api method.
        """
        fn = getattr(self, f"_{registry_key}_{name}", None)
        if fn is None:
            return default
        return functools.partial(fn, slug)

    # ------------------------------------------------------------------
    # Per-scene config overrides
    # ------------------------------------------------------------------

    def scene_overrides(self):
        """Return the scene's agent-overrides overlay, or None if not linked.

        ``scene`` is only present after ``connect()`` runs at scene-load time;
        callers may invoke this before that (e.g. property getters during agent
        init), so we tolerate a missing ``scene`` attribute.
        """
        scene = getattr(self, "scene", None)
        return getattr(scene, "agent_overrides", None) if scene else None

    def _resolve(self, getter, fallback):
        """Consult the scene overlay via ``getter``; fall back if UNSET."""
        overrides = self.scene_overrides()
        if overrides is not None:
            value = getter(overrides)
            if value is not UNSET:
                return value
        return fallback()

    def resolve_config(self, action_key: str, config_key: str):
        """Return the effective value for an action config field — scene override if any, else global."""
        return self._resolve(
            lambda o: o.get_value(self.agent_type, action_key, config_key),
            lambda: self.actions[action_key].config[config_key].value,
        )

    def resolve_enabled(self, action_key: str) -> bool:
        """Return the effective enabled flag for a container action."""
        return bool(
            self._resolve(
                lambda o: o.get_enabled(self.agent_type, action_key),
                lambda: self.actions[action_key].enabled,
            )
        )

    def _route_write(self, has_override, write_override, write_global) -> None:
        """Route a write to the scene overlay when it's overriding this field, else to the global config."""
        overrides = self.scene_overrides()
        if overrides is not None and has_override(overrides):
            write_override(overrides)
        else:
            write_global()

    def write_config(self, action_key: str, config_key: str, value) -> None:
        """Update an action config field — scene override if one is active for this field, else global.

        Note: this updates an *existing* override; it does not create a new one.
        New overrides are installed via the AgentModal save flow
        (see ``server.agent_config.replace_agent_overrides``).
        """
        self._route_write(
            lambda o: o.get_value(self.agent_type, action_key, config_key) is not UNSET,
            lambda o: o.set_value(self.agent_type, action_key, config_key, value),
            lambda: setattr(
                self.actions[action_key].config[config_key], "value", value
            ),
        )

    def write_enabled(self, action_key: str, enabled: bool) -> None:
        """Update an action's enabled flag — scene override if one is active, else global.

        Note: this updates an *existing* override; it does not create a new one.
        """
        self._route_write(
            lambda o: o.get_enabled(self.agent_type, action_key) is not UNSET,
            lambda o: o.set_enabled(self.agent_type, action_key, enabled),
            lambda: setattr(self.actions[action_key], "enabled", enabled),
        )

    async def apply_config(self, *args, **kwargs):
        # Writes global state directly on purpose; runtime edits must go
        # through `write_config` / `write_enabled` to respect any overlay.
        if self.has_toggle and "enabled" in kwargs:
            self.is_enabled = kwargs.get("enabled", False)

        if not getattr(self, "actions", None):
            return

        # Pre-pass: for every dynamic registry, restore the blob value first
        # then synthesize per-child actions, so the standard apply loop below
        # can resolve and apply each child's saved config values.
        for registry_key in self.dynamic_registry_keys():
            blob_value = (
                kwargs.get("actions", {})
                .get(registry_key, {})
                .get("config", {})
                .get(DYNAMIC_CHILDREN_FIELD, {})
                .get("value")
            )
            if blob_value is not None:
                self.actions[registry_key].config[
                    DYNAMIC_CHILDREN_FIELD
                ].value = blob_value
            self.install_dynamic_children(registry_key)

        for action_key, action in self.actions.items():
            if not kwargs.get("actions"):
                continue

            action.enabled = (
                kwargs.get("actions", {}).get(action_key, {}).get("enabled", False)
            )

            if not action.config:
                continue

            for config_key, _config in action.config.items():
                try:
                    _config.value = (
                        kwargs.get("actions", {})
                        .get(action_key, {})
                        .get("config", {})
                        .get(config_key, {})
                        .get("value", _config.value)
                    )
                    if _config.value_migration and callable(_config.value_migration):
                        _config.value = _config.value_migration(_config.value)
                except AttributeError:
                    pass

    async def save_config(self):
        """
        Saves the agent config to the config file.

        If no config object is provided, the config is loaded from the config file.
        """

        app_config: Config = get_config()

        app_config.agents[self.agent_type] = config_schema.Agent(
            name=self.agent_type,
            client=self.client.name if getattr(self, "client", None) else None,
            enabled=self.enabled,
            actions={
                action_key: config_schema.AgentAction(
                    enabled=action.enabled,
                    config={
                        config_key: config_schema.AgentActionConfig(
                            value=config_obj.value
                        )
                        for config_key, config_obj in action.config.items()
                        if config_obj.type != "unified_api_key"
                    },
                )
                for action_key, action in self.actions.items()
            },
        )
        log.debug(
            "saving agent config",
            agent=self.agent_type,
            config=app_config.agents[self.agent_type],
        )

        app_config.dirty = True

    async def on_game_loop_start(self, event: GameLoopStartEvent):
        """
        Finds all ActionConfigs that have a scope of "scene" and resets them to their default values
        """

        if not getattr(self, "actions", None):
            return

        for _, action in self.actions.items():
            if not action.config:
                continue

            for _, _config in action.config.items():
                if _config.scope == "scene":
                    # if default_value is None, just use the `type` of the current
                    # value
                    if _config.default_value is None:
                        default_value = type(_config.value)()
                    else:
                        default_value = _config.default_value

                    log.debug(
                        "resetting config", config=_config, default_value=default_value
                    )
                    _config.value = default_value

        await self.emit_status()

    async def _do_emit_status(self):
        """Internal method that performs the actual emission"""
        emit(
            "agent_status",
            message=self.verbose_name or "",
            id=self.agent_type,
            status=self.status,
            details=self.agent_details,
            meta=self.meta,
            data=self.config_options(agent=self),
        )

    async def _debounced_emit_status(self):
        """Internal method for debounced emission"""
        await asyncio.sleep(0.05)  # 50ms debounce
        self._emit_status_debounce_task = None
        await self._do_emit_status()

    async def emit_status(self, processing: bool = None):
        # should keep a count of processing requests, and when the
        # number is 0 status is "idle", if the number is greater than 0
        # status is "busy"
        #
        # increase / decrease based on value of `processing`

        if getattr(self, "processing", None) is None:
            self.processing = 0

        # Always update processing counter immediately
        if processing is False:
            self.processing -= 1
            self.processing = max(0, self.processing)
        elif processing is True:
            self.processing += 1

        # If processing=True, emit immediately (user expects instant feedback when work starts)
        if processing is True:
            # Cancel any pending debounce
            if (
                self._emit_status_debounce_task
                and not self._emit_status_debounce_task.done()
            ):
                self._emit_status_debounce_task.cancel()
            self._emit_status_debounce_task = None

            await self._do_emit_status()
        else:
            # For processing=False or None, debounce the emission
            # Cancel and replace any existing debounce task
            if (
                self._emit_status_debounce_task
                and not self._emit_status_debounce_task.done()
            ):
                self._emit_status_debounce_task.cancel()

            self._emit_status_debounce_task = asyncio.create_task(
                self._debounced_emit_status()
            )

    async def _handle_background_processing(
        self, fut: asyncio.Future, error_handler=None
    ):
        try:
            if fut.cancelled():
                return

            if fut.exception():
                exc = fut.exception()
                tb = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
                log.error(
                    "background processing error",
                    agent=self.agent_type,
                    exc=exc,
                    traceback=tb,
                )

                if error_handler:
                    await error_handler(fut.exception())

                await self.emit_status()
                return

            log.info("background processing done", agent=self.agent_type)
        finally:
            self.processing_bg -= 1
            await self.emit_status()

    async def set_background_processing(self, task: asyncio.Task, error_handler=None):
        log.info("set_background_processing", agent=self.agent_type)
        if not hasattr(self, "processing_bg"):
            self.processing_bg = 0

        self.processing_bg += 1

        await self.emit_status()
        task.add_done_callback(
            lambda fut: asyncio.create_task(
                self._handle_background_processing(fut, error_handler)
            )
        )

    # ------------------------------------------------------------------
    # Tracked single-flight tasks
    #
    # A small reuse layer over set_background_processing for "run this agent
    # operation as a single-flight task, optionally in the background". Each
    # logical operation is identified by a `key` so an agent can run several
    # independent ones; per-key only one is ever in flight at a time.
    #
    # background=True routes status through set_background_processing ("busy_bg",
    # non-blocking UI) and sets the background_processing contextvar so the
    # operation's @set_processing work reports busy_bg too. background=False runs
    # the same machinery but reports the normal foreground "busy".
    # ------------------------------------------------------------------

    def _tracked_task(self, key: str) -> "asyncio.Task | None":
        return getattr(self, "_tracked_tasks", {}).get(key)

    def tracked_task_running(self, key: str) -> bool:
        """Whether a tracked task under `key` is currently in flight."""
        task = self._tracked_task(key)
        return task is not None and not task.done()

    async def run_tracked_task(
        self,
        key: str,
        coro_factory: Callable[[], Awaitable],
        *,
        background: bool = True,
        cancel_in_flight: bool = False,
        error_handler: Callable | None = None,
    ) -> "asyncio.Task | None":
        """
        Run `coro_factory()` as a single-flight task tracked under `key`.

        Returns the started task, or None if one was already in flight and left
        to run (single-flight skip — `coro_factory` is not invoked, so a skip
        never creates an un-awaited coroutine).

        The entry is removed from the table when the task finishes, so the table
        only ever holds in-flight tasks and never accumulates stale keys (which
        matters for callers that use dynamic per-item keys).

        `cancel_in_flight=True` cancels a running task under `key` and starts a
        fresh one. `error_handler` is an async callable invoked with the
        exception if the task fails.
        """
        if not hasattr(self, "_tracked_tasks"):
            self._tracked_tasks: dict[str, asyncio.Task] = {}

        existing = self._tracked_tasks.get(key)
        if existing is not None and not existing.done():
            if not cancel_in_flight:
                return None
            existing.cancel()

        # The contextvar is copied into the task by create_task; the set/reset
        # is synchronous (no await between), so it never leaks to other tasks.
        token = background_processing.set(True) if background else None
        try:
            task = asyncio.create_task(coro_factory())
        finally:
            if token is not None:
                background_processing.reset(token)

        self._tracked_tasks[key] = task
        task.add_done_callback(lambda fut: self._untrack_task(key, fut))

        if background:
            await self.set_background_processing(task, error_handler)
        else:
            task.add_done_callback(
                lambda fut: self._on_tracked_task_done(fut, error_handler)
            )
        return task

    def _untrack_task(self, key: str, task: asyncio.Task) -> None:
        # Only drop the entry if it's still this task — a cancel_in_flight
        # replacement may have already swapped a newer task under the same key.
        if self._tracked_tasks.get(key) is task:
            del self._tracked_tasks[key]

    def _on_tracked_task_done(self, task: asyncio.Task, error_handler=None) -> None:
        # Foreground tasks report "busy" via @set_processing; this callback only
        # surfaces errors and consumes the result so failures don't go unnoticed.
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log.error("tracked task error", agent=self.agent_type, exc=exc, traceback=tb)
        if error_handler is not None:
            asyncio.create_task(error_handler(exc))

    def cancel_tracked_task(self, key: str) -> bool:
        """Cancel the in-flight tracked task under `key`. Returns True if one
        was running and got cancelled."""
        task = self._tracked_task(key)
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    def connect(self, scene):
        self.scene = scene
        talemate.emit.async_signals.get("game_loop_start").connect(
            self.on_game_loop_start
        )

    def clean_result(self, result):
        if "#" in result:
            result = result.split("#")[0]

        # Removes partial sentence at the end
        result = re.sub(r"[^\.\?\!]+(\n|$)", "", result)
        result = result.strip()

        if ":" in result:
            result = result.split(":")[1].strip()

        return result

    async def get_history_memory_context(
        self,
        memory_history_context_max: int,
        memory_context_max: int,
        exclude: list = [],
        exclude_fn: Callable = None,
    ):
        current_memory_context = []
        memory_helper = instance.get_agent("memory")
        if memory_helper:
            history_messages = "\n".join(
                self.scene.recent_history(memory_history_context_max)
            )
            memory_tokens = 0
            for memory in await memory_helper.agent.get(history_messages):
                if memory in exclude:
                    continue

                if exclude_fn:
                    for split in memory.split("\n"):
                        if exclude_fn(split):
                            continue

                memory_tokens += util.count_tokens(memory)

                if memory_tokens > memory_context_max:
                    break

                current_memory_context.append(memory)
        return current_memory_context

    # LLM client related methods. These are called during or after the client
    # sends the prompt to the API.

    def inject_prompt_paramters(
        self, prompt_param: dict, kind: str, agent_function_name: str
    ):
        """
        Injects prompt parameters before the client sends off the prompt
        Override as needed.
        """
        pass

    def allow_repetition_break(
        self, kind: str, agent_function_name: str, auto: bool = False
    ):
        """
        Returns True if repetition breaking is allowed, False otherwise.
        """
        return False

    @set_processing
    async def delegate(self, fn: Callable, *args, **kwargs):
        """
        Wraps a function as an agent action, allowing it to be called
        by the agent.
        """
        return await fn(*args, **kwargs)

    async def emit_message(
        self, header: str, message: str | list[dict], meta: dict = None, **data
    ):
        if not data:
            data = {}

        if not meta:
            meta = {}

        if "uuid" not in data:
            data["uuid"] = str(uuid.uuid4())

        if "agent" not in data:
            data["agent"] = self.agent_type

        data["header"] = header
        emit(
            "agent_message",
            message=message,
            data=data,
            meta=meta,
            websocket_passthrough=True,
        )


class AgentEmission(pydantic.BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent: Agent


class AgentTemplateEmission(AgentEmission):
    template_vars: dict = pydantic.Field(default_factory=dict)
    response: str | None = None
    dynamic_instructions: list[DynamicInstruction] = pydantic.Field(
        default_factory=list
    )


class RagBuildSubInstructionEmission(AgentEmission):
    sub_instruction: str | None = None
