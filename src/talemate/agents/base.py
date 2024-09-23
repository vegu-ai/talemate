from __future__ import annotations

import asyncio
import dataclasses
import re
from abc import ABC
from functools import wraps
from typing import TYPE_CHECKING, Callable, List, Optional, Union

import pydantic
import structlog
from blinker import signal

import talemate.emit.async_signals
import talemate.instance as instance
import talemate.util as util
from talemate.agents.context import ActiveAgent
from talemate.emit import emit
from talemate.events import GameLoopStartEvent
from talemate.context import active_scene
from talemate.client.context import (
    ClientContext
)

__all__ = [
    "Agent",
    "AgentAction",
    "AgentActionConditional",
    "AgentActionConfig",
    "AgentDetail",
    "AgentEmission",
    "set_processing",
]

log = structlog.get_logger("talemate.agents.base")


class AgentActionConfig(pydantic.BaseModel):
    type: str
    label: str
    description: str = ""
    value: Union[int, float, str, bool, None] = None
    default_value: Union[int, float, str, bool] = None
    max: Union[int, float, None] = None
    min: Union[int, float, None] = None
    step: Union[int, float, None] = None
    scope: str = "global"
    choices: Union[list[dict[str, str]], None] = None
    note: Union[str, None] = None

    class Config:
        arbitrary_types_allowed = True


class AgentActionConditional(pydantic.BaseModel):
    attribute: str
    value: Union[int, float, str, bool, None] = None


class AgentAction(pydantic.BaseModel):
    enabled: bool = True
    label: str
    description: str = ""
    config: Union[dict[str, AgentActionConfig], None] = None
    condition: Union[AgentActionConditional, None] = None
    container: bool = False
    icon: Union[str, None] = None


class AgentDetail(pydantic.BaseModel):
    value: Union[str, None] = None
    description: Union[str, None] = None
    icon: Union[str, None] = None
    color: str = "grey"


def set_processing(fn):
    """
    decorator that emits the agent status as processing while the function
    is running.

    Done via a try - final block to ensure the status is reset even if
    the function fails.
    """

    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        with ClientContext():
            scene = active_scene.get()
            
            if scene:
                scene.continue_actions()
            
            with ActiveAgent(self, fn):
                try:
                    await self.emit_status(processing=True)
                    return await fn(self, *args, **kwargs)
                finally:
                    try:
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
    auto_break_repetition = False
    websocket_handler = None
    essential = True
    ready_check_error = None

    @property
    def agent_details(self):
        if hasattr(self, "client"):
            if self.client:
                return self.client.name
        return None

    @property
    def verbose_name(self):
        return self.agent_type.capitalize()

    @property
    def ready(self):
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

    @classmethod
    def config_options(cls, agent=None):
        config_options = {
            "client": [name for name, _ in instance.client_instances()],
            "enabled": agent.enabled if agent else True,
            "has_toggle": agent.has_toggle if agent else False,
            "experimental": agent.experimental if agent else False,
            "requires_llm_client": cls.requires_llm_client,
        }
        actions = getattr(agent, "actions", None)

        if actions:
            config_options["actions"] = {k: v.model_dump() for k, v in actions.items()}
        else:
            config_options["actions"] = {}

        return config_options

    @property
    def meta(self):
        return {
            "essential": self.essential,
        }

    @property
    def sanitized_action_config(self):
        if not getattr(self, "actions", None):
            return {}

        return {k: v.model_dump() for k, v in self.actions.items()}

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
        if callback:
            await callback()

    async def setup_check(self):
        return False

    async def ready_check(self, task: asyncio.Task = None):
        self.ready_check_error = None
        if task:
            task.add_done_callback(
                lambda fut: asyncio.create_task(self._handle_ready_check(fut))
            )
            return
        return True

    async def apply_config(self, *args, **kwargs):
        if self.has_toggle and "enabled" in kwargs:
            self.is_enabled = kwargs.get("enabled", False)

        if not getattr(self, "actions", None):
            return

        for action_key, action in self.actions.items():
            if not kwargs.get("actions"):
                continue

            action.enabled = (
                kwargs.get("actions", {}).get(action_key, {}).get("enabled", False)
            )

            if not action.config:
                continue

            for config_key, config in action.config.items():
                try:
                    config.value = (
                        kwargs.get("actions", {})
                        .get(action_key, {})
                        .get("config", {})
                        .get(config_key, {})
                        .get("value", config.value)
                    )
                except AttributeError:
                    pass

    async def on_game_loop_start(self, event: GameLoopStartEvent):
        """
        Finds all ActionConfigs that have a scope of "scene" and resets them to their default values
        """

        if not getattr(self, "actions", None):
            return

        for _, action in self.actions.items():
            if not action.config:
                continue

            for _, config in action.config.items():
                if config.scope == "scene":
                    # if default_value is None, just use the `type` of the current
                    # value
                    if config.default_value is None:
                        default_value = type(config.value)()
                    else:
                        default_value = config.default_value

                    log.debug(
                        "resetting config", config=config, default_value=default_value
                    )
                    config.value = default_value

        await self.emit_status()

    async def emit_status(self, processing: bool = None):
        # should keep a count of processing requests, and when the
        # number is 0 status is "idle", if the number is greater than 0
        # status is "busy"
        #
        # increase / decrease based on value of `processing`

        if getattr(self, "processing", None) is None:
            self.processing = 0

        if processing is False:
            self.processing -= 1
            self.processing = max(0, self.processing)
        elif processing is True:
            self.processing += 1

        emit(
            "agent_status",
            message=self.verbose_name or "",
            id=self.agent_type,
            status=self.status,
            details=self.agent_details,
            meta=self.meta,
            data=self.config_options(agent=self),
        )

        await asyncio.sleep(0.01)

    async def _handle_background_processing(self, fut: asyncio.Future, error_handler = None):
        try:
            if fut.cancelled():
                return

            if fut.exception():
                log.error(
                    "background processing error",
                    agent=self.agent_type,
                    exc=fut.exception(),
                )

                if error_handler:
                    await error_handler(fut.exception())

                await self.emit_status()
                return

            log.info("background processing done", agent=self.agent_type)
        finally:
            self.processing_bg -= 1
            await self.emit_status()

    async def set_background_processing(self, task: asyncio.Task, error_handler = None):
        log.info("set_background_processing", agent=self.agent_type)
        if not hasattr(self, "processing_bg"):
            self.processing_bg = 0

        self.processing_bg += 1

        await self.emit_status()
        task.add_done_callback(
            lambda fut: asyncio.create_task(self._handle_background_processing(fut, error_handler))
        )

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
        memory_helper = self.scene.get_helper("memory")
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


@dataclasses.dataclass
class AgentEmission:
    agent: Agent
