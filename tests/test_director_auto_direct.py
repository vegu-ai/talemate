"""Unit tests for talemate.agents.director.auto_direct.AutoDirectMixin.

The mixin is largely deprecated (auto_direct_enabled always returns False),
but its scaffolding still drives the auto_direct_candidates() turn-balancing
logic. The candidate-selection routine examines scene history and returns
characters eligible to speak next based on:
  - max_idle_turns (force speakers who haven't spoken in a while)
  - max_repeat_turns (block characters who just spoke)
  - max_auto_turns (favor player after consecutive auto turns)

Covers:
- All static deprecated property values.
- auto_direct_instruct_any (False+False=False).
- auto_direct_is_due_for_instruction (no last director instruction → True;
  frequency=1 → always True).
- auto_direct_candidates: empty history (returns all chars), repeat blocking,
  player-favoring, idle-character favoring, narrator inclusion when enabled,
  time-passage break.

LLM-driven action paths (auto_direct_set_scene_intent,
auto_direct_generate_scene_types) are NOT exercised — they call into Focal
which would require a full prompt-template round-trip.
"""

from __future__ import annotations

import pytest

from conftest import MockScene, bootstrap_scene

import talemate.instance as instance
from talemate.character import Character
from talemate.scene_message import (
    CharacterMessage,
    NarratorMessage,
    TimePassageMessage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    return s


@pytest.fixture
def director(scene):
    return instance.get_agent("director")


async def _add_character(scene, name, *, is_player=False):
    character = Character(
        name=name,
        description="",
        is_player=is_player,
        base_attributes={},
        details={},
        color="#fff",
    )
    actor = scene.Player(character, None) if is_player else scene.Actor(character, None)
    await scene.add_actor(actor, commit_to_memory=False)
    if name not in scene.active_characters:
        scene.active_characters.append(name)
    return character


# ---------------------------------------------------------------------------
# Deprecated config properties (static)
# ---------------------------------------------------------------------------


class TestDeprecatedAutoDirectProperties:
    def test_auto_direct_enabled_always_false(self, director):
        assert director.auto_direct_enabled is False

    def test_max_auto_turns_static_3(self, director):
        assert director.auto_direct_max_auto_turns == 3

    def test_max_idle_turns_static_5(self, director):
        assert director.auto_direct_max_idle_turns == 5

    def test_max_repeat_turns_static_1(self, director):
        assert director.auto_direct_max_repeat_turns == 1

    def test_instruct_actors_static_false(self, director):
        assert director.auto_direct_instruct_actors is False

    def test_instruct_narrator_static_false(self, director):
        assert director.auto_direct_instruct_narrator is False

    def test_instruct_frequency_static_5(self, director):
        assert director.auto_direct_instruct_frequency == 5

    def test_evaluate_scene_intention_static_0(self, director):
        assert director.auto_direct_evaluate_scene_intention == 0

    def test_instruct_any_default_false(self, director):
        assert director.auto_direct_instruct_any is False


# ---------------------------------------------------------------------------
# auto_direct_is_due_for_instruction
# ---------------------------------------------------------------------------


class TestIsDueForInstruction:
    def test_returns_true_when_no_last_instruction(self, scene, director):
        # No director message in history → returns True
        assert director.auto_direct_is_due_for_instruction("Alice") is True

    def test_frequency_one_always_returns_true(self, scene, director, monkeypatch):
        # auto_direct_instruct_frequency=1 short-circuits to True
        monkeypatch.setattr(
            type(director),
            "auto_direct_instruct_frequency",
            property(lambda self: 1),
        )
        assert director.auto_direct_is_due_for_instruction("Alice") is True


# ---------------------------------------------------------------------------
# auto_direct_candidates
# ---------------------------------------------------------------------------


class TestAutoDirectCandidates:
    @pytest.mark.asyncio
    async def test_empty_history_returns_all_active_characters(self, scene, director):
        await _add_character(scene, "Alice")
        await _add_character(scene, "Bob")
        candidates = director.auto_direct_candidates()
        names = {c.name for c in candidates}
        assert names == {"Alice", "Bob"}

    @pytest.mark.asyncio
    async def test_blocks_most_recent_when_repeated(self, scene, director):
        await _add_character(scene, "Alice")
        await _add_character(scene, "Bob")
        # Alice just spoke — should be blocked from candidates
        scene.history.append(CharacterMessage("Alice: hi"))
        candidates = director.auto_direct_candidates()
        names = {c.name for c in candidates}
        assert "Alice" not in names
        assert "Bob" in names

    @pytest.mark.asyncio
    async def test_prefers_player_after_consecutive_auto_turns(self, scene, director):
        await _add_character(scene, "Alice")
        await _add_character(scene, "Hero", is_player=True)
        # 3 consecutive non-player turns (max_auto_turns is 3)
        scene.history.append(CharacterMessage("Alice: 1"))
        scene.history.append(CharacterMessage("Alice: 2"))
        scene.history.append(CharacterMessage("Alice: 3"))
        candidates = director.auto_direct_candidates()
        # When player has been idle, only the player is returned
        assert len(candidates) == 1
        assert candidates[0].is_player is True

    @pytest.mark.asyncio
    async def test_favored_candidates_when_idle_too_long(self, scene, director):
        await _add_character(scene, "Alice")
        await _add_character(scene, "Bob")
        # Bob hasn't spoken in 6+ turns (> max_idle_turns of 5)
        # Pad with Alice messages
        for _ in range(7):
            scene.history.append(CharacterMessage("Alice: x"))
        candidates = director.auto_direct_candidates()
        names = {c.name for c in candidates}
        # Bob should be in the favored list because he's been idle
        assert "Bob" in names

    @pytest.mark.asyncio
    async def test_time_passage_breaks_history_walk(self, scene, director):
        await _add_character(scene, "Alice")
        await _add_character(scene, "Bob")
        # Alice spoke first, then time passed → loop breaks before
        # encountering anything after the time passage marker
        scene.history.append(CharacterMessage("Alice: long ago"))
        scene.history.append(TimePassageMessage(ts=86400, message="A day passed."))
        candidates = director.auto_direct_candidates()
        # Both characters end up as candidates because the loop breaks at TimePassage
        names = {c.name for c in candidates}
        assert names == {"Alice", "Bob"}

    @pytest.mark.asyncio
    async def test_skips_messages_for_inactive_characters(self, scene, director):
        await _add_character(scene, "Alice")
        # "Stranger" not in active characters list — message is skipped
        scene.history.append(CharacterMessage("Stranger: who?"))
        candidates = director.auto_direct_candidates()
        names = {c.name for c in candidates}
        assert "Alice" in names
        assert "Stranger" not in names

    @pytest.mark.asyncio
    async def test_narrator_skipped_when_instruct_narrator_disabled(
        self, scene, director
    ):
        await _add_character(scene, "Alice")
        # Narrator messages encountered but instruct_narrator is False
        scene.history.append(NarratorMessage("scene starts"))
        scene.history.append(NarratorMessage("more narration"))
        candidates = director.auto_direct_candidates()
        names = {c.name for c in candidates}
        # Narrator not added; Alice still a candidate
        assert "Alice" in names
        assert "__narrator__" not in names

    @pytest.mark.asyncio
    async def test_narrator_included_when_instruct_narrator_enabled(
        self, scene, director, monkeypatch
    ):
        monkeypatch.setattr(
            type(director),
            "auto_direct_instruct_narrator",
            property(lambda self: True),
        )
        await _add_character(scene, "Alice")
        # Push a character message so most_recent_character is set — otherwise
        # the function returns list(scene.characters) which never contains the
        # narrator pseudo-character.
        scene.history.append(CharacterMessage("Alice: hi"))
        candidates = director.auto_direct_candidates()
        names = {c.name for c in candidates}
        # Narrator's underlying name is "__narrator__"
        assert "__narrator__" in names

    @pytest.mark.asyncio
    async def test_returns_list_of_scene_characters_when_no_recent_message(
        self, scene, director
    ):
        # No CharacterMessage / NarratorMessage in history at all
        await _add_character(scene, "Alice")
        await _add_character(scene, "Bob")
        # add an unrelated message that won't establish a "most recent character"
        scene.history.append(NarratorMessage("setup"))
        # instruct_narrator default is False so NarratorMessage is skipped during walk
        candidates = director.auto_direct_candidates()
        names = {c.name for c in candidates}
        # All scene characters returned because no most_recent_character was found
        assert names == {"Alice", "Bob"}
