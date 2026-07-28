"""Tests for the creator agent's character helpers — the dialogue example
generation flow and its signals, consolidated ("Fast") generation, and the
generate_character_aspects orchestrator.

All LLM-backed paths are tested at the client response level (MockClient +
client_responses queue): real templates render, real extraction/parsing
runs, and routing is asserted via MockClient.prompt_history. The response
queue is order-coupled by design — aspect order is behavior."""

import pytest
import pydantic
from unittest.mock import patch

import talemate.instance as instance
from talemate.agents.base import DynamicInstruction
from talemate.agents.creator.character import (
    CHARACTER_GENERATION_ASPECTS,
    CharacterCreatorMixin,
    CharacterGenerationRequest,
    CharacterGenerationResult,
    _ASPECT_FILL_METHODS,
)
from talemate.agents.tts.schema import Voice
from talemate.agents.visual.schema import PromptFinalizer
from talemate.character import Character
from talemate.exceptions import LLMAccuracyError
from talemate.world_state.templates.content import (
    GenerationOptions,
    Spices,
    WritingStyle,
)

from conftest import (
    MockClient,
    MockClientContext,
    MockScene,
    bootstrap_engine,
    client_responses,
)
from _character_test_helpers import (
    DEFAULT_CONSOLIDATE,
    KIND_DESCRIPTION,
    KIND_DIALOGUE_INSTRUCTIONS,
    KIND_NAME,
    KIND_SHEET,
    KIND_UNIFIED,
    description_response,
    example_dialogue_response,
    name_response,
    prompt_kinds,
    sheet_response,
    unified_response,
)


@pytest.fixture
def creator():
    bootstrap_engine()
    scene = MockScene()
    client = MockClient("test_client")
    agent = instance.get_agent("creator")
    # the orchestrator's attributes fallback goes through the world_state
    # agent - wire it to the same client so prompt_history stays one ordered
    # stream across agents
    world_state = instance.get_agent("world_state")
    for _agent in (agent, world_state):
        _agent.client = client
        _agent.scene = scene
    return agent


@pytest.fixture
def scene_writing_style(creator, monkeypatch):
    """Give the scene a writing style. `Scene.writing_style` is a read-only
    property resolving a template id against the template collection, so the
    test shadows it on the MockScene class instead."""

    def _set(instructions: str):
        monkeypatch.setattr(
            type(creator.scene),
            "writing_style",
            WritingStyle(name="Scene style", instructions=instructions),
        )

    return _set


@pytest.fixture
def dialogue_examples_signals(isolate_signals):
    return isolate_signals(
        "agent.creator.dialogue_examples.before",
        "agent.creator.dialogue_examples.after",
    )


def _titles_section(prompt_text: str, title: str) -> str:
    """The body of a `## <title>` section in a rendered prompt (default
    "titles" sectioning)."""
    marker = f"## {title}"
    assert marker in prompt_text, f"section {marker!r} not found in prompt"
    start = prompt_text.index(marker) + len(marker)
    end = prompt_text.find("\n## ", start)
    return prompt_text[start:] if end == -1 else prompt_text[start:end]


@pytest.mark.asyncio
async def test_determine_character_description(creator):
    character = Character(name="Alice", description="A curious girl.")

    async with MockClientContext():
        client_responses.get().append(description_response("Alice", "is a tinkerer."))
        description = await creator.determine_character_description(character)

    assert description == "Alice is a tinkerer."


@pytest.mark.asyncio
async def test_determine_character_description_prime_only_reads_as_empty(creator):
    # the template primes the response with the character's name, so a
    # generation that produced nothing at all (empty client response, e.g.
    # after the user ignores a generation error) comes back as the bare
    # name - callers must see that as "nothing generated", not as a
    # one-word description
    character = Character(name="Alice", description="A curious girl.")

    async with MockClientContext():
        client_responses.get().append("")
        description = await creator.determine_character_description(character)

    assert description == ""


@pytest.mark.asyncio
async def test_determine_character_description_renders_generation_options(creator):
    # the caller's writing style and spice shape the description - the aspect
    # whose prose they apply to
    character = Character(name="Alice", description="A curious girl.")

    async with MockClientContext():
        client_responses.get().append(description_response("Alice", "is a tinkerer."))
        await creator.determine_character_description(
            character,
            generation_options=GenerationOptions(
                writing_style=WritingStyle(
                    name="Terse", instructions="Write in terse prose."
                ),
                spices=Spices(
                    name="Mood", instructions="{spice}", spices=["Make it ominous."]
                ),
                spice_level=1.0,
            ),
        )

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "Write in terse prose." in prompt
    assert "Make it ominous." in prompt


@pytest.mark.asyncio
async def test_determine_character_description_without_generation_options(creator):
    # no options and no scene writing style - no writing style / spice
    # sections at all, and in particular no empty ones
    character = Character(name="Alice", description="A curious girl.")

    async with MockClientContext():
        client_responses.get().append(description_response("Alice", "is a tinkerer."))
        await creator.determine_character_description(character)

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "WRITING STYLE" not in prompt
    assert "SPICE" not in prompt


@pytest.mark.asyncio
async def test_scene_writing_style_applies_to_split_description_without_options(
    creator, scene_writing_style
):
    # the scene's writing style reaches split-mode description generation
    # even when the caller passes no generation options (card import, the
    # DetermineCharacterDescription node and the scripting API pass nothing)
    scene_writing_style("Write in flowery prose.")
    character = Character(name="Alice", description="A curious girl.")

    async with MockClientContext():
        client_responses.get().append(description_response("Alice", "is a tinkerer."))
        await creator.determine_character_description(character)

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "Write in flowery prose." in prompt


@pytest.mark.asyncio
async def test_writing_style_with_literal_braces_renders_raw(
    creator, scene_writing_style
):
    # user-authored writing styles may contain literal braces (JSON
    # examples, {unknown} placeholders) - they must render raw instead of
    # crashing the generation
    scene_writing_style('Emit JSON like {"mood": "dark"} and stay terse.')

    async with MockClientContext():
        client_responses.get().append(
            unified_response(description="Elena is a skilled healer.")
        )
        await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["description"],
                name="Elena",
                content="A healer arrives.",
            )
        )

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert 'Emit JSON like {"mood": "dark"} and stay terse.' in prompt


@pytest.mark.asyncio
async def test_generate_character_unified_renders_generation_options(creator):
    # the one-shot covers the description too, so the same options apply
    async with MockClientContext():
        client_responses.get().append(
            unified_response(description="Elena is a skilled healer.")
        )
        await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["description"],
                name="Elena",
                content="A healer arrives.",
                generation_options=GenerationOptions(
                    writing_style=WritingStyle(
                        name="Terse", instructions="Write in terse prose."
                    ),
                    spices=Spices(
                        name="Mood",
                        instructions="{spice}",
                        spices=["Make it ominous."],
                    ),
                    spice_level=1.0,
                ),
            )
        )

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "Write in terse prose." in prompt
    assert "Make it ominous." in prompt


@pytest.mark.asyncio
async def test_generation_options_writing_style_wins_over_the_scene(
    creator, scene_writing_style
):
    # a caller-selected writing style overrides the scene's, rather than
    # rendering both
    scene_writing_style("Write in flowery prose.")

    async with MockClientContext():
        client_responses.get().append(
            unified_response(description="Elena is a skilled healer.")
        )
        await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["description"],
                name="Elena",
                content="A healer arrives.",
                generation_options=GenerationOptions(
                    writing_style=WritingStyle(
                        name="Terse", instructions="Write in terse prose."
                    )
                ),
            )
        )

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "Write in terse prose." in prompt
    assert "Write in flowery prose." not in prompt


@pytest.mark.asyncio
async def test_scene_writing_style_applies_without_generation_options(
    creator, scene_writing_style
):
    # regression guard for the one-shot's own writing style section, which
    # the generation options share a template with
    scene_writing_style("Write in flowery prose.")

    async with MockClientContext():
        client_responses.get().append(
            unified_response(description="Elena is a skilled healer.")
        )
        await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["description"],
                name="Elena",
                content="A healer arrives.",
            )
        )

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "Write in flowery prose." in prompt


@pytest.mark.asyncio
async def test_determine_character_dialogue_examples(creator):
    character = Character(name="Alice", description="A curious girl.")

    async with MockClientContext():
        client_responses.get().append(example_dialogue_response('"Oh dear!" she gasps'))
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
        client_responses.get().append(example_dialogue_response('"Hello there."'))
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
        client_responses.get().append(example_dialogue_response('"Curiouser!"'))
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
        client_responses.get().append(example_dialogue_response('"Hi."'))
        examples = await creator.determine_character_dialogue_examples(character)

    assert examples == ['Alice: "Hi."', "Alice: added by handler"]


# ---------------------------------------------------------------------------
# Consolidated ("Fast") character generation
# ---------------------------------------------------------------------------

ALL_ASPECTS = [
    "name",
    "description",
    "attributes",
    "dialogue_instructions",
    "example_dialogue",
]


_FULL_RESPONSE = unified_response(
    name="Elena",
    description="Elena is a skilled healer travelling the realm.",
    attributes="Age: early 30s\nOccupation: healer\nTrait: soft-spoken",
    dialogue_instructions="Speaks softly with a gentle tone. When pressed, her "
    "sentences get clipped and clinical.",
    example_dialogue='"Oh dear, let me look at that wound."\nElena: "Sit still."',
)


@pytest.mark.asyncio
async def test_generate_character_unified_all_aspects(creator):
    async with MockClientContext():
        client_responses.get().append(_FULL_RESPONSE)
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=ALL_ASPECTS,
                name="the tall woman with dark hair",
                content="A mysterious healer arrives at the clearing.",
            )
        )

    assert isinstance(result, CharacterGenerationResult)
    assert result.name == "Elena"
    assert result.description == "Elena is a skilled healer travelling the realm."
    assert result.attributes == {
        "Age": "early 30s",
        "Occupation": "healer",
        "Trait": "soft-spoken",
    }
    assert result.dialogue_instructions.startswith("Speaks softly")
    # first line missing the prefix gets normalized with the determined name
    assert result.example_dialogue == [
        'Elena: "Oh dear, let me look at that wound."',
        'Elena: "Sit still."',
    ]
    assert result.extracted_aspects() == set(ALL_ASPECTS)


@pytest.mark.asyncio
async def test_generate_character_unified_prompt_asks_only_requested_aspects(creator):
    async with MockClientContext():
        client_responses.get().append(
            unified_response(description="A healer.", dialogue_instructions="Soft.")
        )
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["description", "dialogue_instructions"],
                name="Elena",
                content="A healer.",
            )
        )

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "<DESCRIPTION>" in prompt
    assert "<DIALOGUE_INSTRUCTIONS>" in prompt
    assert "<NAME>" not in prompt
    assert "<ATTRIBUTES>" not in prompt
    assert "<EXAMPLE_DIALOGUE>" not in prompt
    assert result.extracted_aspects() == {"description", "dialogue_instructions"}


@pytest.mark.asyncio
async def test_generate_character_unified_open_sections_read_as_missed(creator):
    # a model that does not close its tags is not viable for consolidated
    # generation - open sections read as misses, never as salvage
    open_section_response = (
        "<NAME>Bram Velter\n\n"
        "<DESCRIPTION>Bram Velter is a thickly built, scarred veteran.\n\n"
        "<ATTRIBUTES>Age: late 40s\nOccupation: blacksmith\n\n"
        "<DIALOGUE_INSTRUCTIONS>Gruff and economical. When angry, monosyllabic.\n\n"
        '<EXAMPLE_DIALOGUE>Bram Velter: "Steel doesn\'t lie."\n'
        '"Poetry is for the quiet hours."'
    )
    async with MockClientContext():
        client_responses.get().append(open_section_response)
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=ALL_ASPECTS,
                name="a gruff blacksmith",
                content="A gruff blacksmith who secretly writes poetry.",
            )
        )

    assert result.extracted_aspects() == set()

    # closed sections extract; unclosed ones read as misses
    async with MockClientContext():
        client_responses.get().append(
            "<NAME>Elena</NAME>\n\n<DESCRIPTION>A healer without a closing tag."
        )
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["name", "description"],
                name="the tall woman",
                content="A healer arrives.",
            )
        )

    assert result.name == "Elena"
    assert result.description is None


@pytest.mark.asyncio
async def test_generate_character_unified_example_prefix_uses_fallback_name(creator):
    # no name aspect requested -> fallback name prefixes example lines
    async with MockClientContext():
        client_responses.get().append(unified_response(example_dialogue='"Hello."'))
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["example_dialogue"],
                name="Marcus",
                content="Marcus greets people.",
            )
        )

    assert result.example_dialogue == ['Marcus: "Hello."']


@pytest.mark.asyncio
async def test_generate_character_unified_example_prefix_raw_name_replaced(creator):
    # model echoed the raw descriptive name as the speaker prefix - it must
    # be normalized to the determined name
    async with MockClientContext():
        client_responses.get().append(
            unified_response(
                name="Elena",
                example_dialogue='the tall woman: "Hello."\nElena: "Hi."',
            )
        )
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["name", "example_dialogue"],
                name="the tall woman",
                content="A healer arrives.",
            )
        )

    assert result.example_dialogue == ['Elena: "Hello."', 'Elena: "Hi."']


@pytest.mark.asyncio
async def test_generate_character_unified_example_drops_bare_name_lines(creator):
    # models sometimes emit a bare "Name:" header or name-only line as part
    # of the example list - those carry no dialogue and must be dropped
    async with MockClientContext():
        client_responses.get().append(
            unified_response(
                name="Elena",
                example_dialogue='Elena:\nElena\n"Actual line one."\nElena: "Actual line two."',
            )
        )
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["name", "example_dialogue"],
                name="the tall woman",
                content="A healer arrives.",
            )
        )

    assert result.example_dialogue == [
        'Elena: "Actual line one."',
        'Elena: "Actual line two."',
    ]


@pytest.mark.asyncio
async def test_generate_character_unified_example_speaker_heuristics(creator):
    # multi-word name-shaped prefixes (another character's line) are dropped -
    # including non-ASCII names; single-word prefixes are kept - they are
    # more often dialogue content ("Warning:") than another speaker, and a
    # relabeled line is the lesser evil
    async with MockClientContext():
        client_responses.get().append(
            unified_response(
                name="Elena",
                example_dialogue=(
                    "Marcus Webb: hello\n"
                    "Agent 47: reported\n"
                    "Élodie Durand: bonjour\n"
                    "José Álvarez: hola\n"
                    "Warning: stay back!\n"
                    'Elena: "Mine."'
                ),
            )
        )
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["name", "example_dialogue"],
                name="the tall woman",
                content="A healer arrives.",
            )
        )

    assert result.example_dialogue == [
        "Elena: Warning: stay back!",
        'Elena: "Mine."',
    ]


@pytest.mark.asyncio
async def test_generate_character_unified_example_skipped_without_any_name(creator):
    # no determined name and no fallback - examples would come out as
    # ": Hello." lines, so the aspect reads as missed instead
    async with MockClientContext():
        client_responses.get().append(unified_response(example_dialogue='"Hello."'))
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["example_dialogue"], name="", content="A healer arrives."
            )
        )

    assert result.example_dialogue is None


@pytest.mark.asyncio
async def test_generate_character_unified_max_attributes(creator):
    async with MockClientContext():
        client_responses.get().append(
            unified_response(attributes="Age: 30\nOccupation: healer\nTrait: kind")
        )
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["attributes"],
                name="Elena",
                content="A healer.",
                max_attributes=2,
            )
        )

    assert result.attributes == {"Age": "30", "Occupation": "healer"}


@pytest.mark.asyncio
async def test_generate_character_unified_max_attributes_ignores_name_line(creator):
    # the one-shot prompt asks the model not to repeat the name as an
    # attribute, but a model that does anyway must not spend the budget on it
    async with MockClientContext():
        client_responses.get().append(
            unified_response(attributes="Name: Elena\nAge: 30\nOccupation: healer")
        )
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["attributes"],
                name="Elena",
                content="A healer.",
                max_attributes=1,
            )
        )

    assert result.attributes == {"Name": "Elena", "Age": "30"}


def test_unknown_aspect_rejected_at_construction():
    # the aspects Literal is the contract - pydantic rejects unknown aspects
    # at construction, before any generation method runs
    with pytest.raises(pydantic.ValidationError):
        CharacterGenerationRequest(aspects=["bogus"], name="Elena")


@pytest.mark.asyncio
async def test_generate_character_unified_attribute_instructions_rendered(creator):
    # attribute world-state template instructions fold into the attributes
    # section of the one-shot prompt
    async with MockClientContext():
        client_responses.get().append(
            unified_response(attributes="Appearance: scarred and weathered")
        )
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["attributes"],
                name="Bram",
                content="A veteran blacksmith.",
                attribute_instructions=[
                    {
                        "attribute": "Appearance",
                        "instructions": "scarred veteran looks",
                    },
                    {"attribute": "Demeanor", "instructions": ""},
                ],
            )
        )

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "Appearance: scarred veteran looks" in prompt
    assert "- Demeanor" in prompt
    assert "MUST be present" in prompt
    assert result.attributes == {"Appearance": "scarred and weathered"}


@pytest.mark.asyncio
async def test_generate_character_unified_example_dialogue_guidance_rendered(creator):
    # the user-provided example dialogue guidance reaches the one-shot
    # prompt (in split mode it goes through the individual request)
    async with MockClientContext():
        client_responses.get().append(
            unified_response(example_dialogue='Elena: "Oh dear!"')
        )
        result = await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["example_dialogue"],
                name="Elena",
                content="A healer arrives.",
                example_dialogue_instructions="She stammers when nervous.",
            )
        )

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "User-provided guidance for the dialogue examples:" in prompt
    assert "She stammers when nervous." in prompt
    assert result.example_dialogue == ['Elena: "Oh dear!"']


def test_consolidate_default(creator):
    # the shipped setting must stay the derived "everything" composition -
    # a hardcoded, narrowed or reordered value= fails here
    assert creator.cc_consolidate == DEFAULT_CONSOLIDATE


def test_consolidate_templates_default(creator):
    assert creator.cc_consolidate_templates is True


def test_one_shot_token_budget_clamped(creator):
    cfg = creator.actions["character_creation"].config["one_shot_token_budget"]
    cfg.value = 200
    try:
        assert creator.cc_one_shot_token_budget == 1024
        cfg.value = 99999
        assert creator.cc_one_shot_token_budget == 8192
    finally:
        cfg.value = 4096


def test_format_attribute_instructions():
    from talemate.agents.creator.character import format_attribute_instructions

    assert (
        format_attribute_instructions(
            [
                {"attribute": "Appearance", "instructions": "scarred looks"},
                {"attribute": "Demeanor", "instructions": ""},
            ]
        )
        == "- Appearance: scarred looks\n- Demeanor"
    )


@pytest.mark.asyncio
async def test_orchestrator_attributes_fallback_includes_augment(creator):
    # folded templates + one-shot miss + fill-misses: the augment text must
    # reach the rendered fallback prompt (extract-character-sheet's own
    # augmentation branch needs an existing character, which doesn't exist yet)
    async with MockClientContext():
        client_responses.get().append(
            unified_response(description="Bram is a veteran.")
        )
        client_responses.get().append(sheet_response("Bram", {"Age": "40"}))
        result = await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["description", "attributes"],
                name="Bram",
                content="A veteran blacksmith.",
                unified=True,
                consolidate=["description", "attributes"],
                fill_misses=True,
                attribute_instructions=[
                    {"attribute": "Appearance", "instructions": "scarred looks"}
                ],
                augment_attributes="Add some additional, interesting attributes.",
            )
        )

    assert prompt_kinds(creator.client) == [KIND_UNIFIED, KIND_SHEET]
    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "- Appearance: scarred looks" in prompt
    assert "Additionally: Add some additional, interesting attributes." in prompt
    assert result.attributes == {"Name": "Bram", "Age": "40"}


def test_history_budget_clamped():
    from talemate.agents.creator.character import one_shot_history_budget

    # a client context no bigger than the response budget must not produce a
    # negative history reservation
    assert one_shot_history_budget(4096, 4096) == 512
    assert one_shot_history_budget(16384, 4096) == 16384 - 4096 - 256


def test_effective_response_budget_clamped_to_context():
    from talemate.agents.creator.character import (
        one_shot_effective_response_budget,
        one_shot_history_budget,
    )

    # the configured budget wins when it fits
    assert one_shot_effective_response_budget(4096, 16384) == 4096
    # a 4096-context client with the default 4096 budget clamps so
    # history + overhead + response fit the context
    assert one_shot_effective_response_budget(4096, 4096) == 3328
    assert one_shot_history_budget(4096, 3328) + 256 + 3328 == 4096
    # at least 1024 for the response, even on tiny contexts
    assert one_shot_effective_response_budget(4096, 1024) == 1024
    # boundary: at exactly 1792 (= 512 + 256 + 1024) the invariant closes
    assert one_shot_effective_response_budget(4096, 1792) == 1024
    assert one_shot_history_budget(1792, 1024) + 256 + 1024 == 1792


@pytest.mark.asyncio
async def test_generate_character_unified_token_budget_kind(creator):
    # the response budget comes from the character_creation config and is
    # passed through as a parametric prompt kind
    assert creator.cc_one_shot_token_budget == 4096

    async with MockClientContext():
        client_responses.get().append(unified_response(description="A healer."))
        await creator.generate_character_unified(
            CharacterGenerationRequest(
                aspects=["description"], name="Elena", content="A healer."
            )
        )

    assert creator.client.prompt_history[-1]["kind"] == "create_4096"

    creator.actions["character_creation"].config["one_shot_token_budget"].value = 2048
    try:
        async with MockClientContext():
            client_responses.get().append(unified_response(description="A healer."))
            await creator.generate_character_unified(
                CharacterGenerationRequest(
                    aspects=["description"], name="Elena", content="A healer."
                )
            )

        assert creator.client.prompt_history[-1]["kind"] == "create_2048"
    finally:
        creator.actions["character_creation"].config[
            "one_shot_token_budget"
        ].value = 4096


# ---------------------------------------------------------------------------
# generate_character_aspects orchestrator — client-level routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_unified_covers_consolidated_aspects(creator):
    async with MockClientContext():
        client_responses.get().append(_FULL_RESPONSE)
        result = await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=ALL_ASPECTS,
                name="the tall woman",
                content="A healer arrives.",
                unified=True,
                consolidate=ALL_ASPECTS,
            )
        )

    assert result.extracted_aspects() == set(ALL_ASPECTS)
    # everything came from the one-shot - no individual requests were sent
    assert prompt_kinds(creator.client) == [KIND_UNIFIED]


@pytest.mark.asyncio
async def test_orchestrator_unconsolidated_aspects_use_individual(creator):
    async with MockClientContext():
        client_responses.get().append(unified_response(description="A healer."))
        client_responses.get().append(name_response("Elena"))
        result = await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["name", "description"],
                name="the tall woman",
                content="A healer arrives.",
                unified=True,
                consolidate=["description"],
            )
        )

    assert prompt_kinds(creator.client) == [KIND_UNIFIED, KIND_NAME]
    assert result.description == "A healer."
    assert result.name == "Elena"


@pytest.mark.asyncio
async def test_orchestrator_fill_misses_on(creator):
    async with MockClientContext():
        # consolidated response misses dialogue_instructions entirely
        client_responses.get().append(unified_response(description="A healer."))
        client_responses.get().append("Soft.")
        result = await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["description", "dialogue_instructions"],
                name="Elena",
                content="A healer.",
                unified=True,
                consolidate=["description", "dialogue_instructions"],
                fill_misses=True,
            )
        )

    assert prompt_kinds(creator.client) == [KIND_UNIFIED, KIND_DIALOGUE_INSTRUCTIONS]
    assert result.dialogue_instructions == "Soft."
    assert result.description == "A healer."


@pytest.mark.asyncio
async def test_orchestrator_fill_misses_off(creator):
    async with MockClientContext():
        client_responses.get().append(unified_response(description="A healer."))
        result = await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["description", "dialogue_instructions"],
                name="Elena",
                content="A healer.",
                unified=True,
                consolidate=["description", "dialogue_instructions"],
                fill_misses=False,
            )
        )

    # the miss is left empty - no individual fill request was sent
    assert prompt_kinds(creator.client) == [KIND_UNIFIED]
    assert result.dialogue_instructions is None
    assert result.description == "A healer."


@pytest.mark.parametrize(
    "response",
    [
        "total garbage without any sections",
        # fully-open output - a closed section for an aspect that was NOT
        # requested doesn't count as extracted either
        "<NAME>Bram Velter\n\n<DESCRIPTION>A veteran.</DESCRIPTION>",
    ],
    ids=["garbage", "open-output"],
)
@pytest.mark.asyncio
async def test_orchestrator_unparseable_response_is_hard_error(creator, response):
    # the model did not follow the structured format - the error says so
    # (choose a different model or disable Fast mode)
    async with MockClientContext():
        client_responses.get().append(response)
        with pytest.raises(LLMAccuracyError, match="choose a different model"):
            await creator.generate_character_aspects(
                CharacterGenerationRequest(
                    aspects=["name"],
                    name="the tall woman",
                    content="A healer arrives.",
                    unified=True,
                    consolidate=["name"],
                    fill_misses=True,
                )
            )

    # hard error even though fill_misses is on - nothing was extracted at
    # all, and no individual fills ran
    assert prompt_kinds(creator.client) == [KIND_UNIFIED]


@pytest.mark.asyncio
async def test_orchestrator_split_mode_uses_individual_only(creator):
    async with MockClientContext():
        client_responses.get().append(name_response("Elena"))
        client_responses.get().append(description_response("Elena", "is a healer."))
        client_responses.get().append("Soft.")
        result = await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["name", "description", "dialogue_instructions"],
                name="the tall woman",
                content="A healer arrives.",
                unified=False,
            )
        )

    # no unified prompt was sent - each aspect used its individual request,
    # in canonical aspect order
    assert prompt_kinds(creator.client) == [
        KIND_NAME,
        KIND_DESCRIPTION,
        KIND_DIALOGUE_INSTRUCTIONS,
    ]
    assert result.name == "Elena"
    assert result.description == "Elena is a healer."
    assert result.dialogue_instructions == "Soft."
    assert result.extracted_aspects() == {
        "name",
        "description",
        "dialogue_instructions",
    }


@pytest.mark.asyncio
async def test_orchestrator_description_fallback_matches_split_path(creator):
    # the director's split path passes information=content (layered on the
    # scene context) - the orchestrator's fallback must match by default:
    # the content renders in the INFORMATION section, not as the CONTENT
    # section (which keeps the scene context)
    async with MockClientContext():
        client_responses.get().append(description_response("Elena", "is a healer."))
        await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["description"],
                name="Elena",
                content="A healer arrives.",
                unified=False,
            )
        )

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "A healer arrives." in _titles_section(
        prompt, "Information related to the task"
    )
    assert "A healer arrives." not in _titles_section(prompt, "Content")


@pytest.mark.asyncio
async def test_orchestrator_description_fallback_text_role(creator):
    # content_role="text" (card import flow) replaces the scene context:
    # the content renders as the CONTENT section itself
    async with MockClientContext():
        client_responses.get().append(description_response("Elena", "is a healer."))
        await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["description"],
                name="Elena",
                content="A healer arrives.",
                unified=False,
                content_role="text",
            )
        )

    prompt = str(creator.client.prompt_history[-1]["prompt"])
    assert "A healer arrives." in _titles_section(prompt, "Content")
    assert "## Information related to the task" not in prompt


@pytest.mark.asyncio
async def test_orchestrator_does_not_mutate_passed_character(creator):
    character = Character(name="Kira", description="card description")

    async with MockClientContext():
        client_responses.get().append(_FULL_RESPONSE)
        await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=ALL_ASPECTS,
                name="Kira",
                content="Rewrite this card.",
                character=character,
                unified=True,
                consolidate=ALL_ASPECTS,
            )
        )

    assert character.name == "Kira"
    assert character.description == "card description"
    assert character.base_attributes == {}


@pytest.mark.asyncio
async def test_orchestrator_detaches_scene_bound_character(creator):
    # actor/agent are exclude=True and not deep-copyable - the orchestrator
    # detaches its working character via model_dump, so a scene-bound
    # character is safe to pass
    class Uncopyable:
        def __deepcopy__(self, memo):
            raise AssertionError("scene references must not be deep-copied")

    character = Character(name="Kira", description="card description")
    character.actor = Uncopyable()
    character.agent = Uncopyable()

    async with MockClientContext():
        client_responses.get().append(_FULL_RESPONSE)
        await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=ALL_ASPECTS,
                name="Kira",
                content="Rewrite this card.",
                character=character,
                unified=True,
                consolidate=ALL_ASPECTS,
            )
        )

    assert character.name == "Kira"
    assert character.description == "card description"
    assert character.base_attributes == {}


@pytest.mark.asyncio
async def test_orchestrator_working_character_carries_fields(creator):
    # the model_dump round-trip must carry every prompt-relevant field onto
    # the working character the fills see (a lost alias would silently
    # blank it) and drop the scene references
    character = Character(
        name="Kira",
        description="card description",
        details={"goals": "help"},
        dialogue_instructions="Soft.",
        example_dialogue=['Kira: "Hi."'],
        voice=Voice(label="Soft", provider="test", provider_id="v1"),
        visual_finalizers=[PromptFinalizer(match="ugly", replace="plain")],
    )
    character.actor = "scene-bound-actor"
    character.agent = "scene-bound-agent"

    seen = {}

    async def capture_fill(request, result, working_character):
        seen["working"] = working_character

    with patch.object(creator, "_fill_aspect_description", side_effect=capture_fill):
        await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["description"],
                name="Kira",
                character=character,
                unified=False,
            )
        )

    working = seen["working"]
    assert working.details == {"goals": "help"}
    assert working.dialogue_instructions == "Soft."
    assert working.example_dialogue == ['Kira: "Hi."']
    assert working.voice is not None
    assert working.voice.id == "test:v1"
    assert working.visual_finalizers[0].match == "ugly"
    assert working.actor is None
    assert working.agent is None


@pytest.mark.parametrize(
    "consolidate",
    [["example_dialogue"], ["name", "example_dialogue"]],
    ids=["name-not-consolidated", "name-missed-by-one-shot"],
)
@pytest.mark.asyncio
async def test_orchestrator_renames_example_prefixes_after_late_name(
    creator, consolidate
):
    # the one-shot normalizes example dialogue against the raw fallback name
    # (the name aspect was either excluded from the one-shot, or consolidated
    # but missed by the response) - the prefixes must be redone once the real
    # name is determined in the fill loop
    async with MockClientContext():
        client_responses.get().append(
            unified_response(example_dialogue='the tall woman: "Hello."')
        )
        client_responses.get().append(name_response("Elena"))
        result = await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["name", "example_dialogue"],
                name="the tall woman",
                content="A healer arrives.",
                unified=True,
                consolidate=consolidate,
            )
        )

    assert prompt_kinds(creator.client) == [KIND_UNIFIED, KIND_NAME]
    assert result.name == "Elena"
    assert result.example_dialogue == ['Elena: "Hello."']


@pytest.mark.asyncio
async def test_orchestrator_reads_agent_config_by_default(creator):
    creator.actions["character_creation"].config["fast"].value = True
    try:
        async with MockClientContext():
            client_responses.get().append(_FULL_RESPONSE)
            result = await creator.generate_character_aspects(
                CharacterGenerationRequest(
                    aspects=ALL_ASPECTS,
                    name="the tall woman",
                    content="A healer arrives.",
                )
            )
    finally:
        creator.actions["character_creation"].config["fast"].value = False

    # fast + default consolidate (every aspect) means the one-shot covered
    # everything - no individual requests were sent
    assert prompt_kinds(creator.client) == [KIND_UNIFIED]
    assert result.name == "Elena"
    assert result.example_dialogue == [
        'Elena: "Oh dear, let me look at that wound."',
        'Elena: "Sit still."',
    ]


@pytest.mark.asyncio
async def test_orchestrator_attributes_prompt_gets_description_via_context(creator):
    # empty content + pre-supplied description, character not in the scene
    # (the pre-creation paths): the description reaches the sheet prompt via
    # the character context, not mislabelled as instructions
    async with MockClientContext():
        client_responses.get().append(sheet_response("Elena", {"Age": "30"}))
        result = await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["attributes"],
                name="Elena",
                description="A dedicated healer.",
                unified=False,
            )
        )

    assert prompt_kinds(creator.client) == [KIND_SHEET]
    prompt = str(creator.client.prompt_history[0]["prompt"])
    assert "A dedicated healer." in prompt
    assert "Instructions for the character" not in prompt
    assert result.attributes == {"Name": "Elena", "Age": "30"}


@pytest.mark.asyncio
async def test_orchestrator_attributes_prompt_scene_character_not_duplicated(creator):
    # scene-bound path (director split flow: the character is an actor, not
    # yet activated, and the request passes it explicitly): the description
    # renders exactly once, sourced from the working character
    character = Character(name="Elena", description="A dedicated healer.", color="#fff")
    actor = creator.scene.Actor(character, None)
    await creator.scene.add_actor(actor, commit_to_memory=False)

    async with MockClientContext():
        client_responses.get().append(sheet_response("Elena", {"Age": "30"}))
        await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["attributes"],
                name="Elena",
                character=character,
                unified=False,
            )
        )

    prompt = str(creator.client.prompt_history[0]["prompt"])
    assert prompt.count("A dedicated healer.") == 1


@pytest.mark.asyncio
async def test_orchestrator_attributes_prompt_character_data_only(creator):
    # card-import state: the character is registered in character_data but
    # has no actor - the actor loop misses it, so the explicit context
    # character must carry the description. An unrelated active character
    # still renders.
    character = Character(name="Elena", description="A dedicated healer.")
    creator.scene.character_data["Elena"] = character
    other = Character(name="Bram", description="A veteran smith.", color="#fff")
    await creator.scene.add_actor(
        creator.scene.Actor(other, None), commit_to_memory=False
    )

    async with MockClientContext():
        client_responses.get().append(sheet_response("Elena", {"Age": "30"}))
        await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["attributes"],
                name="Elena",
                character=character,
                unified=False,
            )
        )

    prompt = str(creator.client.prompt_history[0]["prompt"])
    assert prompt.count("A dedicated healer.") == 1
    assert prompt.count("A veteran smith.") == 1


@pytest.mark.asyncio
async def test_orchestrator_attributes_prompt_explicit_character_wins(creator):
    # name collision with a different, active scene character: the explicit
    # working character's description renders, the scene one's does not
    scene_character = Character(
        name="Elena", description="The scene Elena.", color="#fff"
    )
    await creator.scene.add_actor(
        creator.scene.Actor(scene_character, None), commit_to_memory=False
    )
    working_source = Character(name="Elena", description="The working Elena.")

    async with MockClientContext():
        client_responses.get().append(sheet_response("Elena", {"Age": "30"}))
        await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["attributes"],
                name="Elena",
                character=working_source,
                unified=False,
            )
        )

    prompt = str(creator.client.prompt_history[0]["prompt"])
    assert "The working Elena." in prompt
    assert "The scene Elena." not in prompt


def test_aspect_fill_methods_cover_every_aspect():
    # the unguarded dispatch lookup depends on the mapping being total
    assert set(_ASPECT_FILL_METHODS) == set(CHARACTER_GENERATION_ASPECTS)
    for method_name in _ASPECT_FILL_METHODS.values():
        assert callable(getattr(CharacterCreatorMixin, method_name))


class TestAspectFillFunctions:
    """The per-aspect fill functions in isolation: result write and
    working-character chaining (prompt routing is covered by the
    orchestrator tests)."""

    @pytest.mark.asyncio
    async def test_fill_name_chains_to_working_character(self, creator):
        async with MockClientContext():
            client_responses.get().append(name_response("Elena"))
            result = CharacterGenerationResult()
            working = Character(name="the tall woman")
            await creator._fill_aspect_name(
                CharacterGenerationRequest(
                    aspects=["name"],
                    name="the tall woman",
                    content="A healer arrives.",
                ),
                result,
                working,
            )
        assert result.name == "Elena"
        assert working.name == "Elena"

    @pytest.mark.asyncio
    async def test_fill_description_chains_to_working_character(self, creator):
        async with MockClientContext():
            client_responses.get().append(description_response("Elena", "is a healer."))
            result = CharacterGenerationResult()
            working = Character(name="Elena")
            await creator._fill_aspect_description(
                CharacterGenerationRequest(
                    aspects=["description"], name="Elena", content="A healer."
                ),
                result,
                working,
            )
        assert result.description == "Elena is a healer."
        assert working.description == "Elena is a healer."

    @pytest.mark.asyncio
    async def test_fill_attributes_chains_to_working_character(self, creator):
        async with MockClientContext():
            client_responses.get().append(sheet_response("Elena", {"Age": "30"}))
            result = CharacterGenerationResult()
            working = Character(name="Elena")
            await creator._fill_aspect_attributes(
                CharacterGenerationRequest(
                    aspects=["attributes"], name="Elena", content="A healer."
                ),
                result,
                working,
            )
        assert result.attributes == {"Name": "Elena", "Age": "30"}
        assert working.base_attributes == result.attributes

    @pytest.mark.asyncio
    async def test_fill_attributes_then_description_renders_sheet(self, creator):
        # the chaining is what lets later aspect prompts see earlier results
        async with MockClientContext():
            client_responses.get().append(sheet_response("Elena", {"Age": "30"}))
            client_responses.get().append(description_response("Elena", "is a healer."))
            result = CharacterGenerationResult()
            working = Character(name="Elena")
            request = CharacterGenerationRequest(
                aspects=["attributes", "description"], name="Elena", content="A healer."
            )
            await creator._fill_aspect_attributes(request, result, working)
            await creator._fill_aspect_description(request, result, working)
        description_prompt = str(creator.client.prompt_history[-1]["prompt"])
        assert "Age: 30" in description_prompt

    @pytest.mark.asyncio
    async def test_fill_dialogue_instructions_does_not_chain(self, creator):
        async with MockClientContext():
            client_responses.get().append("Soft.")
            result = CharacterGenerationResult()
            working = Character(name="Elena")
            await creator._fill_aspect_dialogue_instructions(
                CharacterGenerationRequest(
                    aspects=["dialogue_instructions"], name="Elena", content="A healer."
                ),
                result,
                working,
            )
        assert result.dialogue_instructions == "Soft."
        assert working.dialogue_instructions is None

    @pytest.mark.asyncio
    async def test_fill_example_dialogue_writes_result_only(self, creator):
        async with MockClientContext():
            client_responses.get().append(
                example_dialogue_response('"Oh dear!" she gasps')
            )
            result = CharacterGenerationResult()
            working = Character(name="Elena")
            await creator._fill_aspect_example_dialogue(
                CharacterGenerationRequest(
                    aspects=["example_dialogue"], name="Elena", content="A healer."
                ),
                result,
                working,
            )
        assert result.example_dialogue == ['Elena: "Oh dear!" she gasps']
        assert working.example_dialogue == []


@pytest.mark.asyncio
async def test_orchestrator_on_aspect_start_fires_per_fill(creator):
    # the progress callback fires once per individual fill, in aspect order
    async with MockClientContext():
        client_responses.get().append(sheet_response("Elena", {"Age": "30"}))
        client_responses.get().append(description_response("Elena", "is a healer."))
        calls = []
        await creator.generate_character_aspects(
            CharacterGenerationRequest(
                aspects=["attributes", "description"],
                name="Elena",
                content="A healer.",
                unified=False,
                on_aspect_start=calls.append,
            )
        )

    assert calls == ["attributes", "description"]
