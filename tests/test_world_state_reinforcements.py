"""
Tests for world state reinforcement bugs:

1. Sequential mode truncates multiline output after first newline
2. Removing a world-level reinforcement doesn't clean up its manual_context entry
"""

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.world_state import ManualContext, Reinforcement
from talemate.character import Character
from talemate.tale_mate import Actor

@pytest.fixture
def scene():
    mock_scene = MockScene()
    bootstrap_scene(mock_scene)
    return mock_scene


# ---------------------------------------------------------------------------
# Bug 1: Sequential reinforcement output truncation
# ---------------------------------------------------------------------------


class TestSequentialReinforcementTruncation:
    """
    Bug: When 'Context Attach Method' is 'Sequential', the generated answer
    is split on newline and only the first line is kept, discarding the rest.

    The truncation happens in agents/world_state/__init__.py update_reinforcement():
        if reinforcement.insert == "sequential":
            answer = answer.split("\\n")[0]

    We test the Reinforcement model's answer storage directly to verify
    the fix doesn't strip newlines.
    """

    def test_reinforcement_stores_multiline_answer(self):
        """A Reinforcement object should be able to store multiline answers."""
        r = Reinforcement(
            question="What is the current time of day?",
            insert="sequential",
            answer="It is early morning.\nThe sun is just rising.",
        )
        assert "\n" in r.answer
        assert r.answer == "It is early morning.\nThe sun is just rising."

    def test_as_context_line_preserves_multiline(self):
        """as_context_line should work with multiline answers."""
        r = Reinforcement(
            question="What is the current time of day?",
            insert="sequential",
            answer="It is early morning.\nThe sun is just rising.",
        )
        context_line = r.as_context_line
        assert "It is early morning." in context_line
        assert "The sun is just rising." in context_line


# ---------------------------------------------------------------------------
# Bug 2: Removing world-level reinforcement doesn't clean up manual_context
# ---------------------------------------------------------------------------


class TestReinforcementRemovalCleanup:
    """
    Bug: Removing a world-level reinforcement (e.g., 'Time of Day' tracker)
    removes it from self.reinforce but leaves the corresponding entry in
    world_state.manual_context, so it continues to appear in scene content.
    """

    @pytest.mark.asyncio
    async def test_remove_world_reinforcement_cleans_manual_context(self, scene):
        """Removing a world-level reinforcement should also remove its manual_context entry."""
        world_state = scene.world_state

        # Add a world-level reinforcement (no character)
        await world_state.add_reinforcement(
            question="What is the current time of day?",
            character=None,
            insert="sequential",
            answer="It is early morning.",
        )

        # Simulate what update_reinforcement does: create a manual_context entry
        world_state.manual_context["What is the current time of day?"] = ManualContext(
            id="What is the current time of day?",
            text="What is the current time of day? It is early morning.",
            meta={"source": "manual", "typ": "world_state"},
        )

        # Verify setup
        assert len(world_state.reinforce) == 1
        assert "What is the current time of day?" in world_state.manual_context

        # Now remove the reinforcement
        idx, _ = await world_state.find_reinforcement(
            "What is the current time of day?", None
        )
        await world_state.remove_reinforcement(idx)

        # The reinforcement should be gone from the list
        assert len(world_state.reinforce) == 0

        # The manual_context entry should ALSO be gone
        assert "What is the current time of day?" not in world_state.manual_context, (
            "manual_context entry should be removed when reinforcement is removed"
        )

    @pytest.mark.asyncio
    async def test_remove_character_reinforcement_cleans_detail(self, scene):
        """Removing a character-level reinforcement should also remove its character detail."""
        world_state = scene.world_state

        character = Character(name="Alice")
        actor = Actor(character=character, agent=None)
        scene.actors.append(actor)
        character.details["What is Alice's mood?"] = "Happy and content."

        # Add a character-level reinforcement
        await world_state.add_reinforcement(
            question="What is Alice's mood?",
            character="Alice",
            insert="sequential",
            answer="Happy and content.",
        )

        # Verify setup
        assert character.get_detail("What is Alice's mood?") == "Happy and content."

        # Remove the reinforcement
        idx, _ = await world_state.find_reinforcement(
            "What is Alice's mood?", "Alice"
        )
        await world_state.remove_reinforcement(idx)

        # The character detail should also be cleaned up
        assert character.get_detail("What is Alice's mood?") is None, (
            "Character detail should be removed when reinforcement is removed"
        )

    @pytest.mark.asyncio
    async def test_remove_preserves_other_manual_context(self, scene):
        """Removing one reinforcement shouldn't affect other manual_context entries."""
        world_state = scene.world_state

        # Add two world-level reinforcements
        await world_state.add_reinforcement(
            question="What is the current time of day?",
            character=None,
            insert="sequential",
            answer="It is early morning.",
        )
        await world_state.add_reinforcement(
            question="What is the current weather?",
            character=None,
            insert="sequential",
            answer="Clear skies.",
        )

        # Simulate manual_context entries (as update_reinforcement would create)
        world_state.manual_context["What is the current time of day?"] = ManualContext(
            id="What is the current time of day?",
            text="What is the current time of day? It is early morning.",
            meta={"source": "manual", "typ": "world_state"},
        )
        world_state.manual_context["What is the current weather?"] = ManualContext(
            id="What is the current weather?",
            text="What is the current weather? Clear skies.",
            meta={"source": "manual", "typ": "world_state"},
        )

        # Remove only the first reinforcement
        idx, _ = await world_state.find_reinforcement(
            "What is the current time of day?", None
        )
        await world_state.remove_reinforcement(idx)

        # The other manual_context entry should still exist
        assert "What is the current weather?" in world_state.manual_context
        assert "What is the current time of day?" not in world_state.manual_context
