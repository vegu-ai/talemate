"""
Unit tests for `talemate.world_state.__init__`.

Covers the pure pydantic models and helper methods on `WorldState`,
`Reinforcement`, `Suggestion`, `ContextPin`, `ManualContext`. The async
methods that simply mutate state are also exercised.

Tests use real `MockScene` + bootstrapped agents; they do NOT mock the
function under test.
"""

import pytest

from _world_state_helpers import (
    install_tracking_memory,
    make_actor,
    manager,  # noqa: F401 - pytest fixture
    manager_with_memory,  # noqa: F401 - pytest fixture
    scene,  # noqa: F401 - pytest fixture
    scene_with_memory,  # noqa: F401 - pytest fixture
    world_state,  # noqa: F401 - pytest fixture
)
from talemate.game.focal.schema import Call
from talemate.world_state import (
    ANY_CHARACTER,
    CharacterState,
    ContextPin,
    InsertionMode,
    ManualContext,
    ObjectState,
    Reinforcement,
    Suggestion,
    WorldState,
)


# ---------------------------------------------------------------------------
# Reinforcement.as_context_line
# ---------------------------------------------------------------------------


class TestReinforcementAsContextLine:
    def test_question_with_question_mark_no_character(self):
        r = Reinforcement(question="What is the weather?", answer="Sunny.")
        assert r.as_context_line == "What is the weather? Sunny."

    def test_question_with_question_mark_with_character(self):
        r = Reinforcement(
            question="What is the weather?", answer="Sunny.", character="Alice"
        )
        assert r.as_context_line == "Alice: What is the weather? Sunny."

    def test_statement_no_character(self):
        r = Reinforcement(question="weather", answer="sunny")
        assert r.as_context_line == "weather: sunny"

    def test_statement_with_character(self):
        r = Reinforcement(question="mood", answer="happy", character="Alice")
        assert r.as_context_line == "Alice's mood: happy"

    def test_question_with_trailing_whitespace_still_treated_as_question(self):
        r = Reinforcement(question="What time?  ", answer="3pm")
        # strip().endswith("?") is true for "What time?  "
        assert r.as_context_line == "What time?   3pm"


# ---------------------------------------------------------------------------
# WorldState.normalize_name
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_normalize_underscore_name(self):
        ws = WorldState()
        assert ws.normalize_name("john_doe") == "John Doe"

    def test_normalize_preserves_possessive_lowercase_s(self):
        """title() converts 's to 'S; we expect the regex fix-up."""
        ws = WorldState()
        assert ws.normalize_name("john's hat") == "John's Hat"

    def test_normalize_strips_whitespace(self):
        ws = WorldState()
        assert ws.normalize_name("  alice  ") == "Alice"

    def test_normalize_already_titled(self):
        ws = WorldState()
        assert ws.normalize_name("Bob") == "Bob"


# ---------------------------------------------------------------------------
# WorldState.filter_reinforcements
# ---------------------------------------------------------------------------


class TestFilterReinforcements:
    def _ws(self) -> WorldState:
        ws = WorldState()
        ws.reinforce = [
            Reinforcement(
                question="q1", answer="a1", character="Alice", insert="sequential"
            ),
            Reinforcement(
                question="q2",
                answer="a2",
                character="Alice",
                insert="conversation-context",
            ),
            Reinforcement(
                question="q3", answer="a3", character=None, insert="sequential"
            ),
            Reinforcement(
                question="q4", answer=None, character="Bob", insert="sequential"
            ),
        ]
        return ws

    def test_skips_reinforcement_with_no_answer(self):
        ws = self._ws()
        results = ws.filter_reinforcements()
        questions = [r.question for r in results]
        # q4 has answer=None so it must be excluded
        assert "q4" not in questions

    def test_default_returns_all_with_answer(self):
        ws = self._ws()
        results = ws.filter_reinforcements()
        assert {r.question for r in results} == {"q1", "q2", "q3"}

    def test_filter_by_character(self):
        ws = self._ws()
        results = ws.filter_reinforcements(character="Alice")
        assert {r.question for r in results} == {"q1", "q2"}

    def test_filter_by_none_character(self):
        ws = self._ws()
        results = ws.filter_reinforcements(character=None)
        # character=None filters to those whose character is None
        assert {r.question for r in results} == {"q3"}

    def test_filter_by_insert(self):
        ws = self._ws()
        results = ws.filter_reinforcements(insert=["sequential"])
        assert {r.question for r in results} == {"q1", "q3"}

    def test_filter_by_character_and_insert(self):
        ws = self._ws()
        results = ws.filter_reinforcements(
            character="Alice", insert=["conversation-context"]
        )
        assert {r.question for r in results} == {"q2"}

    def test_any_character_constant_includes_all(self):
        ws = self._ws()
        results = ws.filter_reinforcements(character=ANY_CHARACTER)
        # Should match both Alice's, world's; q4 still skipped (no answer)
        assert {r.question for r in results} == {"q1", "q2", "q3"}


# ---------------------------------------------------------------------------
# WorldState.reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_characters_items_location(self):
        ws = WorldState()
        ws.characters = {"Alice": CharacterState(snapshot="x", emotion="happy")}
        ws.items = {"key": ObjectState(snapshot="rusty")}
        ws.location = "library"
        # reinforce / pins / manual_context should NOT be reset
        ws.reinforce = [Reinforcement(question="q", answer="a")]

        ws.reset()

        assert ws.characters == {}
        assert ws.items == {}
        assert ws.location is None
        # reset only resets these three; others remain
        assert len(ws.reinforce) == 1


# ---------------------------------------------------------------------------
# WorldState.reinforcements_for_character / world / manual_context_for_world
# ---------------------------------------------------------------------------


class TestReinforcementGroups:
    def _ws(self) -> WorldState:
        ws = WorldState()
        ws.reinforce = [
            Reinforcement(question="qA1", answer="x", character="Alice"),
            Reinforcement(question="qA2", answer="y", character="Alice"),
            Reinforcement(question="qB", answer="z", character="Bob"),
            Reinforcement(question="qWorld", answer="w", character=None),
        ]
        return ws

    def test_reinforcements_for_character(self):
        ws = self._ws()
        results = ws.reinforcements_for_character("Alice")
        assert set(results.keys()) == {"qA1", "qA2"}
        assert all(r.character == "Alice" for r in results.values())

    def test_reinforcements_for_character_unknown_returns_empty(self):
        ws = self._ws()
        assert ws.reinforcements_for_character("Nobody") == {}

    def test_reinforcements_for_world(self):
        ws = self._ws()
        results = ws.reinforcements_for_world()
        assert set(results.keys()) == {"qWorld"}

    def test_manual_context_for_world_filters_by_typ(self):
        ws = WorldState()
        ws.manual_context["w1"] = ManualContext(
            id="w1", text="t1", meta={"typ": "world_state"}
        )
        ws.manual_context["d1"] = ManualContext(
            id="d1", text="t2", meta={"typ": "details"}
        )
        ws.manual_context["x"] = ManualContext(id="x", text="t3", meta={})

        result = ws.manual_context_for_world()
        assert set(result.keys()) == {"w1"}


# ---------------------------------------------------------------------------
# WorldState.character_emotion
# ---------------------------------------------------------------------------


class TestCharacterEmotion:
    def test_returns_emotion_when_character_exists(self):
        ws = WorldState()
        ws.characters = {"Alice": CharacterState(emotion="elated")}
        assert ws.character_emotion("Alice") == "elated"

    def test_returns_none_when_character_missing(self):
        ws = WorldState()
        assert ws.character_emotion("Ghost") is None


# ---------------------------------------------------------------------------
# Suggestion model
# ---------------------------------------------------------------------------


class TestSuggestion:
    @staticmethod
    def _proposal(uid: str, name: str = "n") -> Call:
        return Call(uid=uid, name=name, arguments={})

    def test_remove_proposal(self):
        s = Suggestion(
            type="character",
            name="Alice",
            id="sug1",
            proposals=[self._proposal("a"), self._proposal("b")],
        )
        s.remove_proposal("a")
        assert [p.uid for p in s.proposals] == ["b"]

    def test_remove_proposal_unknown_is_noop(self):
        s = Suggestion(
            type="character",
            name="Alice",
            id="sug1",
            proposals=[self._proposal("a")],
        )
        s.remove_proposal("does-not-exist")
        assert [p.uid for p in s.proposals] == ["a"]

    def test_merge_appends_new_proposal(self):
        s1 = Suggestion(
            type="character", name="Alice", id="sug1", proposals=[self._proposal("a")]
        )
        s2 = Suggestion(
            type="character", name="Alice", id="sug1", proposals=[self._proposal("b")]
        )
        s1.merge(s2)
        assert [p.uid for p in s1.proposals] == ["a", "b"]

    def test_merge_overrides_matching_proposal(self):
        first = self._proposal("a", name="old")
        replacement = self._proposal("a", name="new")
        s1 = Suggestion(type="character", name="Alice", id="sug1", proposals=[first])
        s2 = Suggestion(
            type="character", name="Alice", id="sug1", proposals=[replacement]
        )
        s1.merge(s2)
        assert len(s1.proposals) == 1
        assert s1.proposals[0].name == "new"

    def test_merge_assert_id_match(self):
        s1 = Suggestion(type="character", name="Alice", id="sug1", proposals=[])
        s2 = Suggestion(type="character", name="Alice", id="sug2", proposals=[])
        with pytest.raises(AssertionError):
            s1.merge(s2)


# ---------------------------------------------------------------------------
# WorldState.add_reinforcement (existing-update branch coverage)
# ---------------------------------------------------------------------------


class TestAddReinforcementUpdates:
    @pytest.mark.asyncio
    async def test_creating_world_reinforcement_appends(self, world_state):
        r = await world_state.add_reinforcement(
            question="What is the weather?", answer="sunny"
        )
        assert len(world_state.reinforce) == 1
        assert world_state.reinforce[0] is r

    @pytest.mark.asyncio
    async def test_updating_existing_world_reinforcement_in_place(self, world_state):
        r1 = await world_state.add_reinforcement(question="q", answer="a", interval=5)
        r2 = await world_state.add_reinforcement(question="q", answer="b", interval=12)
        # Same object updated, not a duplicate
        assert r1 is r2
        assert len(world_state.reinforce) == 1
        assert r2.answer == "b"
        assert r2.interval == 12

    @pytest.mark.asyncio
    async def test_change_insert_method_from_other_to_sequential_resets_due(
        self, world_state
    ):
        r = await world_state.add_reinforcement(
            question="q", answer="a", insert="conversation-context"
        )
        r.due = 7  # simulate countdown
        # Switch to sequential -> due should be reset to 0 to run next loop
        await world_state.add_reinforcement(
            question="q", answer="a", insert="sequential"
        )
        assert r.due == 0
        assert r.insert == "sequential"

    @pytest.mark.asyncio
    async def test_update_character_reinforcement_sets_detail(self, scene):
        """When the reinforcement is character-bound, updating it should also
        write the answer to the character's detail map."""
        character = make_actor(scene, "Alice")
        install_tracking_memory(scene)  # avoid memory side effects

        ws = scene.world_state
        await ws.add_reinforcement(
            question="What is Alice's mood?", character="Alice", answer="curious"
        )
        # update the existing reinforcement - this should also call set_detail
        await ws.add_reinforcement(
            question="What is Alice's mood?", character="Alice", answer="happy"
        )
        assert character.get_detail("What is Alice's mood?") == "happy"


# ---------------------------------------------------------------------------
# WorldState.find_reinforcement
# ---------------------------------------------------------------------------


class TestFindReinforcement:
    @pytest.mark.asyncio
    async def test_finds_existing(self, world_state):
        await world_state.add_reinforcement(question="q", answer="a", character="Alice")
        idx, r = await world_state.find_reinforcement("q", "Alice")
        assert idx == 0
        assert r is not None
        assert r.character == "Alice"

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, world_state):
        idx, r = await world_state.find_reinforcement("nope", "Alice")
        assert idx is None
        assert r is None

    @pytest.mark.asyncio
    async def test_distinguishes_character_vs_world(self, world_state):
        await world_state.add_reinforcement(question="q", answer="a", character="Alice")
        await world_state.add_reinforcement(question="q", answer="b", character=None)
        idx_alice, r_alice = await world_state.find_reinforcement("q", "Alice")
        idx_world, r_world = await world_state.find_reinforcement("q", None)
        assert r_alice.answer == "a"
        assert r_world.answer == "b"
        assert idx_alice != idx_world


# ---------------------------------------------------------------------------
# WorldState.commit_to_memory
# ---------------------------------------------------------------------------


class TestCommitToMemory:
    @pytest.mark.asyncio
    async def test_commit_to_memory_strips_complex_meta_values(self, scene_with_memory):
        scene, tracking = scene_with_memory
        ws = scene.world_state
        ws.manual_context["a"] = ManualContext(
            id="a",
            text="text-a",
            meta={
                "source": "manual",
                "typ": "world_state",
                "complex": {"nested": "dict"},  # should be filtered out
                "list": [1, 2, 3],  # should be filtered out
                "count": 1,
                "flag": True,
                "ratio": 0.5,
            },
        )

        await ws.commit_to_memory(tracking)

        assert len(tracking.add_many_calls) == 1
        items = tracking.add_many_calls[0]
        assert len(items) == 1
        meta = items[0]["meta"]
        # Only simple-typed values survive
        assert "complex" not in meta
        assert "list" not in meta
        assert meta["count"] == 1
        assert meta["flag"] is True
        assert meta["ratio"] == 0.5
        assert meta["source"] == "manual"

    @pytest.mark.asyncio
    async def test_commit_to_memory_passes_all_entries(self, scene_with_memory):
        scene, tracking = scene_with_memory
        ws = scene.world_state
        ws.manual_context["a"] = ManualContext(id="a", text="t1")
        ws.manual_context["b"] = ManualContext(id="b", text="t2")

        await ws.commit_to_memory(tracking)

        assert len(tracking.add_many_calls) == 1
        items = tracking.add_many_calls[0]
        ids = sorted([i["id"] for i in items])
        assert ids == ["a", "b"]


# ---------------------------------------------------------------------------
# WorldState.persist
# ---------------------------------------------------------------------------


class TestPersist:
    @pytest.mark.asyncio
    async def test_persist_no_chars_no_items_does_not_call_memory(
        self, scene_with_memory
    ):
        scene, tracking = scene_with_memory
        await scene.world_state.persist()
        assert tracking.add_many_calls == []

    @pytest.mark.asyncio
    async def test_persist_emits_one_state_per_character_and_item(
        self, scene_with_memory
    ):
        scene, tracking = scene_with_memory
        ws = scene.world_state
        ws.characters = {"Alice": CharacterState(snapshot="standing", emotion="calm")}
        ws.items = {"Sword": ObjectState(snapshot="sheathed")}

        await ws.persist()

        assert len(tracking.add_many_calls) == 1
        items = tracking.add_many_calls[0]
        ids = sorted(i["id"] for i in items)
        assert ids == ["Alice.world_state.snapshot", "Sword.world_state.snapshot"]

        # Snapshots are concatenated into the text
        text_by_id = {i["id"]: i["text"] for i in items}
        assert "standing" in text_by_id["Alice.world_state.snapshot"]
        assert "sheathed" in text_by_id["Sword.world_state.snapshot"]


# ---------------------------------------------------------------------------
# WorldState.render -- jinja2 template rendering
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    """Verifies the world-state render Jinja2 template produces meaningful
    structure for the data we feed it. This isn't a baseline snapshot;
    it asserts the load-bearing structure (markers and expected fields)."""

    def test_render_with_characters_and_items(self):
        ws = WorldState()
        ws.characters = {"Alice": CharacterState(snapshot="standing", emotion="calm")}
        ws.items = {"Sword": ObjectState(snapshot="sheathed")}
        ws.location = "Library"

        rendered = str(ws.render())
        assert "[world state]" in rendered
        assert "[end of world state]" in rendered
        assert "Name: Alice" in rendered
        assert "Emotion: calm" in rendered
        assert "Snapshot: standing" in rendered
        assert "Name: Sword" in rendered
        assert "Snapshot: sheathed" in rendered

    def test_render_empty(self):
        ws = WorldState()
        rendered = str(ws.render())
        assert "[world state]" in rendered
        assert "[end of world state]" in rendered

    def test_as_list_returns_lines_after_render(self):
        ws = WorldState()
        ws.characters = {"Alice": CharacterState(snapshot="x", emotion="y")}
        prompt = ws.render()
        # Need to actually render the template before .as_list is populated.
        prompt.render()
        lines = prompt.as_list
        assert any("Name: Alice" in line for line in lines)

    def test_world_state_as_list_property_renders(self):
        ws = WorldState()
        ws.characters = {"Alice": CharacterState(snapshot="x", emotion="y")}
        # Property short-cut: WorldState.as_list directly returns rendered list
        # (this can return empty string if prompt isn't rendered—we just verify
        # accessing the property doesn't crash.)
        result = ws.as_list
        # Either a list (after render) or empty string (before render)
        assert isinstance(result, (list, str))


# ---------------------------------------------------------------------------
# InsertionMode enum
# ---------------------------------------------------------------------------


class TestInsertionMode:
    def test_enum_values(self):
        assert InsertionMode.sequential.value == "sequential"
        assert InsertionMode.conversation_context.value == "conversation-context"
        assert InsertionMode.all_context.value == "all-context"
        assert InsertionMode.never.value == "never"

    def test_enum_is_string(self):
        assert InsertionMode.sequential == "sequential"


# ---------------------------------------------------------------------------
# ContextPin defaults / construction
# ---------------------------------------------------------------------------


class TestContextPinModel:
    def test_default_values(self):
        pin = ContextPin(entry_id="x")
        assert pin.entry_id == "x"
        assert pin.condition is None
        assert pin.condition_state is False
        assert pin.gamestate_condition is None
        assert pin.active is False
        assert pin.decay is None
        assert pin.decay_due is None

    def test_with_decay(self):
        pin = ContextPin(entry_id="x", decay=5, active=True, decay_due=5)
        assert pin.decay == 5
        assert pin.decay_due == 5


class TestRequestUpdatePreservesSnapshotOnPartialPatch:
    """Repro: durable on, characters exist, names match, the next pass returns
    only `emotion` + `mentions` (snapshot key omitted). The prior snapshot must
    be carried forward, not wiped."""

    @pytest.mark.asyncio
    async def test_omitted_snapshot_is_preserved(self, world_state):
        import talemate.instance as instance
        from talemate.world_state import WorldStateResponse

        agent = instance.get_agent("world_state")
        assert agent.update_world_state_durable_snapshot is True

        world_state.characters = {
            "Elena": CharacterState(
                snapshot="kneeling by the dying fire",
                emotion="calm",
                mentions=["Elena"],
            ),
            "Hero": CharacterState(
                snapshot="sword still drawn", emotion="tense", mentions=["Hero"]
            ),
        }

        async def fake_request_world_state():
            return WorldStateResponse(
                world_state={
                    "characters": {
                        "Elena": {"emotion": "anxious", "mentions": ["Elena"]},
                        "Hero": {"emotion": "resolute", "mentions": ["Hero"]},
                    },
                    "items": {},
                    "places": {},
                    "location": None,
                },
                anchor_message_ids=[],
            )

        agent.request_world_state = fake_request_world_state
        await world_state.request_update()

        # Emotion updated...
        assert world_state.characters["Elena"].emotion == "anxious"
        assert world_state.characters["Hero"].emotion == "resolute"
        # ...snapshot carried forward, NOT wiped.
        assert world_state.characters["Elena"].snapshot == "kneeling by the dying fire"
        assert world_state.characters["Hero"].snapshot == "sword still drawn"
