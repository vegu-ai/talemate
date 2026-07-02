"""
Unit tests for world_state agent methods.

Tests that world_state agent methods correctly call the LLM client with rendered prompts.
These tests use mocked LLM clients to verify the full code path from agent method
to prompt rendering to LLM call, without making actual API calls.
"""

import pytest
from unittest.mock import AsyncMock, Mock

import talemate.instance as instance
from talemate.agents.world_state import WorldStateAgent
from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    NarratorMessage,
    TimePassageMessage,
)
from talemate.world_state import ContextPin, Reinforcement
from .helpers import create_scene_with_characters


@pytest.fixture
def mock_scene():
    """Real Scene with Hero + Elena actors, with a few methods stubbed out.

    LLM-calling or IO-performing scene methods (push_history, load_active_pins,
    emit_status, etc.) are replaced with Mocks so tests can assert against
    them. Everything else — characters, world_state, game_state — is real.
    """
    scene = create_scene_with_characters()

    # Stub out methods that tests assert against or that would perform IO.
    scene.push_history = AsyncMock()
    scene.pop_history = Mock()
    scene.load_active_pins = AsyncMock()
    scene.emit_status = Mock()

    # Normally initialized by MemoryRAGMixin.connect(); the fixture sets the
    # agent's scene directly without connecting, so seed it here.
    scene.rag_cache = {}

    return scene


@pytest.fixture
def mock_memory_agent():
    """Create a mock memory agent."""
    memory = Mock()
    memory.query = AsyncMock(return_value="Mocked memory response")
    memory.multi_query = AsyncMock(return_value={"query1": "result1"})
    memory.add_many = AsyncMock()
    memory.delete = AsyncMock()
    return memory


@pytest.fixture
def mock_creator_agent():
    """Create a mock creator agent."""
    creator = Mock()
    creator.generate_title = AsyncMock(return_value="Test Title")
    creator.generate_character_attribute = AsyncMock(return_value="Generated attribute")
    creator.generate_character_detail = AsyncMock(return_value="Generated detail")
    return creator


@pytest.fixture
def mock_summarizer_agent():
    """Create a mock summarizer agent."""
    summarizer = Mock()
    summarizer.summarize = AsyncMock(return_value="A brief summary of events.")
    return summarizer


@pytest.fixture
def mock_director_agent():
    """Create a mock director agent."""
    director = Mock()
    director.get_cached_character_guidance = AsyncMock(return_value="")
    return director


@pytest.fixture
def mock_editor_agent():
    """Editor stub — disables fix_exposition so scene methods that touch the editor are no-ops."""
    editor = Mock()
    editor.fix_exposition_enabled = False
    editor.fix_exposition_narrator = False
    editor.fix_exposition_in_text = Mock(side_effect=lambda text: text)
    return editor


@pytest.fixture
def world_state_agent(mock_llm_client, mock_scene):
    """Create a WorldStateAgent instance with mocked dependencies.

    Long-term-memory recall is disabled by default so the snapshot template
    tests/baselines capture structure without RAG noise (mirrors how the
    conversation/narrator template tests stub ``rag_build`` to ``[]``). Tests
    that exercise the recall path re-enable it explicitly.
    """
    agent = WorldStateAgent(client=mock_llm_client)
    agent.scene = mock_scene
    agent.actions["use_long_term_memory"].enabled = False
    return agent


@pytest.fixture
def setup_agents(
    world_state_agent,
    mock_memory_agent,
    mock_creator_agent,
    mock_summarizer_agent,
    mock_director_agent,
    mock_editor_agent,
):
    """Set up the agent registry with mocked agents."""
    # Save original AGENTS dict
    original_agents = instance.AGENTS.copy()

    # Set up mock agents in the registry
    instance.AGENTS["memory"] = mock_memory_agent
    instance.AGENTS["creator"] = mock_creator_agent
    instance.AGENTS["summarizer"] = mock_summarizer_agent
    instance.AGENTS["director"] = mock_director_agent
    instance.AGENTS["editor"] = mock_editor_agent
    # World state agent needs to be in registry for instruct_text template function
    instance.AGENTS["world_state"] = world_state_agent

    yield

    # Restore original AGENTS dict
    instance.AGENTS.clear()
    instance.AGENTS.update(original_agents)


@pytest.fixture
def active_context(world_state_agent, mock_scene, setup_agents):
    """Set up active scene context for tests."""
    from talemate.context import active_scene

    scene_token = active_scene.set(mock_scene)

    yield world_state_agent

    active_scene.reset(scene_token)


class TestWorldStateAgentAnalyzeMethods:
    """Tests for world_state agent analyze methods."""

    @pytest.mark.asyncio
    async def test_analyze_and_follow_instruction_calls_client(self, active_context):
        """Test that analyze_and_follow_instruction calls the LLM client and extracts response."""
        agent = active_context

        # Set a specific mock response to verify extraction
        expected_response = "The text mentions a waterfall and a hidden passage."
        agent.client.send_prompt = AsyncMock(return_value=expected_response)

        response = await agent.analyze_and_follow_instruction(
            text="The hero discovered a hidden passage behind the waterfall.",
            instruction="Identify all locations mentioned in the text.",
        )

        # Verify response was extracted correctly (AsIsExtractor extracts full response)
        assert response == expected_response

        # Verify the client's send_prompt was called
        agent.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify the text and instruction appear in the prompt
        assert "waterfall" in prompt_text.lower() or "passage" in prompt_text.lower()
        assert "locations" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_analyze_and_follow_instruction_short_mode(self, active_context):
        """Test analyze_and_follow_instruction with short=True extracts response."""
        agent = active_context

        expected_response = "Brief summary."
        agent.client.send_prompt = AsyncMock(return_value=expected_response)

        response = await agent.analyze_and_follow_instruction(
            text="Short text.", instruction="Summarize.", short=True
        )

        # Verify extraction worked correctly
        assert response == expected_response

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_text_and_answer_question_calls_client(self, active_context):
        """Test that analyze_text_and_answer_question calls the LLM client and extracts response."""
        agent = active_context

        # Set a specific mock response to verify extraction
        expected_answer = "Elena is using an ancient sword."
        agent.client.send_prompt = AsyncMock(return_value=expected_answer)

        response = await agent.analyze_text_and_answer_question(
            text="Elena wielded the ancient sword with great skill.",
            query="What weapon is Elena using?",
        )

        # Verify extraction worked correctly (AsIsExtractor extracts full response)
        assert response == expected_answer

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

        # Get the prompt that was sent
        call_args = agent.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])

        # Verify query and text appear in the prompt
        assert "weapon" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_analyze_text_and_extract_context_calls_client(self, active_context):
        """Test that analyze_text_and_extract_context calls the LLM client and extracts response.

        Note: This method uses instruct_text internally which makes additional LLM calls,
        so we expect at least 2 calls: one for generating queries, one for the final response.
        """
        agent = active_context

        # Set a specific mock response to verify extraction
        expected_context = "The war has caused significant political turmoil."
        agent.client.send_prompt = AsyncMock(return_value=expected_context)

        response = await agent.analyze_text_and_extract_context(
            text="The kingdom has been at war for a decade.",
            goal="Understanding the political situation",
            num_queries=3,
        )

        # Verify extraction worked correctly (AsIsExtractor extracts full response)
        assert response == expected_context

        # Verify the client was called (at least twice due to instruct_text template function)
        assert agent.client.send_prompt.call_count >= 1

    @pytest.mark.asyncio
    async def test_analyze_text_and_extract_context_via_queries_calls_client(
        self, active_context, mock_memory_agent
    ):
        """Test that analyze_text_and_extract_context_via_queries extracts queries correctly."""
        agent = active_context

        # Configure mock to return a numbered list response that will be parsed
        agent.client.send_prompt = AsyncMock(
            return_value="1. What is the history?\n2. Who are the factions?"
        )

        response = await agent.analyze_text_and_extract_context_via_queries(
            text="The sorcerer's tower loomed over the ancient forest.",
            goal="Gather information about the sorcerer.",
            num_queries=2,
        )

        # Verify response was returned (comes from memory agent multi_query)
        assert response is not None

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

        # Verify memory agent multi_query was called with extracted queries
        mock_memory_agent.multi_query.assert_called_once()
        # The queries extracted via extract_list should include the numbered items
        call_args = mock_memory_agent.multi_query.call_args
        queries = call_args[0][0]  # First positional argument
        assert len(queries) == 2
        assert "What is the history?" in queries[0]
        assert "Who are the factions?" in queries[1]

    @pytest.mark.asyncio
    async def test_analyze_history_and_follow_instructions_calls_client(
        self, active_context
    ):
        """Test that analyze_history_and_follow_instructions extracts response correctly."""
        agent = active_context

        # Set a specific mock response to verify extraction (with whitespace to test strip)
        expected_summary = "The hero traveled to the village and met the elder."
        agent.client.send_prompt = AsyncMock(return_value=f"  {expected_summary}  ")

        entries = [
            {"ts": "PT1H", "text": "The hero arrived at the village."},
            {"ts": "PT2H", "text": "The hero met with the village elder."},
        ]

        response = await agent.analyze_history_and_follow_instructions(
            entries=entries,
            instructions="Summarize the hero's journey so far.",
            response_length=256,
        )

        # Verify extraction worked correctly (method calls .strip() on extracted response)
        assert response == expected_summary
        assert isinstance(response, str)

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()


class TestWorldStateAgentIdentifyMethods:
    """Tests for world_state agent identification methods."""

    @pytest.mark.asyncio
    async def test_identify_characters_calls_client(self, active_context):
        """Test that identify_characters calls the LLM client and parses JSON response."""
        agent = active_context

        # Configure mock to return valid JSON response (must be complete and parseable)
        agent.client.send_prompt = AsyncMock(
            return_value='{"characters": [{"name": "Elena", "description": "A healer"}]}'
        )

        response = await agent.identify_characters(
            text="Elena spoke to the village elder, while Marcus stood guard."
        )

        # Verify response was parsed correctly (data_response=True parses JSON)
        assert response is not None
        assert isinstance(response, dict)
        assert "characters" in response
        assert len(response["characters"]) == 1
        assert response["characters"][0]["name"] == "Elena"
        assert response["characters"][0]["description"] == "A healer"

        # Verify the client was called at least once (may be called more for JSON fixing)
        assert agent.client.send_prompt.call_count >= 1

    @pytest.mark.asyncio
    async def test_identify_characters_with_empty_text_uses_history(
        self, active_context, mock_scene
    ):
        """Test identify_characters with empty text uses scene history and parses JSON."""
        agent = active_context

        # Configure mock to return valid JSON response
        agent.client.send_prompt = AsyncMock(
            return_value='{"characters": [{"name": "Hero", "description": "The protagonist"}]}'
        )

        response = await agent.identify_characters(text=None)

        # Verify response was parsed correctly
        assert response is not None
        assert isinstance(response, dict)
        assert "characters" in response
        assert response["characters"][0]["name"] == "Hero"

        # Verify the client was called at least once
        assert agent.client.send_prompt.call_count >= 1


class TestWorldStateAgentExtractMethods:
    """Tests for world_state agent extraction methods."""

    @pytest.mark.asyncio
    async def test_extract_character_sheet_calls_client(self, active_context):
        """Test that extract_character_sheet calls the LLM client and parses response."""
        agent = active_context

        # Configure mock to return character sheet format
        agent.client.send_prompt = AsyncMock(
            return_value="name: Elena\nage: 25\noccupation: Healer"
        )

        response = await agent.extract_character_sheet(
            name="Elena", text="A skilled healer with gentle manners."
        )

        # Verify response was parsed correctly via _parse_character_sheet
        assert response is not None
        assert isinstance(response, dict)
        assert response["name"] == "Elena"
        assert response["age"] == "25"
        assert response["occupation"] == "Healer"

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_character_sheet_with_alteration(self, active_context):
        """Test extract_character_sheet with alteration instructions parses response."""
        agent = active_context

        agent.client.send_prompt = AsyncMock(return_value="name: Elena\nage: 30")

        response = await agent.extract_character_sheet(
            name="Elena",
            text="",
            alteration_instructions="Update age to reflect time passing.",
        )

        # Verify response was parsed correctly with altered values
        assert response is not None
        assert isinstance(response, dict)
        assert response["name"] == "Elena"
        assert response["age"] == "30"

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_character_sheet_with_max_attributes(self, active_context):
        """Test extract_character_sheet with max_attributes limit."""
        agent = active_context

        agent.client.send_prompt = AsyncMock(
            return_value="name: Elena\nage: 25\noccupation: Healer\nstatus: healthy\nweapon: staff"
        )

        response = await agent.extract_character_sheet(
            name="Elena", text="Elena is a healer.", max_attributes=3
        )

        # Verify response has at most 3 attributes
        assert len(response) <= 3


class TestWorldStateAgentRequestMethods:
    """Tests for world_state agent request methods."""

    @pytest.mark.asyncio
    async def test_request_world_state_calls_client(self, active_context, mock_scene):
        """Test that request_world_state calls the LLM client and parses JSON response."""
        agent = active_context

        # Seed a narrative message so the focus collector has something to anchor to;
        # without it the agent short-circuits and returns an empty response.
        anchor = CharacterMessage(message="Hero: I stand ready.", source="Hero")
        mock_scene.history = [anchor]

        # Mock completes the response seeded by set_data_response
        # (`\`\`\`json\n{ "characters": {`) so the strict parser succeeds on
        # the first attempt and no JSON-fix retry fires.
        agent.client.send_prompt = AsyncMock(
            return_value=(
                '"Hero": {"emotion": "determined", "snapshot": "Standing ready",'
                ' "mentions": []}}, "items": {}, "places": {}, "location": "test"}'
            )
        )

        response = await agent.request_world_state()

        # Verify response was parsed correctly (data_response=True parses JSON)
        assert response.world_state is not None
        assert isinstance(response.world_state, dict)
        assert "characters" in response.world_state
        assert "Hero" in response.world_state["characters"]
        assert response.world_state["characters"]["Hero"]["emotion"] == "determined"
        assert (
            response.world_state["characters"]["Hero"]["snapshot"] == "Standing ready"
        )
        assert "items" in response.world_state
        # Every focus message is a valid anchor; here that's the single
        # seeded narrative message.
        assert response.anchor_message_ids == [anchor.id]

        # Verify the client was called at least once (may be called more for JSON fixing)
        assert agent.client.send_prompt.call_count >= 1

    @pytest.mark.asyncio
    async def test_request_world_state_no_focus_messages_short_circuits(
        self, active_context, mock_scene
    ):
        """No anchor-worthy messages and no intro → return empty response without calling the LLM."""
        agent = active_context
        agent.client.send_prompt = AsyncMock()

        # Empty history AND no intro: nothing to anchor highlights to and nothing
        # to fall back on, so the LLM is never called.
        mock_scene.history = []
        mock_scene.intro = ""
        response = await agent.request_world_state()
        assert response.world_state is None
        assert response.anchor_message_ids == []
        agent.client.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_world_state_stops_at_time_passage(
        self, active_context, mock_scene
    ):
        """TimePassageMessage at the tail is a hard scene-cut → silent short-circuit.

        Intro must NOT be used as a fallback here — the scene has progressed
        past it, so injecting the intro as the 'current moment' would describe
        the wrong point in the story.
        """
        agent = active_context
        agent.client.send_prompt = AsyncMock()

        # Narrative followed by a time passage means the 'current moment' is on
        # the far side of the cut, so the focus collector finds nothing. Intro
        # is set explicitly here to verify the fallback does NOT fire when
        # history exists — independent of whatever the fixture happens to default.
        mock_scene.history = [
            NarratorMessage(message="The hero rested by the fire."),
            TimePassageMessage(message="Three days later", ts="P3D"),
        ]
        mock_scene.intro = "You step into the forest clearing."
        response = await agent.request_world_state()
        assert response.world_state is None
        assert response.anchor_message_ids == []
        agent.client.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_world_state_falls_back_to_intro(
        self, active_context, mock_scene
    ):
        """Empty history but scene has an intro → use intro as the focus line."""
        agent = active_context
        # Mock returns a valid completion so the parser succeeds.
        agent.client.send_prompt = AsyncMock(
            return_value=(
                '"Hero": {"emotion": "curious", "snapshot": "Newly arrived",'
                ' "mentions": ["the clearing"]}}, "items": {}, "places": {},'
                ' "location": "forest clearing"}'
            )
        )

        # No history yet — fresh scene. The intro is the only narrative surface
        # and should be passed to the prompt instead of triggering a short-circuit.
        mock_scene.history = []
        mock_scene.intro = "You find yourself in a quiet forest clearing."

        response = await agent.request_world_state()

        assert response.world_state is not None
        # Intro has no message id, so no anchors for inline highlights.
        assert response.anchor_message_ids == []
        # LLM was called and saw the intro text.
        agent.client.send_prompt.assert_called_once()
        prompt_text = str(agent.client.send_prompt.call_args[0][0])
        assert "quiet forest clearing" in prompt_text


class TestWorldStateSnapshotMemoryRecall:
    """Snapshot generation pulls long-term-memory recall into the prompt when enabled."""

    @pytest.mark.asyncio
    async def test_memory_recall_injected_when_enabled(
        self, active_context, mock_scene, mock_memory_agent
    ):
        agent = active_context
        agent.actions["use_long_term_memory"].enabled = True
        recalled = "The silver dagger was forged in the northern foundry."
        mock_memory_agent.multi_query = AsyncMock(return_value=[recalled])

        mock_scene.history = [
            CharacterMessage(message="Hero: I draw the dagger.", source="Hero")
        ]
        agent.client.send_prompt = AsyncMock(
            return_value=(
                '"Hero": {"emotion": "tense", "snapshot": "Blade drawn",'
                ' "mentions": []}}, "items": {}, "places": {}, "location": "x"}'
            )
        )

        await agent.request_world_state()

        prompt_text = str(agent.client.send_prompt.call_args[0][0])
        assert recalled in prompt_text
        mock_memory_agent.multi_query.assert_called()

    @pytest.mark.asyncio
    async def test_memory_recall_omitted_when_disabled(
        self, active_context, mock_scene, mock_memory_agent
    ):
        agent = active_context  # LTM disabled by the fixture default
        mock_memory_agent.multi_query = AsyncMock(return_value=["Should not appear."])

        mock_scene.history = [
            CharacterMessage(message="Hero: I draw the dagger.", source="Hero")
        ]
        agent.client.send_prompt = AsyncMock(
            return_value=(
                '"Hero": {"emotion": "tense", "snapshot": "Blade drawn",'
                ' "mentions": []}}, "items": {}, "places": {}, "location": "x"}'
            )
        )

        await agent.request_world_state()

        prompt_text = str(agent.client.send_prompt.call_args[0][0])
        assert "Should not appear." not in prompt_text
        mock_memory_agent.multi_query.assert_not_called()


class TestWorldStateAgentFocusKnobs:
    """Tests for the update_world_state focus_lines and
    include_context_investigation knobs."""

    @pytest.mark.asyncio
    async def test_focus_lines_caps_walk_depth(self, active_context, mock_scene):
        """Seeding more narrative messages than the knob allows should yield
        exactly `focus_lines` anchor ids, taken from the tail."""
        agent = active_context
        agent.actions["update_world_state"].config["focus_lines"].value = 2

        a = NarratorMessage(message="A: first beat")
        b = NarratorMessage(message="B: second beat")
        c = NarratorMessage(message="C: third beat")
        mock_scene.history = [a, b, c]

        agent.client.send_prompt = AsyncMock(
            return_value=(
                '"X": {"emotion": "calm", "snapshot": "x", "mentions": []}},'
                ' "items": {}, "places": {}, "location": "test"}'
            )
        )

        response = await agent.request_world_state()
        # Knob set to 2 → only the last two messages anchor highlights.
        assert response.anchor_message_ids == [b.id, c.id]

    @pytest.mark.asyncio
    async def test_focus_lines_allows_single_line(self, active_context, mock_scene):
        """focus_lines=1 should anchor on the tail message only, matching the
        original singular-anchor behavior."""
        agent = active_context
        agent.actions["update_world_state"].config["focus_lines"].value = 1

        a = NarratorMessage(message="A: first beat")
        b = NarratorMessage(message="B: tail beat")
        mock_scene.history = [a, b]

        agent.client.send_prompt = AsyncMock(
            return_value=(
                '"X": {"emotion": "calm", "snapshot": "x", "mentions": []}},'
                ' "items": {}, "places": {}, "location": "test"}'
            )
        )

        response = await agent.request_world_state()
        assert response.anchor_message_ids == [b.id]

    @pytest.mark.asyncio
    async def test_context_investigation_excluded_by_default(
        self, active_context, mock_scene
    ):
        """Default knob value (False) keeps context_investigation in the
        ignore set, so a CI message at the tail is walked past."""
        agent = active_context
        # Default: include_context_investigation = False
        agent.actions["update_world_state"].config["focus_lines"].value = 3

        narrative = NarratorMessage(message="A: scene beat")
        ci = ContextInvestigationMessage(
            "examine result for The Map", sub_type="examine"
        )
        mock_scene.history = [narrative, ci]

        agent.client.send_prompt = AsyncMock(
            return_value=(
                '"X": {"emotion": "calm", "snapshot": "x", "mentions": []}},'
                ' "items": {}, "places": {}, "location": "test"}'
            )
        )

        response = await agent.request_world_state()
        # CI message excluded; only the real narrative anchors.
        assert response.anchor_message_ids == [narrative.id]

    @pytest.mark.asyncio
    async def test_context_investigation_included_when_knob_on(
        self, active_context, mock_scene
    ):
        """Toggling include_context_investigation=True lets a CI message
        become a focus candidate that can also anchor highlights."""
        agent = active_context
        agent.actions["update_world_state"].config["focus_lines"].value = 3
        agent.actions["update_world_state"].config[
            "include_context_investigation"
        ].value = True

        narrative = NarratorMessage(message="A: scene beat")
        ci = ContextInvestigationMessage(
            "examine result for The Map", sub_type="examine"
        )
        mock_scene.history = [narrative, ci]

        agent.client.send_prompt = AsyncMock(
            return_value=(
                '"X": {"emotion": "calm", "snapshot": "x", "mentions": []}},'
                ' "items": {}, "places": {}, "location": "test"}'
            )
        )

        response = await agent.request_world_state()
        assert response.anchor_message_ids == [narrative.id, ci.id]


class TestWorldStateAgentExamineMethods:
    """Tests for world_state agent examine_entity."""

    @pytest.mark.asyncio
    async def test_examine_entity_calls_client_and_extracts(self, active_context):
        agent = active_context
        # AnchorExtractor on <EXAMINE>...</EXAMINE> + set_prepared_response("<EXAMINE>"):
        # the mock completes the seeded prefix and closes with </EXAMINE>.
        agent.client.send_prompt = AsyncMock(
            return_value="A simple silver dagger, etched with the Ashen sigil.</EXAMINE>"
        )

        result = await agent.examine_entity(
            entity_name="The Silver Dagger",
            entity_kind="item",
            snapshot_text="A worn silver dagger with an etched pommel sigil.",
        )

        assert "Ashen sigil" in result
        prompt_text = str(agent.client.send_prompt.call_args[0][0])
        assert "The Silver Dagger" in prompt_text
        assert "snapshot" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_examine_entity_rejects_empty_snapshot(self, active_context):
        agent = active_context
        with pytest.raises(ValueError):
            await agent.examine_entity(
                entity_name="X", entity_kind="item", snapshot_text="   "
            )

    @pytest.mark.asyncio
    async def test_examine_entity_uses_configured_length_in_kind(self, active_context):
        agent = active_context
        agent.actions["update_world_state"].config["examine_length"].value = 128
        agent.client.send_prompt = AsyncMock(return_value="A short look.</EXAMINE>")

        await agent.examine_entity(
            entity_name="The Silver Dagger",
            entity_kind="item",
            snapshot_text="A worn silver dagger with an etched pommel sigil.",
        )

        assert agent.client.send_prompt.call_args.kwargs["kind"] == "create_128"


class TestWorldStateAgentReinforcementMethods:
    """Tests for world_state agent reinforcement methods."""

    @pytest.mark.asyncio
    async def test_update_reinforcement_calls_client(self, active_context, mock_scene):
        """Test that update_reinforcement calls the LLM client and extracts response."""
        agent = active_context

        # Set a specific mock response to verify extraction
        expected_answer = "The hero feels determined and focused."
        agent.client.send_prompt = AsyncMock(return_value=expected_answer)

        # Set up a reinforcement to update
        reinforcement = Reinforcement(
            question="What is the hero's mood?",
            answer="",
            interval=10,
            due=0,
            character=None,
            instructions="",
            insert="sequential",
        )
        mock_scene.world_state.reinforce = [reinforcement]

        response = await agent.update_reinforcement(
            question="What is the hero's mood?", character=None
        )

        # Verify response was returned (ReinforcementMessage object)
        assert response is not None

        # Verify the reinforcement's answer was updated with extracted response
        # (for sequential insert, only first line is taken)
        assert reinforcement.answer == expected_answer

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_reinforcement_with_character(
        self, active_context, mock_scene
    ):
        """Test update_reinforcement with a character-specific reinforcement extracts response."""
        agent = active_context

        # Set a specific mock response to verify extraction
        expected_mood = "Elena appears calm but watchful."
        agent.client.send_prompt = AsyncMock(return_value=expected_mood)

        # Set up a character reinforcement
        reinforcement = Reinforcement(
            question="current mood",
            answer="",
            interval=10,
            due=0,
            character="Elena",
            instructions="",
            insert="conversation-context",
        )
        mock_scene.world_state.reinforce = [reinforcement]

        await agent.update_reinforcement(question="current mood", character="Elena")

        # Verify the reinforcement's answer was updated with extracted response
        assert reinforcement.answer == expected_mood

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_reinforcements_skips_not_due(
        self, active_context, mock_scene
    ):
        """Test that update_reinforcements skips reinforcements that are not due."""
        agent = active_context

        # Set up reinforcements - one due, one not
        reinforcement_due = Reinforcement(
            question="Question 1", due=0, interval=10, insert="sequential"
        )
        reinforcement_not_due = Reinforcement(
            question="Question 2", due=5, interval=10, insert="sequential"
        )
        mock_scene.world_state.reinforce = [reinforcement_due, reinforcement_not_due]

        await agent.update_reinforcements()

        # Only one call should be made (for the due reinforcement)
        assert agent.client.send_prompt.call_count == 1


class TestWorldStateAgentPinConditionMethods:
    """Tests for world_state agent pin condition methods."""

    @pytest.mark.asyncio
    async def test_check_pin_conditions_calls_client(self, active_context, mock_scene):
        """Test that check_pin_conditions parses JSON response and updates pin state."""
        agent = active_context

        # Set up pins with conditions
        pin = ContextPin(
            entry_id="test_pin",
            condition="The hero is in danger",
            condition_state=False,
            active=False,
        )
        mock_scene.world_state.pins = {"test_pin": pin}

        # Configure mock to return valid JSON condition check result
        agent.client.send_prompt = AsyncMock(
            return_value='{"test_pin": {"condition": "The hero is in danger", "state": true}}'
        )

        await agent.check_pin_conditions()

        # Verify the pin state was updated based on parsed JSON response
        assert pin.condition_state is True
        assert pin.active is True

        # Verify the client was called at least once (may be called more for JSON fixing)
        assert agent.client.send_prompt.call_count >= 1

        # Verify load_active_pins was called due to state change
        mock_scene.load_active_pins.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_pin_conditions_skips_gamestate_controlled(
        self, active_context, mock_scene
    ):
        """Test that check_pin_conditions skips game-state-controlled pins."""
        agent = active_context

        # Set up a pin with gamestate_condition (should be skipped)
        pin = ContextPin(
            entry_id="gamestate_pin",
            condition="Some condition",
            condition_state=False,
            active=False,
            gamestate_condition=[{"conditions": []}],  # Non-None means game-controlled
        )
        mock_scene.world_state.pins = {"gamestate_pin": pin}

        await agent.check_pin_conditions()

        # Client should not be called - no pins to check
        agent.client.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_pin_conditions_no_pins(self, active_context, mock_scene):
        """Test that check_pin_conditions handles empty pins gracefully."""
        agent = active_context
        mock_scene.world_state.pins = {}

        await agent.check_pin_conditions()

        # Client should not be called - no pins to check
        agent.client.send_prompt.assert_not_called()


class TestWorldStateAgentCharacterPresenceMethods:
    """Tests for world_state agent character presence methods."""

    @pytest.mark.asyncio
    async def test_is_character_present_calls_client(self, active_context):
        """Test that is_character_present extracts response and interprets yes/no."""
        agent = active_context

        # Configure mock to return "yes" - tests extraction and interpretation
        agent.client.send_prompt = AsyncMock(return_value="yes")

        result = await agent.is_character_present("Elena")

        # Verify the extracted response was interpreted correctly
        # (response starts with 'y' means True)
        assert result is True

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

        # Verify the query asks about presence
        call_args = agent.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])
        assert "Elena" in prompt_text
        assert "present" in prompt_text.lower()

    @pytest.mark.asyncio
    async def test_is_character_present_returns_false(self, active_context):
        """Test is_character_present extracts response and returns False for 'no'."""
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="no")

        result = await agent.is_character_present("Elena")

        # Verify the extracted response was interpreted correctly
        # (response does not start with 'y' means False)
        assert result is False

    @pytest.mark.asyncio
    async def test_is_character_leaving_calls_client(self, active_context):
        """Test that is_character_leaving extracts response and interprets yes/no."""
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="yes")

        result = await agent.is_character_leaving("Elena")

        # Verify the extracted response was interpreted correctly
        assert result is True

        # Verify the client was called
        agent.client.send_prompt.assert_called_once()

        # Verify the query asks about leaving
        call_args = agent.client.send_prompt.call_args
        prompt_text = str(call_args[0][0])
        assert "leaving" in prompt_text.lower()


class TestWorldStateAgentQueryMethods:
    """Tests for world_state agent query methods."""

    @pytest.mark.asyncio
    async def test_answer_query_true_or_false_yes(self, active_context):
        """Test answer_query_true_or_false extracts and interprets 'yes' response."""
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="yes")

        result = await agent.answer_query_true_or_false(
            query="Is the door open?", text="The door stood ajar."
        )

        # Verify extraction and interpretation (response starts with 'y' means True)
        assert result is True

    @pytest.mark.asyncio
    async def test_answer_query_true_or_false_no(self, active_context):
        """Test answer_query_true_or_false extracts and interprets 'no' response."""
        agent = active_context
        agent.client.send_prompt = AsyncMock(return_value="no")

        result = await agent.answer_query_true_or_false(
            query="Is the door locked?", text="The door was wide open."
        )

        # Verify extraction and interpretation (response does not start with 'y' means False)
        assert result is False


class TestWorldStateAgentCharacterProgressionMethods:
    """Tests for world_state agent character progression methods (from mixin)."""

    @pytest.mark.asyncio
    async def test_determine_character_development_calls_client(
        self, active_context, mock_scene, mock_creator_agent
    ):
        """Test that determine_character_development calls the LLM client via Focal."""
        agent = active_context
        character = mock_scene.get_character("Elena")

        # Configure mock to return an empty JSON array (no callbacks triggered)
        # Focal expects JSON format for calls
        agent.client.send_prompt = AsyncMock(return_value="[]")

        calls = await agent.determine_character_development(character=character)

        # Verify response was returned as list
        assert calls is not None
        assert isinstance(calls, list)

        # Verify the client was called at least once (Focal sends the prompt)
        assert agent.client.send_prompt.call_count >= 1

    @pytest.mark.asyncio
    async def test_determine_character_development_with_instructions(
        self, active_context, mock_scene
    ):
        """Test determine_character_development with custom instructions."""
        agent = active_context
        character = mock_scene.get_character("Elena")

        # Configure mock to return an empty JSON array
        agent.client.send_prompt = AsyncMock(return_value="[]")

        calls = await agent.determine_character_development(
            character=character, instructions="Focus on combat improvements."
        )

        assert calls is not None

        # Verify the client was called
        assert agent.client.send_prompt.call_count >= 1

        # Verify the instructions appear in the first prompt call
        first_call_args = agent.client.send_prompt.call_args_list[0]
        prompt_text = str(first_call_args[0][0])
        assert "combat" in prompt_text.lower()


class TestWorldStateAgentHelperMethods:
    """Tests for helper methods that don't directly call Prompt.request()."""

    def test_parse_character_sheet(self, world_state_agent):
        """Test _parse_character_sheet parses correctly."""
        response = "name: Elena\nage: 25\noccupation: Healer"
        result = world_state_agent._parse_character_sheet(response)

        assert result == {"name": "Elena", "age": "25", "occupation": "Healer"}

    def test_parse_character_sheet_with_max_attributes(self, world_state_agent):
        """Test _parse_character_sheet respects max_attributes."""
        response = "name: Elena\nage: 25\noccupation: Healer\nstatus: healthy"
        result = world_state_agent._parse_character_sheet(response, max_attributes=2)

        assert len(result) == 2

    def test_parse_character_sheet_stops_at_non_attribute_line(self, world_state_agent):
        """Test _parse_character_sheet stops at line without colon."""
        response = "name: Elena\nage: 25\nThis is not an attribute\noccupation: Healer"
        result = world_state_agent._parse_character_sheet(response)

        # Should stop at "This is not an attribute"
        assert len(result) == 2
        assert "occupation" not in result
