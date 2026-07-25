"""Tests for the AI generation toggles on CharacterCardImportOptions.

Covers:
- Flag defaults (all generation steps enabled)
- _setup_loading_status step math across option combinations
- _process_characters_for_import gating of the per-character LLM steps and
  raw-card fallback when steps are disabled
- load_scene_from_character_card call-site guards for content context and
  story intent

The per-character steps run against real bootstrapped agents at the client
response level (MockClient + client_responses queue): real templates
render and real parsing runs. Agent-level mocks remain only for
transient-error / cancellation injection (autospec'd so signature drift
fails loudly)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from conftest import MockClientContext, MockScene, bootstrap_scene, client_responses
from _character_test_helpers import (
    KIND_FOCAL,
    KIND_SHEET,
    KIND_UNIFIED,
    description_response,
    example_dialogue_response,
    prompt_kinds,
    sheet_response,
    unified_response,
)

import talemate.instance as instance
import talemate.load.character_card as character_card
from talemate.character import Character
from talemate.exceptions import GenerationCancelled, LLMAccuracyError
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


@pytest.fixture
def agents():
    """Real bootstrapped agents sharing one MockClient (and MockScene, so
    the agents' own templates render against a real scene)."""
    scene = MockScene()
    handles = bootstrap_scene(scene)
    return SimpleNamespace(
        creator=instance.get_agent("creator"),
        world_state=handles["world_state"],
        director=handles["director"],
        client=scene.mock_client,
    )


@pytest.fixture
def fast_mode(agents):
    agents.creator.actions["character_creation"].config["fast"].value = True
    yield agents
    agents.creator.actions["character_creation"].config["fast"].value = False


def _scene_stub():
    return SimpleNamespace(
        name=None,
        description="",
        intro="",
        context="",
        character_data={},
        world_state=SimpleNamespace(manual_context={}),
    )


def _card_character() -> Character:
    character = Character(
        name="Hero", description="raw description", greeting_text="hi"
    )
    character.example_dialogue = ["Hero: raw example"]
    return character


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


def test_setup_loading_status_all_enabled(agents):
    options = CharacterCardImportOptions()
    status = _setup_loading_status(options, num_characters=1)
    # card + memory + context + 4 per-character steps + story intent
    assert status.max_steps == 8
    assert status.current_step == 1

    # all disabled: card + memory only
    status = _setup_loading_status(_options_all_disabled(), num_characters=1)
    assert status.max_steps == 2


def test_setup_loading_status_scales_with_characters(agents):
    options = CharacterCardImportOptions()
    status = _setup_loading_status(options, num_characters=3)
    assert status.max_steps == 2 + 1 + 3 * 4 + 1


def test_setup_loading_status_partial_extractions(agents):
    options = _options_all_disabled(
        extract_description=True, extract_dialogue_examples=True
    )
    status = _setup_loading_status(options, num_characters=2)
    assert status.max_steps == 2 + 2 * 2


def test_setup_loading_status_book_and_episodes(agents):
    options = CharacterCardImportOptions()
    status = _setup_loading_status(
        options, num_characters=1, has_character_book=True, num_episodes=3
    )
    assert status.max_steps == 8 + 1 + 3

    # episode title generation disabled: episodes add no steps
    options = CharacterCardImportOptions(generate_episode_titles=False)
    status = _setup_loading_status(options, num_characters=1, num_episodes=3)
    assert status.max_steps == 8


def test_setup_loading_status_auto_direct_requires_story_intent(agents):
    with patch.object(
        type(agents.director), "auto_direct_enabled", property(lambda self: True)
    ):
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


async def test_process_characters_extractions_enabled(agents):
    character = _card_character()
    scene = _scene_stub()

    with patch.object(
        agents.director, "assign_voice_to_character", autospec=True
    ) as mock_voice:
        async with MockClientContext():
            # split-path generation order: description, attributes,
            # dialogue instructions, dialogue examples
            client_responses.get().append(
                description_response("Hero", "is the generated hero.")
            )
            client_responses.get().append(
                sheet_response("Hero", {"Age": "20", "Tags": "brave, kind"})
            )
            client_responses.get().append("generated instructions")
            client_responses.get().append(
                example_dialogue_response("generated example")
            )
            await _process_characters_for_import(
                scene,
                [character],
                ["hi"],
                "raw mes example",
                LoadingStatus(None),
                CharacterCardImportOptions(),
            )

    assert character.description == "Hero is the generated hero."
    assert character.base_attributes == {
        "Name": "Hero",
        "Age": "20",
        "Tags": "brave, kind",
    }
    assert character.dialogue_instructions == "generated instructions"
    assert character.example_dialogue == ["Hero: generated example"]
    mock_voice.assert_awaited_once()
    assert scene.character_data == {"Hero": character}


async def test_process_characters_extractions_disabled_keeps_raw_data(agents):
    character = _card_character()
    scene = _scene_stub()

    with patch.object(
        agents.director, "assign_voice_to_character", autospec=True
    ) as mock_voice:
        async with MockClientContext():
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
    # no extraction prompt was sent at all
    assert agents.client.prompt_history == []
    # voice assignment is not an extraction and still runs
    mock_voice.assert_awaited_once()


async def test_process_characters_individual_gating(agents):
    character = Character(
        name="Hero", description="raw description", greeting_text="hi"
    )
    scene = _scene_stub()

    async with MockClientContext():
        client_responses.get().append(sheet_response("Hero", {"Age": "20"}))
        await _process_characters_for_import(
            scene,
            [character],
            ["hi"],
            "",
            LoadingStatus(None),
            _options_all_disabled(extract_attributes=True),
        )

    # only the character sheet extraction ran
    assert prompt_kinds(agents.client) == [KIND_SHEET]
    assert character.base_attributes == {"Name": "Hero", "Age": "20"}
    assert character.description == "raw description"


# ---------------------------------------------------------------------------
# Fast (consolidated) mode routing
# ---------------------------------------------------------------------------


async def test_process_characters_fast_mode_routes_through_orchestrator(fast_mode):
    agents = fast_mode
    character = _card_character()
    scene = _scene_stub()

    async with MockClientContext():
        client_responses.get().append(
            unified_response(
                description="generated description",
                attributes="Age: 20",
                dialogue_instructions="generated instructions",
            )
        )
        client_responses.get().append(example_dialogue_response("generated example"))
        await _process_characters_for_import(
            scene,
            [character],
            ["hi"],
            "raw mes example",
            LoadingStatus(None),
            CharacterCardImportOptions(),
        )

    # the consolidated one-shot covers the default Consolidate selection
    # (every aspect); the canned response misses example dialogue, which
    # fill_misses generates with its individual focal request - no
    # per-aspect split prompts
    assert prompt_kinds(agents.client) == [KIND_UNIFIED, KIND_FOCAL]
    prompt = str(agents.client.prompt_history[0]["prompt"])
    for section in ("<DESCRIPTION>", "<ATTRIBUTES>", "<DIALOGUE_INSTRUCTIONS>"):
        assert section in prompt
    assert "<NAME>" not in prompt
    assert "<EXAMPLE_DIALOGUE>" in prompt
    # results are applied to the character
    assert character.description == "generated description"
    assert character.base_attributes == {"Age": "20"}
    assert character.dialogue_instructions == "generated instructions"
    assert character.example_dialogue == ["Hero: generated example"]


async def test_process_characters_fast_mode_respects_import_toggles(fast_mode):
    agents = fast_mode
    character = _card_character()
    scene = _scene_stub()

    async with MockClientContext():
        client_responses.get().append(
            unified_response(description="generated description", attributes="Age: 20")
        )
        await _process_characters_for_import(
            scene,
            [character],
            ["hi"],
            "",
            LoadingStatus(None),
            _options_all_disabled(extract_description=True, extract_attributes=True),
        )

    # a single consolidated prompt asking only for the enabled aspects
    assert prompt_kinds(agents.client) == [KIND_UNIFIED]
    prompt = str(agents.client.prompt_history[0]["prompt"])
    assert "<DESCRIPTION>" in prompt
    assert "<ATTRIBUTES>" in prompt
    assert "<DIALOGUE_INSTRUCTIONS>" not in prompt
    assert "<EXAMPLE_DIALOGUE>" not in prompt
    assert character.description == "generated description"
    assert character.base_attributes == {"Age": "20"}
    # disabled options keep raw card data
    assert character.example_dialogue == ["Hero: raw example"]
    assert character.dialogue_instructions is None


async def test_process_characters_fast_mode_all_disabled_no_generation(fast_mode):
    agents = fast_mode
    character = Character(
        name="Hero", description="raw description", greeting_text="hi"
    )
    scene = _scene_stub()

    async with MockClientContext():
        await _process_characters_for_import(
            scene,
            [character],
            ["hi"],
            "",
            LoadingStatus(None),
            _options_all_disabled(),
        )

    assert agents.client.prompt_history == []
    assert character.description == "raw description"


async def test_process_characters_fast_mode_restores_card_examples_on_miss(fast_mode):
    # example dialogue consolidated (the default) + missed by the response
    # (fill_misses off) - the card's original examples must survive
    agents = fast_mode
    creator = agents.creator
    cc_config = creator.actions["character_creation"].config
    cc_config["fill_misses"].value = False
    character = _card_character()
    scene = _scene_stub()

    try:
        async with MockClientContext():
            client_responses.get().append(
                unified_response(
                    description="generated description",
                    attributes="Age: 20",
                    dialogue_instructions="generated instructions",
                )
            )
            await _process_characters_for_import(
                scene,
                [character],
                ["hi"],
                "raw mes example",
                LoadingStatus(None),
                CharacterCardImportOptions(),
            )
    finally:
        cc_config["fill_misses"].value = True

    assert prompt_kinds(agents.client) == [KIND_UNIFIED]
    assert character.example_dialogue == ["Hero: raw example"]
    assert character.description == "generated description"


async def test_process_characters_fast_mode_transient_error_keeps_card_data(fast_mode):
    # non-accuracy failures (e.g. a transient error in an individual fallback
    # request) warn and keep the card's data, mirroring the split helpers
    agents = fast_mode
    character = _card_character()
    scene = _scene_stub()

    with (
        patch.object(
            agents.creator,
            "generate_character_aspects",
            autospec=True,
            side_effect=RuntimeError("boom"),
        ),
        patch.object(
            agents.director, "assign_voice_to_character", autospec=True
        ) as mock_voice,
    ):
        await _process_characters_for_import(
            scene,
            [character],
            ["hi"],
            "raw mes example",
            LoadingStatus(None),
            CharacterCardImportOptions(),
        )

    assert character.description == "raw description"
    assert character.example_dialogue == ["Hero: raw example"]
    mock_voice.assert_awaited_once()


async def test_process_characters_fast_mode_accuracy_error_is_hard(fast_mode):
    # a completely unparseable consolidated response stays a hard error
    agents = fast_mode
    character = _card_character()
    scene = _scene_stub()

    async with MockClientContext():
        client_responses.get().append("total garbage without any sections")
        with pytest.raises(LLMAccuracyError):
            await _process_characters_for_import(
                scene,
                [character],
                ["hi"],
                "",
                LoadingStatus(None),
                CharacterCardImportOptions(),
            )

    assert prompt_kinds(agents.client) == [KIND_UNIFIED]
    assert character.example_dialogue == ["Hero: raw example"]


async def test_process_characters_fast_mode_cancellation_propagates(fast_mode):
    # user cancellation must abort the import, not be swallowed as a warning
    agents = fast_mode
    character = _card_character()
    scene = _scene_stub()

    with patch.object(
        agents.creator,
        "generate_character_aspects",
        autospec=True,
        side_effect=GenerationCancelled(),
    ):
        with pytest.raises(GenerationCancelled):
            await _process_characters_for_import(
                scene,
                [character],
                ["hi"],
                "",
                LoadingStatus(None),
                CharacterCardImportOptions(),
            )

    assert character.example_dialogue == ["Hero: raw example"]


@pytest.mark.parametrize(
    "aspect,agent_attr,method",
    [
        ("extract_description", "creator", "determine_character_description"),
        ("extract_attributes", "world_state", "extract_character_sheet"),
        (
            "extract_dialogue_instructions",
            "creator",
            "determine_character_dialogue_instructions",
        ),
        (
            "extract_dialogue_examples",
            "creator",
            "determine_character_dialogue_examples",
        ),
    ],
)
async def test_process_characters_split_mode_cancellation_propagates(
    agents, aspect, agent_attr, method
):
    # user cancellation must abort the split-mode import, not be swallowed
    # as one warning per aspect (parity with the fast path)
    character = _card_character()
    scene = _scene_stub()

    with patch.object(
        getattr(agents, agent_attr),
        method,
        autospec=True,
        side_effect=GenerationCancelled(),
    ):
        with pytest.raises(GenerationCancelled):
            await _process_characters_for_import(
                scene,
                [character],
                ["hi"],
                "",
                LoadingStatus(None),
                _options_all_disabled(**{aspect: True}),
            )


async def test_determine_character_context_cancellation_propagates(agents):
    # the content-context step runs before the fast/split branch - a
    # cancellation there must abort the import in both modes
    scene = _scene_stub()

    with patch.object(
        agents.creator,
        "determine_content_context_for_character",
        autospec=True,
        side_effect=GenerationCancelled(),
    ):
        with pytest.raises(GenerationCancelled):
            await character_card._determine_character_context(
                scene, _card_character(), LoadingStatus(None)
            )


async def test_generate_story_intent_cancellation_propagates(agents):
    # the story-intent step runs last in the pipeline - a swallowed
    # cancellation would complete the import and leak the latched cancel
    # flag into the next unrelated generation
    scene = _scene_stub()

    with patch.object(
        agents.creator,
        "contextual_generate_from_args",
        autospec=True,
        side_effect=GenerationCancelled(),
    ):
        with pytest.raises(GenerationCancelled):
            await character_card._generate_story_intent(scene, LoadingStatus(None))


def test_setup_loading_status_fast_mode_counts_one_step_per_character(fast_mode):
    status = _setup_loading_status(CharacterCardImportOptions(), num_characters=2)
    # card + memory + content context + 1 consolidated step per character +
    # story intent
    assert status.max_steps == 2 + 1 + 2 * 1 + 1


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
def pipeline_recorders(monkeypatch, agents):
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
