from __future__ import annotations

import asyncio
import dataclasses
from typing import TYPE_CHECKING, Callable

import structlog

from talemate.context import interaction
from talemate.scene_message import SceneMessage
from talemate.exceptions import RestartSceneLoop, AbortCommand, AbortWaitForInput

from .signals import handlers
import talemate.emit.async_signals as async_signals
from talemate.events import UserInteractionEvent

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene

__all__ = [
    "emit",
    "Receiver",
    "Emission",
    "Emitter",
]

log = structlog.get_logger("talemate.emit.base")

# Register general user interaction signal
async_signals.register("user_interaction")


@dataclasses.dataclass
class Emission:
    typ: str
    message: str = None
    message_object: SceneMessage = None
    character: Character = None
    scene: Scene = None
    status: str = None
    id: str = None
    details: str = None
    data: dict = None
    websocket_passthrough: bool = False
    meta: dict = dataclasses.field(default_factory=dict)
    kwargs: dict = dataclasses.field(default_factory=dict)


def emit(
    typ: str,
    message: str = None,
    character: Character = None,
    scene: Scene = None,
    **kwargs,
):
    if typ not in handlers:
        raise ValueError(f"Unknown message type: {typ}")

    if isinstance(message, SceneMessage):
        kwargs["id"] = message.id
        message_object = message
        message = message.message
    else:
        message_object = None

    handlers[typ].send(
        Emission(
            typ=typ,
            message=message,
            character=character,
            scene=scene,
            message_object=message_object,
            **kwargs,
        )
    )


async def wait_for_input_yesno(message: str, default: str = "yes"):
    return await wait_for_input(
        message,
        data={
            "input_type": "select",
            "default": default,
            "choices": ["yes", "no"],
            "multi_select": False,
        },
    )


async def wait_for_input(
    message: str = "",
    character: Character = None,
    scene: Scene = None,
    data: dict = None,
    return_struct: bool = False,
    abort_condition: Callable = None,
    sleep_time: float = 0.1,
) -> str | dict:
    """
    Wait for input from the user.

    Arguments:

    - message: The message to display to the user.
    - character: The character related to the input.
    - scene: The scene related to the input.
    - data: Additional data to pass to the frontend.
    - return_struct: If True, return the entire input structure.
    """

    input_received = {"message": None}

    def input_receiver(emission: Emission):
        input_received["message"] = emission.message
        input_received["interaction"] = interaction.get()

    handlers["receive_input"].connect(input_receiver)
    try:
        handlers["request_input"].send(
            Emission(
                typ="request_input",
                message=message,
                character=character,
                scene=scene,
                data=data,
            )
        )

        while input_received["message"] is None:
            await asyncio.sleep(sleep_time)

            interaction_state = interaction.get()

            if abort_condition and (await abort_condition()):
                raise AbortWaitForInput()

            if interaction_state.reset_requested:
                interaction_state.reset_requested = False
                raise RestartSceneLoop()

            if scene is not None and scene.restart_scene_loop_requested:
                scene.restart_scene_loop_requested = False
                raise RestartSceneLoop()

            if interaction_state.input:
                input_received["message"] = interaction_state.input
                input_received["interaction"] = interaction_state
                input_received["from_choice"] = interaction_state.from_choice
                interaction_state.input = None
                interaction_state.from_choice = None
                break
    finally:
        handlers["receive_input"].disconnect(input_receiver)

    if input_received["message"] == "!abort":
        raise AbortCommand()

    # Emit general user interaction signal
    try:
        emission = UserInteractionEvent(
            message=input_received["message"],
            character=character,
        )
        await async_signals.get("user_interaction").send(emission)
    except Exception as e:
        log.error("emit.user_interaction.error", error=e)

    if return_struct:
        return input_received
    return input_received["message"]


def abort_wait_for_input():
    for receiver in list(handlers["receive_input"].receivers):
        log.debug("aborting waiting for input", receiver=receiver)
        handlers["receive_input"].disconnect(receiver)


class Receiver:
    def handle(self, emission: Emission):
        fn = getattr(self, f"handle_{emission.typ}", None)
        if not fn:
            return False
        fn(emission)
        return True

    def connect(self):
        for typ in handlers:
            handlers[typ].connect(self.handle)

    def disconnect(self):
        for typ in handlers:
            handlers[typ].disconnect(self.handle)


class Emitter:
    emit_for_scene = None

    def setup_emitter(self, scene: Scene = None):
        self.emit_for_scene = scene

    def emit(self, typ: str, message: str, character: Character = None, **kwargs):
        emit(typ, message, character=character, scene=self.emit_for_scene, **kwargs)

    def system_message(self, message: str, **kwargs):
        self.emit("system", message, **kwargs)

    def narrator_message(self, message: str):
        self.emit("narrator", message)

    def character_message(self, message: str, character: Character):
        self.emit("character", message, character=character)

    def player_message(self, message: str, character: Character):
        self.emit("player", message, character=character)

    def context_investigation_message(self, message: str):
        self.emit("context_investigation", message)
