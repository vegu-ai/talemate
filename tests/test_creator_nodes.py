"""Unit tests for talemate.agents.creator.nodes (GenerateCharacter).

The generation pipeline itself is covered in tests/test_creator_character.py -
these tests pin the node's own contract: how its behavior sockets resolve
against the matching properties, what it hands to the creator agent, and what
it puts on its outputs.
"""

from __future__ import annotations

import pytest

from conftest import MockScene, bootstrap_scene
from _node_test_helpers import (
    build_graph,
    execute_graph,
    make_constant,
    run_node,
)

from talemate.agents.creator.character import (
    CharacterGenerationRequest,
    CharacterGenerationResult,
)
from talemate.agents.creator.nodes import GenerateCharacter
from talemate.game.engine.nodes.registry import import_talemate_node_definitions
from talemate.instance import get_agent
from talemate.world_state.templates.content import GenerationOptions, WritingStyle


@pytest.fixture(scope="session", autouse=True)
def _import_node_definitions():
    import_talemate_node_definitions()


@pytest.fixture
def scene():
    s = MockScene()
    bootstrap_scene(s)
    return s


@pytest.fixture
def creator(scene):
    return get_agent("creator")


@pytest.fixture
def captured_request(creator, monkeypatch):
    """Capture the request the node builds, returning a canned result."""
    captured = {}

    async def _generate(request: CharacterGenerationRequest):
        captured["request"] = request
        return captured.get("result") or CharacterGenerationResult()

    monkeypatch.setattr(creator, "generate_character_aspects", _generate)
    return captured


class TestGenerateCharacterAspectSelection:
    @pytest.mark.asyncio
    async def test_unconnected_sockets_fall_back_to_properties(
        self, scene, captured_request
    ):
        """With nothing connected the node's own properties decide the
        aspects - description, attributes and dialogue instructions on, name
        and example dialogue off."""
        node = GenerateCharacter()
        await run_node(node, scene=scene, inputs={"character_name": "Elena"})

        assert captured_request["request"].aspects == [
            "description",
            "attributes",
            "dialogue_instructions",
        ]

    @pytest.mark.asyncio
    async def test_connected_false_overrides_true_property(
        self, scene, captured_request
    ):
        """A connected socket wins over the property it shadows: the node
        ships with generate_description=True, and a wired False must switch
        the aspect off."""
        node = GenerateCharacter()
        node.set_property("generate_attributes", False)
        node.set_property("generate_dialogue_instructions", False)
        const = make_constant(
            state="marker", generate_description=False, character_name="Elena"
        )

        graph = build_graph(const, node)
        graph.connect(const.get_output_socket("state"), node.get_input_socket("state"))
        graph.connect(
            const.get_output_socket("generate_description"),
            node.get_input_socket("generate_description"),
        )
        graph.connect(
            const.get_output_socket("character_name"),
            node.get_input_socket("character_name"),
        )

        with pytest.raises(Exception) as excinfo:
            await execute_graph(scene, graph)

        # every aspect is now off, which the node reports rather than
        # silently issuing a request for nothing
        assert "No aspects selected for generation" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_connected_true_overrides_false_property(
        self, scene, captured_request
    ):
        """The mirror case - generate_example_dialogue defaults to False and
        a wired True must switch it on."""
        node = GenerateCharacter()
        const = make_constant(
            state="marker", generate_example_dialogue=True, character_name="Elena"
        )

        graph = build_graph(const, node)
        graph.connect(const.get_output_socket("state"), node.get_input_socket("state"))
        graph.connect(
            const.get_output_socket("generate_example_dialogue"),
            node.get_input_socket("generate_example_dialogue"),
        )
        graph.connect(
            const.get_output_socket("character_name"),
            node.get_input_socket("character_name"),
        )

        await execute_graph(scene, graph)

        assert "example_dialogue" in captured_request["request"].aspects

    @pytest.mark.asyncio
    async def test_example_dialogue_without_a_name_errors(
        self, scene, captured_request
    ):
        node = GenerateCharacter()
        with pytest.raises(Exception) as excinfo:
            await run_node(
                node,
                scene=scene,
                inputs={"generate_example_dialogue": True},
            )

        assert "Example dialogue generation needs a name" in str(excinfo.value)
        assert "request" not in captured_request


class TestGenerateCharacterAgentSettings:
    @pytest.mark.asyncio
    async def test_consolidation_is_left_to_the_agent_settings(
        self, scene, captured_request
    ):
        """The node no longer forces consolidated generation - it leaves
        unified/consolidate/fill_misses unset so the creator agent's
        "Fast Character Generation" and "Consolidate" settings decide."""
        node = GenerateCharacter()
        await run_node(node, scene=scene, inputs={"character_name": "Elena"})

        request = captured_request["request"]
        assert request.unified is None
        assert request.consolidate is None
        assert request.fill_misses is None

    @pytest.mark.asyncio
    async def test_generation_options_reach_the_request(self, scene, captured_request):
        generation_options = GenerationOptions(
            writing_style=WritingStyle(
                name="Terse", instructions="Write in terse prose."
            ),
            spice_level=0.5,
        )
        node = GenerateCharacter()
        await run_node(
            node,
            scene=scene,
            inputs={
                "character_name": "Elena",
                "generation_options": generation_options,
            },
        )

        assert captured_request["request"].generation_options is generation_options

    @pytest.mark.asyncio
    async def test_generation_options_default_to_none(self, scene, captured_request):
        node = GenerateCharacter()
        await run_node(node, scene=scene, inputs={"character_name": "Elena"})

        assert captured_request["request"].generation_options is None


class TestGenerateCharacterOutputs:
    @pytest.mark.asyncio
    async def test_supplied_description_passes_through_when_not_generated(
        self, scene, captured_request
    ):
        """Regression: with generate_description off the node used to emit an
        empty string, which downstream state writes then stored over the
        supplied description."""
        captured_request["result"] = CharacterGenerationResult(
            attributes={"Age": "early 30s"}
        )
        node = GenerateCharacter()
        outputs = await run_node(
            node,
            scene=scene,
            inputs={
                "character_name": "Elena",
                "description": "A healer from the northern reaches.",
                "generate_description": False,
                "generate_dialogue_instructions": False,
            },
        )

        assert outputs["description"] == "A healer from the northern reaches."

    @pytest.mark.asyncio
    async def test_generated_description_wins_over_the_supplied_one(
        self, scene, captured_request
    ):
        captured_request["result"] = CharacterGenerationResult(
            description="Elena is a skilled healer."
        )
        node = GenerateCharacter()
        outputs = await run_node(
            node,
            scene=scene,
            inputs={
                "character_name": "Elena",
                "description": "A healer from the northern reaches.",
            },
        )

        assert outputs["description"] == "Elena is a skilled healer."

    @pytest.mark.asyncio
    async def test_supplied_name_passes_through_when_not_generated(
        self, scene, captured_request
    ):
        node = GenerateCharacter()
        outputs = await run_node(node, scene=scene, inputs={"character_name": "Elena"})

        assert outputs["character_name"] == "Elena"

    @pytest.mark.asyncio
    async def test_ungenerated_aspects_emit_empty_values(self, scene, captured_request):
        """Aspects with no input to fall back on stay empty rather than
        None, so downstream sockets keep their declared types."""
        node = GenerateCharacter()
        outputs = await run_node(node, scene=scene, inputs={"character_name": "Elena"})

        assert outputs["description"] == ""
        assert outputs["attributes"] == {}
        assert outputs["dialogue_instructions"] == ""
        assert outputs["example_dialogue"] == []
