from unittest.mock import AsyncMock

import pytest

import test_reinforcement_perspectives as cases
from _perception_response_helpers import excluding_passage
from test_reinforcement_review import response
from talemate.agents.visual.schema import PromptFinalizer
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.game.engine.context_id import context_id_item_from_string, compress_name
from talemate.instance import get_agent
from talemate.knowledge.memory import audience_documents
from talemate.knowledge.reinforcements import entry_binding
from talemate.knowledge.schema import EntryVisibility
from talemate.prompts import Prompt
from talemate.shared_context import SharedContext
from talemate.world_state import Reinforcement

pytestmark = pytest.mark.asyncio
setup = cases.setup
indexed_scene = cases.indexed_scene
chroma_clients = cases.chroma_clients


@pytest.mark.parametrize("changed", [False, True])
async def test_context_id_world_write_compares_before_mutating_live_entry(
    setup, changed
):
    scene, _, request = setup
    await cases.apply(scene, request)
    entry = scene.world_state.manual_context[cases.QUESTION]
    binding = entry.reinforcement
    item = await context_id_item_from_string(
        f"world_entry.manual:{compress_name(cases.QUESTION)}", scene
    )
    assert item.entry is entry
    text = "Public replacement." if changed else entry.text
    await item.set(scene, text)
    assert await item.get(scene) == text
    assert scene.world_state.manual_context[cases.QUESTION].text == text
    assert entry_binding(scene, cases.QUESTION) == (None if changed else binding)
    rows = [
        r for r in audience_documents(scene).values() if r["group"] == ("authored",)
    ]
    assert rows
    if changed:
        assert all(r["meta"]["knowledge_common"] for r in rows)
        assert all("Public replacement." in r["text"] for r in rows)
    else:
        assert all(not r["meta"]["knowledge_common"] for r in rows)
        assert all(r["text"] == cases.VISIBLE for r in rows)


@pytest.mark.parametrize("changed", [False, True])
async def test_context_db_detail_round_trips_real_prefixed_document(
    indexed_scene, monkeypatch, changed
):
    scene, memory, _ = indexed_scene
    request = AsyncMock(
        return_value=response(Elmer="Elmer notices the lantern.", Marie=None)
    )
    monkeypatch.setattr(Prompt, "request", excluding_passage(request))
    monkeypatch.setattr(
        get_agent("summarizer").client,
        "_prompt_generation_error",
        AsyncMock(side_effect=AssertionError("unexpected perception failure")),
    )
    reinforcement = Reinforcement(
        question=cases.QUESTION, character="Marie", insert="all-context"
    )
    scene.world_state.reinforce.append(reinforcement)
    world = get_agent("world_state")
    await world._apply_reinforcement(
        reinforcement,
        world._prepare_reinforcement(reinforcement, False),
        cases.READER,
        False,
    )
    manager = scene.world_state_manager
    identity = f"Marie.detail.{cases.QUESTION}"
    binding = entry_binding(scene, identity)
    (row,) = (await manager.get_context_db_entries(f"id:{identity}")).entries
    assert row.text == f"Marie - {cases.QUESTION}: {cases.READER}"
    assert row.meta["typ"] == "details"
    text = (
        row.text.replace(cases.READER, "Public replacement.") if changed else row.text
    )
    for _ in range(2):
        await manager.update_context_db_entry(row.id, text, row.meta)
        (row,) = (await manager.get_context_db_entries(f"id:{identity}")).entries
        assert row.text == text
        assert scene.character_data["Marie"].details[cases.QUESTION] == (
            "Public replacement." if changed else cases.READER
        )
        assert entry_binding(scene, identity) == (None if changed else binding)
        visible = await memory.get_document(identity, viewer="Elmer")
        assert visible
        if changed:
            assert all("Public replacement." in doc.raw for doc in visible.values())
        else:
            assert all(
                doc.raw == "Elmer notices the lantern." for doc in visible.values()
            )
            assert not await memory.get_document(identity, viewer="Marie")
            assert all(not doc.meta["knowledge_common"] for doc in visible.values())


async def shared_file(tmp_path, character):
    path = tmp_path / "shared.json"
    shared = SharedContext(filepath=path, character_data={character.name: character})
    await shared.write_to_file()
    return await SharedContext(filepath=path).init_from_file()


@pytest.mark.parametrize("existing", [False, True])
async def test_file_loaded_shared_character_preserves_models_and_can_rename(
    scene, tmp_path, monkeypatch, existing
):
    scene.knowledge_eligibility = "legacy"
    character = Character(
        name="Bob",
        shared=True,
        details={"x": "Private", "y": "Listed"},
        shared_details=["x", "y"],
        visibility={
            "detail.x": EntryVisibility(mode="owner"),
            "detail.y": EntryVisibility(mode="list", characters=["Bob"]),
        },
        visual_finalizers=[PromptFinalizer(match="ugly", replace="plain")],
    )
    shared = await shared_file(tmp_path, character)
    scene.character_data = {"Bob": Character(name="Bob")} if existing else {}
    with ActiveScene(scene):
        await shared.update_to_scene(scene)
        imported = scene.character_data["Bob"]
        assert isinstance(imported.visibility["detail.x"], EntryVisibility)
        assert isinstance(imported.visual_finalizers[0], PromptFinalizer)
        assert imported.visual_finalizers[0].match == "ugly"
        assert not imported.visibility["detail.x"].allows("Alice", "Bob")
        imported.rename("Robert")
        assert scene.character_data["Robert"] is imported
        assert imported.visibility["detail.y"].characters == ["Robert"]
    assert shared.character_data["Bob"].visibility["detail.y"].characters == ["Bob"]


async def test_shared_file_removal_unshares_only_the_removed_character(
    scene, tmp_path, monkeypatch
):
    scene.knowledge_eligibility = "legacy"
    removed = Character(
        name="X", shared=True, details={"x": "old"}, shared_details=["x"]
    )
    added = Character(
        name="Y",
        shared=True,
        details={"y": "shared", "private": "local"},
        shared_details=["y"],
    )
    scene.character_data = {"X": removed}
    shared = await shared_file(tmp_path, added)
    with ActiveScene(scene):
        await shared.update_to_scene(scene)
        assert not removed.shared
        assert scene.character_data["Y"].shared
        assert scene.character_data["Y"].shared_details == ["y"]
        exported = SharedContext(filepath=tmp_path / "exported.json")
        await exported.init_from_scene(scene)
        assert set(exported.character_data) == {"Y"}


@pytest.mark.parametrize(
    "refresh", ["changed_answer", "unchanged_answer", "detail_text"]
)
async def test_context_db_save_does_not_overwrite_a_refresh_during_document_read(
    indexed_scene, monkeypatch, refresh
):
    scene, memory, _ = indexed_scene
    request = AsyncMock(
        return_value=response(Elmer="Elmer notices the lantern.", Marie=None)
    )
    monkeypatch.setattr(Prompt, "request", excluding_passage(request))
    monkeypatch.setattr(
        get_agent("summarizer").client,
        "_prompt_generation_error",
        AsyncMock(side_effect=AssertionError("unexpected perception failure")),
    )
    reinforcement = Reinforcement(
        question=cases.QUESTION, character="Marie", insert="all-context"
    )
    scene.world_state.reinforce.append(reinforcement)
    world = get_agent("world_state")
    await world._apply_reinforcement(
        reinforcement,
        world._prepare_reinforcement(reinforcement, False),
        cases.READER,
        False,
    )
    manager = scene.world_state_manager
    identity = f"Marie.detail.{cases.QUESTION}"
    character = scene.character_data["Marie"]
    old_binding = entry_binding(scene, identity)
    (row,) = (await manager.get_context_db_entries(f"id:{identity}")).entries
    get_document = memory.get_document
    refreshed = {}

    async def refresh_after_read(*args, **kwargs):
        previous = await get_document(*args, **kwargs)
        # Interleave the real writer after the database read, before it returns to the guard.
        monkeypatch.setattr(memory, "get_document", get_document)
        if refresh == "detail_text":
            # A text-only mutation must also invalidate the comparison snapshot.
            character.details[cases.QUESTION] = "Newer detail text."
            await character.commit_single_detail_to_memory(
                memory, cases.QUESTION, "Newer detail text."
            )
            assert entry_binding(scene, identity) is old_binding
        else:
            answer = (
                "The lantern is dark; poison remains hidden."
                if refresh == "changed_answer"
                else cases.READER
            )
            request.return_value = response(Elmer="Elmer sees darkness.", Marie=None)
            await world._apply_reinforcement(
                reinforcement,
                world._prepare_reinforcement(reinforcement, False),
                answer,
                False,
            )
            assert entry_binding(scene, identity) is not old_binding
        refreshed["binding"] = entry_binding(scene, identity)
        refreshed["text"] = character.details[cases.QUESTION]
        refreshed["document"] = (await get_document(identity))[identity].raw
        return previous

    monkeypatch.setattr(memory, "get_document", refresh_after_read)
    await manager.update_context_db_entry(row.id, row.text, row.meta)
    assert entry_binding(scene, identity) is refreshed["binding"]
    assert character.details[cases.QUESTION] == refreshed["text"]
    assert (await get_document(identity))[identity].raw == refreshed["document"]
    if refresh != "detail_text":
        visible = await memory.get_document(identity, viewer="Elmer")
        expected = (
            "Elmer sees darkness."
            if refresh == "changed_answer"
            else "Elmer notices the lantern."
        )
        assert visible and all(doc.raw == expected for doc in visible.values())
        assert not await memory.get_document(identity, viewer="Marie")
