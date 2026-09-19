"""#662: Known by on a static history entry governs its text."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.history import ArchiveEntry
from talemate.instance import get_agent
from talemate.knowledge.bucket import KnowledgeIndex, RetrievalFilter, knowledge_digest
from talemate.agents.memory.schema import MemoryDocument
from talemate.scene_message import CharacterMessage
from talemate.knowledge.entry import character_knowledge_report, known_by_line
from talemate.knowledge.schema import EntryVisibility
from talemate.shared_context import SharedContext
from talemate.world_state.manager import WorldStateManager


@pytest.fixture
def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.character_data = {
        name: Character(name=name) for name in ("Alice", "Bob", "Carol")
    }
    scene.archived_history = [
        {"id": "S1", "text": "The war ended.", "ts": 0},
        {"id": "A1", "text": "Alice met Bob.", "start": 0, "end": 0, "ts": 10},
    ]
    return scene


def static_entry(scene):
    return next(entry for entry in scene.archived_history if entry["id"] == "S1")


async def set_known_by(scene, visibility, **patches):
    memory = get_agent("memory")
    with (
        ActiveScene(scene),
        patch(
            "talemate.world_state.manager.emit_archive_add", AsyncMock()
        ) as archive_add,
        patch.object(memory, "add_many", AsyncMock()) as add_many,
        patch("talemate.world_state.manager.emit_knowledge_changes") as emitted,
    ):
        present = await WorldStateManager(scene).set_static_history_known_by(
            "S1", visibility
        )
    return present, archive_add, add_many, emitted


class TestSetKnownBy:
    async def test_specific_characters_reach_the_entry(self, scene):
        present, archive_add, add_many, emitted = await set_known_by(
            scene, EntryVisibility(mode="list", characters=["Alice", "Alice"])
        )
        assert present == ["Alice"]
        assert static_entry(scene)["present"] == ["Alice"]
        archive_add.assert_awaited_once()
        assert archive_add.await_args.args[1].present == ["Alice"]
        changes = emitted.call_args.args[1]
        assert [(c.character, c.target, c.kind) for c in changes] == [
            ("Bob", "S1", "revoke"),
            ("Carol", "S1", "revoke"),
        ]

    async def test_nobody_and_everyone(self, scene):
        await set_known_by(scene, EntryVisibility(mode="owner"))
        assert static_entry(scene)["present"] == []
        present, *_, emitted = await set_known_by(scene, EntryVisibility())
        assert present is None
        assert "present" not in static_entry(scene)
        assert [c.kind for c in emitted.call_args.args[1]] == ["grant"] * 3

    async def test_refused_outside_a_standard_static_entry(self, scene):
        manager = WorldStateManager(scene)
        for entry_id in ("A1", "missing"):
            with pytest.raises(ValueError, match="Only a static history entry"):
                await manager.set_static_history_known_by(entry_id, EntryVisibility())
        scene.knowledge_eligibility = "perception"
        with pytest.raises(ValueError, match="Standard stories only"):
            await manager.set_static_history_known_by("S1", EntryVisibility())


class TestTheEntryTextFollows:
    async def test_bucket_known_by_line_report_and_digest_agree(self, scene):
        index = KnowledgeIndex.from_scene(scene)
        assert all(
            index.knows_entry(scene, name, "S1") for name in ("Alice", "Bob", "Carol")
        )
        assert known_by_line(scene, "S1") == "Known by: everyone"
        before = knowledge_digest(scene)

        await set_known_by(scene, EntryVisibility(mode="list", characters=["Alice"]))

        index = KnowledgeIndex.from_scene(scene)
        assert index.knows_entry(scene, "Alice", "S1")
        assert not index.knows_entry(scene, "Bob", "S1")
        assert known_by_line(scene, "S1") == "Known by: Alice"
        assert knowledge_digest(scene) != before
        assert any(
            line.startswith("- static history: The war ended.")
            and "Known by: Alice" in line
            for line in character_knowledge_report(scene, "Alice").splitlines()
        )
        assert "The war ended." not in character_knowledge_report(scene, "Bob")

        await set_known_by(scene, EntryVisibility(mode="owner"))
        assert known_by_line(scene, "S1") == "Known by: nobody"


class TestPresenceFilter:
    def doc(self, identity, typ, present):
        meta = {"typ": typ, "presence_known": True, "present": json.dumps(present)}
        return MemoryDocument("x", meta, identity, "x")

    async def test_static_known_by_blocks_memory_retrieval(self, scene):
        scene.history.append(CharacterMessage(message="Alice: Bob fought.", id=5))
        await set_known_by(scene, EntryVisibility(mode="list", characters=["Alice"]))
        gate = RetrievalFilter(KnowledgeIndex.from_scene(scene), scene, "Carol")

        assert gate.rejection(self.doc("S1", "history", ["Alice"])) == "presence"


class TestSharedAndSaved:
    async def test_a_loading_scene_writes_no_memory_from_the_shared_entries(
        self, scene
    ):
        from talemate.context import SceneIsLoading

        shared = SharedContext(
            filepath=Path("shared.json"),
            share_static_history=True,
            static_history=[
                ArchiveEntry(id="S1", text="The war ended.", ts=0, present=["Carol"])
            ],
        )
        with (
            patch(
                "talemate.shared_context.emit_archive_add", AsyncMock()
            ) as archive_add,
            SceneIsLoading(scene),
        ):
            await shared.apply_static_history(scene, relative=False)
        archive_add.assert_not_awaited()
        assert static_entry(scene)["present"] == ["Carol"]

    async def test_a_linked_scene_updates_the_audience_of_a_changed_entry(self, scene):
        shared = SharedContext(
            filepath=Path("shared.json"),
            share_static_history=True,
            static_history=[
                ArchiveEntry(id="S1", text="The war ended.", ts=0, present=["Carol"])
            ],
        )
        with (
            patch(
                "talemate.shared_context.emit_archive_add", AsyncMock()
            ) as archive_add,
        ):
            await shared.apply_static_history(scene, relative=False)
            # the entry's own memory document takes the new audience, once
            archive_add.assert_awaited_once()
            assert archive_add.await_args.args[1].id == "S1"
            assert archive_add.await_args.args[1].present == ["Carol"]
            await shared.apply_static_history(scene, relative=False)
            archive_add.assert_awaited_once()

    async def test_loading_keeps_the_stored_audience(self, persistence_scene_factory):
        from talemate.load import load_scene_from_data

        saved_scene = persistence_scene_factory()
        saved_scene.character_data = {"Alice": Character(name="Alice")}
        saved_scene.archived_history = [
            {"id": "S1", "text": "The war ended.", "ts": 0, "present": ["Alice"]}
        ]
        saved = deepcopy(saved_scene.serialize)
        restored = persistence_scene_factory()
        await load_scene_from_data(restored, saved)
        assert static_entry(restored)["present"] == ["Alice"]


class TestHandler:
    @pytest.fixture
    def handler(self, scene):
        from talemate.server.world_state_manager.history import HistoryMixin

        class Handler(HistoryMixin):
            def __init__(self):
                self.scene = scene
                self.failed = []
                self.handle_request_scene_history = AsyncMock()
                self.signal_operation_done = AsyncMock()

            @property
            def world_state_manager(self):
                return WorldStateManager(scene)

            async def signal_operation_failed(self, message, **kwargs):
                self.failed.append((message, kwargs.get("failed_action")))

        return Handler()

    async def test_sets_the_audience_and_sends_the_history(self, scene, handler):
        with (
            ActiveScene(scene),
            patch("talemate.world_state.manager.emit_archive_add", AsyncMock()),
            patch.object(get_agent("memory"), "add_many", AsyncMock()),
        ):
            await handler.handle_set_history_entry_known_by(
                {
                    "entry_id": "S1",
                    "visibility": {"mode": "list", "characters": ["Bob"]},
                }
            )
        assert static_entry(scene)["present"] == ["Bob"]
        handler.handle_request_scene_history.assert_awaited_once()
        handler.signal_operation_done.assert_awaited_once()

    async def test_reports_a_refusal(self, scene, handler):
        await handler.handle_set_history_entry_known_by(
            {"entry_id": "A1", "visibility": {"mode": "everyone"}}
        )
        assert handler.failed == [
            (
                "Only a static history entry has a Known by setting.",
                "set_history_entry_known_by",
            )
        ]
        handler.handle_request_scene_history.assert_not_awaited()
