"""Unit tests for talemate.regenerate.

Tests target the public entry points (regenerate_target_message,
ensure_regenerate_allowed, regenerate_message, regenerate) using a real
Scene instance and real SceneMessage subclasses. Network/UI side effects
(emit, async_signals.send) are silenced by stubbing the imported names
inside the regenerate module.

Skipped path:
- regenerate_character_message: depends on talemate.tale_mate.Actor and
  conversation agent's `converse(actor, instruction=...)` returning a list
  of messages. We test the wrapper (regenerate_message) instead, which
  routes character messages through the real ConversationAgent (with its
  `converse` method stubbed at the instance level — peripheral RPC).
"""

from __future__ import annotations

import pytest

import talemate.instance as instance
import talemate.regenerate as regenerate_mod
from talemate.agents.conversation import ConversationAgent
from talemate.exceptions import GenerationCancelled
from talemate.regenerate import (
    can_regenerate,
    ensure_regenerate_allowed,
    regenerate,
    regenerate_message,
    regenerate_target_message,
    regeneration_status,
)
from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    NarratorMessage,
    ReinforcementMessage,
)
from talemate.tale_mate import Actor, Scene


# ---------------------------------------------------------------------------
# Module-level stubs for emit + signals — keep tests deterministic
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_emit_and_signals(monkeypatch):
    """Stub emit + async_signals.get(...) so regenerate doesn't touch the bus.

    Returns the list of emit-call records: list of {"name": str, "kwargs": dict}.
    """
    emitted: list[dict] = []

    def fake_emit(name, *args, **kwargs):
        emitted.append({"name": name, "args": args, "kwargs": kwargs})

    monkeypatch.setattr(regenerate_mod, "emit", fake_emit)

    class _Signal:
        async def send(self, *args, **kwargs):
            pass

    class _Signals:
        def get(self, name):
            return _Signal()

    monkeypatch.setattr(regenerate_mod, "async_signals", _Signals())

    return emitted


# ---------------------------------------------------------------------------
# Scene fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def scene():
    """Real Scene instance with no actors/history. Tests configure as needed."""
    s = Scene()
    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_actor(character) -> Actor:
    """Build a real `Actor` linked to `character` (no agent needed for these tests)."""
    return Actor(character=character, agent=None)


def _make_character_message(
    name: str = "Alice", body: str = "Hello"
) -> CharacterMessage:
    """Build a real CharacterMessage with proper "Name: body" format."""
    return CharacterMessage(message=f"{name}: {body}")


# ---------------------------------------------------------------------------
# regenerate_target_message
# ---------------------------------------------------------------------------


class TestRegenerateTargetMessage:
    def test_returns_none_for_empty_history(self, scene):
        assert regenerate_target_message(scene) is None

    def test_returns_last_message_by_default(self, scene):
        m1 = NarratorMessage(message="first")
        m2 = NarratorMessage(message="second")
        scene.history = [m1, m2]
        assert regenerate_target_message(scene) is m2

    def test_skips_trailing_reinforcement_messages(self, scene):
        narration = NarratorMessage(message="real target")
        r1 = ReinforcementMessage(message="reinforce 1")
        r2 = ReinforcementMessage(message="reinforce 2")
        scene.history = [narration, r1, r2]
        # Default idx=-1 → walk back over reinforcements → narration
        assert regenerate_target_message(scene) is narration

    def test_returns_none_when_only_reinforcements_present(self, scene):
        # When all messages are reinforcements, walk-back exhausts history → None
        scene.history = [ReinforcementMessage(message="r1")]
        assert regenerate_target_message(scene) is None

    def test_returns_none_on_empty_history(self, scene):
        scene.history = []
        assert regenerate_target_message(scene) is None


# ---------------------------------------------------------------------------
# ensure_regenerate_allowed
# ---------------------------------------------------------------------------


class TestEnsureRegenerateAllowed:
    def test_allows_when_history_is_empty(self, scene):
        allowed, reason = ensure_regenerate_allowed(scene)
        assert allowed is True
        assert reason is None

    def test_allows_for_non_character_messages(self, scene):
        scene.history = [NarratorMessage(message="x")]
        allowed, reason = ensure_regenerate_allowed(scene)
        assert allowed is True
        assert reason is None

    def test_blocks_when_character_not_found(self, scene):
        scene.history = [_make_character_message("Bob")]
        # No characters in scene → get_character returns None → blocked.
        allowed, reason = ensure_regenerate_allowed(scene)
        assert allowed is False
        assert "not found" in reason.lower()

    def test_blocks_when_character_inactive(self, scene):
        # Stub get_character + active_characters: character exists but inactive.
        from talemate.character import Character

        char = Character(name="Bob")
        scene.character_data["Bob"] = char
        # Note: scene.active_characters is empty list — Bob is inactive.
        scene.history = [_make_character_message("Bob")]
        allowed, reason = ensure_regenerate_allowed(scene)
        assert allowed is False
        assert "inactive" in reason.lower()

    def test_blocks_when_character_has_no_actor(self, scene, monkeypatch):
        """An active character without an actor cannot be regenerated."""
        from talemate.character import Character

        char = Character(name="Bob")  # actor=None by default
        # Bypass scene.get_character's strict lookup: we can't easily attach
        # an actor in a real Scene without going through Actor wiring. Patch
        # get_character on this instance.
        scene.history = [_make_character_message("Bob")]
        monkeypatch.setattr(scene, "get_character", lambda name: char)
        scene.active_characters = ["Bob"]

        allowed, reason = ensure_regenerate_allowed(scene)
        assert allowed is False
        assert "no active actor" in reason.lower()

    def test_allows_when_character_active_and_has_actor(self, scene, monkeypatch):
        from talemate.character import Character

        char = Character(name="Bob")
        _make_actor(char)
        monkeypatch.setattr(scene, "get_character", lambda name: char)
        scene.active_characters = ["Bob"]
        scene.history = [_make_character_message("Bob")]

        allowed, reason = ensure_regenerate_allowed(scene)
        assert allowed is True
        assert reason is None


# ---------------------------------------------------------------------------
# regeneration_status / can_regenerate
# ---------------------------------------------------------------------------


class TestRegenerationStatus:
    """`regeneration_status` is the shared predicate behind both the
    regenerate buttons (via scene_status) and `regenerate()`'s own guard,
    so it must mirror every early-return condition of `regenerate()`."""

    def test_blocks_when_history_is_empty(self, scene):
        allowed, reason = regeneration_status(scene)
        assert allowed is False
        assert reason == "Nothing to regenerate yet."

    def test_blocks_static_player_message(self, scene):
        msg = _make_character_message("Alice", "hello")
        msg.source = "player"  # static player msg, no from_choice
        scene.history = [msg]

        allowed, reason = regeneration_status(scene)
        assert allowed is False
        assert "static player message" in reason.lower()

    def test_blocks_unsupported_message_type(self, scene):
        from talemate.scene_message import TimePassageMessage

        scene.history = [TimePassageMessage(message="some time later")]

        allowed, reason = regeneration_status(scene)
        assert allowed is False
        assert "cannot be regenerated" in reason.lower()

    def test_allows_narrator_message(self, scene):
        scene.history = [NarratorMessage(message="the room is quiet")]

        allowed, reason = regeneration_status(scene)
        assert allowed is True
        assert reason is None

    def test_player_sourced_non_character_message_does_not_raise(self, scene):
        # `from_choice` is a CharacterMessage-only field; a NarratorMessage
        # whose `source` is "player" must not raise AttributeError on the
        # static-player guard (this runs on the hot scene_status path).
        msg = NarratorMessage(message="the room is quiet")
        msg.source = "player"
        scene.history = [msg]

        allowed, reason = regeneration_status(scene)
        assert allowed is False
        assert reason is not None

    def test_skips_trailing_reinforcements_to_find_target(self, scene):
        # A regeneratable narrator buried under trailing reinforcements is
        # still the target — same walk-back as `regenerate_target_message`.
        scene.history = [
            NarratorMessage(message="real target"),
            ReinforcementMessage(message="r1"),
        ]

        allowed, reason = regeneration_status(scene)
        assert allowed is True
        assert reason is None

    def test_delegates_inactive_character_guard(self, scene):
        # Character message whose character is inactive → blocked with the
        # reason produced by `ensure_regenerate_allowed`.
        from talemate.character import Character

        scene.character_data["Bob"] = Character(name="Bob")
        # scene.active_characters left empty → Bob is inactive
        scene.history = [_make_character_message("Bob")]

        allowed, reason = regeneration_status(scene)
        assert allowed is False
        assert "inactive" in reason.lower()

    def test_can_regenerate_is_boolean_projection(self, scene):
        assert can_regenerate(scene) is False
        scene.history = [NarratorMessage(message="now there is something")]
        assert can_regenerate(scene) is True


# ---------------------------------------------------------------------------
# Helpers for regenerate / regenerate_message tests
# ---------------------------------------------------------------------------


def _conversation_agent_with_canned(messages):
    """Build a real `ConversationAgent` with `converse` stubbed at the instance level.

    Returns the agent. `agent.calls` is the list of `{"actor", "instruction"}`
    records captured per `converse` invocation. `converse` is a peripheral RPC
    method here — the unit under test is `regenerate_message`, which routes
    character messages through this agent. Stubbing the method on a real
    agent (instead of redefining the whole class) preserves contract checks
    on every other ConversationAgent attribute.
    """
    agent = ConversationAgent()
    agent.calls = []

    async def _converse(actor, instruction=None):
        agent.calls.append({"actor": actor, "instruction": instruction})
        return list(messages)

    agent.converse = _converse
    return agent


class _NoopEditor:
    """No-op editor used when the test doesn't care about auto-revision.

    `_regenerate_inplace` unconditionally calls `editor.maybe_revise_inplace`,
    so the editor must be present in the registry. Returning False mirrors
    the "auto-revision was a no-op or disabled" path.
    """

    async def maybe_revise_inplace(self, message):
        return False


@pytest.fixture
def register_agent():
    """Register / restore agents in instance.AGENTS.

    Pre-registers a no-op editor so `_regenerate_inplace` can always
    reach `editor.maybe_revise_inplace`. Tests that exercise auto-revision
    behavior override the editor by re-registering it via `_set("editor", ...)`.
    """
    original = instance.AGENTS.copy()
    instance.AGENTS["editor"] = _NoopEditor()

    def _set(name, agent):
        instance.AGENTS[name] = agent

    yield _set
    instance.AGENTS.clear()
    instance.AGENTS.update(original)


def _install_append_message_version_spy(scene, monkeypatch) -> list[dict]:
    """Install a spy on ``scene.append_message_version`` that records each
    call as ``{message_id, text, source, reason}`` into the returned list
    and still delegates to the real method so the version stack updates
    as it would in production."""
    calls: list[dict] = []
    real = scene.append_message_version

    def _spy(message_id, text, source, reason=None):
        calls.append(
            {
                "message_id": message_id,
                "text": text,
                "source": source,
                "reason": reason,
            }
        )
        return real(message_id, text, source=source, reason=reason)

    monkeypatch.setattr(scene, "append_message_version", _spy)
    return calls


# ---------------------------------------------------------------------------
# regenerate_message — non-character path (most code paths)
# ---------------------------------------------------------------------------


class TestRegenerateMessageNonCharacter:
    @pytest.mark.asyncio
    async def test_calls_agent_function_and_pushes_new_message(
        self, scene, register_agent
    ):
        new_text = "fresh narration"

        class _NarratorAgent:
            async def progress_story(self, **kwargs):
                return NarratorMessage(message=new_text)

        register_agent("narrator", _NarratorAgent())

        original = NarratorMessage(message="old narration")
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {"narrative_direction": "forward"},
        }

        result = await regenerate_message(original, scene)

        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], NarratorMessage)
        assert result[0].message == new_text
        # The new message should have been pushed onto history.
        assert result[0] in scene.history

    @pytest.mark.asyncio
    async def test_string_return_wrapped_in_message_class(self, scene, register_agent):
        class _NarratorAgent:
            async def progress_story(self, **kwargs):
                # Return raw string — function should wrap it in NarratorMessage
                # using the original message's __class__.
                return "raw text"

        register_agent("narrator", _NarratorAgent())

        original = NarratorMessage(message="old")
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }

        result = await regenerate_message(original, scene)
        assert isinstance(result[0], NarratorMessage)
        assert result[0].message == "raw text"
        # meta is copied from original
        assert result[0].meta == original.meta

    @pytest.mark.asyncio
    async def test_context_investigation_preserves_sub_type(
        self, scene, register_agent
    ):
        class _Investigator:
            async def investigate(self, **kwargs):
                return ContextInvestigationMessage(message="result text")

        register_agent("investigator", _Investigator())

        original = ContextInvestigationMessage(message="prior")
        original.sub_type = "query"
        original.meta = {
            "agent": "investigator",
            "function": "investigate",
            "arguments": {},
        }

        result = await regenerate_message(original, scene)
        assert result and isinstance(result[0], ContextInvestigationMessage)
        # sub_type carries from the original.
        assert result[0].sub_type == "query"

    @pytest.mark.asyncio
    async def test_examine_entity_dispatch_passes_full_arguments(
        self, scene, register_agent
    ):
        """Regression for the world_state examine_entity flow. Covers the
        public stamp path (set_source) and the dispatcher path
        (regenerate_message -> _dispatch_agent_regeneration) together: if
        either side drops a kwarg between SOURCE_ARGS and the agent method,
        captured won't match.
        """
        captured = {}

        class _WorldStateAgent:
            async def examine_entity(self, **kwargs):
                captured.update(kwargs)
                return "regenerated examine text"

        register_agent("world_state", _WorldStateAgent())

        SOURCE_ARGS = {
            "entity_name": "The Silver Dagger",
            "entity_kind": "item",
            "snapshot_text": "A worn silver dagger with an etched pommel sigil.",
        }

        original = ContextInvestigationMessage(message="prior examine text")
        original.sub_type = "examine"
        # Production write path: handle_examine_entity calls set_source the
        # same way. Exercising it here means a drop/rename inside set_source
        # itself would also fail this test.
        original.set_source("world_state", "examine_entity", **SOURCE_ARGS)

        result = await regenerate_message(original, scene)

        assert result and isinstance(result[0], ContextInvestigationMessage)
        assert result[0].sub_type == "examine"
        assert result[0].message == "regenerated examine text"
        # All three arguments stamped by handle_examine_entity must reach
        # the agent method on regeneration.
        assert captured == SOURCE_ARGS

    @pytest.mark.asyncio
    async def test_returns_none_when_agent_function_returns_none(
        self, scene, register_agent
    ):
        class _NarratorAgent:
            async def progress_story(self, **kwargs):
                return None

        register_agent("narrator", _NarratorAgent())

        original = NarratorMessage(message="old")
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }

        result = await regenerate_message(original, scene)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_function_not_found_on_agent(
        self, scene, register_agent
    ):
        class _MinimalAgent:
            pass

        register_agent("narrator", _MinimalAgent())

        original = NarratorMessage(message="old")
        original.meta = {
            "agent": "narrator",
            "function": "does_not_exist",
            "arguments": {},
        }

        result = await regenerate_message(original, scene)
        assert result is None

    @pytest.mark.asyncio
    async def test_string_character_argument_resolved_to_object(
        self, scene, register_agent, monkeypatch
    ):
        from talemate.character import Character

        captured = {}

        class _NarratorAgent:
            async def narrate_character(self, **kwargs):
                captured.update(kwargs)
                return NarratorMessage(message="ok")

        register_agent("narrator", _NarratorAgent())

        bob = Character(name="Bob")
        monkeypatch.setattr(
            scene,
            "get_character",
            lambda name: bob if name == "Bob" else None,
        )

        original = NarratorMessage(message="old")
        original.meta = {
            "agent": "narrator",
            "function": "narrate_character",
            "arguments": {"character": "Bob"},
        }

        await regenerate_message(original, scene)
        # Agent received a Character object — not the original string.
        assert captured.get("character") is bob


# ---------------------------------------------------------------------------
# regenerate_message — character path (delegates to conversation agent)
# ---------------------------------------------------------------------------


class TestRegenerateCharacterMessage:
    @pytest.mark.asyncio
    async def test_returns_none_when_character_not_in_scene(
        self, scene, register_agent
    ):
        """When the named character is missing, regenerate_message returns
        None and the conversation agent is never called. The outer
        `regenerate()` handles None by restoring the original message; direct
        callers get the same contract.
        """
        conv = _conversation_agent_with_canned([])
        register_agent("conversation", conv)
        msg = _make_character_message("Ghost")

        result = await regenerate_message(msg, scene)

        assert result is None
        assert conv.calls == []

    @pytest.mark.asyncio
    async def test_static_player_message_returns_none(
        self, scene, register_agent, monkeypatch
    ):
        """Static player messages (source='player' without from_choice)
        cannot be regenerated. regenerate_message returns None instead of
        crashing.
        """
        from talemate.character import Character

        char = Character(name="Alice")
        _make_actor(char)
        monkeypatch.setattr(scene, "get_character", lambda name: char)

        # source=player and no from_choice → "static user message" path.
        msg = _make_character_message("Alice", "static line")
        msg.source = "player"
        msg.from_choice = None

        conv = _conversation_agent_with_canned([])
        register_agent("conversation", conv)

        result = await regenerate_message(msg, scene)

        assert result is None
        # The conversation agent's `converse` was not invoked.
        assert conv.calls == []

    @pytest.mark.asyncio
    async def test_regenerates_via_conversation_agent_when_from_choice_set(
        self, scene, register_agent, monkeypatch
    ):
        from talemate.character import Character

        char = Character(name="Alice")
        _make_actor(char)
        monkeypatch.setattr(scene, "get_character", lambda name: char)

        new_msg = _make_character_message("Alice", "regenerated dialogue")
        conv = _conversation_agent_with_canned([new_msg])
        register_agent("conversation", conv)

        original = _make_character_message("Alice", "original dialogue")
        original.source = "player"
        original.from_choice = "Be cheerful"

        result = await regenerate_message(original, scene)

        # Conversation agent was called with the actor and from_choice.
        assert len(conv.calls) == 1
        assert conv.calls[0]["actor"] is char.actor
        assert conv.calls[0]["instruction"] == "Be cheerful"
        # The new message was pushed to history.
        assert new_msg in scene.history
        assert result == [new_msg]


# ---------------------------------------------------------------------------
# regenerate (top-level orchestrator)
# ---------------------------------------------------------------------------


class TestRegenerate:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_history_empty(self, scene):
        # Empty history → regeneration_status blocks it → clean no-op,
        # returns the empty regenerated-messages list.
        result = await regenerate(scene)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_static_player_message(
        self, scene, register_agent
    ):
        from talemate.character import Character

        char = Character(name="Alice")
        scene.character_data["Alice"] = char
        scene.active_characters = ["Alice"]
        msg = _make_character_message("Alice", "hello")
        msg.source = "player"  # static player msg with no from_choice
        scene.history = [msg]

        result = await regenerate(scene)
        # Static player messages are not regeneratable.
        assert result == []
        # History is preserved.
        assert msg in scene.history

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_unsupported_message_type(self, scene):
        # Reinforcement-only history: walk-back consumes them all → message ends
        # up at index -1 of an empty/popped state → control flow path varies.
        # Use a simpler unsupported type instead: a plain SceneMessage subclass
        # not in the supported tuple. We use TimePassageMessage.
        from talemate.scene_message import TimePassageMessage

        msg = TimePassageMessage(message="some time later")
        scene.history = [msg]

        result = await regenerate(scene)
        assert result == []
        # Because the message wasn't supported, history is left untouched.
        assert msg in scene.history

    @pytest.mark.asyncio
    async def test_pops_reinforcements_and_regenerates_underlying_message(
        self, scene, register_agent
    ):
        """Trailing reinforcements are popped, primary message regenerated, then re-added."""
        new_text = "regen narration"

        class _NarratorAgent:
            async def progress_story(self, **kwargs):
                return NarratorMessage(message=new_text)

        register_agent("narrator", _NarratorAgent())

        narration = NarratorMessage(message="old")
        narration.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }
        reinforce = ReinforcementMessage(message="reinforced")
        reinforce.meta = {
            "agent": "world_state",
            "function": "update_reinforcement",
            "arguments": {},
        }
        scene.history = [narration, reinforce]

        # The reinforcement message will be regenerated via its agent. Register a
        # world_state agent that returns a new reinforcement message.
        class _WorldStateAgent:
            async def update_reinforcement(self, **kwargs):
                return ReinforcementMessage(message="new reinforced")

        register_agent("world_state", _WorldStateAgent())

        result = await regenerate(scene)

        assert isinstance(result, list)
        # Result should contain the new narrator message + new reinforcement.
        assert any(m.message == new_text for m in result)

    @pytest.mark.asyncio
    async def test_inplace_update_preserves_message_id_and_swaps_text(
        self, scene, register_agent, _silence_emit_and_signals, monkeypatch
    ):
        """Successful in-place regenerate keeps the message id and updates
        its `.message`; no `remove_message` is emitted and `edit_message`
        is called with reason='regenerate'."""

        new_text = "regenerated narration"

        class _NarratorAgent:
            async def progress_story(self, **kwargs):
                return NarratorMessage(message=new_text)

        register_agent("narrator", _NarratorAgent())

        original = NarratorMessage(message="old narration")
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }
        original_id = original.id
        scene.history = [original]

        # The in-place flow grows the message's version stack rather than
        # overwriting the active entry, so spy on append_message_version.
        append_calls = _install_append_message_version_spy(scene, monkeypatch)

        result = await regenerate(scene)

        # Slot kept its id, canonical text bumped in place.
        assert original in scene.history
        assert original.id == original_id
        assert original.message == new_text
        # Returned the same message object.
        assert result == [original]

        # No remove_message — the in-place flow no longer pops the slot.
        names = [e["name"] for e in _silence_emit_and_signals]
        assert "remove_message" not in names

        # No editor revision ran (the default _NoopEditor returns False), so
        # the raw regen output is the only thing appended.
        assert len(append_calls) == 1
        call = append_calls[0]
        assert call["message_id"] == original_id
        assert call["text"] == new_text
        assert call["source"] == "regenerate"

    @pytest.mark.asyncio
    async def test_inplace_auto_revision_appends_both_raw_and_revised(
        self, scene, register_agent, monkeypatch
    ):
        """When ``editor.maybe_revise_inplace`` rewrites the regen output,
        BOTH versions land on the message's stack — the raw regen as a
        navigable prior, then the polished version as the new canonical.
        """

        # Agent returns the raw (pre-revision) text. The editor's
        # maybe_revise_inplace will append a "revision" version on top.
        raw_text = "raw narration"
        revised_text = "revised narration"

        class _NarratorAgent:
            async def progress_story(self, **kwargs):
                return NarratorMessage(message=raw_text)

        class _Editor:
            async def maybe_revise_inplace(self, message):
                if message.message != raw_text:
                    return False
                message.append_version(revised_text, source="revision")
                return True

        register_agent("narrator", _NarratorAgent())
        register_agent("editor", _Editor())

        original = NarratorMessage(message="prior canonical")
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }
        scene.history = [original]

        append_calls = _install_append_message_version_spy(scene, monkeypatch)

        await regenerate(scene)

        # Two appends: raw regen, then polished — both end up on the
        # slot's stack so the user can navigate to the unrevised version.
        assert [(c["text"], c["source"]) for c in append_calls] == [
            (raw_text, "regenerate"),
            (revised_text, "revision"),
        ]
        # Slot's canonical is the revised text (last appended is active).
        assert original.message == revised_text

    @pytest.mark.asyncio
    async def test_inplace_skips_raw_when_matches_prior_canonical(
        self, scene, register_agent, monkeypatch
    ):
        """If the raw regen output equals the message's prior canonical,
        the prior is already on the stack at the active index — appending
        it again would just clutter the stack. Skip it. The revised
        version still appends (since revision actually changed the text).
        """

        raw_text = "shared text"
        revised_text = "revised text"

        class _NarratorAgent:
            async def progress_story(self, **kwargs):
                return NarratorMessage(message=raw_text)

        class _Editor:
            async def maybe_revise_inplace(self, message):
                message.append_version(revised_text, source="revision")
                return True

        register_agent("narrator", _NarratorAgent())
        register_agent("editor", _Editor())

        original = NarratorMessage(message=raw_text)  # prior canonical == raw_text
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }
        scene.history = [original]

        append_calls = _install_append_message_version_spy(scene, monkeypatch)

        await regenerate(scene)

        # Only the revised version is appended — raw_text would have
        # duplicated the prior canonical at the active index.
        assert [(c["text"], c["source"]) for c in append_calls] == [
            (revised_text, "revision")
        ]

    @pytest.mark.asyncio
    async def test_inplace_canonical_source_is_regenerate_when_revision_is_noop(
        self, scene, register_agent, monkeypatch
    ):
        """When ``maybe_revise_inplace`` returns ``False`` (revision was a
        no-op or disabled), only the raw regen lands on the stack and the
        new canonical is tagged ``"regenerate"`` — the new text is the
        raw regen output unchanged.
        """

        raw_text = "regenerated, never revised"

        class _NarratorAgent:
            async def progress_story(self, **kwargs):
                return NarratorMessage(message=raw_text)

        class _Editor:
            async def maybe_revise_inplace(self, message):
                return False  # revision disabled / no-op

        register_agent("narrator", _NarratorAgent())
        register_agent("editor", _Editor())

        original = NarratorMessage(message="prior text")
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }
        scene.history = [original]

        append_calls = _install_append_message_version_spy(scene, monkeypatch)

        await regenerate(scene)

        assert [(c["text"], c["source"]) for c in append_calls] == [
            (raw_text, "regenerate")
        ]

    @pytest.mark.asyncio
    async def test_leaves_original_untouched_when_regeneration_returns_no_messages(
        self, scene, register_agent, _silence_emit_and_signals
    ):
        """In-place regenerate never mutates the slot on failure: text stays
        as-is and the frontend gets a `regenerate_failed` event."""

        class _NarratorAgent:
            async def progress_story(self, **kwargs):
                return None  # triggers failure path

        register_agent("narrator", _NarratorAgent())

        original = NarratorMessage(message="original text")
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }
        scene.history = [original]

        result = await regenerate(scene)

        # Slot is still there, untouched.
        assert original in scene.history
        assert original.message == "original text"
        # No regenerated messages returned.
        assert result == []
        # The failure event was emitted (via websocket_passthrough) with
        # the original message id in the kwargs payload.
        events_by_name = {e["name"]: e for e in _silence_emit_and_signals}
        assert "regenerate_failed" in events_by_name
        failed = events_by_name["regenerate_failed"]["kwargs"]
        assert failed.get("websocket_passthrough") is True
        assert failed.get("kwargs", {}).get("id") == original.id

    @pytest.mark.asyncio
    async def test_leaves_original_and_reinforcements_present_on_failure(
        self, scene, register_agent
    ):
        """When regen fails, the primary slot is untouched and any popped
        reinforcements are re-pushed onto history."""

        class _NarratorAgent:
            async def progress_story(self, **kwargs):
                return None

        register_agent("narrator", _NarratorAgent())

        original = NarratorMessage(message="primary")
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }
        reinforce = ReinforcementMessage(message="reinforce")
        scene.history = [original, reinforce]

        await regenerate(scene)

        # Both messages are present in history again.
        assert original in scene.history
        assert reinforce in scene.history

    @pytest.mark.asyncio
    async def test_handles_exception_during_regeneration_without_mutating(
        self, scene, register_agent, _silence_emit_and_signals
    ):
        class _Boom:
            async def progress_story(self, **kwargs):
                raise RuntimeError("boom")

        register_agent("narrator", _Boom())

        original = NarratorMessage(message="primary")
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }
        scene.history = [original]

        result = await regenerate(scene)

        # Slot is still there with its original text.
        assert original in scene.history
        assert original.message == "primary"
        assert result == []
        # An error status AND a regenerate_failed event were emitted.
        names = [e["name"] for e in _silence_emit_and_signals]
        assert "status" in names
        assert "regenerate_failed" in names

    @pytest.mark.asyncio
    async def test_generation_cancelled_reraises_without_error_status(
        self, scene, register_agent, _silence_emit_and_signals
    ):
        """A user interrupt (GenerationCancelled) is not a failure: history is
        restored, the cancellation is reported as a non-error status, and the
        exception propagates so the task done-callback can handle it."""

        class _Cancelled:
            async def progress_story(self, **kwargs):
                raise GenerationCancelled("Generation cancelled")

        register_agent("narrator", _Cancelled())

        original = NarratorMessage(message="primary")
        original.meta = {
            "agent": "narrator",
            "function": "progress_story",
            "arguments": {},
        }
        reinforce = ReinforcementMessage(message="reinforce")
        scene.history = [original, reinforce]

        with pytest.raises(GenerationCancelled):
            await regenerate(scene)

        # History is restored: primary slot untouched, reinforcement re-pushed.
        assert original in scene.history
        assert original.message == "primary"
        assert reinforce in scene.history
        # The frontend gets a regenerate_failed event so the spinner clears.
        events_by_name = {e["name"]: e for e in _silence_emit_and_signals}
        assert "regenerate_failed" in events_by_name
        # The status is a non-error cancellation notice, not "error".
        status = events_by_name["status"]
        assert status["kwargs"].get("status") != "error"
        assert "cancel" in status["kwargs"].get("message", "").lower()
