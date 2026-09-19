"""
The knowledge bucket predicate: presence, ownership, common lore, visibility,
grant and revoke edges.
"""

import pytest

from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.knowledge.bucket import KnowledgeIndex, KnowledgeItem, knowledge_digest
from talemate.knowledge.schema import EntryVisibility, KnowledgeEdge
from talemate.scene_message import CharacterMessage
from talemate.world_state import ManualContext, WorldState


def doc(id, meta, text="x"):
    return MemoryDocument(text, meta, id, text)


@pytest.fixture
def index():
    return KnowledgeIndex(grants=set(), revokes=set())


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


class TestModels:
    def test_visibility_default_everyone(self):
        v = EntryVisibility()
        assert v.allows("Alice", owner="Bob")

    def test_visibility_owner_only(self):
        v = EntryVisibility(mode="owner")
        assert v.allows("Bob", owner="Bob")
        assert not v.allows("Alice", owner="Bob")

    def test_visibility_list(self):
        v = EntryVisibility(mode="list", characters=["Carol"])
        assert v.allows("Carol", owner="Bob")
        assert v.allows("Bob", owner="Bob")
        assert not v.allows("Alice", owner="Bob")

    def test_character_visibility_round_trip(self):
        c = Character(
            name="Bob", visibility={"detail.secret": EntryVisibility(mode="owner")}
        )
        dumped = c.model_dump()
        assert dumped["visibility"]["detail.secret"]["mode"] == "owner"
        assert Character(**dumped).visibility["detail.secret"].mode == "owner"

    def test_legacy_character_loads_without_visibility(self):
        c = Character(name="Bob", base_attributes={"age": "40"})
        assert c.visibility == {}

    def test_world_state_edges_round_trip(self):
        ws = WorldState(
            knowledge=[KnowledgeEdge(character="Alice", target="F1", kind="grant")]
        )
        loaded = WorldState(**ws.model_dump())
        assert loaded.knowledge[0].target == "F1"
        assert loaded.knowledge[0].source == "manual"
        assert loaded.knowledge[0].message_id is None
        assert loaded.knowledge[0].id

    def test_manual_context_visibility_default(self):
        entry = ManualContext(id="w1", text="lore")
        assert entry.visibility.mode == "everyone"
        assert ManualContext(**entry.model_dump()).visibility.mode == "everyone"


# ---------------------------------------------------------------------------
# predicate
# ---------------------------------------------------------------------------


class TestInBucket:
    def test_present_history(self, index):
        item = KnowledgeItem(id="e1", kind="history", present=["Alice", "Bob"])
        assert index.in_bucket("Alice", item)
        assert not index.in_bucket("Carol", item)

    def test_unknown_presence_is_known_to_everyone(self, index):
        item = KnowledgeItem(id="e1", kind="history", present=None)
        assert index.in_bucket("Carol", item)

    def test_empty_presence_is_known_to_nobody(self, index):
        item = KnowledgeItem(id="e1", kind="history", present=[])
        assert not index.in_bucket("Carol", item)

    def test_owner_always_knows(self, index):
        item = KnowledgeItem(
            id="Bob.detail.secret",
            kind="detail",
            owner="Bob",
            visibility=EntryVisibility(mode="owner"),
        )
        assert index.in_bucket("Bob", item)
        assert not index.in_bucket("Alice", item)

    def test_common_lore_by_default(self, index):
        for kind in ("attribute", "detail", "description", "world_entry", "static"):
            item = KnowledgeItem(id=kind, kind=kind, owner="Bob")
            assert index.in_bucket("Alice", item), kind

    def test_grant_overrides_absence_and_visibility(self):
        index = KnowledgeIndex(
            grants={("Alice", "F1"), ("Alice", "Bob.detail.secret")},
            revokes=set(),
        )
        assert index.in_bucket(
            "Alice", KnowledgeItem(id="F1", kind="history", present=["Bob"])
        )
        assert index.in_bucket(
            "Alice",
            KnowledgeItem(
                id="Bob.detail.secret",
                kind="detail",
                owner="Bob",
                visibility=EntryVisibility(mode="owner"),
            ),
        )

    def test_revoke_beats_everything(self):
        index = KnowledgeIndex(
            grants={("Alice", "F1")},
            revokes={("Alice", "F1"), ("Bob", "Bob.age")},
        )
        assert not index.in_bucket(
            "Alice", KnowledgeItem(id="F1", kind="history", present=["Alice"])
        )
        # even the owner, when a revoke names them
        assert not index.in_bucket(
            "Bob", KnowledgeItem(id="Bob.age", kind="attribute", owner="Bob")
        )

    def test_from_scene_reads_edges(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="F1", kind="grant"),
            KnowledgeEdge(character="Alice", target="F2", kind="revoke"),
        ]
        index = KnowledgeIndex.from_scene(scene)
        assert index.granted("Alice", "F1")
        assert index.revoked("Alice", "F2")
        assert not index.granted("Bob", "F1")


# ---------------------------------------------------------------------------
# item construction
# ---------------------------------------------------------------------------


class TestKnowledgeItem:
    def test_from_message(self):
        msg = CharacterMessage(message="Bob: hi", present=["Bob"])
        item = KnowledgeItem.from_message(msg)
        assert item.kind == "history" and item.present == ["Bob"]

    def test_from_archive_entry(self):
        assert (
            KnowledgeItem.from_archive_entry({"id": "s1", "text": "x", "ts": 0}).kind
            == "static"
        )
        item = KnowledgeItem.from_archive_entry(
            {"id": "e1", "text": "x", "ts": 0, "start": 0, "end": 2, "present": ["Bob"]}
        )
        assert item.kind == "history" and item.present == ["Bob"]

    def test_history_document(self, scene):
        item = KnowledgeItem.from_memory_document(
            doc("e1", {"typ": "history", "presence_known": True, "present": '["Bob"]'}),
            scene,
        )
        assert item.kind == "history" and item.present == ["Bob"]

    def test_history_document_unknown_presence(self, scene):
        item = KnowledgeItem.from_memory_document(
            doc("e1", {"typ": "history", "presence_known": False}), scene
        )
        assert item.present is None

    def test_sheet_documents_carry_visibility(self, scene):
        bob = Character(
            name="Bob",
            base_attributes={"age": "40"},
            details={"secret": "x"},
            visibility={
                "detail.secret": EntryVisibility(mode="owner"),
                "age": EntryVisibility(mode="list", characters=["Carol"]),
            },
        )
        scene.character_data["Bob"] = bob
        detail = KnowledgeItem.from_memory_document(
            doc(
                "Bob.detail.secret",
                {"typ": "details", "character": "Bob", "detail": "secret"},
            ),
            scene,
        )
        assert detail.kind == "detail" and detail.owner == "Bob"
        assert detail.visibility.mode == "owner"
        attr = KnowledgeItem.from_memory_document(
            doc(
                "Bob.age", {"typ": "base_attribute", "character": "Bob", "attr": "age"}
            ),
            scene,
        )
        assert attr.kind == "attribute" and attr.visibility.characters == ["Carol"]
        desc = KnowledgeItem.from_memory_document(
            doc("Bob.description", {"typ": "description", "character": "Bob"}), scene
        )
        assert desc.kind == "description" and desc.visibility is None

    def test_world_entry_document(self, scene):
        scene.world_state.manual_context["w1"] = ManualContext(
            id="w1",
            text="lore",
            visibility=EntryVisibility(mode="list", characters=["Bob"]),
        )
        item = KnowledgeItem.from_memory_document(
            doc("w1", {"typ": "world_state", "source": "manual"}), scene
        )
        assert item.kind == "world_entry" and item.visibility.characters == ["Bob"]

    def test_unclassified_document_is_shared(self, scene):
        item = KnowledgeItem.from_memory_document(
            doc("z", {"typ": "something_else"}), scene
        )
        assert item.kind == "world_entry" and item.visibility is None

    def test_retrieval_filter(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="e2", kind="grant")
        ]
        index = KnowledgeIndex.from_scene(scene)
        keep = index.retrieval_filter(scene, "Alice")
        seen = doc(
            "e1", {"typ": "history", "presence_known": True, "present": '["Alice"]'}
        )
        missed = doc(
            "e3", {"typ": "history", "presence_known": True, "present": '["Bob"]'}
        )
        told = doc(
            "e2", {"typ": "history", "presence_known": True, "present": '["Bob"]'}
        )
        assert keep(seen) and keep(told) and not keep(missed)


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


class TestRename:
    def test_rename_follows_every_reference(self, scene):
        from talemate.context import ActiveScene

        bob = Character(name="Bob", details={"secret": "x"})
        carol = Character(
            name="Carol",
            details={"plan": "y"},
            visibility={
                "detail.plan": EntryVisibility(mode="list", characters=["Bob"])
            },
        )
        scene.character_data = {"Bob": bob, "Carol": carol}
        scene.active_characters = ["Bob", "Carol"]
        scene.history = [CharacterMessage(message="Bob: hi", present=["Bob", "Carol"])]
        scene.archived_history = [
            {"text": "x", "ts": 0, "start": 0, "end": 0, "id": "e1", "present": ["Bob"]}
        ]
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Bob", target="F1", kind="grant"),
            KnowledgeEdge(character="Carol", target="Bob.detail.secret", kind="revoke"),
        ]
        scene.world_state.manual_context["w1"] = ManualContext(
            id="w1",
            text="lore",
            visibility=EntryVisibility(mode="list", characters=["Bob"]),
        )

        with ActiveScene(scene):
            bob.rename("Robert")

        assert scene.active_characters == ["Robert", "Carol"]
        assert scene.history[0].present == ["Robert", "Carol"]
        assert scene.archived_history[0]["present"] == ["Robert"]
        assert scene.world_state.knowledge[0].character == "Robert"
        assert scene.world_state.knowledge[1].target == "Robert.detail.secret"
        assert carol.visibility["detail.plan"].characters == ["Robert"]
        assert scene.world_state.manual_context["w1"].visibility.characters == [
            "Robert"
        ]

    def test_rename_without_scene_context_is_safe(self):
        bob = Character(name="Bob")
        bob.rename("Robert")
        assert bob.name == "Robert"


# ---------------------------------------------------------------------------
# retrieval
# ---------------------------------------------------------------------------


class TestRetrieval:
    @pytest.fixture
    def memory(self, scene):
        from talemate.instance import get_agent

        memory = get_agent("memory")
        memory.calls = []
        scene.rag_cache = {}

        async def fake_get(text, character=None, limit=15, **where):
            memory.calls.append({"text": text, "limit": limit, **where})
            return [
                doc(
                    "e1",
                    {"typ": "history", "presence_known": True, "present": '["Alice"]'},
                    "seen",
                ),
                doc(
                    "e2",
                    {"typ": "history", "presence_known": True, "present": '["Bob"]'},
                    "missed",
                ),
                doc(
                    "Bob.age",
                    {"typ": "base_attribute", "character": "Bob", "attr": "age"},
                    "age",
                ),
            ]

        memory.get = fake_get
        return memory

    async def test_multi_query_filter_without_over_fetch_keeps_limit(
        self, scene, memory
    ):
        from talemate.context import ActiveScene

        with ActiveScene(scene):
            index = KnowledgeIndex.from_scene(scene)
            result = await memory.multi_query(
                ["q"], iterate=5, filter=index.retrieval_filter(scene, "Alice")
            )
        assert result == ["seen", "age"]
        assert memory.calls[0]["limit"] == 10

    async def test_over_fetch_is_explicit(self, scene, memory):
        from talemate.context import ActiveScene

        with ActiveScene(scene):
            await memory.multi_query(["q"], iterate=5, over_fetch=3)
        assert memory.calls[0]["limit"] == 30

    async def test_rag_semantic_context_over_fetches_only_with_a_filter(
        self, scene, memory
    ):
        from talemate.context import ActiveScene
        from talemate.instance import get_agent

        conversation = get_agent("conversation")
        scene.history = [
            CharacterMessage(message="Alice: something happened here today")
        ]
        with ActiveScene(scene):
            await conversation.semantic_context(filter=lambda d: True)
            assert memory.calls[-1]["limit"] == 30
            await conversation.semantic_context()
            assert memory.calls[-1]["limit"] == 10

    async def test_questions_mode_receives_the_filter(self, scene, memory):
        from unittest.mock import AsyncMock, patch

        from talemate.context import ActiveScene
        from talemate.instance import get_agent
        from talemate.prompts import Prompt

        world_state = get_agent("world_state")
        marker = lambda d: True  # noqa: E731
        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", new_callable=AsyncMock) as req,
        ):
            req.return_value = ("", {"response": "answer"})
            await world_state.analyze_text_and_extract_context(
                "text", "goal", filter=marker
            )
        assert req.call_args.kwargs["vars"]["memory_filter"] is marker

    async def test_multi_query_without_filter_keeps_limit(self, scene, memory):
        from talemate.context import ActiveScene

        with ActiveScene(scene):
            result = await memory.multi_query(["q"], iterate=5)
        assert result == ["seen", "missed", "age"]
        assert memory.calls[0]["limit"] == 10

    async def test_rag_build_filters_for_the_speaker(self, scene, memory):
        from talemate.context import ActiveScene
        from talemate.instance import get_agent

        conversation = get_agent("conversation")
        alice = Character(name="Alice")
        bob = Character(name="Bob")
        scene.character_data = {"Alice": alice, "Bob": bob}
        scene.history = [
            CharacterMessage(message="Alice: something happened here today")
        ]

        with ActiveScene(scene):
            for_alice = await conversation.rag_build(character=alice)
            for_bob = await conversation.rag_build(character=bob)
            shared = await conversation.rag_build()

        assert "missed" not in for_alice and "seen" in for_alice
        assert "seen" not in for_bob and "missed" in for_bob
        assert "seen" in shared and "missed" in shared

    async def test_cache_is_keyed_by_speaker(self, scene, memory):
        from talemate.context import ActiveScene
        from talemate.instance import get_agent

        conversation = get_agent("conversation")
        alice = Character(name="Alice")
        bob = Character(name="Bob")
        scene.history = [CharacterMessage(message="Alice: hi")]

        with ActiveScene(scene):
            await conversation.rag_set_cache(["for alice"], alice)
            await conversation.rag_set_cache(["shared"])
            assert await conversation.rag_get_cache(alice) == ["for alice"]
            assert await conversation.rag_get_cache(bob) is None
            assert await conversation.rag_get_cache() == ["shared"]

        assert "-Alice-" in conversation.long_term_memory_cache_key_for(alice)
        author_key = conversation.long_term_memory_cache_key_for(None)
        assert author_key != conversation.long_term_memory_cache_key
        assert author_key.endswith("-author")


# ---------------------------------------------------------------------------
# direct renders: sheets, descriptions, pins
# ---------------------------------------------------------------------------


class TestEntryClassification:
    @pytest.fixture
    def populated(self, scene):
        bob = Character(
            name="Bob",
            description="A keeper.",
            base_attributes={"age": "40", "eyes": "grey"},
            details={"secret": "x"},
            visibility={
                "age": EntryVisibility(mode="owner"),
                "detail.secret": EntryVisibility(mode="list", characters=["Carol"]),
                "description": EntryVisibility(mode="owner"),
            },
        )
        scene.character_data = {"Bob": bob}
        scene.world_state.manual_context["w1"] = ManualContext(
            id="w1", text="lore", visibility=EntryVisibility(mode="owner")
        )
        scene.world_state.manual_context["w2"] = ManualContext(
            id="w2", text="open lore"
        )
        scene.archived_history = [{"id": "s0", "text": "static", "ts": 0}]
        return bob

    def test_item_for_entry_classifies_ids(self, scene, populated):
        index = KnowledgeIndex.from_scene(scene)
        assert index.item_for_entry(scene, "w1").kind == "world_entry"
        assert index.item_for_entry(scene, "Bob.age").kind == "attribute"
        assert index.item_for_entry(scene, "Bob.detail.secret").kind == "detail"
        assert index.item_for_entry(scene, "Bob.description").kind == "description"
        assert index.item_for_entry(scene, "s0").kind == "static"
        assert index.item_for_entry(scene, "unknown-id").kind == "world_entry"

    def test_knows_entry(self, scene, populated):
        index = KnowledgeIndex.from_scene(scene)
        assert not index.knows_entry(scene, "Alice", "w1")
        assert index.knows_entry(scene, "Alice", "w2")
        assert not index.knows_entry(scene, "Alice", "Bob.age")
        assert index.knows_entry(scene, "Bob", "Bob.age")
        assert index.knows_entry(scene, "Carol", "Bob.detail.secret")
        assert index.knows_entry(scene, "Alice", "Bob.eyes")
        assert index.knows_entry(scene, None, "w1")
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="s0", kind="revoke")
        ]
        assert not KnowledgeIndex.from_scene(scene).knows_entry(scene, "Alice", "s0")

    def test_sheet_and_description_for_viewer(self, scene, populated):
        index = KnowledgeIndex.from_scene(scene)
        assert index.sheet(scene, populated, "Alice") == "eyes: grey"
        assert index.sheet(scene, populated, "Bob") == "age: 40\neyes: grey"
        assert index.sheet(scene, populated, None) == "age: 40\neyes: grey"
        assert index.description(scene, populated, "Alice") == ""
        assert index.description(scene, populated, "Bob") == "A keeper."

    def test_sheet_without_base_attributes_keeps_name(self, scene):
        plain = Character(
            name="Zed",
            description="Quiet.",
            visibility={"description": EntryVisibility(mode="owner")},
        )
        scene.character_data = {"Zed": plain}
        index = KnowledgeIndex.from_scene(scene)
        assert (
            index.sheet(scene, plain, "Alice", "description") == "name: Zed\ngender: "
        )
        assert "description" not in index.sheet(scene, plain, "Alice")

    def test_digest_tracks_edges_and_visibility(self, scene, populated):
        before = knowledge_digest(scene)
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Alice", target="w1")
        )
        after_edge = knowledge_digest(scene)
        assert after_edge != before
        populated.visibility["eyes"] = EntryVisibility(mode="owner")
        assert knowledge_digest(scene) != after_edge

    def test_viewer_digest_excludes_other_viewers_and_later_edges(self, scene):
        before = knowledge_digest(scene, viewer="Alice", boundary_ids={1})
        scene.world_state.knowledge.extend(
            [
                KnowledgeEdge(character="Bob", target="w1", message_id=1),
                KnowledgeEdge(character="Alice", target="w2", message_id=2),
            ]
        )
        assert knowledge_digest(scene, viewer="Alice", boundary_ids={1}) == before
        scene.world_state.knowledge.append(
            KnowledgeEdge(character="Alice", target="w3", message_id=1)
        )
        assert knowledge_digest(scene, viewer="Alice", boundary_ids={1}) != before


class TestVisibilityLifecycle:
    async def test_visibility_removed_with_the_entry(self, scene):
        from talemate.context import ActiveScene

        bob = Character(
            name="Bob",
            base_attributes={"age": "40"},
            details={"secret": "x"},
            visibility={
                "age": EntryVisibility(mode="owner"),
                "detail.secret": EntryVisibility(mode="owner"),
            },
        )
        with ActiveScene(scene):
            await bob.set_detail("secret", None)
            await bob.set_base_attribute("age", None)
        assert bob.visibility == {}


# ---------------------------------------------------------------------------
# round 2: description chunks, analysis prompts, query_memory over-fetch
# ---------------------------------------------------------------------------


@pytest.fixture
def memory(scene):
    from talemate.instance import get_agent

    memory = get_agent("memory")
    memory.calls = []
    scene.rag_cache = {}

    async def fake_get(text, character=None, limit=15, **where):
        memory.calls.append({"text": text, "limit": limit, **where})
        return []

    memory.get = fake_get
    return memory


class TestDescriptionChunks:
    def test_chunk_ids_normalise_to_the_entry(self):
        from talemate.knowledge.bucket import canonical_entry_id

        assert canonical_entry_id("Bob.description.0") == "Bob.description"
        assert canonical_entry_id("Bob.description.12") == "Bob.description"
        assert canonical_entry_id("Bob.description") == "Bob.description"
        assert canonical_entry_id("Bob.age") == "Bob.age"
        assert canonical_entry_id("w1") == "w1"

    def test_revoke_and_grant_match_chunk_documents(self, scene):
        bob = Character(name="Bob", description="A keeper.\n\nHe lies.")
        scene.character_data = {"Bob": bob}
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Bob.description", kind="revoke")
        ]
        index = KnowledgeIndex.from_scene(scene)
        chunk = doc(
            "Bob.description.1",
            {"typ": "description", "character": "Bob", "attr": "description"},
            "He lies.",
        )
        assert not index.retrieval_filter(scene, "Alice")(chunk)
        assert index.retrieval_filter(scene, "Carol")(chunk)

        bob.visibility["description"] = EntryVisibility(mode="owner")
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Bob.description", kind="grant")
        ]
        index = KnowledgeIndex.from_scene(scene)
        assert index.retrieval_filter(scene, "Alice")(chunk)
        assert not index.retrieval_filter(scene, "Carol")(chunk)
        assert not index.knows_entry(scene, "Carol", "Bob.description.3")


class TestAnalysisPrompts:
    @pytest.fixture
    def restricted_scene(self, scene):
        from talemate.world_state.manager import AnnotatedContextPin
        from talemate.world_state import ContextPin

        bob = Character(
            name="Bob",
            description="Bob keeps the light.",
            base_attributes={"age": "SECRET-AGE-40", "eyes": "grey"},
            visibility={"age": EntryVisibility(mode="owner")},
        )
        alice = Character(name="Alice", description="Alice surveys wrecks.")
        from talemate.tale_mate import Actor

        scene.character_data = {"Alice": alice, "Bob": bob}
        scene.actors = [
            Actor(character=alice, agent=None),
            Actor(character=bob, agent=None),
        ]
        scene.active_characters = ["Alice", "Bob"]
        scene.world_state.manual_context["w1"] = ManualContext(
            id="w1",
            text="SECRET-LORE the wreck was sabotaged",
            visibility=EntryVisibility(mode="owner"),
        )
        scene.active_pins = [
            AnnotatedContextPin(
                pin=ContextPin(entry_id="w1", active=True),
                is_active=True,
                text="SECRET-LORE the wreck was sabotaged",
                time_aware_text="SECRET-LORE the wreck was sabotaged",
                title="w1",
            )
        ]
        return scene

    def _render(self, scene, uid, viewer):
        from unittest.mock import AsyncMock, Mock, patch

        from talemate.prompts import Prompt

        import talemate.instance as instance

        memory = Mock()
        memory.multi_query = AsyncMock(return_value=[])
        memory.query = AsyncMock(return_value="")
        world_state = Mock()
        world_state.analyze_and_follow_instruction = AsyncMock(
            return_value="1. What happened to the wreck?"
        )
        real_get_agent = instance.get_agent

        def fake_get_agent(name, *args, **kwargs):
            if name == "memory":
                return memory
            if name == "world_state":
                return world_state
            return real_get_agent(name, *args, **kwargs)

        with patch(
            "talemate.prompts.base.instance.get_agent", side_effect=fake_get_agent
        ):
            prompt = Prompt.get(
                uid,
                vars={
                    "scene": scene,
                    "max_tokens": 4096,
                    "text": "Alice asks about the wreck.",
                    "goal": "continue the scene as Alice",
                    "include_character_context": True,
                    "response_length": 512,
                    "num_queries": 1,
                    "extra_context": [],
                    "memory_filter": None,
                    "knowledge_index": KnowledgeIndex.from_scene(scene),
                    "knowledge_viewer": viewer,
                },
            )
            return prompt.render()

    @pytest.mark.parametrize(
        "uid",
        [
            "world_state.analyze-text-and-extract-context",
            "world_state.analyze-text-and-generate-rag-queries",
        ],
    )
    def test_restricted_sheet_and_pin_are_hidden_from_the_viewer(
        self, restricted_scene, uid
    ):
        from talemate.context import ActiveScene

        with ActiveScene(restricted_scene):
            rendered = self._render(restricted_scene, uid, "Alice")
        assert "SECRET-AGE-40" not in rendered
        assert "eyes: grey" in rendered
        assert "Bob keeps the light." in rendered
        if uid.endswith("extract-context"):
            assert "SECRET-LORE" not in rendered

    @pytest.mark.parametrize(
        "uid",
        [
            "world_state.analyze-text-and-extract-context",
            "world_state.analyze-text-and-generate-rag-queries",
        ],
    )
    def test_no_viewer_renders_everything(self, restricted_scene, uid):
        from talemate.context import ActiveScene

        with ActiveScene(restricted_scene):
            rendered = self._render(restricted_scene, uid, None)
        assert "SECRET-AGE-40" in rendered
        if uid.endswith("extract-context"):
            assert "SECRET-LORE" in rendered

    async def test_rag_build_passes_the_viewer(self, scene, memory):
        from unittest.mock import AsyncMock, patch

        from talemate.context import ActiveScene
        from talemate.instance import get_agent

        conversation = get_agent("conversation")
        conversation.actions["use_long_term_memory"].config[
            "retrieval_method"
        ].value = "questions"
        world_state = get_agent("world_state")
        alice = Character(name="Alice")
        scene.character_data = {"Alice": alice}
        scene.history = [CharacterMessage(message="Alice: hi there everyone")]
        try:
            with (
                ActiveScene(scene),
                patch.object(
                    world_state,
                    "analyze_text_and_extract_context",
                    new_callable=AsyncMock,
                    return_value="a",
                ) as call,
            ):
                await conversation.rag_build(character=alice)
            assert call.call_args.kwargs["viewer"] == "Alice"
            assert call.call_args.kwargs["filter"] is not None
        finally:
            conversation.actions["use_long_term_memory"].config[
                "retrieval_method"
            ].value = "direct"


class TestQueryMemoryOverFetch:
    async def test_exclude_history_alone_keeps_the_limit(self, scene, memory):
        from talemate.context import ActiveScene
        from talemate.prompts import Prompt

        with ActiveScene(scene):
            prompt = Prompt.get(
                "world_state.analyze-text-and-extract-context", vars={"scene": scene}
            )
            prompt.query_memory(
                "q", as_question_answer=False, iterate=5, exclude_history=True
            )
            assert memory.calls[-1]["limit"] == 10
            prompt.query_memory(
                "q", as_question_answer=False, iterate=5, filter=lambda d: True
            )
            assert memory.calls[-1]["limit"] == 30


class TestDottedWorldEntryIds:
    def test_world_entry_named_like_a_description_chunk_keeps_its_visibility(
        self, scene
    ):
        scene.world_state.manual_context["lighthouse.description.1"] = ManualContext(
            id="lighthouse.description.1",
            text="secret lore",
            visibility=EntryVisibility(mode="owner"),
        )
        index = KnowledgeIndex.from_scene(scene)
        assert not index.knows_entry(scene, "Alice", "lighthouse.description.1")
        assert (
            index.item_for_entry(scene, "lighthouse.description.1").kind
            == "world_entry"
        )
        document = doc(
            "lighthouse.description.1",
            {"typ": "world_state", "source": "manual"},
            "secret lore",
        )
        assert not index.retrieval_filter(scene, "Alice")(document)
        # an edge on the exact id still matches
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="lighthouse.description.1")
        ]
        assert KnowledgeIndex.from_scene(scene).retrieval_filter(scene, "Alice")(
            document
        )

    def test_only_description_documents_are_folded(self, scene):
        index = KnowledgeIndex.from_scene(scene)
        as_history = doc(
            "Bob.description.2",
            {"typ": "history", "presence_known": True, "present": '["Bob"]'},
            "x",
        )
        assert (
            KnowledgeItem.from_memory_document(as_history, scene).id
            == "Bob.description.2"
        )
        as_description = doc(
            "Bob.description.2",
            {"typ": "base_attribute", "character": "Bob", "attr": "description"},
            "x",
        )
        assert (
            KnowledgeItem.from_memory_document(as_description, scene).id
            == "Bob.description"
        )
        assert (
            index.in_bucket(
                "Alice", KnowledgeItem.from_memory_document(as_history, scene)
            )
            is False
        )


class TestAnalysisPromptsThroughTheAgent:
    async def test_public_method_hides_restricted_entries(self, scene):
        from unittest.mock import AsyncMock, Mock, patch

        import talemate.instance as instance
        from talemate.context import ActiveScene
        from talemate.instance import get_agent
        from talemate.prompts import Prompt
        from talemate.tale_mate import Actor

        bob = Character(
            name="Bob",
            base_attributes={"age": "SECRET-AGE-40", "eyes": "grey"},
            visibility={"age": EntryVisibility(mode="owner")},
        )
        alice = Character(name="Alice")
        scene.character_data = {"Alice": alice, "Bob": bob}
        scene.actors = [
            Actor(character=alice, agent=None),
            Actor(character=bob, agent=None),
        ]
        world_state = get_agent("world_state")
        rendered = {}
        memory = Mock()
        memory.multi_query = AsyncMock(return_value=[])
        memory.query = AsyncMock(return_value="")
        ws_stub = Mock()
        ws_stub.analyze_and_follow_instruction = AsyncMock(return_value="1. q?")
        real_get_agent = instance.get_agent

        def fake_get_agent(name, *a, **k):
            return {"memory": memory, "world_state": ws_stub}.get(
                name
            ) or real_get_agent(name, *a, **k)

        async def fake_request(uid, client, kind, vars=None, **kwargs):
            with patch(
                "talemate.prompts.base.instance.get_agent", side_effect=fake_get_agent
            ):
                rendered[uid] = Prompt.get(uid, vars=vars).render()
            return "", {"response": "1. a query?"}

        with (
            ActiveScene(scene),
            patch.object(Prompt, "request", side_effect=fake_request),
            patch("talemate.agents.world_state.get_agent", side_effect=fake_get_agent),
        ):
            await world_state.analyze_text_and_extract_context(
                "text", "goal", include_character_context=True, viewer="Alice"
            )
            await world_state.analyze_text_and_extract_context_via_queries(
                "text", "goal", include_character_context=True, viewer="Alice"
            )
        for text in rendered.values():
            assert "SECRET-AGE-40" not in text and "eyes: grey" in text
