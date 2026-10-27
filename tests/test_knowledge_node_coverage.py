"""
Knowledge nodes and events added for the node editor: Character Knows Entry,
Remove Knowledge Edge, Set Static History Known By, Add / List Disclosures,
the structured Character Knowledge outputs, and the knowledge.* events.
"""

import asyncio

import pytest

import talemate.emit.async_signals as async_signals
from _node_test_helpers import run_node
from talemate.game.engine.nodes.core import InputValueError
from talemate.game.engine.nodes.knowledge import (
    AddDisclosure,
    CharacterKnowledge,
    CharacterKnowsEntry,
    ListDisclosures,
    RemoveKnowledgeEdge,
    SetEntryVisibility,
    SetStaticHistoryKnownBy,
)
from talemate.knowledge.changes import (
    DisclosureAddedEvent,
    KnowledgeChangedEvent,
    KnowledgeEdgeRemovedEvent,
    KnowledgeVisibilityChangedEvent,
)
from talemate.knowledge.entry import set_edge
from talemate.knowledge.schema import EntryVisibility, KnowledgeEdge

import test_disclosures
import test_knowledge_nodes

scene = test_knowledge_nodes.scene
item = test_knowledge_nodes.item
disclosure_scene = test_disclosures.disclosure_scene


@pytest.fixture
def received():
    events = {}
    connected = []

    def listen(name):
        events[name] = []

        async def handler(event):
            events[name].append(event)

        async_signals.get(name).connect(handler)
        connected.append((name, handler))
        return events[name]

    yield listen
    for name, handler in connected:
        async_signals.get(name).disconnect(handler)


async def settle():
    for _ in range(3):
        await asyncio.sleep(0)


class TestCharacterKnowsEntry:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "character, target, known, reason",
        [
            ("Bob", "Bob.secret", True, None),
            ("Alice", "Bob.secret", False, "visibility"),
            ("Alice", "h1", True, None),
            ("Carol", "h1", False, "presence"),
            ("Carol", "Hidden Door", True, None),
        ],
    )
    async def test_known_and_reason(self, scene, character, target, known, reason):
        out = await run_node(
            CharacterKnowsEntry(),
            scene=scene,
            inputs={"character": character, "target": target},
        )
        assert out["known"] is known
        assert out["reason"] == reason
        assert out["entry_id"] == target

    @pytest.mark.asyncio
    async def test_grant_and_revoke_decide(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Bob.secret"),
            KnowledgeEdge(character="Bob", target="Hidden Door", kind="revoke"),
        ]
        alice = await run_node(
            CharacterKnowsEntry(),
            scene=scene,
            inputs={
                "character": scene.character_data["Alice"],
                "context_id_item": await item(scene, "character.attribute:Bob.secret"),
            },
        )
        bob = await run_node(
            CharacterKnowsEntry(),
            scene=scene,
            inputs={"character": "Bob", "target": "Hidden Door"},
        )
        assert alice["known"] is True
        assert (bob["known"], bob["reason"]) == (False, "revoke")

    @pytest.mark.asyncio
    async def test_needs_a_target(self, scene):
        with pytest.raises(InputValueError):
            await run_node(
                CharacterKnowsEntry(), scene=scene, inputs={"character": "Bob"}
            )


class TestCharacterKnowledgeOutputs:
    @pytest.mark.asyncio
    async def test_structured_edges(self, scene):
        scene.world_state.knowledge = [
            KnowledgeEdge(character="Alice", target="Bob.secret"),
            KnowledgeEdge(character="Alice", target="Hidden Door", kind="revoke"),
            KnowledgeEdge(character="Carol", target="Bob.secret"),
        ]
        out = await run_node(
            CharacterKnowledge(), scene=scene, inputs={"character": "Alice"}
        )
        assert [e["target"] for e in out["grants"]] == ["Bob.secret"]
        assert [e["target"] for e in out["revokes"]] == ["Hidden Door"]
        assert out["disclosures"] == []
        assert out["text"]


class TestRemoveKnowledgeEdge:
    @pytest.mark.asyncio
    async def test_remove_by_pair_sends_edge_removed(self, scene, received):
        scene.active = True
        removed_events = received("knowledge.edge_removed")
        grant = KnowledgeEdge(character="Alice", target="Bob.secret")
        other = KnowledgeEdge(character="Carol", target="Bob.secret")
        scene.world_state.knowledge = [grant, other]
        out = await run_node(
            RemoveKnowledgeEdge(),
            scene=scene,
            inputs={"character": "Alice", "target": "Bob.secret"},
        )
        assert [e["id"] for e in out["removed"]] == [grant.id]
        assert scene.world_state.knowledge == [other]
        await settle()
        [event] = removed_events
        assert isinstance(event, KnowledgeEdgeRemovedEvent)
        assert event.edge.id == grant.id
        assert event.changed is True

    @pytest.mark.asyncio
    async def test_remove_by_id(self, scene):
        edge = KnowledgeEdge(character="Alice", target="Hidden Door", kind="revoke")
        scene.world_state.knowledge = [edge]
        out = await run_node(
            RemoveKnowledgeEdge(), scene=scene, inputs={"edge_id": edge.id}
        )
        assert len(out["removed"]) == 1
        assert scene.world_state.knowledge == []

    @pytest.mark.asyncio
    async def test_needs_an_edge(self, scene):
        with pytest.raises(InputValueError):
            await run_node(
                RemoveKnowledgeEdge(), scene=scene, inputs={"character": "Alice"}
            )


class TestSetStaticHistoryKnownBy:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mode, characters, present",
        [
            ("list", ["Alice"], ["Alice"]),
            ("nobody", [], []),
            ("everyone", [], None),
        ],
    )
    async def test_modes(self, scene, mode, characters, present):
        out = await run_node(
            SetStaticHistoryKnownBy(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "history_entry.static:st1"),
                "mode": mode,
                "characters": characters,
            },
        )
        assert out["entry_id"] == "st1"
        assert out["present"] == present
        assert scene.archived_history[0].get("present") == present

    @pytest.mark.asyncio
    async def test_non_static_entry_is_refused(self, scene):
        with pytest.raises(InputValueError, match="not a static history entry"):
            await run_node(
                SetStaticHistoryKnownBy(),
                scene=scene,
                inputs={
                    "context_id_item": await item(
                        scene, "world_entry.manual:Hidden Door"
                    ),
                    "mode": "nobody",
                },
            )

    @pytest.mark.asyncio
    async def test_refused_with_character_perspectives(self, scene):
        scene.knowledge_eligibility = "perception"
        with pytest.raises(InputValueError, match="Standard stories only"):
            await run_node(
                SetStaticHistoryKnownBy(),
                scene=scene,
                inputs={
                    "context_id_item": await item(scene, "history_entry.static:st1"),
                    "mode": "nobody",
                },
            )


class TestKnowledgeEvents:
    @pytest.mark.asyncio
    async def test_grant_sends_knowledge_changed(self, scene, received):
        scene.active = True
        changed = received("knowledge.changed")
        set_edge(scene, KnowledgeEdge(character="Alice", target="Bob.secret"))
        await settle()
        [event] = changed
        assert isinstance(event, KnowledgeChangedEvent)
        [change] = event.changes
        assert (change.character, change.target, change.kind) == (
            "Alice",
            "Bob.secret",
            "grant",
        )
        assert change.label == "Bob: secret"

    @pytest.mark.asyncio
    async def test_nothing_is_sent_while_the_scene_is_inactive(self, scene, received):
        changed = received("knowledge.changed")
        set_edge(scene, KnowledgeEdge(character="Alice", target="Bob.secret"))
        await settle()
        assert changed == []

    @pytest.mark.asyncio
    async def test_world_entry_visibility_changed(self, scene, received):
        scene.active = True
        events = received("knowledge.visibility_changed")
        await run_node(
            SetEntryVisibility(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "world_entry.manual:Hidden Door"),
                "mode": "list",
                "characters": ["Alice"],
            },
        )
        await settle()
        [event] = events
        assert isinstance(event, KnowledgeVisibilityChangedEvent)
        assert (event.entry_id, event.kind, event.owner) == (
            "Hidden Door",
            "world_entry",
            None,
        )
        assert event.previous.mode == "everyone"
        assert event.visibility == EntryVisibility(mode="list", characters=["Alice"])

    @pytest.mark.asyncio
    async def test_unchanged_sheet_visibility_sends_nothing(self, scene, received):
        scene.active = True
        events = received("knowledge.visibility_changed")
        await run_node(
            SetEntryVisibility(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "character.attribute:Bob.secret"),
                "mode": "owner",
            },
        )
        await settle()
        assert events == []
        await run_node(
            SetEntryVisibility(),
            scene=scene,
            inputs={
                "context_id_item": await item(scene, "character.attribute:Bob.secret"),
                "mode": "everyone",
            },
        )
        await settle()
        [event] = events
        assert (event.entry_id, event.kind, event.owner, event.key) == (
            "Bob.secret",
            "sheet",
            "Bob",
            "secret",
        )
        assert event.previous == EntryVisibility(mode="owner")
        assert event.visibility == EntryVisibility(mode="everyone")


class TestDisclosures:
    @pytest.mark.asyncio
    async def test_add_and_list(self, disclosure_scene, received):
        scene, _ = disclosure_scene
        scene.active = True
        added = received("knowledge.disclosure_added")
        changed = received("knowledge.changed")
        out = await run_node(
            AddDisclosure(),
            scene=scene,
            inputs={"text": "The key is in the well.", "characters": ["Bob", "Cara"]},
        )
        disclosure = out["disclosure"]
        assert disclosure["text"] == "The key is in the well."
        assert list(disclosure["audience"]) == ["Bob", "Cara"]
        await settle()
        [event] = added
        assert isinstance(event, DisclosureAddedEvent)
        assert event.disclosure_id == disclosure["id"]
        assert event.audience == ["Bob", "Cara"]
        assert {c.character for c in changed[0].changes} == {"Bob", "Cara"}

        listed = await run_node(
            ListDisclosures(), scene=scene, inputs={"character": "Cara"}
        )
        assert [d["id"] for d in listed["disclosures"]] == [disclosure["id"]]
        nobody = await run_node(
            ListDisclosures(), scene=scene, inputs={"character": "Alice"}
        )
        assert nobody["disclosures"] == []

    @pytest.mark.asyncio
    async def test_add_disclosure_needs_character_perspectives(self, scene):
        with pytest.raises(InputValueError, match="Character Perspectives"):
            await run_node(
                AddDisclosure(),
                scene=scene,
                inputs={"text": "x", "characters": ["Bob"]},
            )

    @pytest.mark.asyncio
    async def test_unknown_character_is_refused(self, disclosure_scene):
        scene, _ = disclosure_scene
        with pytest.raises(InputValueError, match="does not exist"):
            await run_node(
                AddDisclosure(),
                scene=scene,
                inputs={"text": "x", "characters": ["Zed"]},
            )


class TestCharacterKnowsEntryUnknownTarget:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", ["Hiden Door", "disclosure-1234"])
    async def test_an_id_that_names_no_entry_is_refused(self, scene, target):
        with pytest.raises(InputValueError, match="names no entry") as exc:
            await run_node(
                CharacterKnowsEntry(),
                scene=scene,
                inputs={"character": "Alice", "target": target},
            )
        assert exc.value.input_name == "target"
