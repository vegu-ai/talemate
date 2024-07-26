from __future__ import annotations

import asyncio
import dataclasses
from typing import TYPE_CHECKING, Any

import structlog

from talemate.context import interaction
from talemate.scene_message import SceneMessage

from .signals import handlers

if TYPE_CHECKING:
    from talemate.tale_mate import Character, Scene

__all__ = [
    "emit",
    "Receiver",
    "Emission",
    "Emitter",
]

log = structlog.get_logger("talemate.emit.base")


class AbortCommand(IOError):
    pass


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
        await asyncio.sleep(0.1)

    handlers["receive_input"].disconnect(input_receiver)

    if input_received["message"] == "!abort":
        raise AbortCommand()

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

    def emit(self, typ: str, message: str, character: Character = None):
        emit(typ, message, character=character, scene=self.emit_for_scene)

    def system_message(self, message: str):
        self.emit("system", message)

    def narrator_message(self, message: str):
        self.emit("narrator", message)

    def character_message(self, message: str, character: Character):
        self.emit("character", message, character=character)

    def player_message(self, message: str, character: Character):
        self.emit("player", message, character=character)
