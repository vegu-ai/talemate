"""
Baselines for the scene context format: the rendered scene history, the
context preview, the Conversation dialogue prompt and the Narrator stopping
strings, for each of the four formats.
"""

import json
from unittest.mock import AsyncMock

import pytest

import talemate.instance as instance
from conftest import bootstrap_scene
from talemate.context import active_scene
from talemate.scene_message import (
    CharacterMessage,
    DirectorMessage,
    NarratorMessage,
    TimePassageMessage,
)

from ..helpers import create_scene_with_characters, set_scene_context_format
from .conftest import capture_prompt

AGENT = "scene_context_format"

FORMATS = ["movie_script", "chat", "narrative", "ai_aware"]


@pytest.fixture
def scene(mock_llm_client, monkeypatch):
    scene = create_scene_with_characters()
    bootstrap_scene(scene)
    instance.get_agent("conversation").client = mock_llm_client
    monkeypatch.setattr(
        instance.get_agent("memory"), "_get", lambda *args, **kwargs: []
    )
    scene.history = [
        NarratorMessage(
            message="Rain drums on the lighthouse roof as the lamp turns overhead.",
            source="ai",
        ),
        CharacterMessage(
            message='Hero: *shakes the water from his coat* "Anyone up here?"',
            source="player",
        ),
        CharacterMessage(
            message='Elena: "Only the keeper." *She sets the logbook aside.* "And now you."',
            source="ai",
        ),
        TimePassageMessage(message="10 minutes later", ts=600),
        DirectorMessage(
            message="Ask the stranger why he came out in the storm.",
            meta={"character": "Elena"},
        ),
        CharacterMessage(
            message='Hero: "The ferry left without me." *He glances at the stairs.*',
            source="player",
        ),
    ]
    token = active_scene.set(scene)
    yield scene
    active_scene.reset(token)


@pytest.mark.parametrize("fmt", FORMATS)
def test_scene_history(fmt, scene, baseline_checker):
    set_scene_context_format(fmt)
    history = instance.get_agent("summarizer").context_history(scene, budget=4096)
    baseline_checker("\n".join(history), AGENT, f"scene_history__{fmt}")


@pytest.mark.parametrize("fmt", FORMATS)
def test_context_preview(fmt, scene, baseline_checker):
    set_scene_context_format(fmt)
    preview = instance.get_agent("summarizer").context_history_preview(scene)
    entries = [
        {"type": section["type"], "entries": section["entries"]}
        for section in preview["sections"]
    ]
    baseline_checker(json.dumps(entries, indent=2), AGENT, f"context_preview__{fmt}")


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", FORMATS)
async def test_converse(fmt, scene, mock_llm_client, baseline_checker):
    set_scene_context_format(fmt)
    mock_llm_client.send_prompt = AsyncMock(return_value='Elena: "Stay a while."')
    conversation = instance.get_agent("conversation")
    await conversation.converse(scene.get_character("Elena").actor)
    baseline_checker(capture_prompt(conversation), AGENT, f"converse__{fmt}")


@pytest.mark.parametrize("fmt", FORMATS)
def test_narrator_stopping_strings(fmt, scene, baseline_checker):
    set_scene_context_format(fmt)
    prompt_param = {}
    instance.get_agent("narrator").inject_prompt_paramters(
        prompt_param, "narrate", "narrate_scene"
    )
    baseline_checker(
        json.dumps(prompt_param["extra_stopping_strings"], indent=2),
        AGENT,
        f"narrator_stopping_strings__{fmt}",
    )
