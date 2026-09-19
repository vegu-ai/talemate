import json
from unittest.mock import AsyncMock, Mock

import pytest

from talemate.character import Character
from talemate.context import ActiveScene
from talemate.instance import get_agent
from talemate.knowledge.advice import advice_context
from talemate.knowledge.intro import initialize_intro_audience
from talemate.knowledge.memory import audience_documents
from talemate.knowledge.perspectives import (
    select_character_view,
    set_source_perspectives,
    source_reference,
    validate_saved_knowledge,
)
from talemate.knowledge.rename import rename_knowledge_references
from talemate.knowledge.snapshots import snapshot_audience_context
from talemate.load import load_scene_from_data
from talemate.scene_message import CharacterMessage, NarratorMessage
from talemate.tale_mate import Actor, Scene


INTRO = "The opening bell reveals a ruby beneath the sundial."


@pytest.fixture
def intro_scene(scene):
    for name in ("Alice", "Bob", "Player"):
        character = Character(name=name, is_player=name == "Player")
        scene.character_data[name] = character
        if name != "Bob":
            actor = Actor(character, get_agent("conversation"))
            actor.scene = scene
            scene.actors.append(actor)
    scene.active_characters = ["Alice", "Player"]
    get_agent("editor").actions["fix_exposition"].enabled = False
    return scene


def activate_bob(scene):
    actor = Actor(scene.character_data["Bob"], get_agent("conversation"))
    actor.scene = scene
    scene.actors.append(actor)
    scene.active_characters.append("Bob")


@pytest.mark.parametrize("best_fit", [False, True])
@pytest.mark.parametrize("mode", ["legacy", "perception"])
def test_late_arrival_lacks_intro_but_opening_audience_keeps_it(
    intro_scene, best_fit, mode
):
    scene = intro_scene
    scene.knowledge_eligibility = mode
    scene.set_intro(INTRO)
    summarizer = get_agent("summarizer")
    summarizer.actions["manage_scene_history"].config["best_fit"].value = best_fit
    for index in range(20):
        message = CharacterMessage(
            message=f"Alice: Opening-only exchange {index}.",
            present=["Alice", "Player"],
        )
        scene.history.append(message)
        if mode == "perception":
            set_source_perspectives(
                scene,
                "message",
                message.id,
                [
                    {
                        "audience": ["Alice", "Player"],
                        "status": "ready",
                        "text": message.message,
                    }
                ],
            )
    activate_bob(scene)
    arrival = NarratorMessage(
        message="Bob arrives at the square.", present=list(scene.active_characters)
    )
    scene.history.append(arrival)
    if mode == "perception":
        set_source_perspectives(
            scene,
            "message",
            arrival.id,
            [
                {
                    "audience": list(scene.active_characters),
                    "status": "ready",
                    "text": arrival.message,
                }
            ],
        )
    alice = "\n".join(
        scene.context_history(budget=10000, perspective="Alice", stored_views=True)
    )
    bob = "\n".join(
        scene.context_history(budget=10000, perspective="Bob", stored_views=True)
    )
    assert INTRO in alice
    assert "Opening-only exchange" in alice
    assert INTRO not in bob
    assert "Opening-only exchange" not in bob
    assert "Bob arrives" in bob
    assert INTRO in "\n".join(scene.context_history(budget=10000))
    assert scene.get_intro() == INTRO
    assert scene.intro_present == ["Alice", "Player"]


@pytest.mark.parametrize(
    "present,expected", [(["Alice"], ["Alice"]), ([], []), (None, ["Alice", "Player"])]
)
def test_derive_opening_presence_then_roster_once(intro_scene, present, expected):
    scene = intro_scene
    scene.intro = INTRO
    scene.history = [NarratorMessage(message="Opening moment", present=present)]
    initialize_intro_audience(scene)
    assert scene.intro_present == expected
    activate_bob(scene)
    initialize_intro_audience(scene)
    assert scene.intro_present == expected


def test_explicit_empty_audience_beats_history_and_roster(intro_scene):
    scene = intro_scene
    scene.intro = INTRO
    scene.history = [NarratorMessage(message="Opening", present=["Alice"])]
    initialize_intro_audience(scene, {"intro_present": []})
    assert scene.intro_present == []
    assert scene.get_intro(perspective="Alice") == ""
    assert scene.get_intro() == INTRO
    assert json.loads(scene.json)["intro_present"] == []


@pytest.mark.asyncio
async def test_deterministic_intro_supports_analysis_and_memory(intro_scene):
    scene = intro_scene
    scene.knowledge_eligibility = "perception"
    scene.set_intro(INTRO)
    activate_bob(scene)
    reference = source_reference(scene, "intro", "intro")
    assert select_character_view(scene, reference, "Bob").status == "unavailable"
    assert select_character_view(scene, reference, "Alice").text == INTRO
    documents = audience_documents(scene, groups={("intro", "intro", 0)})
    assert len(documents) == 1
    document = next(iter(documents.values()))
    assert document["text"] == INTRO
    assert document["meta"]["knowledge_audience"] == ["Alice", "Player"]
    assert document["meta"]["knowledge_common"] is False
    assert (
        INTRO in advice_context(scene, scene.character_data["Alice"], 3000)["history"]
    )
    assert (
        INTRO not in advice_context(scene, scene.character_data["Bob"], 3000)["history"]
    )
    cast = {
        item["name"]: item for item in snapshot_audience_context(scene, 3000)["cast"]
    }
    assert cast["Alice"]["established_knowledge"][0]["text"] == INTRO
    assert cast["Bob"]["established_knowledge"] == []


def test_intro_edit_invalidates_old_evidence_and_stamps_new_audience(intro_scene):
    scene = intro_scene
    scene.knowledge_eligibility = "perception"
    scene.set_intro(INTRO)
    previous = source_reference(scene, "intro", "intro")
    scene.active_characters = ["Bob"]
    scene.set_intro("The next opening belongs to Bob.")
    assert scene.intro_present == ["Bob"]
    assert select_character_view(scene, previous, "Alice").status == "pending"
    current = source_reference(scene, "intro", "intro")
    assert current.revision > previous.revision
    assert select_character_view(scene, current, "Bob").status == "ready"
    assert select_character_view(scene, current, "Alice").status == "unavailable"


def test_rename_preserves_intro_access_and_serialized_evidence(intro_scene):
    scene = intro_scene
    scene.knowledge_eligibility = "perception"
    scene.set_intro(INTRO)
    scene.character_data["Alice"].name = "Alicia"
    rename_knowledge_references(scene, "Alice", "Alicia")
    assert scene.intro_present == ["Alicia", "Player"]
    assert INTRO in scene.context_history(perspective="Alicia", stored_views=True)
    data = json.loads(scene.json)
    assert validate_saved_knowledge(data) is not None
    assert data["intro_present"] == ["Alicia", "Player"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "perception"])
async def test_real_load_preserves_intro_audience_after_late_activation(
    intro_scene, tmp_path, monkeypatch, mode
):
    scene = intro_scene
    scene.knowledge_eligibility = mode
    scene.set_intro(INTRO)
    activate_bob(scene)
    data = json.loads(scene.json)
    monkeypatch.setattr(Scene, "scenes_dir", classmethod(lambda cls: str(tmp_path)))
    memory = get_agent("memory")
    monkeypatch.setattr(memory, "set_db", AsyncMock(), raising=False)
    monkeypatch.setattr(
        memory, "get_document", AsyncMock(return_value={}), raising=False
    )
    await load_scene_from_data(scene, data, name="intro-audience.json")
    assert "Bob" in scene.active_characters
    assert scene.intro_present == ["Alice", "Player"]
    assert scene.get_intro(perspective="Bob") == ""
    assert INTRO in scene.context_history(perspective="Alice", stored_views=True)


def test_projected_intro_obeys_budget(intro_scene):
    scene = intro_scene
    scene.knowledge_eligibility = "perception"
    scene.set_intro(INTRO)
    assert scene.context_history(perspective="Alice", stored_views=True, budget=1) == []


@pytest.mark.asyncio
async def test_unchanged_outline_save_preserves_opening_audience(intro_scene):
    scene = intro_scene
    scene.knowledge_eligibility = "perception"
    scene.set_intro(INTRO)
    reference = source_reference(scene, "intro", "intro")
    activate_bob(scene)
    await scene.world_state_manager.update_scene_outline(
        title="A new title", intro=INTRO
    )
    assert scene.intro_present == ["Alice", "Player"]
    assert source_reference(scene, "intro", "intro") == reference
    assert INTRO not in scene.context_history(perspective="Bob", stored_views=True)


@pytest.mark.asyncio
async def test_switch_to_perspectives_initializes_existing_intro(intro_scene):
    scene = intro_scene
    scene.set_intro(INTRO)
    activate_bob(scene)
    await scene.world_state_manager.update_scene_settings(
        knowledge_eligibility="perception"
    )
    assert scene.intro_present == ["Alice", "Player"]
    assert INTRO in scene.context_history(perspective="Alice", stored_views=True)
    assert INTRO not in scene.context_history(perspective="Bob", stored_views=True)


@pytest.mark.asyncio
async def test_intro_apply_uses_no_generation_and_reader_emission_is_unchanged(
    intro_scene, monkeypatch
):
    scene = intro_scene
    scene.knowledge_eligibility = "perception"
    request = AsyncMock(side_effect=AssertionError("Unexpected LLM request"))
    monkeypatch.setattr("talemate.prompts.Prompt.request", request)
    monkeypatch.setattr(scene, "emit_status", Mock())
    reader = Mock()
    monkeypatch.setattr(scene, "narrator_message", reader)
    await scene.apply_intro(INTRO)
    reader.assert_called_once_with(INTRO)
    request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "audience,includes_intro", [(["Alice", "Player"], True), (["Bob"], False)]
)
async def test_first_summary_does_not_attribute_intro_to_a_different_audience(
    intro_scene, monkeypatch, audience, includes_intro
):
    scene = intro_scene
    scene.set_intro(INTRO)
    scene.history = [
        CharacterMessage(
            message=f"{audience[0]}: Later exchange {index}.",
            present=audience if index < 3 else ["Alice", "Bob", "Player"],
        )
        for index in range(5)
    ]
    summarizer = get_agent("summarizer")
    summarizer.actions["archive"].config["threshold"].value = 100000
    summarizer.actions["manage_scene_history"].config["best_fit"].value = False
    summarizer.actions["manage_scene_history"].config["enforce_boundary"].value = True
    summarize = AsyncMock(return_value="A summary of the exchange.")
    monkeypatch.setattr(summarizer, "summarize", summarize)
    monkeypatch.setattr(summarizer, "analyze_dialoge", AsyncMock(return_value=None))
    with ActiveScene(scene):
        assert await summarizer.build_archive(scene)
    assert (INTRO in summarize.call_args.args[0]) is includes_intro
    assert summarize.await_count == 1
    entry = scene.archived_history[0]
    assert entry["intro_included"] is includes_intro
    assert entry["present"] == sorted(audience)
    if not includes_intro:
        assert INTRO in "\n".join(scene.context_history(budget=10000))
        assert INTRO in "\n".join(
            scene.context_history(budget=10000, perspective="Alice")
        )
        bob = "\n".join(
            scene.context_history(
                budget=10000, perspective="Bob", assured_dialogue_num=0
            )
        )
        assert INTRO not in bob
        assert "summary of the exchange" in bob
