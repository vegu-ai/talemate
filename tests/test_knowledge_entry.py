"""
Who knows one entry: the Known by line, edge replacement and the per-character
report the director reads.
"""

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.character import Character
from talemate.game.engine.context_id import context_id_item_from_string
from talemate.knowledge.entry import (
    character_knowledge_report,
    entry_knowledge,
    known_by_line,
    known_by_lines,
    set_edge,
    sheet_visibility_key,
)
from talemate.knowledge.schema import EntryVisibility, KnowledgeEdge
from talemate.world_state import ManualContext


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    bob = Character(
        name="Bob",
        description="Bob keeps the light.",
        base_attributes={"age": "40", "secret": "Bob buried the ledger."},
        details={"the fall": "Bob fell from the gallery."},
        visibility={
            "secret": EntryVisibility(mode="owner"),
            "detail.the fall": EntryVisibility(mode="list", characters=["Alice"]),
        },
    )
    alice = Character(name="Alice", base_attributes={"age": "30"})
    carol = Character(name="Carol")
    s.character_data = {"Bob": bob, "Alice": alice, "Carol": carol}
    s.world_state.manual_context = {
        "The Lighthouse": ManualContext(
            id="The Lighthouse", text="A tall white tower.", meta={"typ": "world_state"}
        ),
        "Hidden Door": ManualContext(
            id="Hidden Door",
            text="Behind the cupboard.",
            meta={"typ": "world_state"},
            visibility=EntryVisibility(mode="owner"),
        ),
        "Cellar Key": ManualContext(
            id="Cellar Key",
            text="Under the mat.",
            meta={"typ": "world_state"},
            visibility=EntryVisibility(mode="list", characters=["Carol"]),
        ),
    }
    s.archived_history = [
        {"id": "st1", "text": "Long ago the tower was built.", "ts": 1},
        {
            "id": "h1",
            "text": "Mara and Edwin argued.",
            "ts": 5,
            "start": 0,
            "end": 4,
            "present": ["Mara", "Edwin"],
        },
        {"id": "h2", "text": "Someone knocked.", "ts": 9, "start": 5, "end": 8},
    ]
    s.ts = 42
    return s


class TestKnownBy:
    def test_default_is_the_shortest_form(self, scene):
        assert known_by_line(scene, "Bob.age") == "Known by: everyone"
        assert known_by_line(scene, "The Lighthouse") == "Known by: everyone"
        assert known_by_line(scene, "st1") == "Known by: everyone"

    def test_owner_and_list_on_a_sheet(self, scene):
        assert known_by_line(scene, "Bob.secret") == "Known by: only Bob (owner)"
        assert (
            known_by_line(scene, "Bob.detail.the fall")
            == "Known by: Bob (owner), Alice"
        )

    def test_world_entry_has_no_owner(self, scene):
        assert known_by_line(scene, "Hidden Door") == "Known by: nobody"
        assert known_by_line(scene, "Cellar Key") == "Known by: Carol"

    def test_history_presence(self, scene):
        assert known_by_line(scene, "h1") == "Known by: Mara, Edwin (present)"
        assert known_by_line(scene, "h2") == "Known by: everyone"

    def test_edges_follow_the_visibility(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Bob.secret", source="told"),
            KnowledgeEdge(
                character="Carol",
                target="Bob.secret",
                kind="revoke",
                source="director",
                note="she forgot",
            ),
        ]
        assert known_by_line(scene, "Bob.secret") == (
            'Known by: only Bob (owner); grants: Alice (told); revokes: Carol (director, "she forgot")'
        )

    def test_description_chunk_folds_onto_the_entry(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Bob.description", kind="revoke")
        ]
        entry = entry_knowledge(scene, "Bob.description.2")
        assert entry.id == "Bob.description"
        assert entry.kind == "description"
        assert [e.character for e in entry.revokes] == ["Alice"]

    def test_sheet_visibility_key(self, scene):
        assert sheet_visibility_key(entry_knowledge(scene, "Bob.secret")) == "secret"
        assert (
            sheet_visibility_key(entry_knowledge(scene, "Bob.detail.the fall"))
            == "detail.the fall"
        )
        assert (
            sheet_visibility_key(entry_knowledge(scene, "Bob.description"))
            == "description"
        )


class TestKnownByLines:
    @pytest.mark.asyncio
    async def test_lines_keyed_by_context_id(self, scene):
        items = [
            await context_id_item_from_string("character.attribute:Bob.secret", scene),
            await context_id_item_from_string("character.description:Bob", scene),
            await context_id_item_from_string("world_entry.manual:Hidden Door", scene),
            await context_id_item_from_string("history_entry.static:st1", scene),
            await context_id_item_from_string(
                "character.acting_instructions:Bob", scene
            ),
        ]
        lines = known_by_lines(scene, items)
        assert lines[str(items[0].context_id)] == "Known by: only Bob (owner)"
        assert lines[str(items[1].context_id)] == "Known by: everyone"
        assert lines[str(items[2].context_id)] == "Known by: nobody"
        assert lines[str(items[3].context_id)] == "Known by: everyone"
        assert str(items[4].context_id) not in lines

    @pytest.mark.asyncio
    async def test_knowledge_id_is_wider_than_memory_id(self, scene):
        description = await context_id_item_from_string(
            "character.description:Bob", scene
        )
        assert description.memory_id is None
        assert description.knowledge_id == "Bob.description"
        history = await context_id_item_from_string("history_entry.static:st1", scene)
        assert history.memory_id is None
        assert history.knowledge_id == "st1"
        attribute = await context_id_item_from_string(
            "character.attribute:Bob.age", scene
        )
        assert attribute.knowledge_id == attribute.memory_id == "Bob.age"


class TestSetEdge:
    def test_new_edge_takes_the_scene_time(self, scene):
        edge = set_edge(
            scene,
            KnowledgeEdge(character="Alice", target="Bob.secret", source="director"),
            replace=True,
        )
        assert edge.ts == 42
        assert scene.world_state.knowledge == [edge]

    def test_replace_keeps_one_edge_per_pair(self, scene):
        set_edge(scene, KnowledgeEdge(character="Alice", target="Bob.secret"))
        set_edge(scene, KnowledgeEdge(character="Carol", target="Bob.secret"))
        revoke = set_edge(
            scene,
            KnowledgeEdge(
                character="Alice", target="Bob.secret", kind="revoke", note="later"
            ),
            replace=True,
        )
        pairs = [(e.character, e.kind) for e in scene.world_state.knowledge]
        assert pairs == [("Carol", "grant"), ("Alice", "revoke")]
        assert scene.world_state.knowledge[-1] is revoke

    def test_default_keeps_every_edge(self, scene):
        set_edge(scene, KnowledgeEdge(character="Alice", target="Bob.secret"))
        set_edge(
            scene,
            KnowledgeEdge(character="Alice", target="Bob.secret", kind="revoke"),
        )
        assert len(scene.world_state.knowledge) == 2

    def test_character_description_chunk_folds_onto_the_entry(self, scene):
        edge = set_edge(
            scene, KnowledgeEdge(character="Alice", target="Bob.description.3")
        )
        assert edge.target == "Bob.description"


class TestCharacterKnowledgeReport:
    def test_perception_headers_edges_and_disclosures(self, scene, monkeypatch):
        from talemate.knowledge.perspectives import add_disclosure

        scene.knowledge_eligibility = "perception"
        add_disclosure(scene, "The ledger is under the bed.", ("Alice",))
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Hidden Door")
        ]
        lines = character_knowledge_report(scene, "Alice").splitlines()
        assert lines[:3] == [
            "### What Alice knows",
            "Explicit disclosures (oldest first):",
            "- The ledger is under the bed.",
        ]
        assert "Grants:" in lines and "Revokes: none" not in lines
        assert "Restricted entries Alice can see:" in lines
        report = character_knowledge_report(scene, "Nobody")
        assert "Explicit disclosures (oldest first): none" in report
        assert "Restricted entries Nobody can see: none" in report

    def test_empty(self, scene):
        report = character_knowledge_report(scene, "Alice")
        assert report.splitlines() == [
            "### What Alice knows",
            "Grants: none",
            "Revokes: none",
            "Restricted entries Alice can see:",
            "- Bob: the fall (Known by: Bob (owner), Alice)",
        ]

    def test_edges_and_restricted_entries(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(
                character="Alice",
                target="Hidden Door",
                source="director",
                note="saw it",
            ),
            KnowledgeEdge(
                character="Alice", target="Bob.detail.the fall", kind="revoke"
            ),
            KnowledgeEdge(character="Carol", target="Bob.secret"),
        ]
        report = character_knowledge_report(scene, "Alice")
        assert report.splitlines() == [
            "### What Alice knows",
            "Grants:",
            '- Hidden Door: director, "saw it"',
            "Revokes:",
            "- Bob: the fall: manual",
            "Restricted entries Alice can see:",
            '- Hidden Door (Known by: nobody; grants: Alice (director, "saw it"))',
        ]


class TestClassification:
    @pytest.fixture
    def layered(self, scene):
        scene.archived_history[2]["present"] = ["Edwin"]
        scene.archived_history += [
            {
                "id": "h3",
                "text": "The lamp went out.",
                "ts": 12,
                "start": 9,
                "end": 12,
                "present": ["Mara"],
            }
        ]
        scene.layered_history = [
            [
                {
                    "id": "L1",
                    "text": "The tower was built, then Mara and Edwin argued.",
                    "ts": 5,
                    "start": 0,
                    "end": 1,
                },
                {
                    "id": "L2",
                    "text": "The lamp went out.",
                    "ts": 12,
                    "start": 1,
                    "end": 3,
                },
            ]
        ]
        return scene

    @pytest.mark.asyncio
    async def test_layered_entry_uses_the_union_of_its_sources(self, layered):
        item = await context_id_item_from_string(
            "history_entry.dynamic:layer.1.id.L2", layered
        )
        entry = entry_knowledge(layered, item)
        assert entry.kind == "history"
        assert entry.line == "Known by: Edwin, Mara (present)"
        # the same entry by bare id classifies the same way
        assert known_by_line(layered, "L2") == "Known by: Edwin, Mara (present)"

    def test_layered_entry_with_an_unknown_source_is_known_to_everyone(self, layered):
        # L1 spans st1 (a static entry, presence unknown) and h1
        entry = entry_knowledge(layered, "L1")
        assert entry.kind == "history"
        assert entry.present is None
        assert entry.line == "Known by: everyone"

    def test_unknown_id(self, scene):
        entry = entry_knowledge(scene, "no-such-entry")
        assert entry.kind == "unknown"
        assert entry.line == "Known by: unknown (no such entry)"

    @pytest.mark.asyncio
    async def test_context_item_without_knowledge_is_unknown(self, scene):
        item = await context_id_item_from_string(
            "character.acting_instructions:Bob", scene
        )
        assert entry_knowledge(scene, item).kind == "unknown"

    def test_longest_character_name_wins(self, scene):
        scene.character_data["Bob.Jr"] = Character(
            name="Bob.Jr",
            base_attributes={"age": "12"},
            visibility={"age": EntryVisibility(mode="owner")},
        )
        entry = entry_knowledge(scene, "Bob.Jr.age")
        assert entry.owner == "Bob.Jr"
        assert entry.kind == "attribute"
        assert entry.line == "Known by: only Bob.Jr (owner)"
        assert sheet_visibility_key(entry) == "age"


class TestReportLabels:
    def test_layered_edges_get_labels(self, scene):
        scene.layered_history = [
            [
                {
                    "id": "L1",
                    "text": "Mara and Edwin argued.",
                    "ts": 5,
                    "start": 1,
                    "end": 1,
                }
            ]
        ]
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="L1", source="director"),
        ]
        report = character_knowledge_report(scene, "Alice")
        assert "- history (layer 1): Mara and Edwin argued.: director" in report


@pytest.mark.parametrize("route", ["entry", "manager"])
async def test_perception_revoke_rejected_before_mutation(scene, route):
    scene.knowledge_eligibility = "perception"
    edge = KnowledgeEdge(character="Alice", target="The Lighthouse", kind="revoke")
    with pytest.raises(ValueError, match="knowledge cannot be erased"):
        if route == "entry":
            set_edge(scene, edge)
        else:
            await scene.world_state_manager.set_knowledge_edge(edge)
    assert scene.world_state.knowledge == []


async def test_stored_revoke_has_no_new_mode_effect_or_report(scene):
    edge = KnowledgeEdge(character="Alice", target="The Lighthouse", kind="revoke")
    set_edge(scene, edge)
    assert "revokes: Alice" in known_by_line(scene, "The Lighthouse")
    scene.knowledge_eligibility = "perception"
    assert known_by_line(scene, "The Lighthouse") == "Known by: everyone"
    report = await scene.world_state_manager.get_character_knowledge("Alice")
    assert report.edges == []
    assert "Revokes:" not in character_knowledge_report(scene, "Alice")
    scene.knowledge_eligibility = "legacy"
    assert (await scene.world_state_manager.get_character_knowledge("Alice")).edges == [
        edge
    ]
