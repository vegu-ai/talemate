"""Tests for the AI generation toggles on CharacterCardImportOptions.

Covers:
- Flag defaults (all generation steps enabled)
- _setup_loading_status step math across option combinations
- _process_characters_for_import gating of the per-character LLM steps and
  raw-card fallback when steps are disabled
- load_scene_from_character_card call-site guards for content context and
  story intent
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import talemate.load.character_card as character_card
from talemate.character import Character
from talemate.load.character_card import (
    CharacterCardImportOptions,
    _process_characters_for_import,
    _setup_loading_status,
    load_scene_from_character_card,
)
from talemate.status import LoadingStatus

EXTRACTION_FLAGS = [
    "determine_content_context",
    "extract_description",
    "extract_attributes",
    "extract_dialogue_instructions",
    "extract_dialogue_examples",
    "generate_story_intent",
]


def _options_all_disabled(**overrides) -> CharacterCardImportOptions:
    kwargs = {flag: False for flag in EXTRACTION_FLAGS}
    kwargs["generate_episode_titles"] = False
    kwargs.update(overrides)
    return CharacterCardImportOptions(**kwargs)


class FakeAgents:
    """Stand-ins for the creator, world_state and director agents."""

    def __init__(self, auto_direct_enabled: bool = False):
        client = SimpleNamespace(max_token_length=8192)
        self.creator = SimpleNamespace(
            client=client,
            determine_character_description=AsyncMock(
                return_value="generated description"
            ),
            determine_character_dialogue_instructions=AsyncMock(
                return_value="generated instructions"
            ),
            determine_character_dialogue_examples=AsyncMock(
                return_value=["Hero: generated example"]
            ),
        )
        self.world_state = SimpleNamespace(
            extract_character_sheet=AsyncMock(
                return_value={"age": "20", "tags": ["brave", "kind"]}
            ),
        )
        self.director = SimpleNamespace(
            auto_direct_enabled=auto_direct_enabled,
            assign_voice_to_character=AsyncMock(),
        )

    def get_agent(self, name):
        return getattr(self, name)


@pytest.fixture
def fake_agents(monkeypatch):
    agents = FakeAgents()
    monkeypatch.setattr(character_card.instance, "get_agent", agents.get_agent)
    return agents


def _scene_stub():
    return SimpleNamespace(
        name=None,
        description="",
        intro="",
        context="",
        character_data={},
        world_state=SimpleNamespace(manual_context={}),
    )


# ---------------------------------------------------------------------------
# Option defaults
# ---------------------------------------------------------------------------


def test_extraction_toggles_default_enabled():
    options = CharacterCardImportOptions()
    for flag in EXTRACTION_FLAGS:
        assert getattr(options, flag) is True, flag


# ---------------------------------------------------------------------------
# Loading status step math
# ---------------------------------------------------------------------------


def test_setup_loading_status_all_enabled(fake_agents):
    options = CharacterCardImportOptions()
    status = _setup_loading_status(options, num_characters=1)
    # card + memory + context + 4 per-character steps + story intent
    assert status.max_steps == 8
    assert status.current_step == 1


def test_setup_loading_status_all_disabled(fake_agents):
    status = _setup_loading_status(_options_all_disabled(), num_characters=1)
    # card + memory only
    assert status.max_steps == 2


def test_setup_loading_status_scales_with_characters(fake_agents):
    options = CharacterCardImportOptions()
    status = _setup_loading_status(options, num_characters=3)
    assert status.max_steps == 2 + 1 + 3 * 4 + 1


def test_setup_loading_status_partial_extractions(fake_agents):
    options = _options_all_disabled(
        extract_description=True, extract_dialogue_examples=True
    )
    status = _setup_loading_status(options, num_characters=2)
    assert status.max_steps == 2 + 2 * 2


def test_setup_loading_status_book_and_episodes(fake_agents):
    options = CharacterCardImportOptions()
    status = _setup_loading_status(
        options, num_characters=1, has_character_book=True, num_episodes=3
    )
    assert status.max_steps == 8 + 1 + 3


def test_setup_loading_status_episode_titles_disabled(fake_agents):
    options = CharacterCardImportOptions(generate_episode_titles=False)
    status = _setup_loading_status(options, num_characters=1, num_episodes=3)
    assert status.max_steps == 8


def test_setup_loading_status_auto_direct_requires_story_intent(fake_agents):
    fake_agents.director.auto_direct_enabled = True
    status = _setup_loading_status(CharacterCardImportOptions(), num_characters=1)
    assert status.max_steps == 10

    status = _setup_loading_status(
        _options_all_disabled(generate_story_intent=True), num_characters=1
    )
    assert status.max_steps == 2 + 3

    status = _setup_loading_status(_options_all_disabled(), num_characters=1)
    assert status.max_steps == 2


# ---------------------------------------------------------------------------
# Per-character gating and raw-card fallback
# ---------------------------------------------------------------------------


async def test_process_characters_extractions_enabled(fake_agents):
    character = Character(
        name="Hero", description="raw description", greeting_text="hi"
    )
    character.example_dialogue = ["Hero: raw example"]
    scene = _scene_stub()

    await _process_characters_for_import(
        scene,
        [character],
        ["hi"],
        "raw mes example",
        LoadingStatus(None),
        CharacterCardImportOptions(),
    )

    assert character.description == "generated description"
    assert character.base_attributes == {"age": "20", "tags": "brave,kind"}
    assert character.dialogue_instructions == "generated instructions"
    assert character.example_dialogue == ["Hero: generated example"]
    fake_agents.director.assign_voice_to_character.assert_awaited_once()
    assert scene.character_data == {"Hero": character}


async def test_process_characters_extractions_disabled_keeps_raw_data(fake_agents):
    character = Character(
        name="Hero", description="raw description", greeting_text="hi"
    )
    character.example_dialogue = ["Hero: raw example"]
    scene = _scene_stub()

    await _process_characters_for_import(
        scene,
        [character],
        ["hi"],
        "raw mes example",
        LoadingStatus(None),
        _options_all_disabled(),
    )

    assert character.description == "raw description"
    assert character.example_dialogue == ["Hero: raw example"]
    assert character.dialogue_instructions is None
    fake_agents.creator.determine_character_description.assert_not_awaited()
    fake_agents.creator.determine_character_dialogue_instructions.assert_not_awaited()
    fake_agents.creator.determine_character_dialogue_examples.assert_not_awaited()
    fake_agents.world_state.extract_character_sheet.assert_not_awaited()
    # voice assignment is not an extraction and still runs
    fake_agents.director.assign_voice_to_character.assert_awaited_once()


async def test_process_characters_individual_gating(fake_agents):
    character = Character(
        name="Hero", description="raw description", greeting_text="hi"
    )
    scene = _scene_stub()

    await _process_characters_for_import(
        scene,
        [character],
        ["hi"],
        "",
        LoadingStatus(None),
        _options_all_disabled(extract_attributes=True),
    )

    assert character.base_attributes == {"age": "20", "tags": "brave,kind"}
    assert character.description == "raw description"
    fake_agents.world_state.extract_character_sheet.assert_awaited_once()
    fake_agents.creator.determine_character_description.assert_not_awaited()
    fake_agents.creator.determine_character_dialogue_instructions.assert_not_awaited()


# ---------------------------------------------------------------------------
# Pipeline call-site guards (content context, story intent)
# ---------------------------------------------------------------------------

_PIPELINE_MOCKS = [
    "_setup_player_character_from_options",
    "_initialize_scene_memory",
    "_determine_character_context",
    "_determine_character_description",
    "_determine_character_attributes",
    "_determine_character_dialogue_instructions",
    "_determine_character_dialogue_examples",
    "_activate_characters_from_greeting",
    "_generate_story_intent",
    "_setup_character_assets_from_icon_data_url",
    "_setup_character_assets",
    "_process_pending_asset_transfers",
    "_save_scene_files",
]


@pytest.fixture
def pipeline_recorders(monkeypatch, fake_agents):
    recorders = {}
    for name in _PIPELINE_MOCKS:
        return_value = None
        if name == "_setup_character_assets_from_icon_data_url":
            return_value = False
        elif name == "_setup_player_character_from_options":
            return_value = True
        mock = AsyncMock(return_value=return_value)
        monkeypatch.setattr(character_card, name, mock)
        recorders[name] = mock
    return recorders


def _write_card(tmp_path) -> str:
    card = {
        "spec": "chara_card_v2",
        "data": {
            "name": "Hero",
            "description": "raw description",
            "first_mes": "Hello there.",
            "mes_example": "<START>\n{{char}}: raw example line",
        },
    }
    path = tmp_path / "card.json"
    path.write_text(json.dumps(card))
    return str(path)


async def test_load_scene_runs_guarded_steps_by_default(tmp_path, pipeline_recorders):
    scene = _scene_stub()
    await load_scene_from_character_card(
        scene, _write_card(tmp_path), CharacterCardImportOptions()
    )

    pipeline_recorders["_determine_character_context"].assert_awaited_once()
    pipeline_recorders["_generate_story_intent"].assert_awaited_once()
    pipeline_recorders["_determine_character_description"].assert_awaited_once()
    pipeline_recorders["_determine_character_attributes"].assert_awaited_once()
    pipeline_recorders[
        "_determine_character_dialogue_instructions"
    ].assert_awaited_once()
    pipeline_recorders["_determine_character_dialogue_examples"].assert_awaited_once()


async def test_load_scene_skips_guarded_steps_when_disabled(
    tmp_path, pipeline_recorders
):
    scene = _scene_stub()
    await load_scene_from_character_card(
        scene, _write_card(tmp_path), _options_all_disabled()
    )

    pipeline_recorders["_determine_character_context"].assert_not_awaited()
    pipeline_recorders["_generate_story_intent"].assert_not_awaited()
    pipeline_recorders["_determine_character_description"].assert_not_awaited()
    pipeline_recorders["_determine_character_attributes"].assert_not_awaited()
    pipeline_recorders[
        "_determine_character_dialogue_instructions"
    ].assert_not_awaited()
    pipeline_recorders["_determine_character_dialogue_examples"].assert_not_awaited()

    # raw card data flows through to the scene and character
    assert scene.description == "raw description"
    assert scene.intro == "Hello there."
    hero = scene.character_data["Hero"]
    assert hero.description == "raw description"
    assert hero.example_dialogue == ["Hero: raw example line"]
