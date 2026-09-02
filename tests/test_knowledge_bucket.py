"""
The knowledge bucket predicate: presence, ownership, common lore, visibility,
grant and revoke edges.
"""

import pytest

from talemate.agents.memory.schema import MemoryDocument
from talemate.character import Character
from talemate.knowledge.bucket import KnowledgeIndex, KnowledgeItem
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

    def test_fact_follows_presence(self, index):
        item = KnowledgeItem(id="F1", kind="fact", present=["Bob"])
        assert not index.in_bucket("Alice", item)
        assert index.in_bucket("Bob", item)

    def test_grant_overrides_absence_and_visibility(self):
        index = KnowledgeIndex(
            grants={("Alice", "F1"), ("Alice", "Bob.detail.secret")}, revokes=set()
        )
        assert index.in_bucket(
            "Alice", KnowledgeItem(id="F1", kind="fact", present=["Bob"])
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
            grants={("Alice", "F1")}, revokes={("Alice", "F1"), ("Bob", "Bob.age")}
        )
        assert not index.in_bucket(
            "Alice", KnowledgeItem(id="F1", kind="fact", present=["Alice"])
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

    async def test_multi_query_filter_over_fetches(self, scene, memory):
        from talemate.context import ActiveScene

        with ActiveScene(scene):
            index = KnowledgeIndex.from_scene(scene)
            result = await memory.multi_query(
                ["q"], iterate=5, filter=index.retrieval_filter(scene, "Alice")
            )
        assert result == ["seen", "age"]
        assert memory.calls[0]["limit"] == 30

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

        assert conversation.long_term_memory_cache_key_for(alice).endswith("-Alice")
        assert (
            conversation.long_term_memory_cache_key_for(None)
            == conversation.long_term_memory_cache_key
        )
