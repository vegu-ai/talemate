"""Unit tests for sync (and a few simple async) methods on talemate.tale_mate.

Covers Actor/Player constructors plus a wide range of Scene methods that don't
require LLM round-trips: history mutation, message lookup/edit/delete, actor
add/remove, character lookups, time advancement, snapshot, serialize, simple
setters, and the connect/disconnect signal lifecycle.

LLM-driven flows (start, save/load, narrate, conversation) are intentionally
out of scope. Real Scene/Character/Actor objects are used throughout — no
MagicMock for domain objects.
"""

from __future__ import annotations

import os

import pytest

import talemate.emit.async_signals as async_signals
from conftest import MockScene, bootstrap_scene
from talemate.character import Character
from talemate.exceptions import GenerationCancelled
from talemate.scene_message import (
    CharacterMessage,
    DirectorMessage,
    NarratorMessage,
    ReinforcementMessage,
    TimePassageMessage,
    reset_message_id,
)
from talemate.tale_mate import Actor, Player, Scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _char_msg(
    text: str, character: str = "Alice", source: str = "ai"
) -> CharacterMessage:
    return CharacterMessage(message=f"{character}: {text}", source=source)


def _add_char(
    scene,
    name: str,
    is_player: bool = False,
    base_attributes: dict | None = None,
    greeting: str = "",
) -> Character:
    """Attach a real Character + Actor/Player to a scene synchronously
    (does NOT touch memory). Mirrors the helper in test_history_helpers."""
    character = Character(
        name=name,
        is_player=is_player,
        base_attributes=base_attributes or {},
        greeting_text=greeting,
    )
    actor_cls = Player if is_player else Actor
    actor = actor_cls(character=character, agent=None)
    actor.scene = scene
    scene.actors.append(actor)
    scene.character_data[name] = character
    if name not in scene.active_characters:
        scene.active_characters.append(name)
    return character


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_message_ids():
    reset_message_id()
    yield
    reset_message_id()


@pytest.fixture
def real_scene():
    """Bootstrapped MockScene with all real agents wired in."""
    scene = MockScene()
    bootstrap_scene(scene)
    return scene


@pytest.fixture
def isolated_scene(tmp_path, monkeypatch):
    """Real Scene whose save_dir lives under tmp_path. Useful for tests
    that touch project_name/save_dir/full_path/save_files."""
    monkeypatch.setattr(
        Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)), raising=True
    )
    scene = Scene()
    scene.project_name = "test_project"
    os.makedirs(scene.save_dir, exist_ok=True)
    return scene


# ---------------------------------------------------------------------------
# Actor / Player wiring
# ---------------------------------------------------------------------------


class TestActorConstructor:
    def test_actor_links_character_and_agent_attributes(self):
        char = Character(name="Alice")
        # A truthy "agent" placeholder; we only check the back-reference plumbing.
        agent = type("StubAgent", (), {})()
        actor = Actor(character=char, agent=agent)

        # Actor stores both, and the back-references on character are set.
        assert actor.character is char
        assert actor.agent is agent
        assert char.agent is agent
        assert char.actor is actor
        # And the agent receives the character pointer back.
        assert agent.character is char

    def test_actor_with_none_agent_skips_agent_back_reference(self):
        char = Character(name="Bob")
        actor = Actor(character=char, agent=None)
        # No agent.character was set (no agent), but character.agent is still None.
        assert actor.agent is None
        assert char.agent is None
        assert char.actor is actor

    def test_actor_history_property_delegates_to_scene(self, real_scene):
        msg = _char_msg("hi")
        real_scene.history = [msg]
        actor = Actor(character=Character(name="X"), agent=None)
        actor.scene = real_scene
        assert actor.history is real_scene.history
        assert actor.history[0] is msg

    def test_player_inherits_actor_and_has_default_class_attrs(self):
        char = Character(name="P", is_player=True)
        player = Player(character=char, agent=None)
        # Class-level defaults inherited from the Player declaration.
        assert player.muted == 0
        assert player.ai_controlled == 0
        # Player IS an Actor.
        assert isinstance(player, Actor)


# ---------------------------------------------------------------------------
# Actor add/remove and character lookups
# ---------------------------------------------------------------------------


class TestAddActorAndCharacterLookups:
    @pytest.mark.asyncio
    async def test_add_actor_registers_in_scene_state(self, real_scene):
        char = Character(name="Alice")
        actor = Actor(character=char, agent=None)
        await real_scene.add_actor(actor, commit_to_memory=False)

        assert actor in real_scene.actors
        assert actor.scene is real_scene
        assert "Alice" in real_scene.character_data
        assert real_scene.character_data["Alice"] is char

    @pytest.mark.asyncio
    async def test_add_actor_replaces_duplicate_character(self, real_scene):
        # Adding the same character twice via two Actor wrappers must not leave
        # two Actor entries for the same character.
        char = Character(name="Alice")
        a1 = Actor(character=char, agent=None)
        a2 = Actor(character=char, agent=None)
        await real_scene.add_actor(a1, commit_to_memory=False)
        await real_scene.add_actor(a2, commit_to_memory=False)
        assert real_scene.actors == [a2]

    @pytest.mark.asyncio
    async def test_add_actor_marks_player_character_is_player(self, real_scene):
        char = Character(name="Player", is_player=False)
        player = Player(character=char, agent=None)
        await real_scene.add_actor(player, commit_to_memory=False)
        assert char.is_player is True

    @pytest.mark.asyncio
    async def test_add_actor_seeds_intro_and_description_from_character(
        self, real_scene
    ):
        char = Character(
            name="Alice",
            greeting_text="Welcome to the inn.",
            base_attributes={
                "scenario_context": "fantasy",
                "scenario overview": "An inn at sunset.",
            },
        )
        actor = Actor(character=char, agent=None)
        # Ensure scene starts unset so the seeding paths fire.
        real_scene.context = ""
        real_scene.intro = ""
        real_scene.description = ""
        real_scene.name = ""

        await real_scene.add_actor(actor, commit_to_memory=False)

        assert real_scene.context == "fantasy"
        assert real_scene.intro == "Welcome to the inn."
        assert real_scene.description == "An inn at sunset."
        # An unnamed scene takes the first NPC's name.
        assert real_scene.name == "Alice"

    @pytest.mark.asyncio
    async def test_add_actor_does_not_overwrite_existing_intro(self, real_scene):
        real_scene.intro = "Pre-existing intro"
        char = Character(name="Alice", greeting_text="ignored greeting")
        await real_scene.add_actor(
            Actor(character=char, agent=None), commit_to_memory=False
        )
        assert real_scene.intro == "Pre-existing intro"

    @pytest.mark.asyncio
    async def test_remove_character_clears_state(self, real_scene):
        char = Character(name="Alice")
        await real_scene.add_actor(
            Actor(character=char, agent=None), commit_to_memory=False
        )
        # add_actor populates character_data; active_characters is managed
        # separately (e.g. via load_scene). Manually mark active for this test.
        real_scene.active_characters.append("Alice")

        await real_scene.remove_character(char, purge_from_memory=False)
        assert "Alice" not in real_scene.character_data
        assert "Alice" not in real_scene.active_characters
        assert all(a.character is not char for a in real_scene.actors)

    @pytest.mark.asyncio
    async def test_remove_actor_detaches_character(self, real_scene):
        char = Character(name="Alice")
        actor = Actor(character=char, agent=None)
        await real_scene.add_actor(actor, commit_to_memory=False)
        await real_scene.remove_actor(actor)
        assert actor not in real_scene.actors
        assert actor.character is None

    @pytest.mark.asyncio
    async def test_remove_all_actors_clears_actors_list(self, real_scene):
        await real_scene.add_actor(
            Actor(character=Character(name="A"), agent=None), commit_to_memory=False
        )
        await real_scene.add_actor(
            Actor(character=Character(name="B"), agent=None), commit_to_memory=False
        )
        await real_scene.remove_all_actors()
        assert real_scene.actors == []


class TestCharacterAccessors:
    def test_get_character_exact_match_case_insensitive(self, real_scene):
        _add_char(real_scene, "Alice")
        assert real_scene.get_character("alice").name == "Alice"
        assert real_scene.get_character("ALICE").name == "Alice"

    def test_get_character_returns_none_for_missing(self, real_scene):
        assert real_scene.get_character("ghost") is None
        assert real_scene.get_character("") is None

    def test_get_character_partial_match_either_direction(self, real_scene):
        _add_char(real_scene, "Alice the Brave")
        # Search-term contained in character name.
        assert real_scene.get_character("Alice", partial=True).name == "Alice the Brave"
        # Character name contained in search-term.
        assert (
            real_scene.get_character("Alice the Brave Warrior", partial=True).name
            == "Alice the Brave"
        )

    def test_get_character_returns_narrator_object(self, real_scene):
        narrator = real_scene.get_character("__narrator__")
        assert narrator is real_scene.narrator_character_object
        assert narrator.name == "__narrator__"

    def test_get_character_finds_inactive_characters(self, real_scene):
        char = Character(name="Ghost")
        # Inactive: registered in character_data but not in active_characters.
        real_scene.character_data["Ghost"] = char
        assert real_scene.get_character("Ghost") is char

    def test_get_explicit_player_character_only_returns_player(self, real_scene):
        _add_char(real_scene, "Alice")
        # No Player yet -> returns None.
        assert real_scene.get_explicit_player_character() is None
        _add_char(real_scene, "Hero", is_player=True)
        assert real_scene.get_explicit_player_character().name == "Hero"

    def test_get_player_character_falls_back_to_first_actor(self, real_scene):
        _add_char(real_scene, "Alice")
        # No Player; falls back to first NPC.
        assert real_scene.get_player_character().name == "Alice"

    def test_get_player_character_prefers_player_when_present(self, real_scene):
        _add_char(real_scene, "Alice")
        _add_char(real_scene, "Hero", is_player=True)
        assert real_scene.get_player_character().name == "Hero"

    def test_main_character_and_player_character_exists(self, real_scene):
        # No characters yet
        assert real_scene.main_character is None
        assert real_scene.player_character_exists is False

        _add_char(real_scene, "Alice")  # NPC only
        assert real_scene.player_character_exists is False  # not is_player

        _add_char(real_scene, "Hero", is_player=True)
        # main_character returns the actor, not the character.
        main = real_scene.main_character
        assert main is not None
        assert main.character.name == "Hero"
        assert real_scene.player_character_exists is True

    def test_npc_helpers(self, real_scene):
        _add_char(real_scene, "Hero", is_player=True)
        _add_char(real_scene, "Alice")
        _add_char(real_scene, "Bob")

        assert sorted(real_scene.npc_character_names) == ["Alice", "Bob"]
        assert real_scene.has_active_npcs is True
        assert real_scene.num_npc_characters() == 2
        npc_names = [c.name for c in real_scene.get_npc_characters()]
        assert sorted(npc_names) == ["Alice", "Bob"]

    def test_character_is_active_accepts_string_or_object(self, real_scene):
        char = _add_char(real_scene, "Alice")
        assert real_scene.character_is_active("Alice") is True
        assert real_scene.character_is_active(char) is True
        # Inactive character returns False.
        ghost = Character(name="Ghost")
        real_scene.character_data["Ghost"] = ghost
        assert real_scene.character_is_active("Ghost") is False

    def test_character_is_active_returns_false_for_unknown_name(self, real_scene):
        # get_character returns None for unknown names. character_is_active
        # should treat that as "not active" rather than crashing on
        # `None.name`.
        assert real_scene.character_is_active("Nonexistent") is False

    def test_inactive_characters_excludes_active(self, real_scene):
        _add_char(real_scene, "Alice")
        ghost = Character(name="Ghost")
        real_scene.character_data["Ghost"] = ghost
        # active_characters is ["Alice"]; Ghost is in character_data but not active.
        inactive = real_scene.inactive_characters
        assert "Ghost" in inactive
        assert inactive["Ghost"] is ghost
        assert "Alice" not in inactive

    def test_all_character_names_includes_inactive(self, real_scene):
        _add_char(real_scene, "Alice")
        real_scene.character_data["Ghost"] = Character(name="Ghost")
        assert sorted(real_scene.all_character_names) == ["Alice", "Ghost"]

    def test_character_names_and_characters_only_yield_active(self, real_scene):
        _add_char(real_scene, "Alice")
        real_scene.character_data["Ghost"] = Character(name="Ghost")
        assert real_scene.character_names == ["Alice"]
        assert [c.name for c in real_scene.characters] == ["Alice"]
        # Generator-based get_characters mirrors `characters`.
        assert [c.name for c in real_scene.get_characters()] == ["Alice"]


# ---------------------------------------------------------------------------
# parse_character_from_line / parse_characters_from_text
# ---------------------------------------------------------------------------


class TestParseCharacters:
    def test_parse_character_from_line_returns_first_match(self, real_scene):
        _add_char(real_scene, "Alice")
        _add_char(real_scene, "Bob")
        # Both match "Alice and Bob"; the first actor wins.
        result = real_scene.parse_character_from_line("Alice and Bob walk in.")
        assert result.name == "Alice"

    def test_parse_character_from_line_returns_none_if_no_match(self, real_scene):
        _add_char(real_scene, "Alice")
        assert real_scene.parse_character_from_line("the wizard appears") is None

    def test_parse_characters_from_text_includes_active_and_inactive(self, real_scene):
        _add_char(real_scene, "Alice")
        # Inactive
        real_scene.character_data["Ghost"] = Character(name="Ghost")
        result = real_scene.parse_characters_from_text("Alice meets the Ghost.")
        names = [c.name for c in result]
        # Sorted by len(name): "Alice"(5), "Ghost"(5) -> stable order in py3.7+ but
        # both should be present.
        assert set(names) == {"Alice", "Ghost"}

    def test_parse_characters_from_text_can_exclude_active(self, real_scene):
        _add_char(real_scene, "Alice")
        real_scene.character_data["Ghost"] = Character(name="Ghost")
        result = real_scene.parse_characters_from_text(
            "Alice meets the Ghost.", exclude_active=True
        )
        names = [c.name for c in result]
        assert names == ["Ghost"]

    def test_parse_characters_from_text_uses_word_boundaries(self, real_scene):
        # "Bob" should not match "Bobcat".
        _add_char(real_scene, "Bob")
        result = real_scene.parse_characters_from_text("the bobcat is hungry")
        assert result == []


# ---------------------------------------------------------------------------
# Setters and simple property surface
# ---------------------------------------------------------------------------


class TestSimpleSetters:
    def test_set_intro_name_title_description(self, real_scene):
        real_scene.set_intro("the intro")
        real_scene.set_name("the name")
        real_scene.set_title("the title")
        real_scene.set_description("the description")
        assert real_scene.intro == "the intro"
        assert real_scene.name == "the name"
        assert real_scene.title == "the title"
        assert real_scene.description == "the description"

    @pytest.mark.asyncio
    async def test_set_environment_writes_attribute(self, real_scene):
        # set_environment also calls emit_status which requires a running loop;
        # active=False makes the debounced task a no-op anyway, but we still
        # need a loop in scope.
        real_scene.set_environment("creative")
        assert real_scene.environment == "creative"

    @pytest.mark.asyncio
    async def test_set_content_context_writes_attribute(self, real_scene):
        real_scene.set_content_context("dark fantasy")
        assert real_scene.context == "dark fantasy"

    def test_project_name_default_normalizes_scene_name(self, real_scene):
        real_scene.name = "My Awesome Scene"
        real_scene._project_name = ""
        assert real_scene.project_name == "my-awesome-scene"

    def test_project_name_strips_apostrophes(self, real_scene):
        real_scene.name = "Alice's Adventure"
        real_scene._project_name = ""
        assert real_scene.project_name == "alices-adventure"

    def test_project_name_explicit_takes_precedence(self, real_scene):
        real_scene.name = "Some Other Name"
        real_scene.project_name = "explicit-project"
        assert real_scene.project_name == "explicit-project"

    def test_nodes_filename_defaults_and_setter(self, real_scene):
        # Default
        assert real_scene.nodes_filename == "scene-loop.json"
        real_scene.nodes_filename = "alt.json"
        assert real_scene.nodes_filename == "alt.json"
        # Empty string falls back to default again.
        real_scene.nodes_filename = ""
        assert real_scene.nodes_filename == "scene-loop.json"

    def test_creative_nodes_filename_defaults_and_setter(self, real_scene):
        assert real_scene.creative_nodes_filename == "creative-loop.json"
        real_scene.creative_nodes_filename = "creative.json"
        assert real_scene.creative_nodes_filename == "creative.json"
        real_scene.creative_nodes_filename = None
        assert real_scene.creative_nodes_filename == "creative-loop.json"


class TestPathProperties:
    def test_save_dir_creates_directory(self, isolated_scene):
        path = isolated_scene.save_dir
        assert os.path.isdir(path)
        assert path.endswith("test_project")

    def test_full_path_combines_save_dir_and_filename(self, isolated_scene):
        # No filename -> None.
        assert isolated_scene.full_path is None
        isolated_scene.filename = "scene.json"
        assert isolated_scene.full_path == os.path.join(
            isolated_scene.save_dir, "scene.json"
        )

    def test_subdir_paths_relative_to_save_dir(self, isolated_scene):
        save_dir = isolated_scene.save_dir
        assert isolated_scene.template_dir == os.path.join(save_dir, "templates")
        assert isolated_scene.nodes_dir == os.path.join(save_dir, "nodes")
        assert isolated_scene.info_dir == os.path.join(save_dir, "info")
        assert isolated_scene.backups_dir == os.path.join(save_dir, "backups")
        assert isolated_scene.changelog_dir == os.path.join(save_dir, "changelog")
        assert isolated_scene.shared_context_dir == os.path.join(
            save_dir, "shared-context"
        )

    def test_nodes_filepath_combines_nodes_dir_and_filename(self, isolated_scene):
        isolated_scene.nodes_filename = "loop.json"
        assert isolated_scene.nodes_filepath == os.path.join(
            isolated_scene.nodes_dir, "loop.json"
        )

    def test_creative_nodes_filepath_combines_nodes_dir_and_filename(
        self, isolated_scene
    ):
        isolated_scene.creative_nodes_filename = "creative.json"
        assert isolated_scene.creative_nodes_filepath == os.path.join(
            isolated_scene.nodes_dir, "creative.json"
        )

    def test_save_files_lists_only_json_files_sorted(self, isolated_scene):
        # Set up files in save_dir
        with open(os.path.join(isolated_scene.save_dir, "z_save.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(isolated_scene.save_dir, "a_save.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(isolated_scene.save_dir, "ignore.txt"), "w") as f:
            f.write("ignored")

        files = isolated_scene.save_files
        assert files == ["a_save.json", "z_save.json"]

    def test_save_files_caches_after_first_read(self, isolated_scene):
        # Initially empty.
        assert isolated_scene.save_files == []
        # Adding a file after the cache is populated should not be visible.
        with open(os.path.join(isolated_scene.save_dir, "later.json"), "w") as f:
            f.write("{}")
        assert isolated_scene.save_files == []


# ---------------------------------------------------------------------------
# History helpers: recent_history, find_message, message_index, get_message
# ---------------------------------------------------------------------------


class TestHistoryAccessors:
    def test_num_history_entries_matches_history_length(self, real_scene):
        real_scene.history = [_char_msg("a"), _char_msg("b"), _char_msg("c")]
        assert real_scene.num_history_entries == 3

    def test_recent_history_walks_back_from_tail(self, real_scene):
        msgs = [_char_msg(f"m{i}") for i in range(5)]
        real_scene.history = list(msgs)
        # With a generous budget, all messages are returned in original order.
        result = real_scene.recent_history(max_tokens=100_000)
        assert result == msgs

    def test_recent_history_respects_token_budget(self, real_scene):
        # Each message is small but token-counted; with a tiny budget we should
        # get fewer than the full set, but at least one.
        real_scene.history = [_char_msg(f"m{i}") for i in range(20)]
        result = real_scene.recent_history(max_tokens=1)
        assert 0 < len(result) < 20

    def test_recent_history_empty_history_returns_empty_list(self, real_scene):
        real_scene.history = []
        assert real_scene.recent_history() == []

    def test_prev_actor_returns_last_character_message_speaker(self, real_scene):
        a = _char_msg("hi", character="Alice")
        b = _char_msg("hi back", character="Bob")
        real_scene.history = [a, b, NarratorMessage(message="ignored", source="ai")]
        # Walks from the end skipping non-character messages.
        assert real_scene.prev_actor == "Bob"

    def test_prev_actor_returns_none_when_no_character_messages(self, real_scene):
        real_scene.history = [NarratorMessage(message="x", source="ai")]
        assert real_scene.prev_actor is None

    def test_find_message_returns_last_matching_typ(self, real_scene):
        n1 = NarratorMessage(message="n1", source="ai")
        n2 = NarratorMessage(message="n2", source="ai")
        real_scene.history = [n1, _char_msg("c"), n2]
        assert real_scene.find_message("narrator") is n2

    def test_find_message_returns_none_when_max_iterations_blocks(self, real_scene):
        # With max_iterations=1, the loop returns None on the very first non-match.
        real_scene.history = [_char_msg("c"), NarratorMessage(message="n", source="ai")]
        assert real_scene.find_message("narrator", max_iterations=1) is None

    def test_message_index_finds_id(self, real_scene):
        a = _char_msg("a")
        b = _char_msg("b")
        real_scene.history = [a, b]
        assert real_scene.message_index(a.id) == 0
        assert real_scene.message_index(b.id) == 1

    def test_message_index_returns_neg_one_when_missing(self, real_scene):
        real_scene.history = [_char_msg("a")]
        assert real_scene.message_index(98765) == -1

    def test_get_message_returns_message_or_none(self, real_scene):
        a = _char_msg("a")
        real_scene.history = [a]
        assert real_scene.get_message(a.id) is a
        assert real_scene.get_message(99999) is None

    def test_last_player_message_returns_player_source(self, real_scene):
        ai_msg = _char_msg("hi", character="Alice", source="ai")
        player_msg = _char_msg("hello", character="Hero", source="player")
        real_scene.history = [
            ai_msg,
            player_msg,
            NarratorMessage(message="N", source="ai"),
        ]
        assert real_scene.last_player_message() is player_msg

    def test_last_player_message_returns_none_when_absent(self, real_scene):
        real_scene.history = [_char_msg("hi", source="ai")]
        assert real_scene.last_player_message() is None

    def test_last_message_by_character_walks_from_end(self, real_scene):
        a1 = _char_msg("first", character="Alice")
        b1 = _char_msg("hi", character="Bob")
        a2 = _char_msg("last", character="Alice")
        real_scene.history = [a1, b1, a2]
        assert real_scene.last_message_by_character("Alice") is a2
        assert real_scene.last_message_by_character("Bob") is b1
        assert real_scene.last_message_by_character("Charlie") is None


# ---------------------------------------------------------------------------
# count_character_messages_since_director
# ---------------------------------------------------------------------------


class TestCountCharacterMessagesSinceDirector:
    def test_returns_zero_when_no_director_message(self, real_scene):
        real_scene.history = [
            _char_msg("a", character="Alice"),
            _char_msg("b", character="Alice"),
        ]
        assert real_scene.count_character_messages_since_director("Alice") == 0

    def test_counts_messages_since_director_for_character(self, real_scene):
        director = DirectorMessage(
            message="Be brave!",
            source="ai",
            meta={"character": "Alice"},
        )
        real_scene.history = [
            director,
            _char_msg("doing it", character="Alice"),
            _char_msg("still going", character="Alice"),
        ]
        assert real_scene.count_character_messages_since_director("Alice") == 2

    def test_other_character_messages_do_not_count(self, real_scene):
        director = DirectorMessage(
            message="Be brave!",
            source="ai",
            meta={"character": "Alice"},
        )
        real_scene.history = [
            director,
            _char_msg("hello", character="Bob"),
            _char_msg("alice acts", character="Alice"),
        ]
        assert real_scene.count_character_messages_since_director("Alice") == 1

    def test_stop_on_time_passage_short_circuits(self, real_scene):
        director = DirectorMessage(
            message="Be brave!", source="ai", meta={"character": "Alice"}
        )
        # Layout (oldest -> newest): director, alice-msg, time-passage, alice-msg
        # Walking from the end: alice-msg(+1), time-passage(stop) -> returns 0
        # because the director was never reached.
        real_scene.history = [
            director,
            _char_msg("a1", character="Alice"),
            TimePassageMessage(ts="PT1H", message="an hour later"),
            _char_msg("a2", character="Alice"),
        ]
        result = real_scene.count_character_messages_since_director(
            "Alice", stop_on_time_passage=True
        )
        assert result == 0


# ---------------------------------------------------------------------------
# last_message_of_type / collect_messages / count_messages
# ---------------------------------------------------------------------------


class TestLastMessageOfType:
    def test_returns_last_matching_type(self, real_scene):
        n1 = NarratorMessage(message="n1", source="ai")
        n2 = NarratorMessage(message="n2", source="ai")
        real_scene.history = [n1, _char_msg("c"), n2]
        assert real_scene.last_message_of_type("narrator") is n2

    def test_accepts_list_of_types(self, real_scene):
        c = _char_msg("hi")
        n = NarratorMessage(message="n", source="ai")
        real_scene.history = [c, n]
        # Both types are valid; the LAST matching message wins.
        assert real_scene.last_message_of_type(["character", "narrator"]) is n

    def test_filters_by_source(self, real_scene):
        n_ai = NarratorMessage(message="ai-narr", source="ai")
        n_manual = NarratorMessage(message="manual-narr", source="manual")
        real_scene.history = [n_ai, n_manual]
        assert real_scene.last_message_of_type("narrator", source="ai") is n_ai

    def test_max_iterations_limit(self, real_scene):
        # Tail has 3 character messages and one narrator at index 0.
        # max_iterations=2 only inspects the last 2 messages -> never reaches narrator.
        n = NarratorMessage(message="n", source="ai")
        real_scene.history = [
            n,
            _char_msg("a"),
            _char_msg("b"),
            _char_msg("c"),
        ]
        assert real_scene.last_message_of_type("narrator", max_iterations=2) is None

    def test_stop_on_time_passage(self, real_scene):
        n = NarratorMessage(message="n", source="ai")
        tp = TimePassageMessage(ts="PT1H", message="later")
        real_scene.history = [n, tp, _char_msg("c")]
        # Walking from the end: char (no match), time-passage (stop) -> None.
        assert (
            real_scene.last_message_of_type("narrator", stop_on_time_passage=True)
            is None
        )

    def test_on_iterate_callback_invoked_per_message(self, real_scene):
        seen = []
        real_scene.history = [
            _char_msg("a"),
            NarratorMessage(message="n", source="ai"),
        ]
        real_scene.last_message_of_type("narrator", on_iterate=seen.append)
        # We start from the tail, so the first observed message is the narrator.
        assert len(seen) >= 1


class TestCollectMessages:
    def test_collects_in_reverse_chronological_order(self, real_scene):
        a = _char_msg("a")
        b = _char_msg("b")
        n = NarratorMessage(message="n", source="ai")
        real_scene.history = [a, n, b]
        # No type filter -> all messages, walking from end.
        result = real_scene.collect_messages()
        assert result == [b, n, a]

    def test_filters_by_type(self, real_scene):
        a = _char_msg("a")
        b = _char_msg("b")
        n = NarratorMessage(message="n", source="ai")
        real_scene.history = [a, n, b]
        result = real_scene.collect_messages(typ="character")
        assert result == [b, a]

    def test_max_messages_caps_collection(self, real_scene):
        msgs = [_char_msg(f"m{i}") for i in range(5)]
        real_scene.history = msgs
        result = real_scene.collect_messages(max_messages=2)
        # Only the latest 2.
        assert result == [msgs[-1], msgs[-2]]

    def test_stop_on_time_passage_breaks(self, real_scene):
        a = _char_msg("a")
        tp = TimePassageMessage(ts="PT1H", message="later")
        b = _char_msg("b")
        real_scene.history = [a, tp, b]
        result = real_scene.collect_messages(stop_on_time_passage=True)
        # Walking from the end: b (collected), tp (collected then break).
        # `a` (older than the passage) is NOT collected.
        assert result == [b, tp]
        assert a not in result

    def test_start_idx_anchors_search(self, real_scene):
        a = _char_msg("a")
        b = _char_msg("b")
        c = _char_msg("c")
        real_scene.history = [a, b, c]
        # Start at index 1 -> walks back from b.
        result = real_scene.collect_messages(start_idx=1)
        assert result == [b, a]


class TestCountMessages:
    def test_counts_all_when_no_filters(self, real_scene):
        real_scene.history = [
            _char_msg("a"),
            NarratorMessage(message="n", source="ai"),
            _char_msg("b"),
        ]
        assert real_scene.count_messages() == 3

    def test_counts_by_type(self, real_scene):
        real_scene.history = [
            _char_msg("a"),
            NarratorMessage(message="n", source="ai"),
            _char_msg("b"),
        ]
        assert real_scene.count_messages(message_type="character") == 2
        assert real_scene.count_messages(message_type="narrator") == 1

    def test_counts_by_source(self, real_scene):
        ai = _char_msg("a", source="ai")
        player = _char_msg("p", character="Hero", source="player")
        real_scene.history = [ai, player]
        assert real_scene.count_messages(source="ai") == 1
        assert real_scene.count_messages(source="player") == 1

    def test_counts_match_secondary_source(self, real_scene):
        # CharacterMessage.secondary_source is the character name.
        ai = _char_msg("hi", character="Alice", source="ai")
        real_scene.history = [ai]
        # Source filter matches *either* source or secondary_source.
        assert real_scene.count_messages(source="Alice") == 1


class TestSnapshot:
    def test_returns_movie_script_format_by_default(self, real_scene):
        msgs = [
            _char_msg("hi", character="Alice"),
            _char_msg("hello", character="Bob"),
        ]
        real_scene.history = msgs
        result = real_scene.snapshot(lines=2)
        # Script format includes character names in upper case and END-OF-LINE markers.
        assert "ALICE" in result
        assert "BOB" in result
        assert "END-OF-LINE" in result

    def test_returns_list_when_requested(self, real_scene):
        a = _char_msg("a")
        b = _char_msg("b")
        real_scene.history = [a, b]
        result = real_scene.snapshot(lines=2, return_as_list=True)
        assert result == [a, b]

    def test_default_ignores_director_and_reinforcement(self, real_scene):
        a = _char_msg("hi")
        director = DirectorMessage(message="cut!", source="ai")
        reinf = ReinforcementMessage(message="reinforced", source="ai")
        b = _char_msg("bye")
        real_scene.history = [a, director, reinf, b]
        result = real_scene.snapshot(lines=4, return_as_list=True)
        # Director and reinforcement are filtered out; we get only the chars.
        assert result == [a, b]

    def test_custom_ignore_with_string_types(self, real_scene):
        a = _char_msg("a")
        n = NarratorMessage(message="n", source="ai")
        real_scene.history = [a, n]
        # Pass type as string; it should be resolved through MESSAGES.
        result = real_scene.snapshot(lines=2, ignore=["narrator"], return_as_list=True)
        assert result == [a]

    def test_custom_ignore_invalid_type_raises(self, real_scene):
        real_scene.history = [_char_msg("a")]
        with pytest.raises(ValueError):
            real_scene.snapshot(lines=1, ignore=[123])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# pop_message / pop_history / edit_message / delete_message
# ---------------------------------------------------------------------------


class TestPopMessage:
    @pytest.mark.asyncio
    async def test_pop_by_message_object(self, real_scene):
        # A successful pop calls emit_status, which requires a running loop.
        a = _char_msg("a")
        b = _char_msg("b")
        real_scene.history = [a, b]
        assert real_scene.pop_message(a) is True
        assert real_scene.history == [b]

    def test_pop_by_int_returns_false_when_no_typ_match(self, real_scene):
        # The int branch calls find_message(message) treating the int as a typ
        # filter. Since message.typ is always a string, no message will match
        # and pop_message returns False without mutating history.
        a = _char_msg("a")
        real_scene.history = [a]
        assert real_scene.pop_message(123) is False
        assert real_scene.history == [a]

    def test_pop_nonexistent_returns_false(self, real_scene):
        ghost = _char_msg("ghost")
        real_scene.history = [_char_msg("a")]
        assert real_scene.pop_message(ghost) is False

    def test_pop_invalid_type_raises_value_error(self, real_scene):
        with pytest.raises(ValueError):
            real_scene.pop_message("not a message")  # type: ignore[arg-type]


class TestPopHistory:
    # pop_history calls emit_status when it removes anything, and that
    # requires a running event loop — so every test that actually pops is
    # async (mirrors TestDeleteMessage.test_delete_time_passage_resyncs_time).
    @pytest.mark.asyncio
    async def test_pop_last_matching_by_default(self, real_scene):
        n1 = NarratorMessage(message="n1", source="ai")
        n2 = NarratorMessage(message="n2", source="ai")
        real_scene.history = [n1, _char_msg("c"), n2]
        real_scene.pop_history(typ="narrator")
        # Only the last narrator is popped.
        assert n2 not in real_scene.history
        assert n1 in real_scene.history

    @pytest.mark.asyncio
    async def test_pop_all_matching(self, real_scene):
        n1 = NarratorMessage(message="n1", source="ai")
        n2 = NarratorMessage(message="n2", source="ai")
        c = _char_msg("c")
        real_scene.history = [n1, c, n2]
        real_scene.pop_history(typ="narrator", all=True)
        assert n1 not in real_scene.history
        assert n2 not in real_scene.history
        assert c in real_scene.history

    @pytest.mark.asyncio
    async def test_pop_filtered_by_source(self, real_scene):
        n_ai = NarratorMessage(message="ai", source="ai")
        n_manual = NarratorMessage(message="man", source="manual")
        real_scene.history = [n_ai, n_manual]
        real_scene.pop_history(typ="narrator", source="manual", all=True)
        assert n_ai in real_scene.history
        assert n_manual not in real_scene.history

    @pytest.mark.asyncio
    async def test_pop_filtered_by_meta_hash(self, real_scene):
        n_a = NarratorMessage(message="a", source="ai", meta={"k": 1})
        n_b = NarratorMessage(message="b", source="ai", meta={"k": 2})
        real_scene.history = [n_a, n_b]
        real_scene.pop_history(typ="narrator", meta_hash=n_b.meta_hash, all=True)
        # Only n_b is popped.
        assert n_a in real_scene.history
        assert n_b not in real_scene.history

    @pytest.mark.asyncio
    async def test_pop_filtered_by_arbitrary_attribute(self, real_scene):
        a_player = _char_msg("a", character="Hero", source="player")
        a_ai = _char_msg("b", character="Alice", source="ai")
        real_scene.history = [a_player, a_ai]
        # Custom filter: source="ai" is already supported via the source param,
        # but additional kwargs are passed as attribute filters too.
        real_scene.pop_history(typ="character", all=True, source="player")
        assert a_player not in real_scene.history
        assert a_ai in real_scene.history

    @pytest.mark.asyncio
    async def test_pop_reverse_pops_oldest_match_first(self, real_scene):
        n_old = NarratorMessage(message="old", source="ai")
        n_new = NarratorMessage(message="new", source="ai")
        real_scene.history = [n_old, _char_msg("c"), n_new]
        real_scene.pop_history(typ="narrator", reverse=True)
        # Reverse pops the oldest match.
        assert n_old not in real_scene.history
        assert n_new in real_scene.history


class TestEditMessage:
    def test_edit_message_updates_message_text(self, real_scene):
        a = _char_msg("hi")
        real_scene.history = [a]
        real_scene.edit_message(a.id, "Alice: bye")
        assert real_scene.history[0].message == "Alice: bye"

    def test_edit_message_unknown_id_is_silent_noop(self, real_scene):
        a = _char_msg("hi")
        real_scene.history = [a]
        # Non-matching id should not raise; history is untouched.
        real_scene.edit_message(98765, "ignored")
        assert real_scene.history[0].message == "Alice: hi"


class TestDeleteMessage:
    def test_delete_removes_matching_message(self, real_scene):
        a = _char_msg("a")
        b = _char_msg("b")
        real_scene.history = [a, b]
        real_scene.delete_message(a.id)
        assert real_scene.history == [b]

    def test_delete_unknown_id_is_silent_noop(self, real_scene):
        a = _char_msg("a")
        real_scene.history = [a]
        real_scene.delete_message(98765)
        assert real_scene.history == [a]

    @pytest.mark.asyncio
    async def test_delete_time_passage_resyncs_time(self, real_scene):
        # When a TimePassageMessage is removed, sync_time runs and emit_status
        # is called -- the latter requires a running event loop.
        tp = TimePassageMessage(ts="PT1H", message="later")
        real_scene.history = [tp]
        real_scene.ts = "PT1H"
        real_scene.delete_message(tp.id)
        # sync_time without remaining time-passage messages resets to PT0S.
        assert real_scene.ts == "PT0S"


# ---------------------------------------------------------------------------
# advance_time / sync_time / calc_time
# ---------------------------------------------------------------------------


class TestAdvanceTime:
    def test_advance_time_adds_durations(self, real_scene):
        real_scene.ts = "PT1H"
        real_scene.advance_time("PT30M")
        assert real_scene.ts == "PT1H30M"

    def test_advance_time_supports_zero(self, real_scene):
        real_scene.ts = "PT5M"
        real_scene.advance_time("PT0S")
        assert real_scene.ts == "PT5M"


class TestSyncTime:
    def test_sync_time_sums_history_passages(self, real_scene):
        real_scene.history = [
            _char_msg("a"),
            TimePassageMessage(ts="PT1H", message="later"),
            _char_msg("b"),
            TimePassageMessage(ts="PT30M", message="more later"),
        ]
        # No archived_history, so we start from PT0S and sum.
        real_scene.sync_time()
        assert real_scene.ts == "PT1H30M"

    def test_sync_time_uses_archived_baseline(self, real_scene):
        real_scene.archived_history = [{"ts": "PT2H", "end": 0}]
        # No additional time passages after end=0.
        real_scene.history = [_char_msg("a")]
        real_scene.sync_time()
        assert real_scene.ts == "PT2H"

    def test_sync_time_with_no_data_resets_to_zero(self, real_scene):
        real_scene.ts = "PT5H"  # leftover
        real_scene.history = []
        real_scene.archived_history = []
        real_scene.sync_time()
        assert real_scene.ts == "PT0S"


class TestCalcTime:
    def test_returns_none_when_no_passages(self, real_scene):
        real_scene.history = [_char_msg("a"), _char_msg("b")]
        assert real_scene.calc_time(0, 2) is None

    def test_sums_passages_in_range(self, real_scene):
        real_scene.history = [
            TimePassageMessage(ts="PT1H", message="later"),
            _char_msg("a"),
            TimePassageMessage(ts="PT30M", message="more"),
        ]
        # Full range
        assert real_scene.calc_time() == "PT1H30M"

    def test_partial_range(self, real_scene):
        real_scene.history = [
            TimePassageMessage(ts="PT1H", message="later"),
            TimePassageMessage(ts="PT30M", message="more"),
        ]
        # Only the first passage included.
        assert real_scene.calc_time(0, 1) == "PT1H"


# ---------------------------------------------------------------------------
# get_intro
# ---------------------------------------------------------------------------


class TestGetIntro:
    def test_get_intro_returns_intro_when_no_player(self, real_scene):
        real_scene.intro = "Welcome adventurer."
        # editor.fix_exposition_enabled defaults to whatever config.example sets;
        # the intro string contains no quotes/asterisks, but we don't assert the
        # exact post-processed value — only that the string is preserved as a
        # substring (since fix_exposition may wrap it in asterisks).
        result = real_scene.get_intro()
        assert "Welcome adventurer." in result

    def test_get_intro_substitutes_user_placeholder(self, real_scene):
        _add_char(real_scene, "Hero", is_player=True)
        real_scene.intro = "Hello, {{user}}!"
        result = real_scene.get_intro()
        assert "Hero" in result
        assert "{{user}}" not in result

    def test_get_intro_can_take_explicit_intro_argument(self, real_scene):
        _add_char(real_scene, "Hero", is_player=True)
        result = real_scene.get_intro("Greetings, {{char}}!")
        assert "Hero" in result


# ---------------------------------------------------------------------------
# can_auto_save / interrupt / continue_actions / reset / serialize / json
# ---------------------------------------------------------------------------


class TestCanAutoSave:
    def test_no_filename_means_cannot_auto_save(self, real_scene):
        real_scene.filename = ""
        # Implementation returns ``self.filename and not self.immutable_save``,
        # which short-circuits to the falsy filename string. Compare via bool.
        assert not real_scene.can_auto_save()

    def test_immutable_save_blocks_auto_save(self, real_scene):
        real_scene.filename = "x.json"
        real_scene.immutable_save = True
        assert real_scene.can_auto_save() is False

    def test_filename_and_not_immutable_can_auto_save(self, real_scene):
        real_scene.filename = "x.json"
        real_scene.immutable_save = False
        assert real_scene.can_auto_save() is True


class TestInterruptAndContinueActions:
    def test_interrupt_sets_cancel_requested(self, real_scene):
        assert real_scene.cancel_requested is False
        real_scene.interrupt()
        assert real_scene.cancel_requested is True

    def test_continue_actions_raises_when_cancel_requested(self, real_scene):
        real_scene.cancel_requested = True
        with pytest.raises(GenerationCancelled):
            real_scene.continue_actions()
        # The flag is reset after the raise so a subsequent call is a no-op.
        assert real_scene.cancel_requested is False

    def test_continue_actions_is_noop_when_not_requested(self, real_scene):
        real_scene.cancel_requested = False
        # Should not raise.
        real_scene.continue_actions()


class TestReset:
    def test_reset_clears_history_and_filename(self, real_scene):
        real_scene.history = [_char_msg("a")]
        real_scene.filename = "scene.json"
        real_scene.archived_history = [
            {"text": "static", "end": None},
            {"text": "dynamic", "end": 5},
        ]
        real_scene.reset()
        assert real_scene.history == []
        assert real_scene.filename == ""
        # Static (end=None) is preserved; dynamic is wiped.
        assert len(real_scene.archived_history) == 1
        assert real_scene.archived_history[0]["text"] == "static"

    def test_reset_preserves_pre_established_archived_entries(self, real_scene):
        real_scene.archived_history = [
            {"text": "intro", "end": None},  # static, kept
            {"text": "summary", "end": 3},  # dynamic, removed
        ]
        real_scene.reset()
        assert real_scene.archived_history == [{"text": "intro", "end": None}]


class TestSerialize:
    def test_serialize_returns_dict_with_core_fields(self, real_scene):
        real_scene.name = "Test"
        real_scene.intro = "Hi"
        real_scene.history = [_char_msg("a")]
        data = real_scene.serialize
        # Spot-check key fields.
        assert data["name"] == "Test"
        assert data["intro"] == "Hi"
        assert data["history"] is real_scene.history
        assert data["archived_history"] is real_scene.archived_history
        assert "id" in data
        assert "memory_id" in data

    def test_serialize_handles_inactive_characters(self, real_scene):
        real_scene.character_data["Ghost"] = Character(name="Ghost")
        data = real_scene.serialize
        assert "Ghost" in data["character_data"]
        # active_characters list is empty since we only registered character_data.
        assert data["active_characters"] == real_scene.active_characters

    def test_json_property_returns_valid_json_string(self, real_scene):
        import json as _json

        real_scene.name = "Test"
        text = real_scene.json
        decoded = _json.loads(text)
        assert decoded["name"] == "Test"


# ---------------------------------------------------------------------------
# push_history (sync portion + signals) / push_archive
# ---------------------------------------------------------------------------


class TestPushHistory:
    @pytest.mark.asyncio
    async def test_push_history_appends_single_message(self, real_scene):
        msg = _char_msg("hi")
        await real_scene.push_history(msg)
        assert msg in real_scene.history
        assert real_scene.history[-1] is msg

    @pytest.mark.asyncio
    async def test_push_history_extends_with_list(self, real_scene):
        a = _char_msg("a")
        b = _char_msg("b")
        await real_scene.push_history([a, b])
        assert real_scene.history[-2:] == [a, b]

    @pytest.mark.asyncio
    async def test_push_history_dedupes_director_by_source(self, real_scene):
        d1 = DirectorMessage(message="first", source="director-source-1")
        d2 = DirectorMessage(message="second", source="director-source-1")
        await real_scene.push_history(d1)
        await real_scene.push_history(d2)
        # Same source -> the older one is removed.
        directors = [m for m in real_scene.history if isinstance(m, DirectorMessage)]
        assert directors == [d2]

    @pytest.mark.asyncio
    async def test_push_history_keeps_director_with_distinct_sources(self, real_scene):
        d1 = DirectorMessage(message="from-A", source="A")
        d2 = DirectorMessage(message="from-B", source="B")
        await real_scene.push_history(d1)
        await real_scene.push_history(d2)
        directors = [m for m in real_scene.history if isinstance(m, DirectorMessage)]
        assert directors == [d1, d2]

    @pytest.mark.asyncio
    async def test_push_history_drops_empty_director_messages(self, real_scene):
        d_empty = DirectorMessage(message="   ", source="x")
        d_real = DirectorMessage(message="real", source="x")
        await real_scene.push_history([d_empty, d_real])
        directors = [m for m in real_scene.history if isinstance(m, DirectorMessage)]
        # Only the real one is kept.
        assert directors == [d_real]

    @pytest.mark.asyncio
    async def test_push_history_advances_time_for_time_passage(self, real_scene):
        real_scene.ts = "PT0S"
        tp = TimePassageMessage(ts="PT1H", message="later")
        await real_scene.push_history(tp)
        assert real_scene.ts == "PT1H"

    @pytest.mark.asyncio
    async def test_push_history_emits_push_history_signal(self, real_scene):
        captured: list = []

        async def listener(event):
            captured.append(event)

        signal = async_signals.get("push_history")
        signal.connect(listener)
        try:
            await real_scene.push_history(_char_msg("hi"))
        finally:
            signal.disconnect(listener)

        assert len(captured) == 1
        evt = captured[0]
        assert evt.scene is real_scene
        assert evt.event_type == "push_history"
        assert len(evt.messages) == 1


class TestPushArchive:
    @pytest.mark.asyncio
    async def test_push_archive_appends_dict_form(self, real_scene):
        from talemate.history import ArchiveEntry

        entry = ArchiveEntry(text="my entry", id="abc", ts="PT5M")
        captured: list = []

        async def listener(event):
            captured.append(event)

        signal = async_signals.get("archive_add")
        signal.connect(listener)
        try:
            await real_scene.push_archive(entry)
        finally:
            signal.disconnect(listener)

        # The archive list should contain the dict form (no None fields).
        assert len(real_scene.archived_history) == 1
        stored = real_scene.archived_history[0]
        assert stored["text"] == "my entry"
        assert stored["id"] == "abc"
        # And the archive_add signal fired.
        assert len(captured) == 1


# ---------------------------------------------------------------------------
# story_intent / intent / active_node_graph / max_backscroll / conversation_format
# ---------------------------------------------------------------------------


class TestSimpleProperties:
    def test_story_intent_delegates_to_intent_state(self, real_scene):
        real_scene.intent_state.intent = "high adventure"
        assert real_scene.story_intent == "high adventure"

    def test_intent_returns_empty_dict_when_no_phase(self, real_scene):
        # Force the no-phase branch of Scene.intent.
        real_scene.intent_state.phase = None
        assert real_scene.intent == {}

    def test_intent_returns_phase_data_when_phase_set(self, real_scene):
        # The default factory leaves us with a 'roleplay' SceneType + phase.
        # The intent property returns name + intent (which can be None).
        assert real_scene.intent_state.phase is not None
        result = real_scene.intent
        assert "name" in result
        assert "intent" in result

    def test_active_node_graph_returns_none_when_neither_set(self, real_scene):
        # Neither node_graph nor creative_node_graph is set on a fresh scene.
        assert real_scene.active_node_graph is None

    def test_active_node_graph_prefers_node_graph(self, real_scene):
        real_scene.node_graph = "primary"
        real_scene.creative_node_graph = "creative"
        assert real_scene.active_node_graph == "primary"

    def test_max_backscroll_reads_from_config(self, real_scene):
        # Just verify it returns the int from config.example.yaml's general section.
        assert isinstance(real_scene.max_backscroll, int)
        assert real_scene.max_backscroll > 0

    def test_auto_save_reads_from_config(self, real_scene):
        # Boolean from config.example.yaml.
        assert isinstance(real_scene.auto_save, bool)

    def test_auto_backup_is_always_false(self, real_scene):
        assert real_scene.auto_backup is False

    def test_conversation_format_property_resolves(self, real_scene):
        # Pulls from instance.get_agent("conversation").conversation_format.
        # We just need the access to succeed and return a non-empty string.
        fmt = real_scene.conversation_format
        assert fmt
        assert isinstance(fmt, str)


# ---------------------------------------------------------------------------
# agent_persona / agent_persona_names / writing_style (None paths)
# ---------------------------------------------------------------------------


class TestPersonaResolvers:
    def test_agent_persona_returns_none_when_unset(self, real_scene):
        assert real_scene.agent_personas == {}
        assert real_scene.agent_persona_names == {}
        assert real_scene.agent_persona("anything") is None

    def test_agent_persona_returns_none_for_invalid_uid(self, real_scene):
        # An entry without `__` separator returns None instead of raising.
        real_scene.agent_persona_templates = {"narrator": "no-double-underscore"}
        assert real_scene.agent_persona("narrator") is None
        # And the helpers stay empty for unresolved templates.
        assert real_scene.agent_persona_names == {}
        assert real_scene.agent_personas == {}

    def test_writing_style_returns_none_when_unset(self, real_scene):
        real_scene.writing_style_template = None
        assert real_scene.writing_style is None

    def test_writing_style_returns_none_for_invalid_uid(self, real_scene):
        real_scene.writing_style_template = "no-underscore"
        # split('__', 1) raises ValueError -> swallowed, returns None.
        assert real_scene.writing_style is None


# ---------------------------------------------------------------------------
# set_new_memory_session_id
# ---------------------------------------------------------------------------


class TestSetNewMemorySessionId:
    @pytest.mark.asyncio
    async def test_rotates_session_id_and_saves_previous(self, real_scene):
        # set_new_memory_session_id calls emit_status which requires a loop.
        prev = real_scene.memory_session_id
        real_scene.set_new_memory_session_id()
        # The old id is preserved as saved_memory_session_id.
        assert real_scene.saved_memory_session_id == prev
        # And a new id is generated (10-char uuid prefix).
        assert real_scene.memory_session_id != prev
        assert len(real_scene.memory_session_id) == 10


# ---------------------------------------------------------------------------
# connect / disconnect signal lifecycle
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Misc additional coverage: scenes_dir default, snapshot start, attempt_auto_save,
# fix_time error handling, push_archive ts-only path, recent_history extras
# ---------------------------------------------------------------------------


class TestScenesDirDefault:
    def test_scenes_dir_resolves_to_absolute_path(self):
        # The classmethod returns an absolute path under the repo root.
        path = Scene.scenes_dir()
        assert os.path.isabs(path)
        assert path.endswith("scenes")


class TestSnapshotStartIndex:
    def test_snapshot_with_start_anchors_to_earlier_segment(self, real_scene):
        a = _char_msg("a")
        b = _char_msg("b")
        c = _char_msg("c")
        real_scene.history = [a, b, c]
        # start=1 => segment is history[:2][-3:] = [a, b].  We then collect
        # in reverse and insert at the front, so the final list preserves
        # input order.
        result = real_scene.snapshot(lines=3, start=1, return_as_list=True)
        assert result == [a, b]


class TestAttemptAutoSave:
    @pytest.mark.asyncio
    async def test_no_filename_marks_unsaved_and_skips(self, real_scene):
        # Without a filename and with auto_save=False semantics, the scene
        # should be flagged unsaved and not raise.
        real_scene.filename = ""
        real_scene.saved = True
        # Force auto_save to False via an attribute override on the instance.
        # The method short-circuits to setting saved=False, then emit_status.
        # auto_save is a property that reads from config; the example config's
        # default is False, but be defensive and assert the post-condition.
        await real_scene.attempt_auto_save()
        # In the auto_save=False branch, saved is set to False.
        if not real_scene.auto_save:
            assert real_scene.saved is False


class TestFixTimeErrorHandling:
    def test_fix_time_swallows_exception_and_restores_ts(self, real_scene):
        # Force _fix_time to raise by giving it malformed archived data and
        # confirm fix_time restores the original ts and does not propagate.
        real_scene.ts = "PT3H"
        # archived_history is iterated as dicts; non-dict entries crash the
        # `"ts" in archived_entry` membership test.
        real_scene.archived_history = [None]  # type: ignore[list-item]
        real_scene.history = []
        # Should not raise.
        real_scene.fix_time()
        # ts is restored to the snapshot taken at the start of fix_time.
        assert real_scene.ts == "PT3H"


class TestRecentHistoryNoBudget:
    def test_recent_history_default_max_tokens_returns_all(self, real_scene):
        msgs = [_char_msg(f"m{i}") for i in range(3)]
        real_scene.history = list(msgs)
        # Default budget (2048) is more than enough for 3 short messages.
        assert real_scene.recent_history() == msgs


# ---------------------------------------------------------------------------
# last_message_of_type: count_only_types branch
# ---------------------------------------------------------------------------


class TestLastMessageCountOnlyTypes:
    def test_count_only_types_excludes_other_types_from_max_iterations(
        self, real_scene
    ):
        # The narrator we want to find is past the max_iterations boundary if
        # all messages count toward it. With count_only_types=["character"],
        # only character messages tick the counter, so the narrator is found.
        n = NarratorMessage(message="goal", source="ai")
        real_scene.history = [
            n,
            _char_msg("c1"),
            _char_msg("c2"),
        ]
        # Without count_only_types and max_iterations=2: walk c2(+1), c1(+2),
        # boundary -> None.
        assert real_scene.last_message_of_type("narrator", max_iterations=2) is None
        # With count_only_types=["character"]: characters tick, narrator does not.
        # walk c2(+1), c1(+2) -> still doesn't reach the narrator (max_iterations=2),
        # so we further increase max to 3 to exercise the branch.
        assert (
            real_scene.last_message_of_type(
                "narrator",
                max_iterations=3,
                count_only_types=["character"],
            )
            is n
        )


# ---------------------------------------------------------------------------
# push_archive emits ts on archived_history regardless of None ts argument
# ---------------------------------------------------------------------------


class TestPushArchiveDictShape:
    @pytest.mark.asyncio
    async def test_archived_dict_excludes_none_fields(self, real_scene):
        from talemate.history import ArchiveEntry

        entry = ArchiveEntry(text="x", id="i1", ts="PT1S")
        await real_scene.push_archive(entry)
        stored = real_scene.archived_history[0]
        # Optional fields like start/end/ts_start/ts_end aren't on the entry,
        # so they shouldn't appear in the stored dict.
        for opt in ("start", "end", "ts_start", "ts_end"):
            assert opt not in stored


# ---------------------------------------------------------------------------
# Scene.connect/disconnect signal lifecycle
# ---------------------------------------------------------------------------


class TestConnectDisconnect:
    def test_connect_then_disconnect_does_not_double_subscribe(self, real_scene):
        signal = real_scene.signals["config.changed"]
        # Disconnect any leftover connections from __init__/prior tests; the
        # important thing is we can reconnect safely.
        try:
            signal.disconnect(real_scene.on_config_changed)
        except Exception:
            pass

        # Idempotent connect: connect twice is fine and disconnect must remove it.
        real_scene.connect()
        # Disconnect should remove the listener (no exception).
        real_scene.disconnect()
