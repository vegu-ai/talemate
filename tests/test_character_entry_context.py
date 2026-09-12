"""Regression tests for Conversation's zero-request character-entry window."""

from copy import deepcopy

import pytest

from conftest import MockScene, bootstrap_scene
from talemate.agents.conversation.entry_context import (
    ENTRY_FACT_LIMIT,
    ENTRY_BRIEFING_MIN_CHARS,
    ENTRY_ORIENTATION_TOKEN_LIMIT,
    ENTRY_WINDOWS_STATE_KEY,
    CharacterEntryOrientation,
    build_entry_orientation,
    entry_windows,
    render_entry_block,
    set_entry_briefing,
)
from talemate.character import Character, activate_character
from talemate.context import ActiveScene
from talemate.events import CharacterActivatedEvent, GameLoopNewMessageEvent
from talemate.instance import get_agent
from talemate.knowledge.schema import Fact
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage, NarratorMessage
from talemate.tale_mate import Actor, Player
from talemate.util import count_tokens


def add_characters(scene, conversation):
    characters = {
        "Alice": Character(name="Alice"),
        "Bob": Character(name="Bob", is_player=True),
        "Cara": Character(name="Cara"),
    }
    for character in characters.values():
        actor_type = Player if character.is_player else Actor
        actor = actor_type(character, None if character.is_player else conversation)
        actor.scene = scene
        scene.character_data[character.name] = character
        if character.name != "Cara":
            scene.actors.append(actor)
            scene.active_characters.append(character.name)
    return characters


@pytest.fixture
def entry_scene(scene):
    conversation = get_agent("conversation")
    characters = add_characters(scene, conversation)
    with ActiveScene(scene):
        yield scene, conversation, characters


def activation(scene, character):
    return CharacterActivatedEvent(
        scene=scene,
        character=character,
        event_type="character.activated",
    )


def line_event(scene, text):
    return GameLoopNewMessageEvent(
        scene=scene,
        event_type="game_loop_new_message",
        message=CharacterMessage(text),
    )


@pytest.mark.asyncio
async def test_activation_window_consumes_only_committed_own_lines(entry_scene):
    scene, conversation, characters = entry_scene
    scene.ts = 120
    scene.history.append(NarratorMessage("The scene was already underway."))

    await conversation.on_character_activated(activation(scene, characters["Alice"]))

    window = entry_windows(conversation)["Alice"]
    assert window.boundary_message_id == scene.history[-1].id
    assert window.entry_scene_time == 120
    assert window.remaining_turns == 3

    # Building or retrying a prompt is read-only, and another speaker cannot
    # consume Alice's private entry window.
    assert build_entry_orientation(conversation, characters["Alice"])
    assert build_entry_orientation(conversation, characters["Alice"])
    await conversation.on_new_message(line_event(scene, "Bob: Welcome back."))
    assert entry_windows(conversation)["Alice"].remaining_turns == 3

    await conversation.on_new_message(line_event(scene, "Alice: First reply."))
    await conversation.on_new_message(line_event(scene, "Alice: Second reply."))
    assert entry_windows(conversation)["Alice"].remaining_turns == 1
    await conversation.on_new_message(line_event(scene, "Alice: Third reply."))
    assert "Alice" not in entry_windows(conversation)


@pytest.mark.asyncio
async def test_explicit_activate_character_signal_starts_window(
    scene, activation_signal
):
    conversation = get_agent("conversation")
    alice = Character(name="Alice")
    scene.character_data[alice.name] = alice
    conversation.connect(scene)

    with ActiveScene(scene):
        result = await activate_character(scene, alice)

    assert result is None
    assert entry_windows(conversation)["Alice"].remaining_turns == 3


@pytest.mark.asyncio
async def test_reentry_restarts_window_at_new_boundary(entry_scene):
    scene, conversation, characters = entry_scene
    await conversation.on_character_activated(activation(scene, characters["Alice"]))
    await conversation.on_new_message(line_event(scene, "Alice: One reply."))
    scene.history.append(NarratorMessage("Time passes before Alice returns."))
    scene.ts = 600

    await conversation.on_character_activated(activation(scene, characters["Alice"]))

    restarted = entry_windows(conversation)["Alice"]
    assert restarted.boundary_message_id == scene.history[-1].id
    assert restarted.entry_scene_time == 600
    assert restarted.remaining_turns == 3


@pytest.mark.asyncio
async def test_disabled_character_knowledge_does_not_start_window(entry_scene):
    scene, conversation, characters = entry_scene
    conversation.actions["character_knowledge"].enabled = False

    await conversation.on_character_activated(activation(scene, characters["Alice"]))

    assert entry_windows(conversation) == {}


def test_entry_turn_setting_is_available_in_both_knowledge_modes(entry_scene):
    scene, conversation, _ = entry_scene
    config = conversation.actions["character_knowledge"].config
    assert config["character_entry_turns"].value == 3
    scene.knowledge_eligibility = "perception"
    sanitized = conversation.sanitized_action_config["character_knowledge"]["config"]
    assert "character_entry_turns" in sanitized
    assert "brief_characters_on_entry" in sanitized


@pytest.mark.asyncio
async def test_player_activation_gets_orientation_without_a_request(entry_scene):
    scene, conversation, characters = entry_scene
    before = len(scene.mock_client.prompt_history)

    await conversation.on_character_activated(activation(scene, characters["Bob"]))

    orientation = build_entry_orientation(conversation, characters["Bob"])
    assert orientation is not None
    assert orientation.character_name == "Bob"
    assert len(scene.mock_client.prompt_history) == before


@pytest.mark.asyncio
async def test_saved_window_resumes_and_connect_does_not_reactivate(entry_scene):
    scene, conversation, characters = entry_scene
    await conversation.on_character_activated(activation(scene, characters["Alice"]))
    await conversation.on_new_message(line_event(scene, "Alice: One reply."))
    saved_state = deepcopy(scene.agent_state)

    reloaded = MockScene()
    agents = bootstrap_scene(reloaded)
    reloaded.agent_state = saved_state
    reloaded_characters = add_characters(reloaded, agents["conversation"])
    agents["conversation"].connect(reloaded)

    resumed = entry_windows(agents["conversation"])["Alice"]
    assert resumed.remaining_turns == 2
    assert build_entry_orientation(agents["conversation"], reloaded_characters["Alice"])


@pytest.mark.asyncio
async def test_live_orientation_scopes_facts_lines_roster_and_time(entry_scene):
    scene, conversation, characters = entry_scene
    scene.description = "READER-ONLY RAW SCENE DESCRIPTION"
    scene.ts = 100
    scene.history.append(NarratorMessage("Before Alice entered."))
    await conversation.on_character_activated(activation(scene, characters["Alice"]))

    scene.world_state.facts = {
        "F1": Fact(
            id="F1",
            text="Bob wears a silver compass.",
            subjects=["Bob"],
            present=["Alice"],
            importance=3,
            ts=90,
        ),
        "F2": Fact(
            id="F2",
            text="Bob hides a reader-only map.",
            subjects=["Bob"],
            present=["Bob"],
            importance=3,
            ts=95,
        ),
        "F3": Fact(
            id="F3",
            text="Cara carries a green lantern.",
            subjects=["Cara"],
            present=["Alice"],
            importance=3,
            ts=95,
        ),
        "F4": Fact(
            id="F4",
            text="Bob's boots are muddy.",
            subjects=["Bob"],
            present=["Alice"],
            importance=1,
            ts=99,
        ),
    }
    for index in range(7):
        scene.history.append(
            NarratorMessage(
                f"Visible moment {index}.",
                present=["Alice", "Bob"],
            )
        )
    scene.history.append(NarratorMessage("Bob's private aside.", present=["Bob"]))
    scene.ts = 900

    orientation = build_entry_orientation(conversation, characters["Alice"])
    assert orientation is not None
    assert orientation.present_characters == ["Alice", "Bob"]
    assert "13 Minutes" in orientation.elapsed
    assert len(orientation.visible_lines) == 5
    assert orientation.visible_lines[0] == "Visible moment 2."
    rendered = conversation.character_entry_context(characters["Alice"])
    assert "Bob wears a silver compass" in rendered
    assert "Bob's boots are muddy" in rendered
    assert rendered.index("silver compass") < rendered.index("boots are muddy")
    assert "reader-only map" not in rendered
    assert "green lantern" not in rendered
    assert "private aside" not in rendered
    assert "READER-ONLY RAW SCENE DESCRIPTION" not in rendered

    # The content is recomputed on each prompt while the durable boundary stays
    # fixed rather than caching a stale snapshot at activation time.
    scene.world_state.facts["F5"] = Fact(
        id="F5",
        text="Bob now holds a brass key.",
        subjects=["Bob"],
        present=["Alice"],
        importance=3,
        ts=900,
    )
    assert "brass key" in conversation.character_entry_context(characters["Alice"])


@pytest.mark.asyncio
async def test_orientation_caps_ranked_facts_and_rendered_tokens(entry_scene):
    scene, conversation, characters = entry_scene
    await conversation.on_character_activated(activation(scene, characters["Alice"]))
    scene.world_state.facts = {
        f"F{index}": Fact(
            id=f"F{index}",
            text=f"Bob remembers bounded fact {index}. " + "detail " * 200,
            subjects=["Bob"],
            present=["Alice"],
            importance=3,
            ts=index,
        )
        for index in range(1, 25)
    }

    orientation = build_entry_orientation(conversation, characters["Alice"])

    assert len(orientation.known_facts) == ENTRY_FACT_LIMIT
    orientation.visible_lines = [
        f"Visible line {index}: " + "scene " * 40 for index in range(5)
    ]
    rendered = render_entry_block(orientation)
    assert count_tokens(rendered) <= ENTRY_ORIENTATION_TOKEN_LIMIT
    assert rendered.startswith("## Character entry orientation")
    assert "Visible line 4" in rendered


def test_orientation_ceiling_counts_newlines_and_keeps_complete_section():
    orientation = CharacterEntryOrientation(
        character_name="Alice",
        remaining_turns=3,
        present_characters=["Alice", "Bob"],
        elapsed="Moments",
        known_facts=["\n".join([f"detail-{index}"] * 300) for index in range(12)],
        visible_lines=[f"Visible line {index}" for index in range(5)],
    )

    rendered = render_entry_block(orientation)

    assert count_tokens(rendered) <= ENTRY_ORIENTATION_TOKEN_LIMIT
    assert rendered.startswith("## Character entry orientation")
    assert "Visible line 4" in rendered
    raw = Prompt.get(
        "conversation.character-entry",
        vars={"entry_orientation": orientation},
    ).render(apply_sectioning=False)
    assert raw.rstrip().endswith("<|CLOSE_SECTION|>")


@pytest.mark.asyncio
async def test_generated_briefing_uses_same_complete_section_ceiling(entry_scene):
    _, conversation, characters = entry_scene
    await conversation.on_character_activated(
        activation(conversation.scene, characters["Alice"])
    )
    assert set_entry_briefing(
        conversation,
        "Alice",
        "\n".join(["A densely detailed private observation."] * 1500),
    )

    rendered = conversation.character_entry_context(characters["Alice"])

    assert count_tokens(rendered) <= ENTRY_ORIENTATION_TOKEN_LIMIT
    assert rendered.startswith("## Character entry briefing")
    raw = Prompt.get(
        "conversation.character-entry-briefing-context",
        vars={
            "character_name": "Alice",
            "briefing": "A complete briefing.",
            "remaining_turns": 3,
        },
    ).render(apply_sectioning=False)
    assert raw.rstrip().endswith("<|CLOSE_SECTION|>")


@pytest.mark.parametrize(
    "briefing",
    [
        "\n".join(["x"] * 1500),
        "界" * 1500,
    ],
)
def test_generated_briefing_ceiling_preserves_low_ratio_text(briefing):
    from talemate.agents.conversation.entry_context import (
        render_entry_briefing_context,
    )

    rendered = render_entry_briefing_context("Alice", briefing, 3)

    assert count_tokens(rendered) <= ENTRY_ORIENTATION_TOKEN_LIMIT
    retained = rendered.count("x") if "x" in briefing else rendered.count("界")
    assert retained >= ENTRY_BRIEFING_MIN_CHARS


@pytest.mark.asyncio
async def test_orientation_uses_shared_conversation_format(entry_scene):
    scene, conversation, characters = entry_scene
    await conversation.on_character_activated(activation(scene, characters["Alice"]))
    message = CharacterMessage("Bob: Welcome back.", present=["Alice", "Bob"])
    scene.history.append(message)

    orientation = build_entry_orientation(conversation, characters["Alice"])

    assert orientation.visible_lines == [message.as_format("movie_script").strip()]


@pytest.mark.asyncio
async def test_reentry_reports_time_since_character_was_away(entry_scene):
    scene, conversation, characters = entry_scene
    scene.archived_history = [
        {"id": "a1", "text": "Alice was here.", "ts": 100, "present": ["Alice"]},
        {"id": "a2", "text": "Alice was away.", "ts": 1000, "present": ["Bob"]},
    ]
    scene.ts = 173800

    await conversation.on_character_activated(activation(scene, characters["Alice"]))
    orientation = build_entry_orientation(conversation, characters["Alice"])

    assert entry_windows(conversation)["Alice"].away_scene_time == 1000
    assert "2 Days" in orientation.away_elapsed
    assert "Time away before entry: 2 Days" in render_entry_block(orientation)

    scene.ts += 86400
    later = build_entry_orientation(conversation, characters["Alice"])
    assert "2 Days" in later.away_elapsed
    assert "3 Days" not in later.away_elapsed


def test_malformed_saved_windows_are_ignored(entry_scene):
    _, conversation, _ = entry_scene
    conversation.set_scene_states(
        **{
            ENTRY_WINDOWS_STATE_KEY: {
                "Alice": {"remaining_turns": -2},
                "Bob": "not a window",
            }
        }
    )
    assert entry_windows(conversation) == {}
