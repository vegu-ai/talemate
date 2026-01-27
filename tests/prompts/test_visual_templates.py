"""
Unit tests for visual agent templates.

Tests template rendering without requiring an LLM connection.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from .helpers import (
    create_mock_agent,
    create_mock_scene,
    create_mock_character,
    create_base_context,
    render_template,
    assert_template_renders,
    assert_has_bot_token,
)


@pytest.fixture
def visual_context():
    """Base context for visual templates."""
    return create_base_context()


@pytest.fixture
def active_context(visual_context):
    """Set up active scene and agent context."""
    from talemate.context import active_scene
    from talemate.agents.context import active_agent

    mock_agent = create_mock_agent(agent_type="visual")
    scene_token = active_scene.set(visual_context["scene"])
    agent_token = active_agent.set(mock_agent)

    yield visual_context

    active_scene.reset(scene_token)
    active_agent.reset(agent_token)


def create_mock_visual_prompt(
    instructions: str = "",
    positive_prompt_descriptive: str = "A beautiful landscape with mountains",
):
    """Create a mock visual prompt object."""
    prompt = Mock()
    prompt.instructions = instructions
    prompt.positive_prompt_descriptive = positive_prompt_descriptive
    return prompt


def create_mock_asset(
    has_analysis: bool = True,
    has_tags: bool = True,
    analysis: str = "A character portrait showing a young woman with red hair",
    tags: list = None,
):
    """Create a mock asset for refine-prompt testing."""
    asset = Mock()
    asset.meta = Mock()

    if has_analysis:
        asset.meta.analysis = analysis
    else:
        asset.meta.analysis = None

    if has_tags:
        asset.meta.tags = tags or ["portrait", "character", "fantasy"]
    else:
        asset.meta.tags = None

    return asset


class TestVisualSystemTemplates:
    """Tests for visual system templates."""

    def test_system_no_decensor_renders(self, active_context):
        """Test system-no-decensor.jinja2 renders."""
        result = render_template("visual.system-no-decensor", active_context)
        assert result is not None
        assert len(result) > 0
        # Should contain visual interpreter description
        assert "visual" in result.lower()
        assert "image" in result.lower() or "interpreter" in result.lower()

    def test_system_renders(self, active_context):
        """Test system.jinja2 renders (includes system-no-decensor)."""
        result = render_template("visual.system", active_context)
        assert result is not None
        assert len(result) > 0
        # Should include base system content plus decensor text
        assert "visual" in result.lower()
        # Should mention explicit visual elements
        assert "explicit" in result.lower() or "strong" in result.lower()


class TestVisualExtraContextTemplate:
    """Tests for extra-context.jinja2 template."""

    def test_extra_context_renders(self, active_context):
        """Test extra-context.jinja2 renders with basic context."""
        result = render_template("visual.extra-context", active_context)
        assert result is not None
        assert len(result) > 0
        # Should include scenario premise
        assert "scenario" in result.lower() or "premise" in result.lower()

    def test_extra_context_with_memory_query(self, active_context):
        """Test extra-context.jinja2 with memory query."""
        context = active_context.copy()
        context["memory_query"] = "What does the character look like?"

        with patch('talemate.instance.get_agent') as mock_get_agent:
            mock_memory = Mock()
            # The template uses iterate=10, which triggers multi_query
            mock_memory.multi_query = AsyncMock(return_value=["Character has blue eyes and dark hair."])
            mock_get_agent.return_value = mock_memory

            result = render_template("visual.extra-context", context)
            assert result is not None
            assert len(result) > 0

    def test_extra_context_shows_scene_description(self, active_context):
        """Test extra-context.jinja2 includes scene description."""
        result = render_template("visual.extra-context", active_context)
        assert result is not None
        # Should include the scene description from mock
        assert "clearing" in result.lower() or "forest" in result.lower()


class TestGenerateScenePromptTemplate:
    """Tests for generate-scene-prompt.jinja2 template."""

    def test_generate_scene_prompt_renders(self, active_context):
        """Test generate-scene-prompt.jinja2 renders."""
        result = render_template("visual.generate-scene-prompt", active_context)
        assert result is not None
        assert len(result) > 0
        # Should include scene section
        assert "scene" in result.lower()
        # Should include task section
        assert "task" in result.lower()
        # Should mention painter or image generation
        assert "painter" in result.lower() or "describe" in result.lower()

    def test_generate_scene_prompt_includes_context(self, active_context):
        """Test generate-scene-prompt.jinja2 includes context section."""
        result = render_template("visual.generate-scene-prompt", active_context)
        assert result is not None
        # Should have context section
        assert "context" in result.lower()


class TestGenerateEnvironmentPromptTemplate:
    """Tests for generate-environment-prompt.jinja2 template."""

    def test_generate_environment_prompt_renders(self, active_context, patch_agent_queries):
        """Test generate-environment-prompt.jinja2 renders."""
        context = active_context.copy()
        context["instructions"] = ""

        result = render_template("visual.generate-environment-prompt", context)
        assert result is not None
        assert len(result) > 0
        # Should mention environment
        assert "environment" in result.lower()
        # Should mention no characters/animals
        assert "character" in result.lower() or "animal" in result.lower()

    def test_generate_environment_prompt_with_instructions(self, active_context, patch_agent_queries):
        """Test generate-environment-prompt.jinja2 with instructions."""
        context = active_context.copy()
        context["instructions"] = "Focus on the moonlit garden"

        result = render_template("visual.generate-environment-prompt", context)
        assert result is not None
        assert len(result) > 0
        # Should include the instructions
        assert "moonlit garden" in result.lower()

    def test_generate_environment_prompt_has_prepared_response(self, active_context, patch_agent_queries):
        """Test generate-environment-prompt.jinja2 sets prepared response."""
        context = active_context.copy()
        context["instructions"] = ""

        assert_has_bot_token("visual.generate-environment-prompt", context)


class TestGenerateImagePromptTypeTemplate:
    """Tests for generate-image-prompt-type.jinja2 template."""

    def test_generate_image_prompt_type_renders(self, active_context):
        """Test generate-image-prompt-type.jinja2 renders."""
        result = render_template("visual.generate-image-prompt-type", active_context)
        assert result is not None
        assert len(result) > 0
        # Should mention two versions of prompt
        assert "keyword" in result.lower()
        assert "descriptive" in result.lower()
        # Should mention tags
        assert "keywords" in result.lower() or "tags" in result.lower()


class TestGenerateImageTemplate:
    """Tests for generate-image.jinja2 template."""

    def test_generate_image_renders_unspecified(self, active_context, patch_agent_queries):
        """Test generate-image.jinja2 renders with UNSPECIFIED type."""
        context = active_context.copy()
        context["vis_type"] = "UNSPECIFIED"
        context["visual_prompt"] = create_mock_visual_prompt()

        result = render_template("visual.generate-image", context)
        assert result is not None
        assert len(result) > 0
        # Should include general context section
        assert "context" in result.lower()
        # Should include task section
        assert "task" in result.lower()

    def test_generate_image_with_character_portrait(self, active_context, patch_agent_queries):
        """Test generate-image.jinja2 renders with CHARACTER_PORTRAIT type."""
        context = active_context.copy()
        context["vis_type"] = "CHARACTER_PORTRAIT"
        context["visual_prompt"] = create_mock_visual_prompt()
        context["character"] = create_mock_character()
        context["instructions"] = ""

        result = render_template("visual.generate-image", context)
        assert result is not None
        assert len(result) > 0
        # Should include character context
        assert "character" in result.lower()

    def test_generate_image_with_instructions(self, active_context, patch_agent_queries):
        """Test generate-image.jinja2 includes visual_prompt instructions."""
        context = active_context.copy()
        context["vis_type"] = "UNSPECIFIED"
        context["visual_prompt"] = create_mock_visual_prompt(
            instructions="Make it dramatic with stormy skies"
        )
        context["instructions"] = ""

        result = render_template("visual.generate-image", context)
        assert result is not None
        # Should include the custom instructions
        assert "dramatic" in result.lower() or "stormy" in result.lower()


class TestGenerateImageUnspecifiedTemplate:
    """Tests for generate-image-UNSPECIFIED.jinja2 template."""

    def test_generate_image_unspecified_renders(self, active_context):
        """Test generate-image-UNSPECIFIED.jinja2 renders."""
        context = active_context.copy()
        context["instructions"] = ""

        result = render_template("visual.generate-image-UNSPECIFIED", context)
        assert result is not None
        assert len(result) > 0
        # Should include task section
        assert "task" in result.lower()
        # Should mention image generation
        assert "image" in result.lower()

    def test_generate_image_unspecified_with_instructions(self, active_context):
        """Test generate-image-UNSPECIFIED.jinja2 with instructions."""
        context = active_context.copy()
        context["instructions"] = "Create a fantasy landscape"

        result = render_template("visual.generate-image-UNSPECIFIED", context)
        assert result is not None
        # Should include the instructions
        assert "fantasy landscape" in result.lower()


class TestGenerateImageCharacterPortraitTemplate:
    """Tests for generate-image-CHARACTER_PORTRAIT.jinja2 template."""

    def test_character_portrait_renders(self, active_context, patch_agent_queries):
        """Test generate-image-CHARACTER_PORTRAIT.jinja2 renders."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Elena")
        context["instructions"] = ""

        result = render_template("visual.generate-image-CHARACTER_PORTRAIT", context)
        assert result is not None
        assert len(result) > 0
        # Should include character context section
        assert "character" in result.lower()
        # Should include requirements section
        assert "requirements" in result.lower()
        # Should mention headshot/portrait
        assert "head" in result.lower() or "face" in result.lower()

    def test_character_portrait_includes_character_sheet(self, active_context, patch_agent_queries):
        """Test character portrait includes character sheet."""
        char = create_mock_character(name="Marcus")
        context = active_context.copy()
        context["character"] = char
        context["instructions"] = ""

        result = render_template("visual.generate-image-CHARACTER_PORTRAIT", context)
        assert result is not None
        # Should include character name
        assert "marcus" in result.lower()

    def test_character_portrait_with_visual_rules(self, active_context, patch_agent_queries):
        """Test character portrait respects visual rules."""
        char = create_mock_character(name="Aria")
        char.visual_rules = "Always show her with golden eyes"
        context = active_context.copy()
        context["character"] = char
        context["instructions"] = ""

        result = render_template("visual.generate-image-CHARACTER_PORTRAIT", context)
        assert result is not None
        # Should include visual rules
        assert "golden eyes" in result.lower()

    def test_character_portrait_with_instructions(self, active_context, patch_agent_queries):
        """Test character portrait with specific instructions."""
        context = active_context.copy()
        context["character"] = create_mock_character()
        context["instructions"] = "Show her smiling"

        result = render_template("visual.generate-image-CHARACTER_PORTRAIT", context)
        assert result is not None
        # Should include the instructions
        assert "smiling" in result.lower()


class TestGenerateImageCharacterCardTemplate:
    """Tests for generate-image-CHARACTER_CARD.jinja2 template."""

    def test_character_card_renders(self, active_context, patch_agent_queries):
        """Test generate-image-CHARACTER_CARD.jinja2 renders."""
        context = active_context.copy()
        context["character"] = create_mock_character(name="Elena")
        context["instructions"] = ""

        result = render_template("visual.generate-image-CHARACTER_CARD", context)
        assert result is not None
        assert len(result) > 0
        # Should include character context section
        assert "character" in result.lower()
        # Should include requirements section
        assert "requirements" in result.lower()
        # Should mention portrait orientation
        assert "portrait" in result.lower()

    def test_character_card_includes_character_details(self, active_context, patch_agent_queries):
        """Test character card includes character details."""
        char = create_mock_character(name="Marcus")
        char.details = {
            "background": "A noble warrior",
            "appearance": "Tall and muscular"
        }
        context = active_context.copy()
        context["character"] = char
        context["instructions"] = ""

        result = render_template("visual.generate-image-CHARACTER_CARD", context)
        assert result is not None
        # Should include detail sections
        assert "background" in result.lower() or "noble" in result.lower()

    def test_character_card_with_visual_rules(self, active_context, patch_agent_queries):
        """Test character card respects visual rules."""
        char = create_mock_character(name="Aria")
        char.visual_rules = "Always depicted with her signature blue cloak"
        context = active_context.copy()
        context["character"] = char
        context["instructions"] = ""

        result = render_template("visual.generate-image-CHARACTER_CARD", context)
        assert result is not None
        # Should include visual rules
        assert "blue cloak" in result.lower()

    def test_character_card_single_subject_requirement(self, active_context, patch_agent_queries):
        """Test character card emphasizes single character focus."""
        context = active_context.copy()
        context["character"] = create_mock_character()
        context["instructions"] = ""

        result = render_template("visual.generate-image-CHARACTER_CARD", context)
        assert result is not None
        # Should mention single character focus
        assert "one" in result.lower() or "single" in result.lower()


class TestGenerateImageSceneBackgroundTemplate:
    """Tests for generate-image-SCENE_BACKGROUND.jinja2 template."""

    def test_scene_background_renders(self, active_context, patch_agent_queries):
        """Test generate-image-SCENE_BACKGROUND.jinja2 renders."""
        context = active_context.copy()
        context["instructions"] = ""
        context["scene_context"] = "A peaceful meadow at sunset"

        result = render_template("visual.generate-image-SCENE_BACKGROUND", context)
        assert result is not None
        assert len(result) > 0
        # Should include requirements section
        assert "requirements" in result.lower()
        # Should mention environment focus
        assert "environment" in result.lower()

    def test_scene_background_no_characters(self, active_context, patch_agent_queries):
        """Test scene background emphasizes no characters."""
        context = active_context.copy()
        context["instructions"] = ""
        context["scene_context"] = "A dark forest path"

        result = render_template("visual.generate-image-SCENE_BACKGROUND", context)
        assert result is not None
        # Should explicitly mention no characters
        assert "no character" in result.lower() or "character exclusion" in result.lower()

    def test_scene_background_with_instructions(self, active_context, patch_agent_queries):
        """Test scene background with specific instructions."""
        context = active_context.copy()
        context["instructions"] = "Make it look ominous with fog"
        context["scene_context"] = "A dark forest"

        result = render_template("visual.generate-image-SCENE_BACKGROUND", context)
        assert result is not None
        # Should include instructions
        assert "ominous" in result.lower() or "fog" in result.lower()


class TestGenerateImageSceneIllustrationTemplate:
    """Tests for generate-image-SCENE_ILLUSTRATION.jinja2 template."""

    def test_scene_illustration_renders(self, active_context, patch_agent_queries):
        """Test generate-image-SCENE_ILLUSTRATION.jinja2 renders."""
        context = active_context.copy()
        context["instructions"] = ""

        result = render_template("visual.generate-image-SCENE_ILLUSTRATION", context)
        assert result is not None
        assert len(result) > 0
        # Should include visual context section
        assert "visual" in result.lower() or "context" in result.lower()
        # Should include requirements section
        assert "requirements" in result.lower()

    def test_scene_illustration_horizontal_format(self, active_context, patch_agent_queries):
        """Test scene illustration emphasizes horizontal format."""
        context = active_context.copy()
        context["instructions"] = ""

        result = render_template("visual.generate-image-SCENE_ILLUSTRATION", context)
        assert result is not None
        # Should mention horizontal/landscape format
        assert "horizontal" in result.lower() or "landscape" in result.lower()

    def test_scene_illustration_dynamic_moment(self, active_context, patch_agent_queries):
        """Test scene illustration captures dynamic moments."""
        context = active_context.copy()
        context["instructions"] = ""

        result = render_template("visual.generate-image-SCENE_ILLUSTRATION", context)
        assert result is not None
        # Should mention action/moment/dynamic
        assert "moment" in result.lower() or "action" in result.lower() or "dynamic" in result.lower()

    def test_scene_illustration_with_characters(self, active_context, patch_agent_queries):
        """Test scene illustration with scene characters."""
        scene = create_mock_scene()
        scene.characters = [
            create_mock_character(name="Elena"),
            create_mock_character(name="Marcus", is_player=True),
        ]
        context = active_context.copy()
        context["scene"] = scene
        context["instructions"] = ""

        # Update active scene
        from talemate.context import active_scene
        scene_token = active_scene.set(scene)

        try:
            result = render_template("visual.generate-image-SCENE_ILLUSTRATION", context)
            assert result is not None
            # Should query for each character
            assert "elena" in result.lower() or "marcus" in result.lower()
        finally:
            active_scene.reset(scene_token)


class TestGenerateImageSceneCardTemplate:
    """Tests for generate-image-SCENE_CARD.jinja2 template."""

    def test_scene_card_renders(self, active_context, patch_agent_queries):
        """Test generate-image-SCENE_CARD.jinja2 renders."""
        context = active_context.copy()
        context["instructions"] = ""
        context["scene_context"] = "A bustling marketplace"

        result = render_template("visual.generate-image-SCENE_CARD", context)
        assert result is not None
        assert len(result) > 0
        # Should include requirements section
        assert "requirements" in result.lower()
        # Should mention cover image
        assert "cover" in result.lower()

    def test_scene_card_establishing_shot(self, active_context, patch_agent_queries):
        """Test scene card describes establishing shot style."""
        context = active_context.copy()
        context["instructions"] = ""
        context["scene_context"] = "A grand castle"

        result = render_template("visual.generate-image-SCENE_CARD", context)
        assert result is not None
        # Should mention establishing shot or preview
        assert "establishing" in result.lower() or "preview" in result.lower() or "cover" in result.lower()

    def test_scene_card_with_instructions(self, active_context, patch_agent_queries):
        """Test scene card with specific instructions."""
        context = active_context.copy()
        context["instructions"] = "Focus on the ancient ruins"
        context["scene_context"] = "Ancient temple ruins"

        result = render_template("visual.generate-image-SCENE_CARD", context)
        assert result is not None
        # Should include instructions
        assert "ancient" in result.lower() or "ruins" in result.lower()


class TestRefinePromptTemplate:
    """Tests for refine-prompt.jinja2 template."""

    def test_refine_prompt_renders(self, active_context):
        """Test refine-prompt.jinja2 renders."""
        context = active_context.copy()
        context["assets"] = [create_mock_asset()]
        context["gathered_information"] = "The character has blue eyes"
        context["instructions"] = "Create a portrait"
        context["visual_prompt"] = create_mock_visual_prompt(
            positive_prompt_descriptive="A woman standing in a garden"
        )

        result = render_template("visual.refine-prompt", context)
        assert result is not None
        assert len(result) > 0
        # Should include selected references section
        assert "references" in result.lower()
        # Should include original prompt section
        assert "original prompt" in result.lower()

    def test_refine_prompt_with_analysis(self, active_context):
        """Test refine-prompt.jinja2 displays asset analysis."""
        context = active_context.copy()
        context["assets"] = [
            create_mock_asset(
                has_analysis=True,
                analysis="A portrait of a young warrior with armor"
            )
        ]
        context["gathered_information"] = ""
        context["instructions"] = ""
        context["visual_prompt"] = create_mock_visual_prompt()

        result = render_template("visual.refine-prompt", context)
        assert result is not None
        # Should include the analysis text
        assert "warrior" in result.lower() or "armor" in result.lower()

    def test_refine_prompt_with_tags_only(self, active_context):
        """Test refine-prompt.jinja2 displays tags when no analysis."""
        context = active_context.copy()
        context["assets"] = [
            create_mock_asset(
                has_analysis=False,
                has_tags=True,
                tags=["portrait", "fantasy", "warrior"]
            )
        ]
        context["gathered_information"] = ""
        context["instructions"] = ""
        context["visual_prompt"] = create_mock_visual_prompt()

        result = render_template("visual.refine-prompt", context)
        assert result is not None
        # Should mention no analysis but show tags
        assert "no analysis" in result.lower()
        assert "tags" in result.lower()

    def test_refine_prompt_no_analysis_no_tags(self, active_context):
        """Test refine-prompt.jinja2 handles assets without analysis or tags."""
        context = active_context.copy()
        context["assets"] = [
            create_mock_asset(has_analysis=False, has_tags=False)
        ]
        context["gathered_information"] = ""
        context["instructions"] = ""
        context["visual_prompt"] = create_mock_visual_prompt()

        result = render_template("visual.refine-prompt", context)
        assert result is not None
        # Should mention no analysis and no tags
        assert "no analysis" in result.lower()
        assert "no tags" in result.lower()

    def test_refine_prompt_multiple_assets(self, active_context):
        """Test refine-prompt.jinja2 handles multiple assets."""
        context = active_context.copy()
        context["assets"] = [
            create_mock_asset(analysis="First character portrait"),
            create_mock_asset(analysis="Second scene background"),
        ]
        context["gathered_information"] = ""
        context["instructions"] = ""
        context["visual_prompt"] = create_mock_visual_prompt()

        result = render_template("visual.refine-prompt", context)
        assert result is not None
        # Should include multiple image references
        assert "image 1" in result.lower()
        assert "image 2" in result.lower()

    def test_refine_prompt_includes_original_prompt(self, active_context):
        """Test refine-prompt.jinja2 includes original prompt."""
        context = active_context.copy()
        context["assets"] = [create_mock_asset()]
        context["gathered_information"] = ""
        context["instructions"] = ""
        context["visual_prompt"] = create_mock_visual_prompt(
            positive_prompt_descriptive="A knight in shining armor stands before the castle gates"
        )

        result = render_template("visual.refine-prompt", context)
        assert result is not None
        # Should include the original prompt text
        assert "knight" in result.lower() or "castle" in result.lower()

    def test_refine_prompt_includes_gathered_info(self, active_context):
        """Test refine-prompt.jinja2 includes gathered information."""
        context = active_context.copy()
        context["assets"] = [create_mock_asset()]
        context["gathered_information"] = "The scene takes place at midnight during a thunderstorm"
        context["instructions"] = ""
        context["visual_prompt"] = create_mock_visual_prompt()

        result = render_template("visual.refine-prompt", context)
        assert result is not None
        # Should include gathered information
        assert "midnight" in result.lower() or "thunderstorm" in result.lower()

    def test_refine_prompt_includes_instructions(self, active_context):
        """Test refine-prompt.jinja2 includes original instructions."""
        context = active_context.copy()
        context["assets"] = [create_mock_asset()]
        context["gathered_information"] = ""
        context["instructions"] = "Use a cinematic style with dramatic lighting"
        context["visual_prompt"] = create_mock_visual_prompt()

        result = render_template("visual.refine-prompt", context)
        assert result is not None
        # Should include original instructions
        assert "cinematic" in result.lower() or "dramatic" in result.lower()
