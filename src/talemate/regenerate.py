import structlog
from typing import TYPE_CHECKING
from talemate.instance import get_agent
from talemate.emit import emit
import talemate.events as events
import talemate.emit.async_signals as async_signals
from talemate.agents.editor.revision import RevisionContext
from talemate.context import regeneration_context
from talemate.exceptions import GenerationCancelled
from talemate.scene_message import (
    SceneMessage,
    CharacterMessage,
    VersionSource,
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
    "regeneration_status",
    "can_regenerate",
]

log = structlog.get_logger("talemate.regenerate")


def regenerate_target_message(scene: "Scene") -> SceneMessage | None:
    """
    Return the message that ``regenerate(scene)`` would attempt to
    regenerate, without mutating history (skips trailing reinforcement
    messages).
    """
    cur_idx = -1
    try:
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


def ensure_regenerate_allowed(scene: "Scene") -> tuple[bool, str | None]:
    """
    Returns (allowed, error_message).

    We currently block regeneration if the regen target is a CharacterMessage whose
    character is inactive (or has no active actor). This keeps regeneration behavior
    consistent and avoids hard failures in the conversation agent.
    """
    message = regenerate_target_message(scene)
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


def regeneration_status(scene: "Scene") -> tuple[bool, str | None]:
    """
    Single source of truth for whether the tail of ``scene.history`` can
    be regenerated right now. Returns ``(can_regenerate, reason)`` where
    ``reason`` is a user-facing explanation when regeneration is blocked
    (``None`` when it's allowed).

    Mirrors the guard conditions inside ``regenerate()`` without mutating
    history, so the UI's button state and the actual regenerate flow
    never disagree.
    """
    message = regenerate_target_message(scene)
    if message is None:
        return False, "Nothing to regenerate yet."

    # `from_choice` is a CharacterMessage-only field; `source` lives on the
    # base SceneMessage, so guard the access — this runs on the hot
    # scene_status path and an AttributeError here would break every emit.
    if message.source == "player" and not getattr(message, "from_choice", False):
        return False, "Cannot regenerate a static player message."

    if not isinstance(
        message, (CharacterMessage, NarratorMessage, ContextInvestigationMessage)
    ):
        return False, "The most recent message cannot be regenerated."

    # folds in the inactive-character guard
    return ensure_regenerate_allowed(scene)


def can_regenerate(scene: "Scene") -> bool:
    """
    Whether the tail of ``scene.history`` can be regenerated right now.

    Drops the blocked-reason from :func:`regeneration_status`; call that
    directly when the reason is needed (e.g. to surface it in the UI).
    """
    return regeneration_status(scene)[0]


async def _converse_for_character_message(
    message: CharacterMessage, scene: "Scene"
) -> tuple["Character", list[CharacterMessage]] | None:
    """
    Resolve the character that owns ``message`` and ask the conversation
    agent to produce replacement message(s). Returns ``(character,
    messages)`` or ``None`` when the message can't be regenerated (no
    character, or a static user line). Side-effect free — does NOT push
    to history or emit.
    """
    character: "Character | None" = scene.get_character(message.character_name)
    if not character:
        log.error("regenerate: Could not find character for message", message=message)
        return None

    if message.source == "player" and not message.from_choice:
        log.warning(
            "regenerate: Static user message, no regeneration possible",
            message=message,
        )
        return None

    agent = get_agent("conversation")
    messages = await agent.converse(character.actor, instruction=message.from_choice)
    return character, messages


async def regenerate_character_message(
    message: CharacterMessage, scene: "Scene"
) -> list[CharacterMessage] | None:
    result = await _converse_for_character_message(message, scene)
    if result is None:
        return None
    character, messages = result

    for message in messages:
        await scene.push_history(message)
        emit("character", message=message, character=character)

    return messages


async def _dispatch_agent_regeneration(
    message: SceneMessage, scene: "Scene"
) -> list[SceneMessage] | None:
    """
    Build replacement message(s) by calling the agent function recorded on
    ``message.meta``. Does NOT push to history or emit — caller decides
    what to do with the result.

    For ``CharacterMessage`` the conversation agent's ``converse`` returns
    one or more ``CharacterMessage`` objects directly.
    For other supported types the meta-driven function may return either a
    new ``SceneMessage`` or a raw string (wrapped into ``message.__class__``).

    Returns the list of new SceneMessage objects (auto-revision has NOT
    been applied yet — that's the caller's job via push_history or
    ``editor.maybe_revise_inplace``).
    """
    if isinstance(message, CharacterMessage):
        result = await _converse_for_character_message(message, scene)
        if result is None:
            return None
        _character, messages = result
        return messages

    try:
        agent = get_agent(message.meta.get("agent"))
    except Exception as e:
        log.error(
            "_dispatch_agent_regeneration: Could not find agent",
            message=message,
            error=e,
        )
        return None

    if not agent:
        log.error("_dispatch_agent_regeneration: Could not find agent", message=message)
        return None

    function_name = message.meta.get("function")
    fn = getattr(agent, function_name, None)

    if not fn:
        log.error(
            "_dispatch_agent_regeneration: Could not find agent function",
            message=message,
        )
        return None

    arguments = message.meta.get("arguments", {}).copy()

    # if `character` is set and a string, convert it to a Character
    if arguments.get("character") and isinstance(arguments.get("character"), str):
        arguments["character"] = scene.get_character(arguments.get("character"))

    log.debug(
        "_dispatch_agent_regeneration: Calling agent function",
        function=function_name,
        arguments=arguments,
    )

    new_message = await fn(**arguments)

    if not new_message:
        log.error(
            "_dispatch_agent_regeneration: No new message generated", message=message
        )
        return None

    if isinstance(new_message, str):
        new_message = message.__class__(new_message)
        new_message.meta = message.meta.copy()

    if isinstance(message, ContextInvestigationMessage):
        new_message.sub_type = message.sub_type

    return [new_message]


async def regenerate_message(
    message: SceneMessage, scene: "Scene"
) -> list[SceneMessage] | None:
    """
    Regenerate the message via the dispatch table and push the result(s)
    onto scene history. Used by the reinforcement-message re-generation
    pass — the in-place top-level ``regenerate`` flow uses
    ``_regenerate_inplace`` instead.
    """

    if isinstance(message, CharacterMessage):
        # character messages need specific handling — including its own
        # push + emit loop
        messages = await regenerate_character_message(message, scene)
        if messages is None:
            return None
    else:
        new_messages = await _dispatch_agent_regeneration(message, scene)
        if not new_messages:
            return None

        messages = new_messages
        for new_message in messages:
            if not isinstance(new_message, (ReinforcementMessage,)):
                await scene.push_history(new_message)
                emit(new_message.typ, message=new_message)

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


async def _regenerate_inplace(
    message: SceneMessage, scene: "Scene"
) -> list[tuple[str, VersionSource]] | None:
    """
    Run the agent path for ``message`` and return the version(s) the
    caller should append onto the existing message's revision stack.

    This does NOT push the new message to history nor emit any
    ``character``/``narrator`` message — the caller is expected to
    re-attach the original message to history and walk the returned list,
    calling ``scene.append_message_version`` for each entry so the slot
    keeps its id and grows its stack with the regen output.

    Returned shape, in append order:
    - ``[(raw_regen, "regenerate")]`` — auto-revision did not rewrite the
      regen output, so the canonical is the raw regenerate text.
    - ``[(raw_regen, "regenerate"), (polished, "revision")]`` —
      auto-revision rewrote the regen; both stay on the stack so the
      user can navigate to the unrevised version.

    The ``raw_regen`` entry is dropped when it matches the prior
    canonical (i.e. the active version on the message at regen time),
    since that text is already at the active index — appending a
    duplicate would just clutter the stack.

    Returns ``None`` on failure or empty result.
    """
    # Snapshot the canonical text before regeneration so we can detect
    # the "raw regen matches prior canonical" duplicate case.
    prior_canonical = message.message

    new_messages = await _dispatch_agent_regeneration(message, scene)
    if not new_messages:
        return None

    # Use the first generated message as the new canonical. Multi-message
    # results (rare; conversation can split) collapse to the first.
    new_message = new_messages[0]
    if not new_message.message:
        return None

    raw_regen = new_message.message

    # Auto-revision normally runs at push_history time, but in-place
    # regenerate skips push_history. Invoke the editor's in-place hook
    # directly so the same gating + behavior applies. Scope the revision
    # context to the original message slot (still in history) so the
    # repetition range excludes it — new_message isn't in history yet.
    editor = get_agent("editor")
    with RevisionContext(message.id):
        canonical_was_revised = await editor.maybe_revise_inplace(new_message)

    versions_to_append: list[tuple[str, VersionSource]] = []
    if raw_regen != prior_canonical:
        versions_to_append.append((raw_regen, "regenerate"))
    if canonical_was_revised:
        versions_to_append.append((new_message.message, "revision"))

    # No-op: raw regen matched prior canonical and revision didn't fire.
    if not versions_to_append:
        return None

    # Fire the regenerate.msg.* signals for downstream consumers (e.g.
    # avatar/asset hooks) — matches the previous push-emit flow.
    for m in new_messages:
        await async_signals.get(f"regenerate.msg.{m.typ}").send(
            events.RegenerateGeneration(
                scene=scene,
                message=m,
                character=scene.get_character(m.character_name)
                if isinstance(m, CharacterMessage)
                else None,
                event_type=f"regenerate.msg.{m.typ}",
            )
        )

    return versions_to_append


async def _restore_history_after_failed_regenerate(
    scene: "Scene",
    message: SceneMessage,
    popped_reinforcement_messages: list[ReinforcementMessage],
) -> None:
    """
    Put history back the way it was before the regenerate attempt and tell
    the frontend to drop the spinner on the message's slot. Shared by the
    failure and the user-cancellation paths of ``regenerate``.
    """
    scene.history.append(message)
    emit(
        "regenerate_failed",
        "",
        websocket_passthrough=True,
        kwargs={"id": message.id},
    )
    for reinforcement_message in reversed(popped_reinforcement_messages):
        await scene.push_history(reinforcement_message)


async def regenerate(scene: "Scene") -> list[SceneMessage]:
    """
    In-place regenerate the most recent AI response (the tail of
    ``scene.history``, skipping trailing reinforcement messages): keep
    the original SceneMessage id and append the regen output(s) as new
    versions on the message's revision stack via
    ``scene.append_message_version``. When auto-revision rewrites the
    regen, both the raw and revised versions land on the stack so the
    user can navigate to either.
    """
    regenerated_messages: list[SceneMessage] = []

    # Guard via the shared predicate so the UI's button state and this
    # flow can't drift apart. Checked before any history mutation, so a
    # blocked regenerate is a clean no-op.
    can_regen, reason = regeneration_status(scene)
    if not can_regen:
        log.warning("Cannot regenerate", reason=reason)
        return regenerated_messages

    # while message type is ReinforcementMessage, keep going back in history
    # until we find a message that is not a ReinforcementMessage
    #
    # we need to pop the ReinforcementMessage from the history because
    # previous messages may have contributed to the answer that the AI gave
    # for the reinforcement message
    popped_reinforcement_messages: list[ReinforcementMessage] = []

    message = scene.history[-1]
    while isinstance(message, (ReinforcementMessage,)):
        popped_reinforcement_messages.append(scene.history.pop())
        message = scene.history[-1]

    # `regeneration_status` already validated this target (non-static,
    # regeneratable type, active character).
    log.debug(f"Regenerating message: {message} [{message.id}]")

    current_regeneration_context = regeneration_context.get()
    if current_regeneration_context:
        current_regeneration_context.message = message.message

    # Pop the target from history before invoking the agent — otherwise
    # the LLM sees its own prior output in context and just rephrases it.
    # After the reinforcement-message pop loop above, the target is at the
    # tail, so a plain pop suffices. We re-append it afterward so the
    # message id (and the frontend's revision stack tied to it) is
    # preserved.
    scene.history.pop()

    try:
        outcome = await _regenerate_inplace(message, scene)
    except GenerationCancelled:
        # User-initiated interrupt — not a failure. Restore history, report
        # the cancellation as a normal (non-error) status, then re-raise so
        # the task done-callback posts the regenerate_failed envelope and
        # the scene's cancel flag is cleared.
        log.warning("regenerate: Generation cancelled by user", message=message)
        await _restore_history_after_failed_regenerate(
            scene, message, popped_reinforcement_messages
        )
        emit("status", message="Regeneration cancelled.", status="idle")
        raise
    except Exception as e:
        log.error("regenerate: Exception during regeneration", message=message, error=e)
        outcome = None

    if not outcome:
        log.error("No new message generated", message=message)
        await _restore_history_after_failed_regenerate(
            scene, message, popped_reinforcement_messages
        )
        emit(
            "status",
            message="Could not regenerate message.",
            status="error",
        )
        return regenerated_messages

    versions_to_append = outcome

    # Re-append with the same id so the slot keeps its frontend
    # revision stack; each call below pushes one entry onto the stack,
    # with the last one becoming the active canonical.
    scene.history.append(message)
    for text, source in versions_to_append:
        scene.append_message_version(message.id, text, source=source)

    regenerated_messages.append(message)

    for reinforcement_message in popped_reinforcement_messages:
        new_messages = await regenerate_message(reinforcement_message, scene)
        if new_messages:
            regenerated_messages.extend(new_messages)

    return regenerated_messages
