"""The scene context format is the Summarizer's Scene History ``format`` setting."""

import json
from pathlib import Path

import pytest

import talemate.instance as instance
from conftest import MockScene, bootstrap_scene
from talemate.agents.conversation import ConversationAgent
from talemate.agents.summarize import SummarizeAgent
from talemate.config import get_config
from talemate.scene_agent_settings import SceneAgentSettings
from talemate.scene_message import CharacterMessage
from talemate.server.agent_config import AgentConfigPlugin


@pytest.fixture
def scene():
    scene = MockScene()
    bootstrap_scene(scene)
    scene.history = [
        CharacterMessage(message='Elena: "Only the keeper."', source="ai"),
    ]
    return scene


def _format_field(agent):
    return agent.actions["manage_scene_history"].config["format"]


def test_scene_history_declares_the_format():
    field = SummarizeAgent.init_actions()["manage_scene_history"].config["format"]
    assert field.value == "movie_script"
    assert [choice["value"] for choice in field.choices] == [
        "movie_script",
        "chat",
        "narrative",
        "ai_aware",
    ]
    assert field.scene_overridable is True
    assert set(field.note_on_value) == {"narrative", "ai_aware"}


def test_conversation_generation_has_no_format():
    config = ConversationAgent.init_actions()["generation_override"].config
    assert "format" not in config
    assert {"instructions", "actor_instructions"} <= set(config)


@pytest.mark.asyncio
async def test_global_value_round_trips_through_the_config(scene):
    summarizer = instance.get_agent("summarizer")
    _format_field(summarizer).value = "narrative"
    await summarizer.save_config()

    saved = get_config().agents["summarizer"].model_dump()
    fresh = SummarizeAgent()
    await fresh.apply_config(actions=saved["actions"], enabled=saved["enabled"])

    assert _format_field(fresh).value == "narrative"


@pytest.mark.asyncio
async def test_released_conversation_value_is_dropped(scene):
    conversation = instance.get_agent("conversation")
    await conversation.apply_config(
        actions={
            "generation_override": {
                "enabled": True,
                "config": {"format": {"value": "narrative"}},
            }
        },
        enabled=True,
    )

    assert scene.conversation_format == "movie_script"
    await conversation.save_config()
    saved = get_config().agents["conversation"].actions["generation_override"]
    assert "format" not in saved.config


def test_scene_override_wins_over_the_global_value(scene):
    summarizer = instance.get_agent("summarizer")
    _format_field(summarizer).value = "narrative"
    overlay = SceneAgentSettings(filepath=Path("unused.json"))
    overlay.set_value("summarizer", "manage_scene_history", "format", "chat")
    scene.agent_overrides = overlay

    assert scene.conversation_format == "chat"
    assert _format_field(summarizer).value == "narrative"


def test_scene_override_write_goes_to_the_overlay(scene):
    summarizer = instance.get_agent("summarizer")
    overlay = SceneAgentSettings(filepath=Path("unused.json"))
    overlay.set_value("summarizer", "manage_scene_history", "format", "chat")
    scene.agent_overrides = overlay

    summarizer.write_config("manage_scene_history", "format", "narrative")

    assert overlay.get_value("summarizer", "manage_scene_history", "format") == (
        "narrative"
    )
    assert _format_field(summarizer).value == "movie_script"
    assert scene.conversation_format == "narrative"


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("chat", 'Elena: "Only the keeper."'),
        ("movie_script", '\nELENA\n"Only the keeper."\nEND-OF-LINE'),
    ],
)
def test_scene_history_renders_with_the_summarizer_value(scene, fmt, expected):
    summarizer = instance.get_agent("summarizer")
    _format_field(summarizer).value = fmt

    history = summarizer.context_history(scene, budget=4096)

    assert expected in "\n".join(history)


# `agent-settings.json` as 0.39.0 wrote it for a Scene-mode override of
# Conversation → Generation → Format
RELEASED_OVERLAY = {
    "agents": {
        "conversation": {
            "actions": {
                "generation_override": {
                    "config": {
                        "format": {"value": "narrative"},
                        "length": {"value": 384},
                    }
                }
            }
        }
    }
}


class _WebsocketHandler:
    def __init__(self, scene):
        self.scene = scene
        self.messages = []

    def queue_put(self, message):
        self.messages.append(message)


@pytest.fixture
async def released_overlay(scene, tmp_path):
    path = tmp_path / "agent-settings" / "agent-settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps(RELEASED_OVERLAY))
    scene.agent_overrides = await SceneAgentSettings(filepath=path).init_from_file()
    scene.filename = "scene.json"
    scene.project_name = "proj"
    return path


@pytest.mark.asyncio
async def test_released_format_override_is_neither_applied_nor_shown(
    scene, released_overlay
):
    conversation = instance.get_agent("conversation")

    assert scene.conversation_format == "movie_script"
    assert type(conversation)._scene_overrides_payload(conversation) == {
        "actions": {"generation_override": {"config": {"length": {"value": 384}}}}
    }


@pytest.mark.asyncio
async def test_released_format_override_leaves_the_file_at_the_next_save(
    scene, released_overlay
):
    plugin = AgentConfigPlugin(_WebsocketHandler(scene))

    await plugin.handle_save_scene_overrides(
        {
            "agent_type": "conversation",
            "patch": {
                "set": {
                    "actions": {
                        "generation_override": {"config": {"jiggle": {"value": 0.2}}}
                    }
                }
            },
        }
    )

    stored = json.loads(released_overlay.read_text())
    assert stored["agents"]["conversation"]["actions"]["generation_override"][
        "config"
    ] == {"length": {"value": 384}, "jiggle": {"value": 0.2}}
