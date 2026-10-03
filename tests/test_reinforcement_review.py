from _knowledge_step_helpers import push_and_step
from talemate.knowledge.step import knowledge_step, repair_knowledge
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import test_reinforcement_perspectives as cases
from talemate.agents.memory import ChromaDBMemoryAgent
from talemate.agents.summarize.perceptions import perception_context, perception_prefix
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.memory import audience_documents
from talemate.knowledge.perspective_models import SourceReference
from talemate.knowledge.perspectives import (
    add_disclosure,
    source_reference,
    validate_saved_knowledge,
)
from talemate.knowledge.reinforcements import entry_binding
from talemate.load import load_scene_from_data
from talemate.prompts import Prompt
from talemate.scene_message import (
    ContextInvestigationMessage,
    NarratorMessage,
    ReinforcementMessage,
    reset_message_id,
    advance_message_id,
)
from talemate.shared_context import SharedContext
from talemate.world_state import Reinforcement, WorldState

pytestmark = pytest.mark.asyncio
setup = cases.setup


def response(**views):
    return cases.result(
        json.dumps(
            {
                "views": [
                    {
                        "audience": [name],
                        "status": "ready" if text else "omitted",
                        "text": text,
                    }
                    for name, text in views.items()
                ]
            }
        )
    )


@pytest.mark.parametrize("orphan", [False, True])
async def test_actual_loader_binds_direct_sources_before_any_new_message(
    setup, monkeypatch, orphan
):
    scene, _, request = setup
    reinforcement = await cases.apply(scene, request)
    identity = reinforcement.perspective_source.id
    saved = json.loads(scene.json)
    if orphan:
        saved["world_state"]["reinforce"] = []
    scene.world_state = WorldState()
    scene.history = []
    monkeypatch.setattr(get_agent("memory"), "set_db", AsyncMock())
    monkeypatch.setattr(scene, "add_to_recent_scenes", AsyncMock())
    reset_message_id()
    await load_scene_from_data(scene, saved, name="reinforcement-loader.json")
    if not orphan:
        restored = scene.world_state.reinforce[0].perspective_source
        assert restored._knowledge_scene() is scene
    assert ReinforcementMessage(message="next").id > identity
    assert (source_reference(scene, "message", identity) is None) == orphan
    validate_saved_knowledge(json.loads(scene.json))


async def test_new_answer_uses_current_evidence_disclosure_and_presence(setup):
    scene, summarizer, request = setup
    reinforcement = await cases.apply(scene, request)
    old = reinforcement.perspective_source
    learned = NarratorMessage(message="Bob sees the lantern go dark.")
    request.return_value = response(Alice=None, Bob=learned.message)
    await push_and_step(scene, learned)
    disclosure = add_disclosure(
        scene, audience=["Bob"], text="The current code is 5298."
    )
    scene.active_characters = ["Bob"]
    request.return_value = response(Bob="Bob sees the lantern is dark.")
    await scene.world_state.add_reinforcement(
        cases.QUESTION, answer="The lantern is dark.", insert="all-context"
    )
    await knowledge_step(scene)
    current = reinforcement.perspective_source
    context = request.call_args.kwargs["vars"]["context"]
    assert current.id > learned.id > old.id
    assert (
        current.knowledge.acquired.order
        > disclosure.acquired.order
        > old.knowledge.acquired.order
    )
    assert current.present == ["Bob"]
    assert [actor["name"] for actor in context["cast"]] == ["Bob"]
    assert learned.id in [item["id"] for item in context["prior_physical_context"]]
    assert any(
        "5298" in item["text"] for item in context["cast"][0]["established_knowledge"]
    )
    assert source_reference(scene, "message", old.id) is None
    calls = request.await_count
    await knowledge_step(scene)
    assert reinforcement.perspective_source is current
    assert request.await_count == calls


@pytest.mark.parametrize(
    "sub_type", ["query", "examine", "visual-character", "visual-scene"]
)
async def test_investigation_metadata_describes_reader_operation_and_subject(
    setup, sub_type
):
    scene, _, request = setup
    message = ContextInvestigationMessage(
        message="Only the reader is shown this private detail.", sub_type=sub_type
    )
    message.set_source(
        "narrator", "narrate_character", character="Alice", query="Reader question"
    )
    request.return_value = response(Alice=None, Bob=None)
    await push_and_step(scene, message)
    passage = request.call_args.kwargs["vars"]["context"]["passage"]
    assert passage["sub_type"] == sub_type
    assert passage["subject_character"] == "Alice"
    assert "initiating_character" not in passage


def pin(scene, identity=cases.QUESTION):
    scene.active_pins = [
        SimpleNamespace(
            pin=SimpleNamespace(entry_id=identity),
            title=cases.QUESTION,
            time_aware_text=cases.READER,
            context_id=identity,
        )
    ]


@pytest.mark.parametrize("reason", ["mode", "deleted", "reset_failure"])
async def test_missing_sequential_source_omits_pins_without_blocking(setup, reason):
    scene, _, request = setup
    reinforcement = await cases.apply(
        scene, request, insert="all-context" if reason == "mode" else "sequential"
    )
    pin(scene)
    if reason == "mode":
        await scene.world_state.add_reinforcement(
            cases.QUESTION, answer=cases.READER, insert="sequential"
        )
    elif reason == "deleted":
        scene.pop_history(
            typ="reinforcement", meta_hash=reinforcement.source_for(scene).meta_hash
        )
    else:
        get_agent("world_state")._prepare_reinforcement(reinforcement, True)
    assert reinforcement.source_for(scene) is None
    for template in ["common.extra-context-static", "visual.extra-context"]:
        rendered = Prompt.get(
            template,
            vars={"scene": scene, "knowledge_viewer": "Alice", "technical": True},
        ).render()
        assert (
            "poison" not in rendered
            and "---" not in rendered
            and "ACTIVE PINS" not in rendered
        )


@pytest.mark.parametrize("character", [None, "Bob"])
async def test_authored_entry_is_not_claimed_by_unanswered_tracker_or_reused_name(
    setup, character
):
    scene, _, request = setup
    await cases.apply(scene, request, character=character)
    await scene.world_state.remove_reinforcement(0)
    identity = f"Bob.detail.{cases.QUESTION}" if character else cases.QUESTION
    if character:
        await scene.character_data[character].set_detail(
            cases.QUESTION, "Authored public lantern lore."
        )
    else:
        await scene.world_state_manager.save_world_entry(
            cases.QUESTION, "Authored public lantern lore.", {}
        )
    scene.world_state.reinforce.append(
        Reinforcement(
            question=cases.QUESTION, character=character, insert="all-context"
        )
    )
    await scene.world_state.add_reinforcement(
        cases.QUESTION,
        character=character,
        answer=None,
        insert="all-context",
        interval=20,
    )
    assert entry_binding(scene, identity) is None
    rows = [
        row
        for row in audience_documents(scene).values()
        if row["group"] == ("authored",)
    ]
    assert any(
        "Authored public lantern lore" in row["text"]
        and row["meta"]["knowledge_common"]
        for row in rows
    )
    pin(scene, identity)
    scene.active_pins[0].time_aware_text = "Authored public lantern lore."
    assert "Authored public lantern lore" in cases.render_inserts(scene, "Alice")


@pytest.mark.parametrize("character", [None, "Bob"])
async def test_author_edit_detaches_generated_binding(setup, character):
    scene, _, request = setup
    await cases.apply(scene, request, character=character)
    identity = f"Bob.detail.{cases.QUESTION}" if character else cases.QUESTION
    assert entry_binding(scene, identity) is not None
    if character:
        await scene.character_data[character].set_detail(
            cases.QUESTION, "Public replacement"
        )
    else:
        await scene.world_state_manager.save_world_entry(
            cases.QUESTION, "Public replacement", {}
        )
    assert entry_binding(scene, identity) is None
    assert any(
        "Public replacement" in row["text"] and row["meta"]["knowledge_common"]
        for row in audience_documents(scene).values()
    )


async def test_rename_live_character_reinforcement_leaves_world_question_untouched(
    setup,
):
    scene, summarizer, request = setup
    reinforcement = await cases.apply(scene, request, character="Bob")
    world_question = "Bob. What is he hiding?"
    world = Reinforcement(question=world_question, insert="never")
    scene.world_state.reinforce.append(world)
    agent = get_agent("world_state")
    await agent._apply_reinforcement(
        world, agent._prepare_reinforcement(world, False), cases.READER, False
    )
    world_binding = entry_binding(scene, world_question)
    scene.world_state.reinforce.remove(world)
    scene.character_data["Bob"].rename("Robert")
    assert reinforcement.character == "Robert"
    assert reinforcement.perspective_source.character_name == "Robert"
    assert entry_binding(scene, f"Robert.detail.{cases.QUESTION}") is not None
    assert entry_binding(scene, world_question) == world_binding
    request.return_value = response(Alice=cases.VISIBLE, Robert=None)
    await knowledge_step(scene)
    assert (
        scene.world_state.reinforcement_entry_context(
            f"Robert.detail.{cases.QUESTION}", "Alice"
        )
        == f"# Internal note for Robert - {cases.VISIBLE}"
    )
    assert not scene.world_state.reinforcement_entry_context(world_question, "Alice")
    assert not any(
        "poison" in row["text"] for row in audience_documents(scene).values()
    )


async def test_unrelated_perspective_events_do_not_rederive_authored_group(
    setup, monkeypatch
):
    scene, _, request = setup
    reinforcement = await cases.apply(scene, request)
    memory = ChromaDBMemoryAgent()
    memory.scene = scene
    invalidate = Mock()
    monkeypatch.setattr(memory, "invalidate_audience_index", invalidate)
    reference = source_reference(scene, "message", reinforcement.perspective_source.id)
    for unrelated in [
        SourceReference(kind="message", id=reference.id + 100, revision=1),
        SourceReference(kind="disclosure", id="unrelated", revision=1),
    ]:
        memory._audiences_changed(scene, event=SimpleNamespace(affected=[unrelated]))
        assert ("authored",) not in invalidate.call_args.kwargs["groups"]
    memory._audiences_changed(scene, event=SimpleNamespace(affected=[reference]))
    assert ("authored",) in invalidate.call_args.kwargs["groups"]
    scene.world_state.reinforce.clear()
    memory._audiences_changed(scene, event=SimpleNamespace(affected=[reference]))
    assert ("authored",) in invalidate.call_args.kwargs["groups"]


@pytest.mark.parametrize(
    "character, prefix",
    [(None, "# Internal note - "), ("Bob", "# Internal note for Bob - ")],
)
@pytest.mark.parametrize("insert", ["all-context", "sequential"])
async def test_blocked_perception_keeps_canonical_entry_and_answer_together(
    setup, monkeypatch, character, prefix, insert
):
    scene, summarizer, request = setup
    reinforcement = await cases.apply(
        scene, request, character=character, insert=insert
    )
    request.return_value = cases.result("not JSON")
    monkeypatch.setattr(
        summarizer.client, "_prompt_generation_error", AsyncMock(return_value="ignore")
    )
    new_answer = "The lantern is now dark; poison remains hidden."
    world = get_agent("world_state")
    await world._apply_reinforcement(
        reinforcement,
        world._prepare_reinforcement(reinforcement, False),
        new_answer,
        False,
    )
    with pytest.raises(GenerationCancelled):
        await knowledge_step(scene)
    assert reinforcement.answer == new_answer
    canonical = (
        scene.character_data[character].details[cases.QUESTION]
        if character
        else scene.world_state.manual_context[cases.QUESTION].text
    )
    assert new_answer in canonical
    request.return_value = response(Alice="Alice sees darkness.", Bob=None)
    # the failed analysis waits for Repair
    await repair_knowledge(scene)
    assert reinforcement.context_for(scene, "Alice") == prefix + "Alice sees darkness."


async def test_index_keeps_an_out_of_sync_reinforcement_view(setup, monkeypatch):
    import talemate.knowledge.memory as module

    scene, summarizer, request = setup
    reinforcement = await cases.apply(scene, request)
    reinforcement.perspective_source.message += " Edited."
    reinforcement.answer = reinforcement.perspective_source.message
    summarizer._perception_status(scene, reinforcement.perspective_source, "pending")
    assert all(
        view.stale
        for view in reinforcement.perspective_source.knowledge.views
        if view.status in ("ready", "omitted")
    )
    debug = Mock()
    monkeypatch.setattr(module.log, "debug", debug)
    audience_documents(scene)
    # the last view stays in the index until a repair
    assert not any(
        call.args == ("reinforcement_memory.skip",) and call.kwargs["viewer"] == "Alice"
        for call in debug.call_args_list
    )


async def test_missing_character_record_denies_reinforcement_visibility(setup):
    scene, _, request = setup
    reinforcement = await cases.apply(scene, request, character="Bob")
    scene.character_data.pop("Bob")
    assert not reinforcement.context_for(scene, "Alice")


async def test_shared_prefix_matches_context_and_unchanged_sources_are_not_rebound(
    setup, monkeypatch
):
    scene, summarizer, request = setup
    direct = await cases.apply(scene, request)
    message = NarratorMessage(message="Alice sees rain.")
    await push_and_step(scene, message)
    assert [
        item["id"]
        for item in perception_context(scene, message)["prior_physical_context"]
    ] == [item.id for item in perception_prefix(scene, message.id)]
    set_source = Mock(side_effect=AssertionError("unchanged source rebound"))
    monkeypatch.setattr(type(direct.perspective_source), "set_source", set_source)
    await knowledge_step(scene)
    set_source.assert_not_called()


@pytest.mark.parametrize("viewer", ["Bob", "Alice"])
async def test_omitted_or_denied_pin_has_no_separator_or_section(setup, viewer):
    from talemate.knowledge.schema import EntryVisibility

    scene, _, request = setup
    await cases.apply(scene, request)
    if viewer == "Alice":
        await scene.world_state_manager.set_world_entry_visibility(
            cases.QUESTION, EntryVisibility(mode="owner")
        )
    pin(scene)
    for template in ["common.extra-context-static", "visual.extra-context"]:
        rendered = Prompt.get(
            template,
            vars={"scene": scene, "knowledge_viewer": viewer, "technical": True},
        ).render()
        assert (
            "---" not in rendered
            and "ACTIVE PINS" not in rendered
            and "poison" not in rendered
        )


@pytest.mark.parametrize("insert", ["all-context", "conversation-context", "never"])
async def test_unchanged_scheduled_answer_retains_ready_source_and_acquisition(
    setup, insert
):
    scene, _, request = setup
    reinforcement = await cases.apply(scene, request, insert=insert)
    source = reinforcement.perspective_source
    acquired = source.knowledge.acquired.model_dump()
    views = source.knowledge.model_dump()
    request.side_effect = AssertionError("unchanged answer must not request analysis")
    world = get_agent("world_state")
    await world._apply_reinforcement(
        reinforcement,
        world._prepare_reinforcement(reinforcement, False),
        cases.READER,
        False,
    )
    assert reinforcement.perspective_source is source
    assert source.knowledge.acquired.model_dump() == acquired
    assert source.knowledge.model_dump() == views
    assert request.await_count == 1
    assert (
        reinforcement.context_for(scene, "Alice")
        == f"# Internal note - {cases.VISIBLE}"
    )


@pytest.mark.parametrize("route", ["world", "detail", "detail_defer"])
async def test_unchanged_entry_save_retains_projected_audience(setup, route):
    scene, _, request = setup
    character = None if route == "world" else "Bob"
    prefix = "# Internal note - " if route == "world" else "# Internal note for Bob - "
    await cases.apply(scene, request, character=character)
    identity = f"Bob.detail.{cases.QUESTION}" if character else cases.QUESTION
    binding = entry_binding(scene, identity)
    manager = scene.world_state_manager
    if route == "world":
        entry = scene.world_state.manual_context[identity]
        await manager.save_world_entry(
            identity, entry.text, {**entry.meta, "pin_only": True}
        )
        await manager.set_world_entry_shared(identity, True)
        entry = scene.world_state.manual_context[identity]
        await manager.save_world_entry(identity, entry.text, entry.meta)
        assert scene.world_state.manual_context[identity].shared
    elif route == "detail":
        await scene.character_data[character].set_detail(cases.QUESTION, cases.READER)
    else:
        scene.character_data[character].set_detail_defer(cases.QUESTION, cases.READER)
    assert entry_binding(scene, identity) == binding
    rows = [
        row
        for row in audience_documents(scene).values()
        if row["group"] == ("authored",)
    ]
    assert rows
    assert all(not row["meta"]["knowledge_common"] for row in rows)
    assert all(row["text"] == prefix + cases.VISIBLE for row in rows)
    pin(scene, identity)
    for template in ["common.extra-context-static", "visual.extra-context"]:
        for viewer in ("Alice", "Bob"):
            rendered = Prompt.get(
                template, vars={"scene": scene, "knowledge_viewer": viewer}
            ).render()
            assert "poison" not in rendered
            assert (cases.VISIBLE in rendered) == (viewer == "Alice")


@pytest.mark.parametrize("export", ["init_from_scene", "update_from_scene"])
@pytest.mark.parametrize("character", [None, "Bob"])
async def test_shared_entries_do_not_export_scene_local_source_ids(
    setup, tmp_path, monkeypatch, export, character
):
    scene, summarizer, request = setup
    monkeypatch.setattr(
        summarizer.client,
        "_prompt_generation_error",
        AsyncMock(side_effect=AssertionError("unexpected perception response failure")),
    )
    reinforcement = await cases.apply(scene, request, character=character)
    identity = f"Bob.detail.{cases.QUESTION}" if character else cases.QUESTION
    binding = entry_binding(scene, identity)
    if character:
        original = scene.character_data[character]
        original.shared = True
        original.shared_details = [cases.QUESTION]
    else:
        await scene.world_state_manager.set_world_entry_shared(identity, True)
    shared = SharedContext(filepath=tmp_path / "shared.json")
    await getattr(shared, export)(scene)
    assert entry_binding(scene, identity) == binding
    exported_binding = (
        shared.character_data[character].reinforcement_entries.get(cases.QUESTION)
        if character
        else shared.world_state.manual_context[identity].reinforcement
    )
    assert exported_binding is None
    # Another shared field changes: syncing back must retain the origin's binding.
    if character:
        shared.character_data[character].description = "Shared description."
    else:
        shared.world_state.manual_context[identity].meta["pin_only"] = True
    await shared.update_to_scene(scene)
    assert entry_binding(scene, identity) == binding
    assert "poison" not in scene.world_state.reinforcement_entry_context(
        identity, "Alice"
    )
    # Simulate scene B's independent message namespace with a colliding local source.
    scene.world_state = WorldState()
    reset_message_id()
    advance_message_id(reinforcement.perspective_source.id - 1)
    local = ReinforcementMessage(message="Unrelated local passage.")
    assert local.id == binding.source_id
    local.set_source(
        "world_state", "update_reinforcement", question="Other question", character=None
    )
    request.return_value = response(Alice="Unrelated local view.", Bob=None)
    await push_and_step(scene, local)
    if character:
        scene.character_data.pop(character)
    await shared.update_to_scene(scene)
    if character:
        assert scene.character_data[character] is not shared.character_data[character]
    assert entry_binding(scene, identity) is None
    assert scene.world_state.reinforcement_entry_context(identity, "Alice") is None
    rows = [
        row
        for row in audience_documents(scene).values()
        if row["group"] == ("authored",)
    ]
    assert any(
        cases.READER in row["text"] and row["meta"]["knowledge_common"] for row in rows
    )
    assert all("Unrelated local view" not in row["text"] for row in rows)
