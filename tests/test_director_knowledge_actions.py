import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.agents.director.action_core import utils
from talemate.agents.director.action_core.exceptions import ActionRejected
from talemate.agents.director.action_core.gating import extract_callback_descriptors
from talemate.agents.director.chat.context import DirectorChatContext
from talemate.agents.director.chat.nodes import DirectorChatAction
import talemate.agents.director.chat.nodes as chat_nodes
from talemate.character import Character
from talemate.client.presets import max_tokens_for_kind
from talemate.context import ActiveScene
from talemate.game.engine.nodes.core import GraphContext
import talemate.game.engine.nodes.load_definitions  # noqa: F401
from talemate.game.engine.nodes.registry import import_talemate_node_definitions
from talemate.game.engine.nodes.run import FunctionWrapper
from talemate.instance import get_agent
from talemate.knowledge.schema import EntryVisibility
from talemate.util import TIKTOKEN_ENCODING
from talemate.world_state import ManualContext


MODULES = Path("src/talemate/agents/director/modules")


@pytest.fixture
def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.active = True
    scene.knowledge_eligibility = "legacy"
    scene.character_data = {
        "Alice": Character(name="Alice"),
        "Bob": Character(
            name="Bob", base_attributes={"secret": "The ledger is under the bed."}
        ),
    }
    scene.world_state.manual_context = {
        "Hidden Door": ManualContext(
            id="Hidden Door", text="Behind the cupboard.", meta={"typ": "world_state"}
        )
    }
    import_talemate_node_definitions()
    return scene


def function_calls(*calls):
    return "\n".join(
        "```json\n" + json.dumps({"function": name, "arguments": args}) + "\n```"
        for name, args in calls
    )


async def run_instruction(
    scene,
    monkeypatch,
    calls,
    *,
    decision="confirm",
    instructions="Make the requested knowledge changes.",
    child_responses=(),
):
    action = DirectorChatAction(
        **json.loads((MODULES / "director-action-update-context.json").read_text())
    )
    responses = [
        function_calls(("character_changes", {"instructions": instructions})),
        function_calls(*calls),
        *child_responses,
    ]

    async def respond(prompt, kind, **kwargs):
        assert responses, "Unexpected extra LLM request"
        tokens = TIKTOKEN_ENCODING.encode(responses.pop(0))
        cap = max_tokens_for_kind(kind, scene.mock_client.max_token_length)
        return TIKTOKEN_ENCODING.decode(tokens[:cap])

    send = AsyncMock(side_effect=respond)
    monkeypatch.setattr(scene.mock_client, "send_prompt", send)
    confirmations = []
    with (
        ActiveScene(scene),
        DirectorChatContext(chat_id="test", confirm_write_actions=True),
        GraphContext() as state,
    ):

        def confirm(event, **kwargs):
            if event == "request_action_confirmation":
                data = kwargs["data"]
                confirmations.append(data)
                state.shared[f"_director_chat_action_confirm_{data['id']}"][
                    "decision"
                ] = decision

        monkeypatch.setattr(chat_nodes, "emit", confirm)
        wrapper = FunctionWrapper(action, action, state)
        if decision == "reject":
            with pytest.raises(ActionRejected) as rejected:
                await wrapper(instructions=instructions)
            result = str(rejected.value)
        else:
            result = await wrapper(instructions=instructions)
    return result, confirmations, send


@pytest.mark.parametrize(
    "operation", ["set_known_by", "grant_knowledge", "revoke_knowledge"]
)
async def test_knowledge_writes_through_existing_characters(
    scene, monkeypatch, operation
):
    arguments = {"context_id": "world_entry.manual:Hidden Door"}
    if operation == "set_known_by":
        arguments.update(known_by="list", characters=["Bob"])
    else:
        arguments.update(character="Alice", note="Requested by the author.")
    result, confirmations, send = await run_instruction(
        scene, monkeypatch, [(operation, arguments)]
    )
    assert len(confirmations) == 1
    assert confirmations[0]["name"] == operation
    assert "SUCCESS" in result
    assert send.await_count == 2
    if operation == "set_known_by":
        assert scene.world_state.manual_context[
            "Hidden Door"
        ].visibility == EntryVisibility(mode="list", characters=["Bob"])
    else:
        edge = scene.world_state.knowledge[0]
        assert (edge.character, edge.target, edge.kind, edge.source) == (
            "Alice",
            "Hidden Door",
            "grant" if operation == "grant_knowledge" else "revoke",
            "director",
        )


async def test_two_changes_have_two_confirmations_in_one_instruction(
    scene, monkeypatch
):
    result, confirmations, send = await run_instruction(
        scene,
        monkeypatch,
        [
            (
                "set_known_by",
                {
                    "context_id": "world_entry.manual:Hidden Door",
                    "known_by": "owner",
                    "characters": [],
                },
            ),
            (
                "grant_knowledge",
                {
                    "context_id": "world_entry.manual:Hidden Door",
                    "character": "Alice",
                    "note": "She found it.",
                },
            ),
        ],
        instructions="Hide the Hidden Door entry, then grant Alice knowledge of it.",
    )
    assert [item["name"] for item in confirmations] == [
        "set_known_by",
        "grant_knowledge",
    ]
    assert scene.world_state.manual_context["Hidden Door"].visibility.mode == "owner"
    assert len(scene.world_state.knowledge) == 1
    assert "Granted" in result and "Set who knows" in result
    assert send.await_count == 2


async def test_large_disclosure_batch_extracts_without_an_extra_llm_request(
    scene, monkeypatch
):
    scene.knowledge_eligibility = "perception"
    information = "\n".join(
        f"Record {index}: the northern harbor gate stays locked after sunset."
        for index in range(1, 61)
    )
    entry = scene.world_state.manual_context["Hidden Door"]
    entry.text = information + "\nPrivate: the spare key is under the watchman's bed."
    entry.visibility = EntryVisibility(mode="owner")
    calls = [
        (
            "grant_knowledge",
            {
                "context_id": "world_entry.manual:Hidden Door",
                "character": character,
                "note": "",
                "information": information,
                "whole_entry": False,
            },
        )
        for character in ("Alice", "Bob")
    ]
    assert 1024 < len(TIKTOKEN_ENCODING.encode(function_calls(*calls))) < 4096

    result, confirmations, send = await run_instruction(
        scene,
        monkeypatch,
        calls,
        instructions="Disclose the selected harbor records to Alice and Bob; keep the spare key private.",
    )

    assert send.await_count == 2  # Parent and instructor, no AI extraction/repair.
    assert send.await_args_list[1].kwargs["kind"] == "analyze_4096"
    assert [item["name"] for item in confirmations] == [
        "grant_knowledge",
        "grant_knowledge",
    ]
    assert len(scene.knowledge.disclosures) == 2
    assert all(item.text == information for item in scene.knowledge.disclosures)
    assert {tuple(item.audience) for item in scene.knowledge.disclosures} == {
        ("Alice",),
        ("Bob",),
    }
    assert entry.visibility == EntryVisibility(mode="owner")
    assert "SUCCESS" in result


@pytest.mark.parametrize("operation", ["update_character", "character_setup"])
async def test_short_character_updates_keep_their_normal_request_count(
    scene, monkeypatch, operation
):
    character = scene.character_data["Bob"]
    character.example_dialogue = ["Bob: I keep my promises."]
    if operation == "update_character":
        instructions = "Remove the secret attribute."
        child_call = (
            "remove_attribute",
            {"character_name": "Bob", "attribute_name": "secret"},
        )
    else:
        instructions = "Remove the first dialogue example."
        child_call = (
            "remove_dialogue_example",
            {"character_name": "Bob", "index": 0},
        )
    calls = [(operation, {"character": "Bob", "instructions": instructions})]
    assert len(TIKTOKEN_ENCODING.encode(function_calls(*calls))) < 1024

    result, confirmations, send = await run_instruction(
        scene,
        monkeypatch,
        calls,
        instructions=instructions,
        child_responses=[function_calls(child_call)],
    )

    assert send.await_count == 3  # Parent, instructor, existing update child.
    assert send.await_args_list[1].kwargs["kind"] == "analyze_4096"
    assert send.await_args_list[2].kwargs["kind"] == (
        "analyze_4096" if operation == "update_character" else "analyze_2048"
    )
    assert len(confirmations) == 1
    if operation == "update_character":
        assert "secret" not in character.base_attributes
    else:
        assert character.example_dialogue == []
    assert "SUCCESS" in result


async def test_short_character_toggle_keeps_its_normal_request_count(
    scene, monkeypatch
):
    character = scene.character_data["Bob"]
    await scene.add_actor(scene.Actor(character, get_agent("conversation")))
    assert scene.character_is_active(character)

    result, _, send = await run_instruction(
        scene,
        monkeypatch,
        [
            (
                "toggle_character",
                {
                    "character": "Bob",
                    "status": "inactive",
                    "narrate_instructions": "Bob leaves quietly.",
                },
            )
        ],
        instructions="Deactivate Bob and narrate his quiet exit.",
        child_responses=["Bob leaves quietly."],
    )

    assert send.await_count == 3  # Parent, instructor, explicitly requested narration.
    assert send.await_args_list[1].kwargs["kind"] == "analyze_4096"
    assert not scene.character_is_active(character)
    assert "SUCCESS" in result


@pytest.mark.parametrize(
    "operation", ["set_known_by", "grant_knowledge", "revoke_knowledge"]
)
async def test_rejection_prevents_each_knowledge_write(scene, monkeypatch, operation):
    args = {
        "context_id": "world_entry.manual:Hidden Door",
        "known_by": "owner",
        "characters": [],
        "character": "Alice",
        "note": "",
    }
    result, confirmations, _ = await run_instruction(
        scene, monkeypatch, [(operation, args)], decision="reject"
    )
    assert len(confirmations) == 1
    assert scene.world_state.manual_context["Hidden Door"].visibility.mode == "everyone"
    assert scene.world_state.knowledge == []
    assert "Action reject:" in result


@pytest.mark.parametrize("whole_entry", [False, True])
async def test_perception_disclosure_inputs_survive_the_move(
    scene, monkeypatch, whole_entry
):
    scene.knowledge_eligibility = "perception"
    result, confirmations, send = await run_instruction(
        scene,
        monkeypatch,
        [
            (
                "grant_knowledge",
                {
                    "context_id": "character.attribute:Bob.secret",
                    "character": "Alice",
                    "note": "",
                    "information": "The ledger is under the bed."
                    if not whole_entry
                    else "",
                    "whole_entry": whole_entry,
                },
            )
        ],
    )
    assert len(confirmations) == 1
    assert f"Whole entry: {whole_entry}" in confirmations[0]["description"]
    assert scene.knowledge.disclosures[0].text == "The ledger is under the bed."
    assert scene.world_state.knowledge == []
    assert send.await_count == 2
    assert "SUCCESS" in result


async def test_disabled_existing_characters_exposes_no_knowledge_callbacks(
    scene, monkeypatch
):
    scene.agent_state["director"] = {
        "disabled_sub_actions": {"chat": ["update_context.edit_characters"]}
    }
    _, confirmations, send = await run_instruction(scene, monkeypatch, [])
    assert not confirmations
    assert scene.world_state.knowledge == []
    assert send.await_count == 1
    prompt = str(send.call_args.args[0])
    assert '"name": "character_changes"' not in prompt


async def test_old_knowledge_subaction_is_absent(scene):
    with ActiveScene(scene), GraphContext() as state:
        await utils.init_action_nodes(scene, state)
        ids = {
            item.action_id
            for item in await extract_callback_descriptors("update_context")
        }
        assert "update_context.knowledge" not in ids
        assert "update_context.edit_characters" in ids
