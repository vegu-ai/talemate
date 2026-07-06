"""Tests for the creator agent's character helpers — currently the
dialogue example generation flow and its signals."""

import json

import pytest

import talemate.instance as instance
from talemate.agents.base import DynamicInstruction
from talemate.character import Character

from conftest import MockClient, MockClientContext, bootstrap_engine, client_responses


@pytest.fixture
def creator():
    bootstrap_engine()
    agent = instance.get_agent("creator")
    agent.client = MockClient("test_client")
    agent.scene = None
    return agent


@pytest.fixture
def dialogue_examples_signals(isolate_signals):
    return isolate_signals(
        "agent.creator.dialogue_examples.before",
        "agent.creator.dialogue_examples.after",
    )


def _example_call_block(example: str) -> str:
    call = json.dumps(
        {"function": "add_dialogue_example", "arguments": {"example": example}}
    )
    return f"```json\n{call}\n```"


@pytest.mark.asyncio
async def test_determine_character_dialogue_examples(creator):
    character = Character(name="Alice", description="A curious girl.")

    async with MockClientContext():
        client_responses.get().append(_example_call_block('"Oh dear!" she gasps'))
        examples = await creator.determine_character_dialogue_examples(
            character, text="Alice is easily startled."
        )

    assert examples == ['Alice: "Oh dear!" she gasps']


@pytest.mark.asyncio
async def test_dialogue_examples_signals_fire(creator, dialogue_examples_signals):
    before, after = dialogue_examples_signals
    character = Character(name="Alice", description="A curious girl.")
    received = {}

    async def on_before(emission):
        received["before"] = (emission.character.name, emission.text)

    async def on_after(emission):
        received["after"] = list(emission.dialogue_examples)

    before.connect(on_before)
    after.connect(on_after)

    async with MockClientContext():
        client_responses.get().append(_example_call_block('"Hello there."'))
        await creator.determine_character_dialogue_examples(
            character, text="Alice greets people."
        )

    assert received["before"] == ("Alice", "Alice greets people.")
    assert received["after"] == ['Alice: "Hello there."']


@pytest.mark.asyncio
async def test_dialogue_examples_before_injects_dynamic_instructions(
    creator, dialogue_examples_signals
):
    before, _ = dialogue_examples_signals
    character = Character(name="Alice", description="A curious girl.")

    async def on_before(emission):
        emission.dynamic_instructions.append(
            DynamicInstruction(title="Tone", content="Keep it whimsical.")
        )

    before.connect(on_before)

    async with MockClientContext():
        client_responses.get().append(_example_call_block('"Curiouser!"'))
        await creator.determine_character_dialogue_examples(character)

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "Keep it whimsical." in prompt


@pytest.mark.asyncio
async def test_dialogue_examples_after_can_mutate_result(
    creator, dialogue_examples_signals
):
    _, after = dialogue_examples_signals
    character = Character(name="Alice", description="A curious girl.")

    async def on_after(emission):
        emission.dialogue_examples.append("Alice: added by handler")

    after.connect(on_after)

    async with MockClientContext():
        client_responses.get().append(_example_call_block('"Hi."'))
        examples = await creator.determine_character_dialogue_examples(character)

    assert examples == ['Alice: "Hi."', "Alice: added by handler"]
