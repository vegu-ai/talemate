import structlog
from typing import TYPE_CHECKING
from talemate.instance import get_agent
from talemate.emit import emit
import talemate.events as events
import talemate.emit.async_signals as async_signals
from talemate.context import regeneration_context
from talemate.scene_message import (
    SceneMessage,
    CharacterMessage,
    NarratorMessage,
    ReinforcementMessage,
    ContextInvestigationMessage,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character

__all__ = [
    "regenerate",
    "regenerate_message",
    "regenerate_character_message",
    "regenerate_target_message",
    "ensure_regenerate_allowed",
]

log = structlog.get_logger("talemate.regenerate")


def regenerate_target_message(scene: "Scene", idx: int = -1) -> SceneMessage | None:
    """
    Return the message that `regenerate(scene, idx)` would attempt to regenerate,
    without mutating history (skips trailing reinforcement messages).
    """
    try:
        cur_idx = idx
        message = scene.history[cur_idx]
    except Exception:
        return None

    # mirror regenerate() behavior: skip trailing reinforcement messages
    while isinstance(message, ReinforcementMessage):
        try:
            cur_idx -= 1
            message = scene.history[cur_idx]
        except Exception:
            return None

    return message


def ensure_regenerate_allowed(scene: "Scene", idx: int = -1) -> tuple[bool, str | None]:
    """
    Returns (allowed, error_message).

    We currently block regeneration if the regen target is a CharacterMessage whose
    character is inactive (or has no active actor). This keeps regeneration behavior
    consistent and avoids hard failures in the conversation agent.
    """
    message = regenerate_target_message(scene, idx=idx)
    if not message or not isinstance(message, CharacterMessage):
        return True, None

    character = scene.get_character(message.character_name)
    if not character:
        return False, "Cannot regenerate: character not found."

    if character.name not in scene.active_characters:
        return (
            False,
            f"Cannot regenerate: character '{character.name}' is inactive. Activate the character first.",
        )

    if not getattr(character, "actor", None):
        return (
            False,
            f"Cannot regenerate: character '{character.name}' has no active actor.",
        )

    return True, None


async def regenerate_character_message(
    message: CharacterMessage, scene: "Scene"
) -> CharacterMessage:
    character: "Character | None" = scene.get_character(message.character_name)

    if not character:
        log.error(
            "regenerate_character_message: Could not find character", message=message
        )
        return message

    agent = get_agent("conversation")

    if message.source == "player" and not message.from_choice:
        log.warning(
            "regenerate_character_message: Static user message, no regeneration possible",
            message=message,
        )
        return

    messages = await agent.converse(character.actor, instruction=message.from_choice)

    for message in messages:
        await scene.push_history(message)
        emit("character", message=message, character=character)

    return messages


async def regenerate_message(
    message: SceneMessage, scene: "Scene"
) -> list[SceneMessage] | None:
    """
    Will regenerate the message, using the meta information
    """

    if isinstance(message, CharacterMessage):
        # character messages need specific handling
        messages = await regenerate_character_message(message, scene)
    else:
        # all other message types

        try:
            agent = get_agent(message.meta.get("agent"))
        except Exception as e:
            log.error(
                "regenerate_message: Could not find agent", message=message, error=e
            )
            return

        if not agent:
            log.error("regenerate_message: Could not find agent", message=message)
            return

        function_name = message.meta.get("function")
        fn = getattr(agent, function_name, None)

        if not fn:
            log.error(
                "regenerate_message: Could not find agent function", message=message
            )
            return

        arguments = message.meta.get("arguments", {}).copy()

        # if `character` is set and a string, convert it to a Character
        if arguments.get("character") and isinstance(arguments.get("character"), str):
            arguments["character"] = scene.get_character(arguments.get("character"))

        log.debug(
            "regenerate_message: Calling agent function",
            function=function_name,
            arguments=arguments,
        )

        new_message = await fn(**arguments)

        if not new_message:
            log.error("regenerate_message: No new message generated", message=message)
            return

        if isinstance(new_message, str):
            new_message = message.__class__(new_message)
            new_message.meta = message.meta.copy()

        if isinstance(message, ContextInvestigationMessage):
            new_message.sub_type = message.sub_type

        if not isinstance(new_message, (ReinforcementMessage)):
            await scene.push_history(new_message)
            emit(new_message.typ, message=new_message)

        messages = [new_message]

    for message in messages:
        await async_signals.get(f"regenerate.msg.{message.typ}").send(
            events.RegenerateGeneration(
                scene=scene,
                message=message,
                character=scene.get_character(message.character_name)
                if isinstance(message, CharacterMessage)
                else None,
                event_type=f"regenerate.msg.{message.typ}",
            )
        )

    return messages


async def regenerate(scene: "Scene", idx: int = -1) -> list[SceneMessage]:
    """
    Regenerate the most recent AI response, remove their previous message from the history,
    and call talk() for the most recent AI Character.
    """
    # Remove AI's last response and player's last message from the history
    try:
        message = scene.history[idx]
    except IndexError:
        return

    regenerated_messages = []

    # while message type is ReinforcementMessage, keep going back in history
    # until we find a message that is not a ReinforcementMessage
    #
    # we need to pop the ReinforcementMessage from the history because
    # previous messages may have contributed to the answer that the AI gave
    # for the reinforcement message

    popped_reinforcement_messages = []

    while isinstance(message, (ReinforcementMessage,)):
        popped_reinforcement_messages.append(scene.history.pop())
        message = scene.history[idx]

    log.debug(f"Regenerating message: {message} [{message.id}]")

    if message.source == "player" and not message.from_choice:
        log.warning("Cannot regenerate player's message", message=message)
        # re-add the reinforcement messages
        for message in reversed(popped_reinforcement_messages):
            await scene.push_history(message)
        return regenerated_messages

    current_regeneration_context = regeneration_context.get()
    if current_regeneration_context:
        current_regeneration_context.message = message.message

    if not isinstance(
        message, (CharacterMessage, NarratorMessage, ContextInvestigationMessage)
    ):
        log.warning("Cannot regenerate message", message=message)
        return regenerated_messages

    scene.history.pop()
    emit("remove_message", "", id=message.id)
    new_messages = await regenerate_message(message, scene)

    if not new_messages:
        log.error("No new messages generated", message=message)
        await scene.push_history(message)
        for message in reversed(popped_reinforcement_messages):
            await scene.push_history(message)
        return regenerated_messages

    if new_messages:
        regenerated_messages.extend(new_messages)

    for message in popped_reinforcement_messages:
        new_messages = await regenerate_message(message, scene)
        if new_messages:
            regenerated_messages.extend(new_messages)

    return regenerated_messages
