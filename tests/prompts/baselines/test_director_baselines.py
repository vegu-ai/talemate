"""
Baseline snapshot tests for director agent prompt templates.

Captures the rendered prompt text passed to client.send_prompt() and compares
against stored baseline files. Run with --update-baselines to create/update.
"""

from pathlib import Path

import pytest
from unittest.mock import Mock, AsyncMock, patch

import talemate.emit.async_signals
import talemate.instance as instance
from talemate.agents.base import DynamicInstruction

from talemate.agents.director.chat.schema import DirectorChatMessage
from talemate.agents.director.plan.schema import Beat
from talemate.agents.director.plan.expand import ChunkArcInfo

TEST_TEMPLATES_DIR = (
    Path(__file__).parent.parent.parent / "data" / "instruction_templates"
)

from ..conftest import mock_llm_client  # noqa: F401
from ..test_director_templates import (  # noqa: F401
    mock_scene,
    mock_summarizer_agent,
    mock_narrator_agent,
    mock_conversation_agent,
    mock_world_state_agent,
    mock_creator_agent,
    mock_memory_agent,
    mock_tts_agent,
    mock_editor_agent,
    director_agent,
    setup_agents,
    active_context,
)
from ..helpers import add_character_knowledge
from .conftest import capture_prompt

AGENT = "director"


async def _inject_dynamic_instruction(emission):
    """Signal handler that injects a test dynamic instruction."""
    emission.dynamic_instructions.append(
        DynamicInstruction(
            title="Deep Analysis Context",
            content="Test deep analysis context content.",
        )
    )


class TestDirectorBaselines:
    """Baseline tests for director agent methods."""

    @pytest.mark.asyncio
    async def test_guide_actor_off_of_scene_analysis(
        self, active_context, baseline_checker
    ):
        director = active_context
        character = director.scene.get_character("Elena")
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><GUIDANCE>Guidance text.</GUIDANCE>"
        )
        await director.guide_actor_off_of_scene_analysis(
            analysis="The scene is tense and dramatic.",
            character=character,
            response_length=256,
        )
        baseline_checker(
            capture_prompt(director), AGENT, "guide_actor_off_of_scene_analysis"
        )

    @pytest.mark.asyncio
    async def test_guide_narrator_off_of_scene_analysis(
        self, active_context, baseline_checker
    ):
        director = active_context
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><GUIDANCE>Guidance text.</GUIDANCE>"
        )
        await director.guide_narrator_off_of_scene_analysis(
            analysis="The scene needs more description.",
            response_length=256,
        )
        baseline_checker(
            capture_prompt(director), AGENT, "guide_narrator_off_of_scene_analysis"
        )

    @pytest.mark.asyncio
    async def test_generate_choices(self, active_context, baseline_checker):
        director = active_context
        director.client.send_prompt = AsyncMock(
            return_value='Analysis.\nACTIONS:\n- "Go to the forest"'
        )
        await director.generate_choices(
            instructions="Generate choices for the player",
        )
        baseline_checker(capture_prompt(director), AGENT, "generate_choices")

    @pytest.mark.asyncio
    async def test_generate_choices__with_character(
        self, active_context, baseline_checker
    ):
        director = active_context
        character = director.scene.get_character("Elena")
        director.client.send_prompt = AsyncMock(
            return_value='Analysis.\nACTIONS:\n- "Ask about the herbs"'
        )
        await director.generate_choices(
            character=character,
            instructions="Generate choices for Elena",
        )
        baseline_checker(
            capture_prompt(director), AGENT, "generate_choices__with_character"
        )

    @pytest.mark.asyncio
    async def test_chat_send(self, active_context, baseline_checker):
        director = active_context
        chat = director.chat_create()
        chat_id = chat.id
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><MESSAGE>Response message.</MESSAGE>"
        )
        with (
            patch(
                "talemate.agents.director.action_core.utils.get_available_actions"
            ) as mock_actions,
            patch(
                "talemate.agents.director.action_core.utils.get_meta_groups"
            ) as mock_meta,
            patch.object(director, "_chat_has_enough_for_title", return_value=False),
        ):
            mock_actions.return_value = []
            mock_meta.return_value = []
            await director.chat_send(
                chat_id=chat_id,
                message="What should happen next in the scene?",
            )
        baseline_checker(capture_prompt(director), AGENT, "chat_send")

    @pytest.mark.asyncio
    async def test_direction_execute_turn(self, active_context, baseline_checker):
        director = active_context
        director.actions["scene_direction"].enabled = True
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><DECISION>Decision text.</DECISION>"
        )
        with (
            patch(
                "talemate.agents.director.action_core.utils.get_available_actions"
            ) as mock_actions,
            patch(
                "talemate.agents.director.action_core.utils.get_meta_groups"
            ) as mock_meta,
        ):
            mock_actions.return_value = []
            mock_meta.return_value = []
            await director.direction_execute_turn(always_on=True)
        baseline_checker(capture_prompt(director), AGENT, "direction_execute_turn")

    @pytest.mark.asyncio
    async def test_guide_actor_off_of_scene_analysis__with_character_knowledge(
        self, active_context, baseline_checker
    ):
        director = active_context
        add_character_knowledge(director.scene)
        # The guidance freshness key reads the audience index revision.
        instance.get_agent("memory")._audience_state = Mock(
            return_value=Mock(revision=0)
        )
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><GUIDANCE>Guidance text.</GUIDANCE>"
        )
        await director.guide_actor_off_of_scene_analysis(
            analysis="The scene is tense and dramatic.",
            character=director.scene.get_character("Elena"),
            response_length=256,
        )
        baseline_checker(
            capture_prompt(director),
            AGENT,
            "guide_actor_off_of_scene_analysis__with_character_knowledge",
        )

    @pytest.mark.asyncio
    async def test_chat_send__with_character_knowledge(
        self, active_context, baseline_checker
    ):
        director = active_context
        add_character_knowledge(director.scene)
        chat = director.chat_create()
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><MESSAGE>Response message.</MESSAGE>"
        )
        with (
            patch(
                "talemate.agents.director.action_core.utils.get_available_actions"
            ) as mock_actions,
            patch(
                "talemate.agents.director.action_core.utils.get_meta_groups"
            ) as mock_meta,
            patch.object(director, "_chat_has_enough_for_title", return_value=False),
        ):
            mock_actions.return_value = []
            mock_meta.return_value = []
            await director.chat_send(
                chat_id=chat.id,
                message="What should happen next in the scene?",
            )
        baseline_checker(
            capture_prompt(director), AGENT, "chat_send__with_character_knowledge"
        )

    @pytest.mark.asyncio
    async def test_direction_execute_turn__with_character_knowledge(
        self, active_context, baseline_checker
    ):
        director = active_context
        add_character_knowledge(director.scene)
        director.actions["scene_direction"].enabled = True
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><DECISION>Decision text.</DECISION>"
        )
        with (
            patch(
                "talemate.agents.director.action_core.utils.get_available_actions"
            ) as mock_actions,
            patch(
                "talemate.agents.director.action_core.utils.get_meta_groups"
            ) as mock_meta,
        ):
            mock_actions.return_value = []
            mock_meta.return_value = []
            await director.direction_execute_turn(always_on=True)
        baseline_checker(
            capture_prompt(director),
            AGENT,
            "direction_execute_turn__with_character_knowledge",
        )

    @pytest.mark.asyncio
    async def test_direction_execute_turn__with_instruction_template(
        self, active_context, baseline_checker
    ):
        """Verify instruction_template addon renders alongside raw instructions text."""
        director = active_context
        director.actions["scene_direction"].enabled = True

        from talemate.scene.schema import ScenePhase, SceneType

        director.scene.template_dir = str(TEST_TEMPLATES_DIR)
        director.scene.intent_state.instructions = "Keep the pacing brisk."
        director.scene.intent_state.instruction_template = (
            "test-instruction-template.jinja2"
        )
        # Install a real SceneType and point ``phase`` at it so
        # ``SceneIntent.current_scene_type`` resolves via the real property.
        director.scene.intent_state.scene_types = {
            "exploration": SceneType(
                id="exploration",
                name="Exploration",
                description="An exploration scene.",
                instructions="Focus on discovery.",
                instruction_template="test-instruction-template.jinja2",
            )
        }
        director.scene.intent_state.phase = ScenePhase(scene_type="exploration")

        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><DECISION>Decision text.</DECISION>"
        )
        with (
            patch(
                "talemate.agents.director.action_core.utils.get_available_actions"
            ) as mock_actions,
            patch(
                "talemate.agents.director.action_core.utils.get_meta_groups"
            ) as mock_meta,
        ):
            mock_actions.return_value = []
            mock_meta.return_value = []
            await director.direction_execute_turn(always_on=True)
        baseline_checker(
            capture_prompt(director),
            AGENT,
            "direction_execute_turn__with_instruction_template",
        )

    @pytest.mark.asyncio
    async def test_guide_actor_off_of_scene_analysis__with_dynamic_instructions(
        self, active_context, baseline_checker
    ):
        """Verify dynamic instructions appear in volatile context, not static context."""
        director = active_context
        character = director.scene.get_character("Elena")
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><GUIDANCE>Guidance text.</GUIDANCE>"
        )
        signal = talemate.emit.async_signals.get(
            "agent.director.guide.inject_instructions"
        )
        signal.connect(_inject_dynamic_instruction)
        try:
            await director.guide_actor_off_of_scene_analysis(
                analysis="The scene is tense and dramatic.",
                character=character,
                response_length=256,
            )
            baseline_checker(
                capture_prompt(director),
                AGENT,
                "guide_actor_off_of_scene_analysis__with_dynamic_instructions",
            )
        finally:
            signal.disconnect(_inject_dynamic_instruction)

    @pytest.mark.asyncio
    async def test_guide_narrator_off_of_scene_analysis__with_dynamic_instructions(
        self, active_context, baseline_checker
    ):
        """Verify dynamic instructions appear in volatile context, not static context."""
        director = active_context
        director.client.send_prompt = AsyncMock(
            return_value="<ANALYSIS>Analysis.</ANALYSIS><GUIDANCE>Guidance text.</GUIDANCE>"
        )
        signal = talemate.emit.async_signals.get(
            "agent.director.guide.inject_instructions"
        )
        signal.connect(_inject_dynamic_instruction)
        try:
            await director.guide_narrator_off_of_scene_analysis(
                analysis="The scene needs more description.",
                response_length=256,
            )
            baseline_checker(
                capture_prompt(director),
                AGENT,
                "guide_narrator_off_of_scene_analysis__with_dynamic_instructions",
            )
        finally:
            signal.disconnect(_inject_dynamic_instruction)

    @pytest.mark.asyncio
    async def test_auto_direct_set_scene_intent(self, active_context, baseline_checker):
        director = active_context
        director.scene.intent_state.scene_types = {
            "exploration": Mock(id="exploration", name="Exploration"),
            "combat": Mock(id="combat", name="Combat"),
        }
        director.client.send_prompt = AsyncMock(
            return_value='{"function": "do_nothing"}'
        )
        await director.auto_direct_set_scene_intent(require=False)
        baseline_checker(
            capture_prompt(director), AGENT, "auto_direct_set_scene_intent"
        )

    @pytest.mark.asyncio
    async def test_chat_generate_title(self, active_context, baseline_checker):
        director = active_context
        chat = director.chat_create()
        chat_id = chat.id
        # Populate the chat with a user message and director response
        await director.chat_append_message(
            chat_id,
            DirectorChatMessage(
                source="user", message="What should happen next in the scene?"
            ),
        )
        await director.chat_append_message(
            chat_id,
            DirectorChatMessage(
                source="director", message="Let me analyze the current situation."
            ),
        )
        director.client.send_prompt = AsyncMock(
            return_value="<TITLE>Planning next scene steps</TITLE>"
        )
        await director.chat_generate_title(chat_id)
        baseline_checker(capture_prompt(director), AGENT, "chat_generate_title")

    @pytest.mark.asyncio
    async def test_detect_characters_from_texts(self, active_context, baseline_checker):
        director = active_context
        texts = [
            "Alice said: 'Hello there!'",
            "Bob replied: 'Nice to meet you.'",
        ]
        director.client.send_prompt = AsyncMock(
            return_value='{"function": "add_detected_character", "character_name": "Alice"}'
        )
        with patch(
            "talemate.agents.director.character_management.ClientContext"
        ) as mock_ctx:
            mock_ctx.return_value.__enter__ = Mock()
            mock_ctx.return_value.__exit__ = Mock()
            await director.detect_characters_from_texts(texts=texts)
        baseline_checker(
            capture_prompt(director), AGENT, "detect_characters_from_texts"
        )


def _make_test_beats() -> list[Beat]:
    """Create a small set of beats for testing expand templates."""
    return [
        Beat(
            description="The protagonist discovers the door is locked from the inside.",
            order=1,
            tension=0.3,
            pacing="slow",
            type="narration",
            characters=["Elena"],
        ),
        Beat(
            description="Elena confronts Hero about what happened last night, demanding answers.",
            order=2,
            tension=0.5,
            pacing="moderate",
            type="dialogue",
            characters=["Elena"],
        ),
        Beat(
            description="A sudden noise from the basement forces both characters to investigate together.",
            order=3,
            tension=0.7,
            pacing="fast",
            type="action",
            characters=["Hero", "Elena"],
        ),
    ]


class TestPlanExpandBaselines:
    """Baseline tests for plan expand templates (arc-expand, arc-expand-critique)."""

    @pytest.mark.asyncio
    async def test_arc_expand(self, active_context, baseline_checker):
        """Test the arc-expand template renders correctly with beats and arc info."""
        from talemate.prompts import Prompt
        from talemate.agents.base import ActiveAgent

        director = active_context
        from talemate.instance import AGENTS

        narrator = AGENTS.get("narrator")
        narrator.agent_type = "narrator"
        narrator.client = director.client
        narrator.extra_instructions = ""
        narrator.content_use_writing_style = False
        narrator.action_response_length = Mock(return_value=4096)

        beats = _make_test_beats()
        arc_info = ChunkArcInfo(
            position="opening",
            chunk_index=0,
            total_chunks=2,
            tension_range=(0.3, 0.7),
            has_peak=False,
        )

        director.client.send_prompt = AsyncMock(
            return_value='<BLOCKS>\n[{"type": "narrator", "content": "Test narration."}]\n</BLOCKS>'
        )

        with ActiveAgent(narrator, lambda: None):
            await Prompt.request(
                "narrator.arc-expand",
                narrator.client,
                "narrate_4096",
                vars={
                    "scene": director.scene,
                    "max_tokens": 8192,
                    "beats": beats,
                    "following_beats": [],
                    "preceding_text": "",
                    "director_notes": "Focus on building tension.",
                    "extra_instructions": "",
                    "response_length": 4096,
                    "arc_info": arc_info,
                },
            )

        baseline_checker(capture_prompt(director), AGENT, "arc_expand")

    @pytest.mark.asyncio
    async def test_arc_expand__with_preceding_text(
        self, active_context, baseline_checker
    ):
        """Test arc-expand with preceding text context."""
        from talemate.prompts import Prompt
        from talemate.agents.base import ActiveAgent

        director = active_context
        from talemate.instance import AGENTS

        narrator = AGENTS.get("narrator")
        narrator.agent_type = "narrator"
        narrator.client = director.client
        narrator.extra_instructions = ""
        narrator.content_use_writing_style = False
        narrator.action_response_length = Mock(return_value=4096)

        beats = _make_test_beats()[1:]  # beats 2-3
        arc_info = ChunkArcInfo(
            position="climax",
            chunk_index=1,
            total_chunks=2,
            tension_range=(0.5, 0.7),
            has_peak=True,
        )

        director.client.send_prompt = AsyncMock(
            return_value='<BLOCKS>\n[{"type": "narrator", "content": "More narration."}]\n</BLOCKS>'
        )

        with ActiveAgent(narrator, lambda: None):
            await Prompt.request(
                "narrator.arc-expand",
                narrator.client,
                "narrate_4096",
                vars={
                    "scene": director.scene,
                    "max_tokens": 8192,
                    "beats": beats,
                    "following_beats": [],
                    "preceding_text": "The door creaked open, revealing an empty room. Elena stepped inside cautiously.",
                    "director_notes": "",
                    "extra_instructions": "",
                    "response_length": 4096,
                    "arc_info": arc_info,
                },
            )

        baseline_checker(
            capture_prompt(director), AGENT, "arc_expand__with_preceding_text"
        )

    @pytest.mark.asyncio
    async def test_arc_expand_critique(self, active_context, baseline_checker):
        """Test the arc-expand-critique template renders correctly."""
        from talemate.prompts import Prompt
        from talemate.agents.base import ActiveAgent

        director = active_context
        narrator = Mock()
        narrator.client = director.client
        narrator.extra_instructions = ""
        narrator.content_use_writing_style = False

        blocks = [
            {
                "type": "narrator",
                "content": "The room was dark and cold. A chill ran down her spine.",
            },
            {
                "type": "character",
                "name": "Elena",
                "content": 'She stepped forward, her hands trembling. "Who\'s there?" she whispered.',
            },
            {
                "type": "narrator",
                "content": "A chill ran through the room. The darkness pressed in from all sides.",
            },
        ]

        director.client.send_prompt = AsyncMock(
            return_value='<BLOCKS>\n[{"type": "narrator", "content": "Revised narration."}]\n</BLOCKS>'
        )

        with ActiveAgent(narrator, lambda: None):
            await Prompt.request(
                "narrator.arc-expand-critique",
                narrator.client,
                "narrate_4096",
                vars={
                    "blocks": blocks,
                    "max_tokens": 8192,
                    "response_length": 4096,
                },
            )

        baseline_checker(capture_prompt(director), AGENT, "arc_expand_critique")

    @pytest.mark.asyncio
    async def test_scene_plan_create_outline(self, active_context, baseline_checker):
        """Test the scene-plan-create-outline template renders correctly."""
        from talemate.prompts import Prompt
        from talemate.agents.base import ActiveAgent

        director = active_context
        characters = list(director.scene.get_characters())

        director.client.send_prompt = AsyncMock(
            return_value='<PERSPECTIVE>Third person limited, past tense.</PERSPECTIVE>\n<OUTLINE>[{"type":"narration","description":"Test","characters":[],"pacing":"slow","tension":0.2}]</OUTLINE>'
        )

        with ActiveAgent(director, lambda: None):
            await Prompt.request(
                "director.scene-plan-create-outline",
                director.client,
                "scene_direction_4096",
                vars={
                    "scene": director.scene,
                    "max_tokens": 8192,
                    "characters": characters,
                    "beat_count": 8,
                    "instructions": "A tense confrontation between the characters in the library.",
                    "estimated_words": 2000,
                },
            )

        baseline_checker(capture_prompt(director), AGENT, "scene_plan_create_outline")

    @pytest.mark.asyncio
    async def test_scene_plan_critique_outline(self, active_context, baseline_checker):
        """Test the scene-plan-critique-outline template renders correctly."""
        from talemate.prompts import Prompt
        from talemate.agents.base import ActiveAgent

        director = active_context
        characters = list(director.scene.get_characters())
        beats = _make_test_beats()
        outline = [b.model_dump() for b in beats]

        director.client.send_prompt = AsyncMock(return_value="<NO_CHANGES/>")

        with ActiveAgent(director, lambda: None):
            await Prompt.request(
                "director.scene-plan-critique-outline",
                director.client,
                "scene_direction_4096",
                vars={
                    "scene": director.scene,
                    "max_tokens": 8192,
                    "characters": characters,
                    "outline": outline,
                    "outline_instructions": "A tense confrontation between the characters in the library.",
                    "perspective": "Third person limited, past tense.",
                },
            )

        baseline_checker(capture_prompt(director), AGENT, "scene_plan_critique_outline")
