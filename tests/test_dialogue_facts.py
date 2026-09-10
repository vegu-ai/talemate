import json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from talemate.character import Character
from talemate.context import ActiveScene
from talemate.events import GameLoopNewMessageEvent
from talemate.instance import get_agent
from talemate.knowledge.dialogue_facts import (
    invalidate_dialogue_facts,
    prune_invalid_dialogue_facts,
)
from talemate.knowledge.facts import prune_serialized_facts, store_facts
from talemate.knowledge.graph import bucket
from talemate.knowledge.schema import Fact, ParsedFact, KnowledgeEdge
from talemate.agents.memory.schema import MemoryDocument
from talemate.agents.conversation.response_specs import (
    KNOWLEDGE_LEDGER_FACTS_SPEC,
    KNOWLEDGE_LEDGER_SPEC,
)
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, NarratorMessage
from talemate.tale_mate import Actor
from talemate.server.world_state_manager.history import HistoryMixin
from talemate.server.world_state_manager.knowledge import KnowledgeMixin
import pydantic


@pytest.fixture
def dialogue(scene, monkeypatch):
    conversation = get_agent("conversation")
    config = conversation.actions["character_knowledge"]
    config.enabled = True
    config.config["ledger"].value = True
    config.config["establish_facts"].value = True
    scene.character_data = {
        name: Character(name=name, is_player=name == "Alice")
        for name in ("Alice", "Edwin", "Mara")
    }
    scene.active_characters = ["Alice", "Edwin", "Mara"]
    scene.actors = [
        Actor(character, conversation) for character in scene.character_data.values()
    ]
    for actor in scene.actors:
        actor.scene = scene
    scene.ts = 500
    scene.history = []
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "get", AsyncMock(return_value=[]))
    monkeypatch.setattr(memory, "add_many", AsyncMock())
    monkeypatch.setattr(memory, "delete", AsyncMock())
    monkeypatch.setattr(
        memory, "compare_string_lists", AsyncMock(return_value={"distance_matches": []})
    )
    monkeypatch.setattr(
        memory, "compare_strings", AsyncMock(return_value={"euclidean_distance": 0.01})
    )
    monkeypatch.setattr(scene, "emit_status", Mock())
    monkeypatch.setattr(
        "talemate.agents.conversation.knowledge.refresh_topics", AsyncMock()
    )
    request = AsyncMock(
        return_value=(
            "",
            {
                "ledger": "{}",
                "facts": json.dumps(
                    [
                        {
                            "text": "Alice says she has moved into the lighthouse.",
                            "importance": 3,
                            "subjects": ["Alice", "lighthouse"],
                            "known_by": ["Edwin", "Nobody"],
                        }
                    ]
                ),
            },
        )
    )
    monkeypatch.setattr(Prompt, "request", request)
    with ActiveScene(scene):
        yield scene, conversation, memory, request


async def record(dialogue, *, source="ai", speaker="Alice"):
    scene, conversation, _, _ = dialogue
    message = CharacterMessage(
        message=f"{speaker}: I have moved into the lighthouse.",
        source=source,
        present=list(scene.active_characters),
    )
    scene.history.append(message)
    await conversation.on_new_message(
        GameLoopNewMessageEvent(
            scene=scene,
            event_type="game_loop_new_message",
            message=message,
        )
    )
    return message


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["ai", "player"])
async def test_fact_exists_before_archive_with_one_request_and_original_audience(
    dialogue, source
):
    scene, _, memory, request = dialogue
    message = await record(dialogue, source=source)
    assert scene.archived_history == []
    fact = next(iter(scene.world_state.facts.values()))
    assert (fact.message_id, fact.ts, fact.source, fact.archive_id) == (
        message.id,
        500,
        "dialogue",
        None,
    )
    assert fact.present == ["Alice", "Edwin", "Mara"]
    assert fact.known_by == {"Edwin": "told"}
    assert fact.importance == 3
    assert [item[0].id for item in bucket(scene, "Mara")] == [fact.id]
    assert memory.add_many.await_count == 1
    request.assert_awaited_once()
    assert request.call_args.kwargs["response_spec"] is KNOWLEDGE_LEDGER_FACTS_SPEC
    assert request.call_args.kwargs["vars"]["listeners"] == "Edwin, Mara"
    assert request.call_args.kwargs["vars"]["absence"] == {}


@pytest.mark.asyncio
async def test_lone_speaker_still_establishes_a_fact(dialogue):
    scene, _, _, request = dialogue
    scene.active_characters = ["Alice"]
    await record(dialogue)
    assert len(scene.world_state.facts) == 1
    assert next(iter(scene.world_state.facts.values())).present == ["Alice"]
    request.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["toggle-off", "ledger-off", "group-off", "perception"]
)
async def test_disabled_and_perspectives_paths_make_no_new_request(dialogue, mode):
    scene, conversation, _, request = dialogue
    config = conversation.actions["character_knowledge"]
    if mode == "toggle-off":
        config.config["establish_facts"].value = False
    elif mode == "ledger-off":
        config.config["ledger"].value = False
    elif mode == "group-off":
        config.enabled = False
    else:
        scene.knowledge_eligibility = "perception"
    await record(dialogue)
    assert scene.world_state.facts == {}
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_toggle_off_keeps_existing_ledger_request_and_grants(
    dialogue, monkeypatch
):
    scene, conversation, _, request = dialogue
    conversation.actions["character_knowledge"].config["establish_facts"].value = False
    fact = Fact(id="F1", text="Alice found the key.", present=["Alice"])
    scene.world_state.facts[fact.id] = fact
    monkeypatch.setattr(
        "talemate.agents.conversation.knowledge.absence_facts",
        AsyncMock(return_value=[fact]),
    )
    request.return_value = ("", {"ledger": '{"Edwin": ["F1"]}'})
    await record(dialogue)
    request.assert_awaited_once()
    assert request.call_args.kwargs["response_spec"] is KNOWLEDGE_LEDGER_SPEC
    assert "establish_facts" not in request.call_args.kwargs["vars"]
    assert "previous_facts" not in request.call_args.kwargs["vars"]
    assert scene.world_state.facts["F1"].known_by == {"Edwin": "inferred"}


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["[]", "bad JSON"])
async def test_empty_or_malformed_facts_create_no_fact(dialogue, raw):
    scene, _, memory, request = dialogue
    request.return_value = ("", {"ledger": "{}", "facts": raw})
    await record(dialogue)
    assert scene.world_state.facts == {}
    memory.add_many.assert_not_awaited()
    request.assert_awaited_once()


@pytest.mark.asyncio
async def test_malformed_ledger_does_not_discard_valid_new_facts(dialogue):
    scene, _, _, request = dialogue
    request.return_value[1]["ledger"] = "unreadable"
    await record(dialogue)
    assert len(scene.world_state.facts) == 1


@pytest.mark.asyncio
async def test_narrator_line_is_left_to_archive(dialogue):
    scene, conversation, _, request = dialogue
    message = NarratorMessage(message="Alice moved in.")
    scene.history.append(message)
    await conversation.on_new_message(
        GameLoopNewMessageEvent(
            scene=scene,
            event_type="game_loop_new_message",
            message=message,
        )
    )
    request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["delete", "edit", "disable", "replace"])
async def test_late_response_cannot_establish_facts_for_changed_source(
    dialogue, mutation
):
    scene, conversation, memory, request = dialogue
    answer = request.return_value

    async def change_source(*args, **kwargs):
        if mutation == "delete":
            scene.history.clear()
        elif mutation == "edit":
            scene.history[-1].message = "Alice: Never mind."
        elif mutation == "disable":
            conversation.actions["character_knowledge"].config[
                "establish_facts"
            ].value = False
        else:
            old = scene.history[-1]
            scene.history[-1] = CharacterMessage(id=old.id, message=old.message)
        return answer

    request.side_effect = change_source
    await record(dialogue)
    request.assert_awaited_once()
    assert scene.world_state.facts == {}
    memory.add_many.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["delete", "edit", "version", "pop", "reset"])
async def test_source_lifecycle_removes_dialogue_fact_and_knowledge_links(
    dialogue, mutation
):
    scene, _, memory, _ = dialogue
    message = await record(dialogue)
    fact = next(iter(scene.world_state.facts.values()))
    scene.world_state.knowledge.append(KnowledgeEdge(character="Mara", target=fact.id))
    if mutation == "delete":
        scene.delete_message(message.id)
    elif mutation == "edit":
        message.message = "Alice: I will stay elsewhere."
    elif mutation == "version":
        message.append_version("Alice: I will stay elsewhere.", source="revision")
    elif mutation == "pop":
        scene.pop_history("character")
    else:
        assert fact.id in scene.reset()
    assert fact.id not in scene.world_state.facts
    assert scene.world_state.knowledge == []
    if mutation != "reset":
        await get_agent("summarizer").flush_fact_memory(scene)
        assert any(
            fact.id in call.args[0]["ids"] for call in memory.delete.await_args_list
        )


@pytest.mark.asyncio
async def test_archive_restatement_uses_existing_dialogue_fact(dialogue, monkeypatch):
    scene, _, memory, _ = dialogue
    message = await record(dialogue)
    fact = next(iter(scene.world_state.facts.values()))
    monkeypatch.setattr(
        memory,
        "get",
        AsyncMock(
            return_value=[
                MemoryDocument(fact.text, {"typ": "fact"}, fact.id, fact.text)
            ]
        ),
    )
    stored = await store_facts(
        scene,
        "archive-1",
        scene.active_characters,
        600,
        [ParsedFact(text="Alice says she moved into the lighthouse.", importance=2)],
        0.15,
    )
    assert stored == []
    assert list(scene.world_state.facts) == [fact.id]
    assert fact.restatements == 1
    assert fact.importance == 3
    assert fact.message_id == message.id
    assert fact.archive_id is None


@pytest.mark.asyncio
async def test_reset_export_and_missing_source_prune_dialogue_facts(dialogue):
    scene, _, _, _ = dialogue
    await record(dialogue)
    identity = next(iter(scene.world_state.facts))
    serialized = scene.world_state.model_dump()
    assert prune_serialized_facts(serialized, set(), reset_sources=True) == {identity}
    assert serialized["facts"] == {}
    assert identity in scene.world_state.facts
    scene.history.clear()
    assert prune_invalid_dialogue_facts(scene) == {identity}


def test_toggle_default_and_visibility_contract(scene):
    conversation = get_agent("conversation")
    field = conversation.actions["character_knowledge"].config["establish_facts"]
    assert field.value is False
    assert field.condition.attribute == "character_knowledge.config.ledger"
    assert field.condition.value is True
    scene.knowledge_eligibility = "perception"
    assert (
        "establish_facts"
        not in conversation.sanitized_action_config["character_knowledge"]["config"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "add_many"])
async def test_source_removed_during_memory_operation_leaves_no_fact(
    dialogue, operation
):
    scene, _, memory, request = dialogue

    async def remove_source(*args, **kwargs):
        scene.history.clear()
        return []

    getattr(memory, operation).side_effect = remove_source
    await record(dialogue)
    request.assert_awaited_once()
    getattr(memory, operation).assert_awaited_once()
    assert scene.world_state.facts == {}
    if operation == "add_many":
        memory.delete.assert_awaited_once_with({"ids": ["F1"]})


def test_toggle_off_preserves_ledger_inputs_and_output_contract(scene):
    variables = {
        "scene": scene,
        "speaker": "Alice",
        "listeners": "Edwin",
        "line": "Alice: I found the key.",
        "recent_lines": ["Edwin: Hello."],
        "absence": {"Edwin": [Fact(id="F1", text="Alice found the key.")]},
    }
    original = (
        Path(__file__).parent / "data/dialogue_facts/ledger_before.jinja2"
    ).read_text()
    with ActiveScene(scene):
        before = Prompt.get("conversation.knowledge-ledger", vars=variables)
        before.template = original
        after = Prompt.get("conversation.knowledge-ledger", vars=variables)
        rendered = after.render()
        assert rendered.count("(Time unknown)") == 1
        prior = before.render()
        current = rendered.replace("(Time unknown) ", "")
        assert (
            current.split("Alice just said", 1)[0]
            == prior.split("Alice just said", 1)[0]
        )
        assert (
            current.split("Answer with a JSON object", 1)[1]
            == prior.split("Answer with a JSON object", 1)[1]
        )


def test_enabled_prompt_and_extractor_carry_both_blocks(scene):
    with ActiveScene(scene):
        rendered = Prompt.get(
            "conversation.knowledge-ledger",
            vars={
                "scene": scene,
                "speaker": "Alice",
                "listeners": "Edwin",
                "line": "Alice: I moved in.",
                "absence": {},
                "establish_facts": True,
                "previous_facts": [Fact(id="F1", text="Edwin owns the lighthouse.")],
            },
        ).render()
    assert "[F1] Fact: Edwin owns the lighthouse." in rendered
    assert "Record age (metadata, do not copy): Time unknown" in rendered
    assert "Do not copy it into extracted facts." in rendered
    assert "[F1] (Time unknown)" not in rendered
    assert "NEW LINE only" in rendered
    assert "first hug" in rendered
    assert '"importance": 2' in rendered
    assert "Between 0 and 12" in rendered
    extracted = KNOWLEDGE_LEDGER_FACTS_SPEC.extract_all(
        '<LEDGER>{"Edwin":["F1"]}</LEDGER>\n<FACTS>[{"text":"Alice moved in.","importance":2}]</FACTS>'
    )
    assert json.loads(extracted["ledger"]) == {"Edwin": ["F1"]}
    assert json.loads(extracted["facts"])[0]["importance"] == 2


@pytest.fixture
def history_handler(dialogue, monkeypatch):
    scene, _, _, _ = dialogue

    class Handler(HistoryMixin, KnowledgeMixin):
        pass

    handler = Handler()
    handler.scene = scene
    handler.sent = []
    handler.websocket_handler = SimpleNamespace(queue_put=handler.sent.append)
    handler.signal_operation_done = AsyncMock()
    monkeypatch.setattr(
        "talemate.server.world_state_manager.knowledge.refresh_topics", AsyncMock()
    )
    return handler


@pytest.mark.asyncio
async def test_history_payload_source_lookup_and_importance_edit(
    dialogue, history_handler
):
    scene, _, _, _ = dialogue
    message = await record(dialogue, source="player")
    fact = next(iter(scene.world_state.facts.values()))
    await history_handler.handle_request_scene_history({})
    payload = history_handler.sent[-1]["data"]
    assert payload["history"] == []
    assert payload["dialogue_facts"][0]["message_id"] == message.id
    assert payload["dialogue_facts"][0]["importance"] == 3
    await history_handler.handle_get_fact_source({"fact_id": fact.id})
    assert history_handler.sent[-1]["data"] == {
        "fact_id": fact.id,
        "message_id": message.id,
        "text": str(message),
    }
    await history_handler.handle_update_fact(
        {"fact": {**fact.model_dump(), "importance": 1}}
    )
    assert scene.world_state.facts[fact.id].importance == 1
    assert history_handler.sent[-1]["action"] == "fact_updated"
    assert history_handler.sent[-1]["data"]["importance"] == 1
    with pytest.raises(pydantic.ValidationError):
        await history_handler.handle_update_fact(
            {"fact": {**fact.model_dump(), "importance": 4}}
        )
    assert scene.world_state.facts[fact.id].importance == 1


@pytest.mark.asyncio
async def test_removed_fact_source_and_stale_edit_are_refused(
    dialogue, history_handler
):
    scene, _, _, _ = dialogue
    message = await record(dialogue)
    fact = next(iter(scene.world_state.facts.values()))
    scene.delete_message(message.id)
    await history_handler.handle_get_fact_source({"fact_id": fact.id})
    assert history_handler.sent[-1]["data"]["text"] is None
    await history_handler.handle_update_fact({"fact": fact.model_dump()})
    assert fact.id not in scene.world_state.facts
    assert not any(frame["action"] == "fact_updated" for frame in history_handler.sent)
    await get_agent("summarizer").flush_fact_memory(scene)


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt", ["second_lookup", "memory_write"])
async def test_stale_source_does_not_publish_merged_facts_or_grants(
    dialogue, monkeypatch, interrupt
):
    scene, _, memory, request = dialogue
    original = Fact(
        id="F10",
        text="Alice lives at the lighthouse.",
        present=["Alice"],
        restatements=4,
        last_seen_ts=10,
        known_by={"Edwin": "inferred"},
    )
    scene.world_state.facts[original.id] = original
    scene.world_state.fact_counter = 10
    before = original.model_dump()
    request.return_value = (
        "",
        {
            "ledger": "{}",
            "facts": json.dumps(
                [{"text": original.text}, {"text": "A brass key was found."}]
            ),
        },
    )
    calls = 0

    async def lookup(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [
                MemoryDocument(
                    original.text, {"typ": "fact"}, original.id, original.text
                )
            ]
        if interrupt == "second_lookup":
            scene.history.clear()
        return []

    memory.get.side_effect = lookup

    async def write(documents):
        assert scene.world_state.facts[original.id].model_dump() == before
        assert scene.world_state.knowledge == []
        scene.history.clear()

    if interrupt == "memory_write":
        memory.add_many.side_effect = write
    await record(dialogue)
    assert scene.world_state.facts == {original.id: original}
    assert original.model_dump() == before
    assert scene.world_state.knowledge == []
    request.assert_awaited_once()
    if interrupt == "memory_write":
        assert memory.add_many.await_count == 2
        assert memory.add_many.await_args.args[0][0]["meta"]["restatements"] == 4
        memory.delete.assert_awaited_once_with({"ids": ["F11"]})
    else:
        memory.add_many.assert_not_awaited()


def test_fact_free_ledger_omits_empty_known_section(scene):
    with ActiveScene(scene):
        rendered = Prompt.get(
            "conversation.knowledge-ledger",
            vars={
                "scene": scene,
                "speaker": "Alice",
                "listeners": "Edwin",
                "line": "Alice: Hello.",
                "absence": {},
                "establish_facts": True,
                "previous_facts": [],
            },
        ).render(apply_sectioning=False)
    assert "SECTION:KNOWN FACTS" not in rendered
    assert "<FACTS>" in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["edit", "delete"])
async def test_restatement_preserves_merge_target_changes_during_memory_write(
    dialogue, operation
):
    scene, _, memory, request = dialogue
    original = Fact(
        id="F10",
        text="Alice lives at the lighthouse.",
        importance=3,
        present=["Alice"],
        restatements=4,
        last_seen_ts=10,
    )
    scene.world_state.facts[original.id] = original
    memory.get.return_value = [
        MemoryDocument(original.text, {"typ": "fact"}, original.id, original.text)
    ]
    request.return_value = (
        "",
        {"ledger": "{}", "facts": json.dumps([{"text": original.text}])},
    )
    edited = original.model_copy(
        update={
            "text": "Alice lives in the mountains.",
            "importance": 1,
            "restatements": 8,
            "last_seen_ts": 700,
            "known_by": {"Edwin": "inferred"},
        }
    )
    writes = []

    async def write(documents):
        writes.extend(documents)
        if memory.add_many.await_count != 1:
            return
        assert scene.world_state.facts[original.id] is original
        if operation == "edit":
            scene.world_state.facts[original.id] = edited
        else:
            scene.world_state.facts.pop(original.id)

    memory.add_many.side_effect = write
    await record(dialogue)
    if operation == "edit":
        assert scene.world_state.facts[original.id] is edited
        assert (edited.text, edited.importance) == ("Alice lives in the mountains.", 1)
        assert (edited.restatements, edited.last_seen_ts) == (9, 700)
        assert edited.known_by == {"Edwin": "inferred", "Mara": "told"}
        assert [
            (edge.character, edge.target) for edge in scene.world_state.knowledge
        ] == [("Mara", original.id)]
        assert writes[-1]["text"] == edited.text
        assert writes[-1]["meta"]["restatements"] == 9
        memory.delete.assert_not_awaited()
    else:
        assert original.id not in scene.world_state.facts
        assert scene.world_state.knowledge == []
        memory.delete.assert_awaited_once_with({"ids": [original.id]})


@pytest.mark.asyncio
async def test_deleted_dialogue_fact_marker_retains_fact_text(dialogue, monkeypatch):
    scene, _, _, _ = dialogue
    scene.active = True
    await record(dialogue)
    original = next(iter(scene.world_state.facts.values()))
    emit = Mock()
    monkeypatch.setattr("talemate.knowledge.changes.emit", emit)
    scene.history.clear()
    invalidate_dialogue_facts(scene)
    assert {item["label"] for item in emit.call_args.kwargs["data"]["changes"]} == {
        original.text
    }
    assert all(
        item["kind"] == "revoke" for item in emit.call_args.kwargs["data"]["changes"]
    )


@pytest.mark.asyncio
async def test_restatement_and_ledger_update_the_same_committed_fact(dialogue):
    scene, _, memory, request = dialogue
    fact = Fact(id="F10", text="Alice lives at the lighthouse.", present=["Alice"])
    scene.world_state.facts[fact.id] = fact
    memory.get.return_value = [
        MemoryDocument(fact.text, {"typ": "fact"}, fact.id, fact.text)
    ]
    request.return_value = (
        "",
        {"ledger": '{"Edwin":["F10"]}', "facts": json.dumps([{"text": fact.text}])},
    )
    await record(dialogue)
    saved = scene.world_state.facts[fact.id]
    assert saved.restatements == 1
    assert saved.last_seen_ts == 500
    assert saved.known_by == {"Edwin": "inferred", "Mara": "told"}
