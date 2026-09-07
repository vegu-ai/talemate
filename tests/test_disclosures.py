from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from _node_test_helpers import run_node
from talemate.agents.context import ActiveAgent
from talemate.character import Character
from talemate.context import ActiveScene
from talemate.game.engine.nodes.knowledge import GrantKnowledge
from talemate.history import ArchiveEntry, LayeredArchiveEntry
from talemate.instance import get_agent
from talemate.knowledge.context import project_character_history
from talemate.knowledge.disclosures import grant_disclosure, disclosure_text
from talemate.knowledge.graph import facts_about
from talemate.knowledge.perspectives import (
    set_source_perspectives,
    select_character_view,
    source_reference,
)
from talemate.knowledge.schema import ParsedFact
from talemate.knowledge.summaries import summary_inputs
from talemate.load import load_scene_from_data
from talemate.scene_message import NarratorMessage
from talemate.tale_mate import Actor, Scene
from talemate.world_state import ManualContext

LOCATION = "The ledger is under the bed."
PLAN = "Alice plans to betray the entire crew at dawn."


def append(scene, text="The rain stops."):
    message = NarratorMessage(message=text)
    scene.history.append(message)
    set_source_perspectives(
        scene,
        "message",
        message.id,
        [{"audience": ["Alice", "Bob", "Cara"], "status": "ready", "text": text}],
    )
    return message


@pytest.fixture
def disclosure_scene(scene, monkeypatch):
    scene.knowledge_eligibility = "perception"
    scene.history = []
    scene.archived_history = []
    scene.layered_history = []
    for name in ("Alice", "Bob", "Cara"):
        character = Character(name=name, is_player=name == "Alice")
        actor = Actor(character, get_agent("conversation"))
        actor.scene = scene
        scene.actors.append(actor)
        scene.character_data[name] = character
    scene.active_characters = ["Alice", "Bob", "Cara"]
    append(scene)
    scene.archived_history = [
        ArchiveEntry(id="mixed", text=LOCATION + " " + PLAN, start=0, end=0).model_dump(
            exclude_none=True
        )
    ]
    summarizer = get_agent("summarizer")
    summarizer.connect(scene)
    summarizer.actions["archive"].config["extract_facts"].value = False
    monkeypatch.setattr(summarizer, "schedule_audience_summaries", AsyncMock())
    monkeypatch.setattr(
        summarizer.client, "_prompt_generation_error", AsyncMock(return_value="cancel")
    )
    monkeypatch.setattr(
        get_agent("conversation"), "rag_build", AsyncMock(return_value=[])
    )
    get_agent("conversation").actions["character_knowledge"].enabled = False
    for method in ("add_many", "delete"):
        monkeypatch.setattr(get_agent("memory"), method, AsyncMock())
    with ActiveScene(scene):
        yield scene, summarizer


@pytest.mark.asyncio
async def test_partial_grant_renders_only_selected_information_for_grantee(
    disclosure_scene,
):
    scene, _ = disclosure_scene
    previous = deepcopy(scene.history[0].model_dump())
    archive = deepcopy(scene.archived_history)
    result = await run_node(
        GrantKnowledge(),
        scene=scene,
        inputs={"character": "Bob", "target": "mixed", "information": LOCATION},
    )
    assert result["edge"] is None
    assert scene.world_state.knowledge == []
    assert result["disclosure"]["text"] == LOCATION
    assert scene.history[0].model_dump() == previous
    assert scene.archived_history == archive
    conversation = get_agent("conversation")
    for name in ("Bob", "Cara"):
        with ActiveAgent(conversation, conversation.build_prompt_default):
            prompt = (
                await conversation.build_prompt_default(scene.character_data[name])
            ).render()
        assert (LOCATION in prompt) == (name == "Bob")
        assert PLAN not in prompt
    assert LOCATION not in "\n".join(
        project_character_history(scene, "Bob", before_message_id=scene.history[0].id)
    )


@pytest.mark.parametrize(
    "kwargs", [{}, {"text": " "}, {"text": LOCATION, "whole_entry": "false"}]
)
def test_partial_requires_valid_explicit_information(disclosure_scene, kwargs):
    scene, _ = disclosure_scene
    original = scene.knowledge
    with pytest.raises(ValueError):
        grant_disclosure(scene, "Bob", "mixed", **kwargs)
    assert scene.knowledge == original


@pytest.mark.parametrize("target", ["missing", "Alice.nonexistent", "", " "])
def test_unresolved_sources_create_nothing(disclosure_scene, target):
    scene, _ = disclosure_scene
    original = scene.knowledge
    with pytest.raises(ValueError):
        grant_disclosure(scene, "Bob", target, text=LOCATION)
    assert scene.knowledge == original


def test_unknown_audience_and_legacy_cannot_create_disclosures(disclosure_scene):
    scene, _ = disclosure_scene
    with pytest.raises(ValueError, match="audience"):
        grant_disclosure(scene, "Nobody", "mixed", text=LOCATION)
    scene.knowledge_eligibility = "legacy"
    with pytest.raises(ValueError, match="perception"):
        grant_disclosure(scene, "Bob", "mixed", text=LOCATION)


def test_whole_entry_copies_current_content_and_source_is_historical(disclosure_scene):
    scene, _ = disclosure_scene
    grant = grant_disclosure(scene, "Bob", "mixed", whole_entry=True)
    assert grant.text == LOCATION + " " + PLAN
    scene.archived_history.clear()
    assert LOCATION in "\n".join(project_character_history(scene, "Bob"))
    assert PLAN in "\n".join(project_character_history(scene, "Bob"))
    assert grant.origin == "mixed"
    with pytest.raises(ValueError):
        grant_disclosure(scene, "Cara", "mixed", whole_entry=True)


@pytest.mark.parametrize(
    "target", ["Alice.description", "Alice.secret", "Alice.detail.secret", "world"]
)
def test_authored_sources_resolve_without_inventing_a_conversation(
    disclosure_scene, target
):
    scene, _ = disclosure_scene
    character = scene.character_data["Alice"]
    character.description = "A sailor."
    character.base_attributes["secret"] = PLAN
    character.details["secret"] = PLAN
    scene.world_state.manual_context["world"] = ManualContext(id="world", text=PLAN)
    grant = grant_disclosure(scene, "Bob", target, text=LOCATION)
    assert grant.text == LOCATION
    assert grant.origin == target
    assert len(scene.history) == 1


@pytest.mark.asyncio
async def test_summary_order_and_actor_prefix_do_not_backdate_a_grant(
    disclosure_scene, monkeypatch
):
    scene, summarizer = disclosure_scene
    before = scene.history[0]
    first = grant_disclosure(scene, "Bob", "mixed", text=LOCATION)
    middle = append(scene, "Bob reads a map.")
    second = grant_disclosure(
        scene, "Bob", "mixed", text="Alice says the ledger might be a decoy."
    )
    last = append(scene, "The sun rises.")
    assert first.acquired.ts == second.acquired.ts
    assert first.acquired.order < second.acquired.order
    earlier = summary_inputs(scene, scene.archived_history[0], 0)
    assert all(LOCATION not in " ".join(item.texts) for item in earlier.values())
    later = ArchiveEntry(id="later", text="READER", start=1, end=2).model_dump(
        exclude_none=True
    )
    scene.archived_history.append(later)
    inputs = summary_inputs(scene, later, 0)
    assert inputs["Bob"].texts == (
        disclosure_text(first),
        "Bob reads a map.",
        disclosure_text(second),
        "The sun rises.",
    )
    assert LOCATION not in " ".join(inputs["Cara"].texts)
    assert [ref.id for ref in inputs["Bob"].sources if ref.kind == "disclosure"] == [
        first.id,
        second.id,
    ]
    assert first.text in " ".join(
        project_character_history(scene, "Bob", before_message_id=middle.id)
    )
    assert second.text not in " ".join(
        project_character_history(scene, "Bob", before_message_id=middle.id)
    )
    assert second.text in " ".join(
        project_character_history(scene, "Bob", before_message_id=last.id)
    )
    monkeypatch.setattr(
        summarizer, "summarize", AsyncMock(side_effect=lambda text, **kw: text)
    )
    monkeypatch.setattr(
        summarizer, "summarize_events", AsyncMock(side_effect=lambda text, **kw: text)
    )
    await summarizer.ensure_summary_views(scene, "later")
    projected = " ".join(project_character_history(scene, "Bob"))
    assert projected.count(LOCATION) == 1
    assert (
        projected.index(first.text)
        < projected.index("Bob reads")
        < projected.index(second.text)
    )
    layer = LayeredArchiveEntry(
        id="layer", text="READER LAYER", start=1, end=1
    ).model_dump(exclude_none=True)
    scene.layered_history = [[layer]]
    await summarizer.ensure_summary_views(scene, "layer", layer=1)
    assert (
        LOCATION
        in select_character_view(
            scene, source_reference(scene, "summary", "layer", layer=1), "Bob"
        ).text
    )
    assert PLAN not in " ".join(project_character_history(scene, "Bob"))
    assert LOCATION not in " ".join(project_character_history(scene, "Cara"))
    assert before.id == scene.history[0].id


@pytest.mark.asyncio
async def test_saved_grant_survives_fact_regeneration_and_deleted_boundary(
    disclosure_scene, monkeypatch
):
    scene, summarizer = disclosure_scene
    first = grant_disclosure(scene, "Bob", "mixed", text=LOCATION)
    reference = source_reference(scene, "disclosure", first.id)
    summarizer.actions["archive"].config["extract_facts"].value = True
    monkeypatch.setattr(
        summarizer,
        "summarize",
        AsyncMock(
            return_value=(LOCATION, [ParsedFact(text=LOCATION, subjects=["ledger"])])
        ),
    )
    assert await summarizer.rebuild_supported_facts(scene, [reference]) == "ok"
    original = deepcopy(scene.world_state.facts)
    # The original archive is disposable; learning is not tied to its fact IDs.
    scene.archived_history.clear()
    scene.delete_message(scene.history[0].id)
    saved = deepcopy(scene.serialize)
    restored = Scene()
    monkeypatch.setattr(restored, "commit_to_memory", AsyncMock())
    monkeypatch.setattr(restored, "add_to_recent_scenes", AsyncMock())
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "set_db", AsyncMock(), raising=False)
    monkeypatch.setattr(memory, "close_db", Mock(), raising=False)
    monkeypatch.setattr(
        memory, "get_document", AsyncMock(return_value={}), raising=False
    )
    await load_scene_from_data(restored, saved, name="disclosure-test.json")
    assert restored.knowledge.disclosures == (first,)
    assert restored.world_state.facts == original
    new = NarratorMessage(message="A later scene begins.")
    assert new.id > first.message_id_boundary
    restored.history.append(new)
    set_source_perspectives(
        restored,
        "message",
        new.id,
        [{"audience": ["Bob"], "status": "ready", "text": new.message}],
    )
    assert LOCATION in " ".join(
        project_character_history(restored, "Bob", before_message_id=new.id)
    )
    summarizer.connect(restored)
    with ActiveScene(restored):
        assert await summarizer.rebuild_supported_facts(restored, [reference]) == "ok"
    assert facts_about(restored, "ledger", character="Bob")[0].text == LOCATION
    assert facts_about(restored, "ledger", character="Cara") == []


@pytest.mark.asyncio
async def test_real_author_handler_validates_then_indexes_only_disclosure(
    disclosure_scene, monkeypatch
):
    from talemate.server.world_state_manager import WorldStateManagerPlugin

    scene, summarizer = disclosure_scene
    websocket = Mock(scene=scene)
    plugin = WorldStateManagerPlugin(websocket)
    monkeypatch.setattr(scene.config.game.general, "auto_save", True)
    monkeypatch.setattr(scene, "save", AsyncMock())
    summarizer.actions["archive"].config["extract_facts"].value = True
    extract = AsyncMock(return_value=(LOCATION, [ParsedFact(text=LOCATION)]))
    monkeypatch.setattr(summarizer, "summarize", extract)
    task = await plugin.handle_grant_disclosure(
        {
            "name": "Bob",
            "target": "mixed",
            "information": LOCATION,
            "request_id": "grant-a",
        }
    )
    await task
    disclosure = scene.knowledge.disclosures[0]
    assert extract.call_args.args[0] == LOCATION
    assert extract.call_args.kwargs["audience"] == ("Bob",)
    assert (
        next(iter(scene.world_state.facts.values())).contributions[0].source.id
        == disclosure.id
    )
    assert scene.save.await_count == 1
    messages = [call.args[0] for call in websocket.queue_put.call_args_list]
    assert [m for m in messages if m["action"] == "disclosure_indexed"][0]["data"][
        "name"
    ] == "Bob"
    refreshes = [m for m in messages if m["action"] == "character_knowledge"]
    assert len(refreshes) == 2
    assert all(m["request_id"] == "grant-a" for m in refreshes)
    snapshot = scene.knowledge
    for payload in (
        {"target": "removed"},
        {"whole_entry": "false"},
        {"name": "Nobody"},
    ):
        task = await plugin.handle_grant_disclosure(
            {"name": "Bob", "target": "mixed", "information": LOCATION, **payload}
        )
        await task
        assert websocket.queue_put.call_args.args[0]["action"] == "operation_done"
        assert (
            websocket.queue_put.call_args.args[0]["failed_action"] == "grant_disclosure"
        )
        assert scene.knowledge == snapshot
    assert extract.await_count == 1


@pytest.mark.asyncio
async def test_extraction_failure_keeps_disclosure_and_reports_failed(
    disclosure_scene, monkeypatch
):
    scene, summarizer = disclosure_scene
    summarizer.actions["archive"].config["extract_facts"].value = True
    monkeypatch.setattr(summarizer, "summarize", AsyncMock(return_value=("", None)))
    result = await run_node(
        GrantKnowledge(),
        scene=scene,
        inputs={"character": "Bob", "target": "mixed", "information": LOCATION},
    )
    assert "failed" in result["text"]
    assert scene.knowledge.disclosures[0].text == LOCATION
    assert scene.world_state.facts == {}
    assert LOCATION in " ".join(project_character_history(scene, "Bob"))


def test_delayed_perception_does_not_use_a_later_disclosure(disclosure_scene):
    from talemate.agents.summarize.perceptions import perception_context

    scene, _ = disclosure_scene
    old = append(scene)
    old.knowledge = None
    grant_disclosure(scene, "Bob", "mixed", text=LOCATION)
    set_source_perspectives(
        scene, "message", old.id, [{"audience": ["Bob"], "status": "pending"}]
    )
    context = perception_context(scene, old)
    assert LOCATION not in str(context)


def test_disclosure_target_uses_canonical_precedence_and_offered_ids(disclosure_scene):
    from talemate.knowledge.schema import Fact

    scene, _ = disclosure_scene
    alice = scene.character_data["Alice"]
    alice.description = "Sailor description."
    alice.base_attributes.update(
        {"age": 34, "_secret": "private", "detail.secret": "attribute"}
    )
    alice.details["secret"] = "detail"
    scene.world_state.manual_context["mixed"] = ManualContext(
        id="mixed", text="world takes precedence"
    )
    scene.world_state.facts["mixed"] = Fact(id="mixed", text="fact loses")
    offered = [
        t for t in scene.world_state_manager.knowledge_targets() if t.id == "mixed"
    ]
    assert len(offered) == 1 and offered[0].kind == "world_entry"
    assert (
        grant_disclosure(scene, "Bob", "mixed", whole_entry=True).text
        == "world takes precedence"
    )
    assert (
        grant_disclosure(scene, "Bob", "Alice.description.0", whole_entry=True).text
        == alice.description
    )
    assert (
        grant_disclosure(scene, "Bob", "Alice.description.0", text=LOCATION).origin
        == "Alice.description"
    )
    assert (
        grant_disclosure(scene, "Bob", "Alice.detail.secret", whole_entry=True).text
        == "detail"
    )
    assert grant_disclosure(scene, "Bob", "Alice.age", text=LOCATION).text == LOCATION
    for target in (
        "Alice._secret",
        "Alice.missing",
        "Alice.scenario_context",
        "Alice.name",
    ):
        with pytest.raises(ValueError, match="unresolved"):
            grant_disclosure(scene, "Bob", target, text=LOCATION)
    with pytest.raises(ValueError, match="no text"):
        grant_disclosure(scene, "Bob", "Alice.age", whole_entry=True)


def test_required_acquisition_boundary(disclosure_scene):
    from pydantic import ValidationError
    from talemate.knowledge.perspective_models import Disclosure

    scene, _ = disclosure_scene
    data = grant_disclosure(scene, "Bob", "mixed", text=LOCATION).model_dump()
    for value in (None, -1):
        with pytest.raises(ValidationError):
            Disclosure.model_validate({**data, "message_id_boundary": value})
    data.pop("message_id_boundary")
    with pytest.raises(ValidationError):
        Disclosure.model_validate(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_director_grant_wording_matches_mode(disclosure_scene, enabled):
    import json
    from pathlib import Path
    from talemate.game.engine.nodes.knowledge import (
        GrantKnowledgeMetadata,
        GrantKnowledgeConfirmation,
    )

    scene, _ = disclosure_scene
    scene.knowledge_eligibility = "perception" if enabled else "legacy"
    module = json.loads(
        Path(
            "src/talemate/agents/director/modules/director-action-update-context.json"
        ).read_text()
    )
    nodes = module["nodes"]
    metadata = GrantKnowledgeMetadata()
    for key, value in nodes["7bf23a31-8362-4753-88df-09450433babf"][
        "properties"
    ].items():
        metadata.set_property(key, value)
    instructions = metadata.normalized_input_value("instructions")
    examples = metadata.normalized_input_value("examples")
    confirmation = GrantKnowledgeConfirmation()
    for key, value in nodes["00f9caa5-c93e-48b1-967c-56025f02d647"][
        "properties"
    ].items():
        confirmation.set_property(key, value)
    result = await run_node(
        confirmation,
        scene=scene,
        inputs={
            "variables": {
                "character": "Bob",
                "name": "Archive",
                "context_id": "history:id",
                "information": LOCATION,
                "whole_entry": False,
            }
        },
    )
    if enabled:
        assert "independent disclosure" in instructions
        assert examples[0]["information"] == LOCATION
        assert LOCATION in result["result"] and "Whole entry: False" in result["result"]
    else:
        assert "disclosure" not in instructions and "perception" not in instructions
        assert examples[0]["note"] == "She found it behind the cupboard."
        assert (
            result["result"]
            == "Grant `Bob` knowledge of `Archive` (Context ID `history:id`)"
        )


@pytest.mark.asyncio
async def test_author_failure_correlates_missing_name_and_refreshes_failed_facts(
    disclosure_scene, monkeypatch
):
    from talemate.server.world_state_manager import WorldStateManagerPlugin

    scene, summarizer = disclosure_scene
    websocket = Mock(scene=scene)
    plugin = WorldStateManagerPlugin(websocket)
    monkeypatch.setattr(scene.config.game.general, "auto_save", True)
    monkeypatch.setattr(scene, "save", AsyncMock())
    task = await plugin.handle_grant_disclosure(
        {"target": "mixed", "information": LOCATION, "request_id": "missing-name"}
    )
    await task
    error = websocket.queue_put.call_args.args[0]
    assert error["action"] == "operation_done" and error["request_id"] == "missing-name"
    assert error["failed_action"] == "grant_disclosure" and error["error"]
    scene.save.assert_not_awaited()
    summarizer.actions["archive"].config["extract_facts"].value = True
    monkeypatch.setattr(summarizer, "summarize", AsyncMock(return_value=("", None)))
    task = await plugin.handle_grant_disclosure(
        {"name": "Bob", "target": "mixed", "information": LOCATION}
    )
    await task
    assert scene.knowledge.disclosures[0].text == LOCATION
    indexed = [
        c.args[0]
        for c in websocket.queue_put.call_args_list
        if c.args[0]["action"] == "disclosure_indexed"
    ]
    assert indexed[0]["data"]["facts_status"] == "failed"
    assert indexed[0]["data"]["name"] == "Bob"
    assert scene.save.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("blurb", ["Imported card blurb.", ""])
async def test_imported_description_grant_matches_memory_document(
    disclosure_scene, blurb
):
    scene, _ = disclosure_scene
    character = scene.character_data["Alice"]
    character.description = blurb
    character.base_attributes["description"] = "Extracted character sheet."
    memory = Mock(add_many=AsyncMock())
    await character.commit_to_memory(memory)
    document = next(
        item
        for item in memory.add_many.call_args.args[0]
        if item["id"] == "Alice.description"
    )
    grant = grant_disclosure(scene, "Bob", document["id"], whole_entry=True)
    assert grant.text == "Extracted character sheet."
    assert document["text"] == f"Alice's description: {grant.text}"
    assert (
        grant_disclosure(scene, "Bob", "Alice.description.0", whole_entry=True).text
        == grant.text
    )


def test_standalone_detail_prefix_attribute_can_be_disclosed(disclosure_scene):
    scene, _ = disclosure_scene
    character = scene.character_data["Alice"]
    character.base_attributes["detail.secret"] = LOCATION
    assert "secret" not in character.details
    target = next(
        item
        for item in scene.world_state_manager.knowledge_targets()
        if item.id == "Alice.detail.secret"
    )
    assert target.kind == "attribute"
    assert grant_disclosure(scene, "Bob", target.id, whole_entry=True).text == LOCATION
