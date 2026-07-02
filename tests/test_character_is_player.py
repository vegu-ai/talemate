"""
Tests for ``WorldStateManager.set_character_is_player`` — toggling a character's
player status from the World State Manager.

Design contract:
- At most one character may be the player at any time.
- Promoting a non-player demotes the existing player (if any) to a plain
  AI Actor; the previous player stays active in the scene.
- Active characters get their actor swapped in place (Actor↔Player).
- Inactive characters being promoted are auto-activated.
- No-ops (same state, unknown name) must not raise.
"""

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.character import Character
from talemate.tale_mate import Actor, Player
from talemate.world_state.manager import WorldStateManager


@pytest.fixture
def scene():
    mock_scene = MockScene()
    bootstrap_scene(mock_scene)
    return mock_scene


@pytest.fixture
def manager(scene):
    return WorldStateManager(scene)


def _add_active_npc(scene, name: str) -> Character:
    """Active AI character — wrapped in a plain Actor, registered in both
    ``scene.actors`` and ``scene.active_characters`` to mirror production.
    """
    character = Character(name=name, is_player=False)
    actor = Actor(character=character, agent=None)
    scene.actors.append(actor)
    scene.character_data[character.name] = character
    if character.name not in scene.active_characters:
        scene.active_characters.append(character.name)
    return character


def _add_active_player(scene, name: str) -> Character:
    """Active player character — wrapped in a Player actor."""
    character = Character(name=name, is_player=True)
    actor = Player(character=character, agent=None)
    scene.actors.append(actor)
    scene.character_data[character.name] = character
    if character.name not in scene.active_characters:
        scene.active_characters.append(character.name)
    return character


def _add_inactive_character(scene, name: str, is_player: bool = False) -> Character:
    """Inactive character — present in ``character_data`` but without an
    actor and not in ``active_characters``.
    """
    character = Character(name=name, is_player=is_player)
    scene.character_data[character.name] = character
    if character.name in scene.active_characters:
        scene.active_characters.remove(character.name)
    return character


def _actor_for(scene, name: str):
    for actor in scene.actors:
        if actor.character is not None and actor.character.name == name:
            return actor
    return None


class TestSetCharacterIsPlayer:
    @pytest.mark.asyncio
    async def test_promote_active_npc_when_no_player(self, scene, manager):
        npc = _add_active_npc(scene, "Alice")
        assert scene.get_explicit_player_character() is None

        await manager.set_character_is_player("Alice", True)

        assert npc.is_player is True
        assert isinstance(_actor_for(scene, "Alice"), Player)
        assert scene.get_explicit_player_character() is npc

    @pytest.mark.asyncio
    async def test_promote_active_npc_demotes_existing_player(self, scene, manager):
        prev = _add_active_player(scene, "Hero")
        npc = _add_active_npc(scene, "Bob")

        await manager.set_character_is_player("Bob", True)

        # New player is correctly promoted
        assert npc.is_player is True
        assert isinstance(_actor_for(scene, "Bob"), Player)
        # Previous player is demoted to plain Actor, still active
        assert prev.is_player is False
        prev_actor = _actor_for(scene, "Hero")
        assert prev_actor is not None
        assert isinstance(prev_actor, Actor)
        assert not isinstance(prev_actor, Player)
        assert "Hero" in scene.active_characters
        # Only one explicit player remains
        assert scene.get_explicit_player_character() is npc

    @pytest.mark.asyncio
    async def test_promote_inactive_character_auto_activates(self, scene, manager):
        ghost = _add_inactive_character(scene, "Ghost")
        assert "Ghost" not in scene.active_characters
        assert _actor_for(scene, "Ghost") is None

        await manager.set_character_is_player("Ghost", True)

        assert ghost.is_player is True
        # Should have been activated as a Player
        assert "Ghost" in scene.active_characters
        assert isinstance(_actor_for(scene, "Ghost"), Player)
        assert scene.get_explicit_player_character() is ghost

    @pytest.mark.asyncio
    async def test_promote_inactive_demotes_existing_active_player(
        self, scene, manager
    ):
        prev = _add_active_player(scene, "Hero")
        ghost = _add_inactive_character(scene, "Ghost")

        await manager.set_character_is_player("Ghost", True)

        # Inactive target activated as Player
        assert ghost.is_player is True
        assert "Ghost" in scene.active_characters
        assert isinstance(_actor_for(scene, "Ghost"), Player)
        # Previous active player demoted but still active
        assert prev.is_player is False
        assert "Hero" in scene.active_characters
        assert isinstance(_actor_for(scene, "Hero"), Actor)
        assert not isinstance(_actor_for(scene, "Hero"), Player)

    @pytest.mark.asyncio
    async def test_demote_active_player(self, scene, manager):
        player = _add_active_player(scene, "Hero")

        await manager.set_character_is_player("Hero", False)

        assert player.is_player is False
        actor = _actor_for(scene, "Hero")
        assert actor is not None
        assert isinstance(actor, Actor)
        assert not isinstance(actor, Player)
        # Still active in the scene
        assert "Hero" in scene.active_characters
        # No explicit player remains
        assert scene.get_explicit_player_character() is None

    @pytest.mark.asyncio
    async def test_set_same_state_is_noop_for_player(self, scene, manager):
        player = _add_active_player(scene, "Hero")
        original_actor = _actor_for(scene, "Hero")

        await manager.set_character_is_player("Hero", True)

        assert player.is_player is True
        # Actor identity preserved — no unnecessary swap
        assert _actor_for(scene, "Hero") is original_actor

    @pytest.mark.asyncio
    async def test_set_same_state_is_noop_for_npc(self, scene, manager):
        npc = _add_active_npc(scene, "Alice")
        original_actor = _actor_for(scene, "Alice")

        await manager.set_character_is_player("Alice", False)

        assert npc.is_player is False
        assert _actor_for(scene, "Alice") is original_actor

    @pytest.mark.asyncio
    async def test_unknown_character_is_noop(self, scene, manager):
        existing = _add_active_npc(scene, "Alice")

        # Must not raise
        await manager.set_character_is_player("DoesNotExist", True)

        # Unrelated state is untouched
        assert existing.is_player is False
        assert scene.get_explicit_player_character() is None

    @pytest.mark.asyncio
    async def test_demote_inactive_player_just_flips_flag(self, scene, manager):
        """An inactive character that was marked as player (e.g. waiting to be
        re-activated) can be unmarked without being touched in the scene.
        """
        dormant = _add_inactive_character(scene, "Dormant", is_player=True)

        await manager.set_character_is_player("Dormant", False)

        assert dormant.is_player is False
        # Still inactive, still no actor
        assert "Dormant" not in scene.active_characters
        assert _actor_for(scene, "Dormant") is None
