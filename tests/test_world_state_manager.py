"""
Unit tests for `talemate.world_state.manager.WorldStateManager`.

Focuses on the pure CRUD / state-mutation entry points - skipping the
LLM-driven generation paths (`create_character`, `apply_template_*`,
`add_suggestion`, etc. that depend on creator agents producing real
content). Each test invokes the real manager method on a real scene.
"""

import pytest

from _world_state_helpers import (
    make_actor,
    manager,  # noqa: F401 - pytest fixture
    manager_with_memory,  # noqa: F401 - pytest fixture
    scene,  # noqa: F401 - pytest fixture
    scene_with_memory,  # noqa: F401 - pytest fixture
    world_state,  # noqa: F401 - pytest fixture
)
from talemate.agents.tts.schema import Voice, VoiceLibrary
from talemate.game.focal.schema import Call
from talemate.game.schema import Condition, ConditionGroup
from talemate.world_state import (
    ContextPin,
    ManualContext,
    Reinforcement,
    Suggestion,
)
from talemate.world_state.manager import (
    CharacterDetails,
    CharacterList,
    CharacterSelect,
    ContextDB,
    ContextDBEntry,
    History,
    HistoryEntry,
    World,
)


# ---------------------------------------------------------------------------
# Pure model construction
# ---------------------------------------------------------------------------


class TestModelDefaults:
    def test_character_select_defaults(self):
        c = CharacterSelect(name="Alice")
        assert c.name == "Alice"
        assert c.active is True
        assert c.is_player is False
        assert c.shared is False
        assert c.avatar is None
        assert c.folder is None

    def test_character_details_defaults(self):
        d = CharacterDetails(name="Bob")
        assert d.name == "Bob"
        assert d.active is True
        assert d.is_player is False
        assert d.description == ""
        assert d.base_attributes == {}
        assert d.details == {}
        assert d.actor.dialogue_examples == []

    def test_character_list_defaults(self):
        cl = CharacterList()
        assert cl.characters == {}

    def test_world_defaults(self):
        w = World()
        assert w.entries == {}
        assert w.reinforcements == {}

    def test_history_entry(self):
        e = HistoryEntry(text="x")
        assert e.text == "x"
        assert e.start is None

    def test_history(self):
        h = History()
        assert h.history == []

    def test_context_db_entry(self):
        e = ContextDBEntry(text="t", meta={"foo": "bar"}, id="x")
        assert e.text == "t"
        assert e.meta == {"foo": "bar"}
        assert e.id == "x"

    def test_context_db_default_entries(self):
        db = ContextDB()
        assert db.entries == []


# ---------------------------------------------------------------------------
# get_character_list
# ---------------------------------------------------------------------------


class TestGetCharacterList:
    @pytest.mark.asyncio
    async def test_lists_active_characters(self, scene, manager):
        make_actor(scene, "Alice")
        make_actor(scene, "Bob")
        result = await manager.get_character_list()
        assert set(result.characters.keys()) == {"Alice", "Bob"}
        assert all(c.active for c in result.characters.values())

    @pytest.mark.asyncio
    async def test_includes_inactive_with_active_false(self, scene, manager):
        # Active character
        make_actor(scene, "Alice")
        # Inactive character: present in character_data but NOT in active_characters
        from talemate.character import Character

        ghost = Character(name="Ghost")
        scene.character_data["Ghost"] = ghost  # not added to active_characters

        result = await manager.get_character_list()
        assert result.characters["Alice"].active is True
        assert result.characters["Ghost"].active is False

    @pytest.mark.asyncio
    async def test_empty_scene(self, manager):
        result = await manager.get_character_list()
        assert result.characters == {}


# ---------------------------------------------------------------------------
# get_character_details
# ---------------------------------------------------------------------------


class TestGetCharacterDetails:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown(self, manager):
        result = await manager.get_character_details("Nobody")
        assert result is None

    @pytest.mark.asyncio
    async def test_includes_attributes_and_details(self, scene, manager):
        ch = make_actor(scene, "Alice")
        ch.description = "A warrior"
        ch.base_attributes = {"age": "30", "_hidden": "secret", "class": "knight"}
        ch.details = {"hometown": "Eldoria"}

        result = await manager.get_character_details("Alice")
        assert result.name == "Alice"
        assert result.description == "A warrior"
        # Underscore-prefixed attributes are filtered out
        assert "_hidden" not in result.base_attributes
        assert result.base_attributes["age"] == "30"
        assert result.base_attributes["class"] == "knight"
        # Sorted keys
        keys = list(result.base_attributes.keys())
        assert keys == sorted(keys)
        assert result.details["hometown"] == "Eldoria"

    @pytest.mark.asyncio
    async def test_includes_character_reinforcements(self, scene, manager):
        make_actor(scene, "Alice")
        await scene.world_state.add_reinforcement(
            question="What is Alice's mood?", character="Alice", answer="curious"
        )
        await scene.world_state.add_reinforcement(
            question="What is Bob's mood?", character="Bob", answer="bored"
        )

        result = await manager.get_character_details("Alice")
        assert "What is Alice's mood?" in result.reinforcements
        assert "What is Bob's mood?" not in result.reinforcements


# ---------------------------------------------------------------------------
# get_world
# ---------------------------------------------------------------------------


class TestGetWorld:
    @pytest.mark.asyncio
    async def test_returns_world_entries_and_reinforcements(self, scene, manager):
        ws = scene.world_state
        ws.manual_context["e1"] = ManualContext(
            id="e1", text="entry-one", meta={"typ": "world_state"}
        )
        ws.manual_context["e2"] = ManualContext(
            id="e2", text="char-detail", meta={"typ": "details"}
        )
        await ws.add_reinforcement(question="q", answer="a", character=None)
        await ws.add_reinforcement(question="char_q", answer="ax", character="Alice")

        world = await manager.get_world()
        # Only world-typed entries appear
        assert "e1" in world.entries
        assert "e2" not in world.entries
        # Only world reinforcements (no character)
        assert "q" in world.reinforcements
        assert "char_q" not in world.reinforcements


# ---------------------------------------------------------------------------
# update_character_attribute / detail / description / color / folder /
# visual_rules / actor
# ---------------------------------------------------------------------------


class TestUpdateCharacterScalars:
    @pytest.mark.asyncio
    async def test_update_character_attribute(self, scene, manager_with_memory):
        manager, _ = manager_with_memory
        make_actor(scene, "Alice")
        await manager.update_character_attribute("Alice", "age", "30")
        assert scene.get_character("Alice").base_attributes["age"] == "30"

    @pytest.mark.asyncio
    async def test_update_character_detail(self, scene, manager_with_memory):
        manager, _ = manager_with_memory
        make_actor(scene, "Alice")
        await manager.update_character_detail("Alice", "mood", "curious")
        assert scene.get_character("Alice").details["mood"] == "curious"

    @pytest.mark.asyncio
    async def test_update_character_description(self, scene, manager_with_memory):
        manager, _ = manager_with_memory
        make_actor(scene, "Alice")
        await manager.update_character_description("Alice", "A wandering warrior.")
        assert scene.get_character("Alice").description == "A wandering warrior."

    @pytest.mark.asyncio
    async def test_update_character_color_unknown_logs_and_returns(self, manager):
        # Should not raise even for unknown character (logs and returns)
        await manager.update_character_color("Nobody", "#fff")

    @pytest.mark.asyncio
    async def test_update_character_color_known(self, scene, manager):
        ch = make_actor(scene, "Alice")
        await manager.update_character_color("Alice", "#abc123")
        assert ch.color == "#abc123"

    @pytest.mark.asyncio
    async def test_update_character_folder_known(self, scene, manager):
        ch = make_actor(scene, "Alice")
        await manager.update_character_folder("Alice", "Heroes")
        assert ch.folder == "Heroes"

    @pytest.mark.asyncio
    async def test_update_character_folder_clear(self, scene, manager):
        ch = make_actor(scene, "Alice")
        ch.folder = "Heroes"
        await manager.update_character_folder("Alice", None)
        assert ch.folder is None

    @pytest.mark.asyncio
    async def test_update_character_folder_unknown_no_raise(self, manager):
        await manager.update_character_folder("Ghost", "Heroes")

    @pytest.mark.asyncio
    async def test_update_character_visual_rules(self, scene, manager):
        ch = make_actor(scene, "Alice")
        await manager.update_character_visual_rules("Alice", "tall, blonde")
        assert ch.visual_rules == "tall, blonde"
        assert ch.memory_dirty is True

    @pytest.mark.asyncio
    async def test_update_character_visual_rules_clear_with_empty_string(
        self, scene, manager
    ):
        ch = make_actor(scene, "Alice")
        ch.visual_rules = "old"
        # empty string is falsy; manager normalises to None
        await manager.update_character_visual_rules("Alice", "")
        assert ch.visual_rules is None

    @pytest.mark.asyncio
    async def test_update_character_actor_appends_name_prefix(self, scene, manager):
        ch = make_actor(scene, "Alice")
        await manager.update_character_actor(
            "Alice",
            dialogue_instructions="stay calm",
            example_dialogue=["Alice: hi", "hello!", "Alice: goodbye"],
        )
        assert ch.dialogue_instructions == "stay calm"
        # entries without "Alice:" prefix should be prefixed
        assert ch.example_dialogue == [
            "Alice: hi",
            "Alice: hello!",
            "Alice: goodbye",
        ]


# ---------------------------------------------------------------------------
# rename_character_folder
# ---------------------------------------------------------------------------


class TestRenameCharacterFolder:
    @pytest.mark.asyncio
    async def test_renames_only_matching_folder(self, scene, manager):
        a = make_actor(scene, "Alice")
        b = make_actor(scene, "Bob")
        c = make_actor(scene, "Carol")
        a.folder = "Heroes"
        b.folder = "Heroes"
        c.folder = "Villains"

        await manager.rename_character_folder("Heroes", "Protagonists")

        assert a.folder == "Protagonists"
        assert b.folder == "Protagonists"
        assert c.folder == "Villains"


# ---------------------------------------------------------------------------
# update_character_voice
# ---------------------------------------------------------------------------


class TestUpdateCharacterVoice:
    @pytest.mark.asyncio
    async def test_unknown_character_returns_silently(self, manager):
        await manager.update_character_voice("Ghost", "p:v1")  # no raise

    @pytest.mark.asyncio
    async def test_clear_voice(self, scene, manager):
        ch = make_actor(scene, "Alice")
        ch.voice = Voice(label="x", provider="p", provider_id="v1")
        await manager.update_character_voice("Alice", None)
        assert ch.voice is None

    @pytest.mark.asyncio
    async def test_assigns_voice_from_scene_library(self, scene, manager):
        ch = make_actor(scene, "Alice")
        voice = Voice(label="My voice", provider="p", provider_id="v1")
        scene.voice_library = VoiceLibrary(voices={voice.id: voice})

        await manager.update_character_voice("Alice", voice.id)
        assert ch.voice is not None
        assert ch.voice.id == voice.id


# ---------------------------------------------------------------------------
# Reinforcement helpers (add / run / delete)
# ---------------------------------------------------------------------------


class TestReinforcementsViaManager:
    @pytest.mark.asyncio
    async def test_add_detail_reinforcement_appends(self, scene, manager):
        make_actor(scene, "Alice")
        r = await manager.add_detail_reinforcement(
            character_name="Alice", question="mood", answer="curious"
        )
        assert isinstance(r, Reinforcement)
        assert len(scene.world_state.reinforce) == 1
        assert scene.world_state.reinforce[0].question == "mood"

    @pytest.mark.asyncio
    async def test_add_detail_reinforcement_with_no_character(self, scene, manager):
        r = await manager.add_detail_reinforcement(
            character_name=None, question="weather", answer="sunny"
        )
        assert r.character is None
        assert len(scene.world_state.reinforce) == 1

    @pytest.mark.asyncio
    async def test_delete_detail_reinforcement_removes(self, scene, manager):
        make_actor(scene, "Alice")
        await manager.add_detail_reinforcement(
            character_name="Alice", question="mood", answer="curious"
        )
        assert len(scene.world_state.reinforce) == 1

        await manager.delete_detail_reinforcement("Alice", "mood")
        assert len(scene.world_state.reinforce) == 0

    @pytest.mark.asyncio
    async def test_delete_detail_reinforcement_missing_is_noop(self, manager):
        # Nothing to delete -- should not raise
        await manager.delete_detail_reinforcement("Nobody", "nope")


# ---------------------------------------------------------------------------
# save_world_entry / set_world_entry_shared / update_context_db_entry /
# delete_context_db_entry
# ---------------------------------------------------------------------------


class TestWorldEntryCRUD:
    @pytest.mark.asyncio
    async def test_save_world_entry_creates_manual_context_and_calls_memory(
        self, scene, manager_with_memory
    ):
        manager, tracking = manager_with_memory
        await manager.save_world_entry(
            entry_id="lore.dragons", text="Dragons sleep in mountains.", meta={}
        )

        # manual_context populated
        assert "lore.dragons" in scene.world_state.manual_context
        ctx = scene.world_state.manual_context["lore.dragons"]
        assert ctx.text == "Dragons sleep in mountains."
        # Manager forces source/typ on save_world_entry
        assert ctx.meta["source"] == "manual"
        assert ctx.meta["typ"] == "world_state"

        # Memory was called
        assert len(tracking.add_many_calls) == 1
        item = tracking.add_many_calls[0][0]
        assert item["id"] == "lore.dragons"

    @pytest.mark.asyncio
    async def test_save_world_entry_with_pin_creates_active_pin(
        self, scene, manager_with_memory
    ):
        manager, _ = manager_with_memory
        await manager.save_world_entry(
            entry_id="lore.dragons", text="text", meta={}, pin=True
        )
        assert "lore.dragons" in scene.world_state.pins
        assert scene.world_state.pins["lore.dragons"].active is True

    @pytest.mark.asyncio
    async def test_set_world_entry_shared_toggles_flag(
        self, scene, manager_with_memory
    ):
        manager, _ = manager_with_memory
        await manager.save_world_entry("lore.x", "text", meta={})
        assert scene.world_state.manual_context["lore.x"].shared is False

        await manager.set_world_entry_shared("lore.x", True)
        assert scene.world_state.manual_context["lore.x"].shared is True

    @pytest.mark.asyncio
    async def test_update_context_db_entry_preserves_shared_flag(
        self, scene, manager_with_memory
    ):
        manager, _ = manager_with_memory
        scene.world_state.manual_context["x"] = ManualContext(
            id="x", text="old", meta={"source": "manual"}, shared=True
        )
        await manager.update_context_db_entry(
            "x", "new", {"source": "manual", "typ": "world_state"}
        )
        ctx = scene.world_state.manual_context["x"]
        assert ctx.text == "new"
        assert ctx.shared is True  # preserved

    @pytest.mark.asyncio
    async def test_update_context_db_entry_details_writes_to_character(
        self, scene, manager_with_memory
    ):
        manager, _ = manager_with_memory
        ch = make_actor(scene, "Alice")
        await manager.update_context_db_entry(
            "Alice.detail.mood",
            "happy",
            {"typ": "details", "character": "Alice", "detail": "mood"},
        )
        assert ch.details["mood"] == "happy"

    @pytest.mark.asyncio
    async def test_delete_context_db_entry_removes_manual_context_and_pin(
        self, scene, manager_with_memory
    ):
        manager, tracking = manager_with_memory
        await manager.save_world_entry("e1", "text", meta={}, pin=True)
        assert "e1" in scene.world_state.manual_context
        assert "e1" in scene.world_state.pins

        await manager.delete_context_db_entry("e1")

        assert "e1" not in scene.world_state.manual_context
        assert "e1" not in scene.world_state.pins
        # delete should have invoked memory.delete with the id
        assert any(call.get("ids") == "e1" for call in tracking.delete_calls)


# ---------------------------------------------------------------------------
# Pin CRUD: set_pin / remove_pin / is_pin_active
# ---------------------------------------------------------------------------


class TestPinManagement:
    @pytest.mark.asyncio
    async def test_set_pin_creates_new(self, scene, manager):
        await manager.set_pin("entry1", active=True)
        pin = scene.world_state.pins.get("entry1")
        assert pin is not None
        assert pin.active is True
        assert pin.condition is None

    @pytest.mark.asyncio
    async def test_set_pin_updates_existing(self, scene, manager):
        await manager.set_pin("entry1", active=False)
        await manager.set_pin(
            "entry1", active=True, condition="x", condition_state=True
        )
        pin = scene.world_state.pins["entry1"]
        assert pin.active is True
        assert pin.condition == "x"
        assert pin.condition_state is True

    @pytest.mark.asyncio
    async def test_set_pin_with_decay_initializes_decay_due(self, scene, manager):
        await manager.set_pin("entry1", active=True, decay=3)
        pin = scene.world_state.pins["entry1"]
        assert pin.decay == 3
        assert pin.decay_due == 3

    @pytest.mark.asyncio
    async def test_set_pin_existing_active_with_decay_initializes_decay_due(
        self, scene, manager
    ):
        # Create inactive pin first
        await manager.set_pin("entry1", active=False, decay=5)
        # Then activate — decay_due should now be initialized
        await manager.set_pin("entry1", active=True, decay=5)
        pin = scene.world_state.pins["entry1"]
        assert pin.decay_due == 5

    @pytest.mark.asyncio
    async def test_set_pin_normalises_empty_condition(self, scene, manager):
        await manager.set_pin("entry1", condition="", condition_state=True, active=True)
        pin = scene.world_state.pins["entry1"]
        assert pin.condition is None
        assert pin.condition_state is False

    @pytest.mark.asyncio
    async def test_set_pin_with_gamestate_condition(self, scene, manager):
        cg = ConditionGroup(
            conditions=[Condition(path="weather", operator="==", value="sunny")],
            operator="and",
        )
        await manager.set_pin("entry1", active=True, gamestate_condition=[cg])
        pin = scene.world_state.pins["entry1"]
        assert pin.gamestate_condition == [cg]

    @pytest.mark.asyncio
    async def test_set_pin_empty_gamestate_condition_normalises_to_none(
        self, scene, manager
    ):
        await manager.set_pin("entry1", active=True, gamestate_condition=[])
        pin = scene.world_state.pins["entry1"]
        assert pin.gamestate_condition is None

    @pytest.mark.asyncio
    async def test_remove_pin_removes_existing(self, scene, manager):
        await manager.set_pin("entry1", active=True)
        await manager.remove_pin("entry1")
        assert "entry1" not in scene.world_state.pins

    @pytest.mark.asyncio
    async def test_remove_pin_missing_is_noop(self, manager):
        await manager.remove_pin("does-not-exist")  # should not raise

    @pytest.mark.asyncio
    async def test_is_pin_active_returns_true_for_active_pin(self, scene, manager):
        await manager.set_pin("entry1", active=True)
        assert await manager.is_pin_active("entry1") is True

    @pytest.mark.asyncio
    async def test_is_pin_active_returns_false_for_inactive_pin(self, scene, manager):
        await manager.set_pin("entry1", active=False)
        assert await manager.is_pin_active("entry1") is False

    @pytest.mark.asyncio
    async def test_is_pin_active_false_when_no_pin(self, manager):
        assert await manager.is_pin_active("missing") is False


# ---------------------------------------------------------------------------
# get_pins
# ---------------------------------------------------------------------------


class TestGetPins:
    @pytest.mark.asyncio
    async def test_get_pins_filters_by_active_state(self, scene, manager_with_memory):
        manager, tracking = manager_with_memory

        # Set up two pins, one active, one not
        scene.world_state.pins["a"] = ContextPin(entry_id="a", active=True)
        scene.world_state.pins["b"] = ContextPin(entry_id="b", active=False)

        # Provide stub documents
        from _world_state_helpers import _StubDocument

        tracking.documents = {
            "a": _StubDocument(raw="text-a"),
            "b": _StubDocument(raw="text-b"),
        }

        active = await manager.get_pins(active=True)
        inactive = await manager.get_pins(active=False)
        all_pins = await manager.get_pins()

        assert set(active.pins.keys()) == {"a"}
        assert set(inactive.pins.keys()) == {"b"}
        assert set(all_pins.pins.keys()) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_get_pins_handles_missing_documents(self, scene, manager_with_memory):
        manager, tracking = manager_with_memory
        scene.world_state.pins["a"] = ContextPin(entry_id="a", active=True)
        # No documents configured
        result = await manager.get_pins(active=True)
        assert "a" in result.pins
        assert result.pins["a"].text == ""

    @pytest.mark.asyncio
    async def test_remove_all_empty_pins_removes_only_those_without_text(
        self, scene, manager_with_memory
    ):
        manager, tracking = manager_with_memory
        scene.world_state.pins["a"] = ContextPin(entry_id="a", active=True)
        scene.world_state.pins["b"] = ContextPin(entry_id="b", active=True)

        from _world_state_helpers import _StubDocument

        tracking.documents = {
            "a": _StubDocument(raw=""),  # empty -> should be removed
            "b": _StubDocument(raw="present"),
        }

        await manager.remove_all_empty_pins()

        assert "a" not in scene.world_state.pins
        assert "b" in scene.world_state.pins

    @pytest.mark.asyncio
    async def test_get_pins_evaluates_gamestate_condition(
        self, scene, manager_with_memory
    ):
        manager, tracking = manager_with_memory
        scene.game_state.set_var("weather", "sunny")

        cg = ConditionGroup(
            conditions=[Condition(path="weather", operator="==", value="sunny")],
            operator="and",
        )

        scene.world_state.pins["a"] = ContextPin(
            entry_id="a", active=False, gamestate_condition=[cg]
        )

        from _world_state_helpers import _StubDocument

        tracking.documents = {"a": _StubDocument(raw="text-a")}

        # gamestate_condition matches, so pin should be considered active even
        # though its `active` field is False.
        active = await manager.get_pins(active=True)
        assert "a" in active.pins
        assert active.pins["a"].is_active is True


# ---------------------------------------------------------------------------
# update_scene_outline / update_scene_settings
# ---------------------------------------------------------------------------


class TestSceneSettings:
    @pytest.mark.asyncio
    async def test_update_scene_outline_sets_fields(self, scene, manager):
        from talemate.scene.schema import ScenePerspectives

        await manager.update_scene_outline(
            title="My Story",
            description="An epic tale.",
            intro="Once upon a time",
            context="Fantasy world",
            perspectives=ScenePerspectives(
                default="third",
                player="first person, present tense",
            ),
        )
        assert scene.title == "My Story"
        assert scene.description == "An epic tale."
        assert scene.intro == "Once upon a time"
        assert scene.context == "Fantasy world"
        assert scene.perspectives.default == "third"
        assert scene.perspectives.player == "first person, present tense"
        assert scene.perspectives.other == ""
        assert scene.perspectives.narrator == ""

    @pytest.mark.asyncio
    async def test_update_scene_outline_perspectives_default_empty(
        self, scene, manager
    ):
        await manager.update_scene_outline(title="x")
        assert scene.perspectives.default == ""
        assert scene.perspectives.player == ""
        assert scene.perspectives.other == ""
        assert scene.perspectives.narrator == ""

    @pytest.mark.asyncio
    async def test_update_scene_settings_basic(self, scene, manager):
        await manager.update_scene_settings(
            immutable_save=True,
            experimental=True,
            writing_style_template="ws-uid",
            visual_style_template="vs-uid",
        )
        assert scene.immutable_save is True
        assert scene.experimental is True
        assert scene.writing_style_template == "ws-uid"
        assert scene.visual_style_template == "vs-uid"

    @pytest.mark.asyncio
    async def test_update_scene_settings_agent_persona_templates(self, scene, manager):
        await manager.update_scene_settings(
            agent_persona_templates={"director": "uid-1"}
        )
        assert scene.agent_persona_templates == {"director": "uid-1"}

    @pytest.mark.asyncio
    async def test_update_scene_settings_invalid_restore_from_raises(
        self, scene, manager
    ):
        # Empty save_files -> "missing.json" not in -> ValueError
        scene._save_files = []
        with pytest.raises(ValueError, match="not found"):
            await manager.update_scene_settings(restore_from="missing.json")

    @pytest.mark.asyncio
    async def test_update_scene_settings_valid_restore_from(self, scene, manager):
        scene._save_files = ["save1.json"]
        await manager.update_scene_settings(restore_from="save1.json")
        assert scene.restore_from == "save1.json"


# ---------------------------------------------------------------------------
# Suggestions: clear / add (no LLM) / get_by_id / remove / remove_proposal
# ---------------------------------------------------------------------------


class TestSuggestionsCRUD:
    @staticmethod
    def _make_suggestion(id_="sug1", proposals=None):
        return Suggestion(
            type="character",
            name="Alice",
            id=id_,
            proposals=proposals or [Call(uid="p1", name="n", arguments={})],
        )

    @pytest.mark.asyncio
    async def test_clear_suggestions(self, scene, manager):
        scene.world_state.suggestions.append(self._make_suggestion())
        await manager.clear_suggestions()
        assert scene.world_state.suggestions == []

    @pytest.mark.asyncio
    async def test_add_suggestion_appends_new(self, scene, manager):
        s = self._make_suggestion()
        await manager.add_suggestion(s)
        assert scene.world_state.suggestions == [s]

    @pytest.mark.asyncio
    async def test_add_suggestion_merges_existing(self, scene, manager):
        first = self._make_suggestion(
            proposals=[Call(uid="p1", name="n", arguments={})]
        )
        second = self._make_suggestion(
            proposals=[Call(uid="p2", name="n", arguments={})]
        )
        await manager.add_suggestion(first)
        await manager.add_suggestion(second)
        # Should remain a single suggestion with merged proposals
        assert len(scene.world_state.suggestions) == 1
        assert {p.uid for p in scene.world_state.suggestions[0].proposals} == {
            "p1",
            "p2",
        }

    @pytest.mark.asyncio
    async def test_get_suggestion_by_id_known(self, scene, manager):
        s = self._make_suggestion()
        scene.world_state.suggestions.append(s)
        found = await manager.get_suggestion_by_id("sug1")
        assert found is s

    @pytest.mark.asyncio
    async def test_get_suggestion_by_id_unknown(self, scene, manager):
        result = await manager.get_suggestion_by_id("nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_remove_suggestion_by_object(self, scene, manager):
        s = self._make_suggestion()
        scene.world_state.suggestions.append(s)
        await manager.remove_suggestion(s)
        assert scene.world_state.suggestions == []

    @pytest.mark.asyncio
    async def test_remove_suggestion_by_id(self, scene, manager):
        s = self._make_suggestion()
        scene.world_state.suggestions.append(s)
        await manager.remove_suggestion("sug1")
        assert scene.world_state.suggestions == []

    @pytest.mark.asyncio
    async def test_remove_suggestion_missing_is_noop(self, manager):
        await manager.remove_suggestion("nope")  # no raise

    @pytest.mark.asyncio
    async def test_remove_suggestion_proposal_removes_one(self, scene, manager):
        s = self._make_suggestion(
            proposals=[
                Call(uid="p1", name="n", arguments={}),
                Call(uid="p2", name="n", arguments={}),
            ]
        )
        scene.world_state.suggestions.append(s)
        await manager.remove_suggestion_proposal("sug1", "p1")
        # Suggestion still present, but only p2 remains
        assert len(scene.world_state.suggestions) == 1
        remaining = scene.world_state.suggestions[0].proposals
        assert {p.uid for p in remaining} == {"p2"}

    @pytest.mark.asyncio
    async def test_remove_last_proposal_removes_suggestion(self, scene, manager):
        s = self._make_suggestion()  # has only 1 proposal
        scene.world_state.suggestions.append(s)
        await manager.remove_suggestion_proposal("sug1", "p1")
        # suggestion should now be removed entirely
        assert scene.world_state.suggestions == []


# ---------------------------------------------------------------------------
# Activate/deactivate character
# ---------------------------------------------------------------------------


class TestActivateDeactivateCharacter:
    @pytest.mark.asyncio
    async def test_deactivate_then_activate_roundtrip(self, scene, manager_with_memory):
        manager, _ = manager_with_memory
        ch = make_actor(scene, "Alice")
        # Plug an agent with a `connect` method on actor for activate path
        from talemate.instance import get_agent

        ch.agent = get_agent("conversation")

        # Deactivate
        await manager.deactivate_character("Alice")
        assert "Alice" not in scene.active_characters
        assert "Alice" in scene.character_data  # still present in inactive

        # Reactivate
        await manager.activate_character("Alice")
        assert "Alice" in scene.active_characters


# ---------------------------------------------------------------------------
# Templates: save / remove (no auto-create)
# ---------------------------------------------------------------------------


class TestManagerTemplateGroupCRUD:
    """Use the manager's template_collection (mounted on scene)."""

    @pytest.mark.asyncio
    async def test_save_template_group_appends_new(self, scene, manager, tmp_path):
        from talemate.world_state.templates.base import Group

        # Inject empty collection so we don't depend on real disk
        scene._world_state_templates = type(manager.template_collection)(groups=[])
        group = Group(author="me", name="g1", description="x", uid="g1-uid")
        # Pre-set path so save() writes to tmp_path instead of the project dir
        group.path = str(tmp_path / "g1.yaml")

        await manager.save_template_group(group)
        assert manager.template_collection.find("g1-uid") is not None
        # The file was written
        import os

        assert os.path.exists(group.path)

    @pytest.mark.asyncio
    async def test_save_template_group_update_existing(self, scene, manager, tmp_path):
        from talemate.world_state.templates.base import Group

        existing = Group(
            author="orig",
            name="g1",
            description="orig",
            uid="g1-uid",
            path=str(tmp_path / "g1.yaml"),
        )
        # Make sure the file exists (update calls save())
        existing.save(str(tmp_path))
        scene._world_state_templates = type(manager.template_collection)(
            groups=[existing]
        )
        replacement = Group(
            author="new",
            name="g1-new",
            description="updated",
            uid="g1-uid",
        )

        await manager.save_template_group(replacement)
        # The existing group's metadata should be updated in-place
        assert existing.name == "g1-new"
        assert existing.description == "updated"
        # Same uid still in collection
        assert manager.template_collection.find("g1-uid") is existing

    @pytest.mark.asyncio
    async def test_get_templates_returns_typed_collection(self, scene, manager):
        from talemate.world_state.templates.base import Group
        from talemate.world_state.templates.state_reinforcement import (
            StateReinforcement,
        )

        sr = StateReinforcement(
            name="t1", template_type="state_reinforcement", query="q"
        )
        group = Group(
            author="x",
            name="g1",
            description="d",
            templates={sr.uid: sr},
            uid="g1-uid",
        )
        scene._world_state_templates = type(manager.template_collection)(groups=[group])

        typed = await manager.get_templates(types=["state_reinforcement"])
        assert "state_reinforcement" in typed.templates
        assert len(typed.templates["state_reinforcement"]) == 1

    @pytest.mark.asyncio
    async def test_remove_template_group_removes_from_collection(
        self, scene, manager, tmp_path
    ):
        from talemate.world_state.templates.base import Collection, Group

        g = Group(author="x", name="g1", description="d", uid="g1-uid")
        g.path = str(tmp_path / "g1.yaml")
        g.save(str(tmp_path))

        scene._world_state_templates = Collection(groups=[g])
        await manager.remove_template_group(g)
        assert manager.template_collection.find("g1-uid") is None

    @pytest.mark.asyncio
    async def test_save_template_inserts_new_template(self, scene, manager, tmp_path):
        from talemate.world_state.templates.base import Collection, Group
        from talemate.world_state.templates.state_reinforcement import (
            StateReinforcement,
        )

        g = Group(author="x", name="g1", description="d", uid="g1-uid")
        g.path = str(tmp_path / "g1.yaml")
        g.save(str(tmp_path))

        scene._world_state_templates = Collection(groups=[g])

        sr = StateReinforcement(
            name="t",
            template_type="state_reinforcement",
            query="q",
            group="g1-uid",
        )
        await manager.save_template(sr)
        # The template now exists in the group
        assert g.find(sr.uid) is sr

    @pytest.mark.asyncio
    async def test_remove_template(self, scene, manager, tmp_path):
        from talemate.world_state.templates.base import Collection, Group
        from talemate.world_state.templates.state_reinforcement import (
            StateReinforcement,
        )

        sr = StateReinforcement(
            name="t",
            template_type="state_reinforcement",
            query="q",
            group="g1-uid",
        )
        g = Group(
            author="x",
            name="g1",
            description="d",
            uid="g1-uid",
            templates={sr.uid: sr},
        )
        g.path = str(tmp_path / "g1.yaml")
        g.save(str(tmp_path))

        scene._world_state_templates = Collection(groups=[g])
        await manager.remove_template(sr)
        assert g.find(sr.uid) is None


# ---------------------------------------------------------------------------
# get_context_db_entries
# ---------------------------------------------------------------------------


class TestGetContextDBEntries:
    @pytest.mark.asyncio
    async def test_id_query_uses_get_document(self, scene, manager_with_memory):
        from _world_state_helpers import _StubDocument

        manager, tracking = manager_with_memory
        tracking.documents = {
            "abc": _StubDocument(raw="hello", meta={"k": "v"}, id="abc"),
        }

        result = await manager.get_context_db_entries("id:abc")
        assert isinstance(result, ContextDB)
        assert len(result.entries) == 1
        assert result.entries[0].text == "hello"
        assert result.entries[0].meta == {"k": "v"}
        assert result.entries[0].id == "abc"

    @pytest.mark.asyncio
    async def test_text_query_uses_multi_query(self, scene, manager_with_memory):
        from _world_state_helpers import _StubDocument

        manager, tracking = manager_with_memory
        tracking._multi_query_result = [
            _StubDocument(raw="r1", meta={}, id="i1"),
            _StubDocument(raw="r2", meta={}, id="i2"),
        ]
        result = await manager.get_context_db_entries("dragon")
        assert len(result.entries) == 2
        assert {e.id for e in result.entries} == {"i1", "i2"}


# ---------------------------------------------------------------------------
# auto_apply_template / apply_template type dispatch
# ---------------------------------------------------------------------------


class TestApplyTemplateDispatch:
    @pytest.mark.asyncio
    async def test_auto_apply_unsupported_template_logs_and_returns(
        self, scene, manager
    ):
        # Build an object with a fake template_type — manager should log and
        # return None without raising.
        from talemate.world_state.templates.base import Template

        class Fake(Template):
            template_type: str = "no_such_type"

        # Bypass registry validation: the registry only matters for typed
        # collections, not for direct dispatch.
        result = await manager.auto_apply_template(Fake(name="x"))
        assert result is None

    @pytest.mark.asyncio
    async def test_apply_template_unsupported_returns_none(self, scene, manager):
        from talemate.world_state.templates.base import Template

        class Fake(Template):
            template_type: str = "no_such_type"

        result = await manager.apply_template(Fake(name="x"))
        assert result is None
