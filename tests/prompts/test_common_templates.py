"""
Unit tests for common templates.

Common templates are **include-only templates** - they are building blocks
included by other agent templates via Jinja2's {% include %} directive.
They are NOT called directly via Prompt.request() by any agent method.

According to the testing guidelines in AGENT_CONTEXT.md:
- Only test agent methods that call Prompt.request() to send prompts to the LLM
- Common templates don't have corresponding agent methods
- They are tested indirectly through the agent tests that use templates which include them

This file documents the common templates and their usage patterns.
Direct rendering tests are NOT included as they don't test real code paths.

Common Template Usage Summary:
-----------------------------
All 24 common templates are include-only templates used by various agent templates:

1. base.jinja2 - Base template that assembles context (includes many other common templates)
2. building-blocks.jinja2 - Scene building blocks documentation (1 use)
3. character-context.jinja2 - Character information section (16 uses)
4. character-guidance.jinja2 - Character direction and acting instructions (2 uses)
5. content-classification.jinja2 - Content classification section (12 uses)
6. context_id_items.jinja2 - Context ID item rendering (used via game engine nodes)
7. dynamic-instructions.jinja2 - Dynamic instruction injection (22 uses)
8. extra-context.jinja2 - Additional context including reinforcements/pins (31 uses)
9. full-scene-context.jinja2 - Full scene context assembly (includes other commons)
10. gamestate-context.jinja2 - Game state data section (2 uses)
11. internal-note-help.jinja2 - Internal note help text (8 uses)
12. memory-context.jinja2 - Memory/RAG context section (12 uses)
13. narrative-patterns.jinja2 - Narrative pattern instructions (1 use)
14. response-length.jinja2 - Response length instructions (7 uses)
15. scene-context.jinja2 - Scene history section (20 uses)
16. scene-intent-hybrid.jinja2 - Scene intent with technical option (3 uses)
17. scene-intent-inline.jinja2 - Inline scene intent instructions (10 uses)
18. scene-intent.jinja2 - Scene intent (non-technical) (19 uses)
19. scene-intent-technical.jinja2 - Technical scene intent format (1 use)
20. scene-types.jinja2 - Scene types listing (1 use)
21. task-information.jinja2 - Task-specific information section (4 uses)
22. useful-context-ids.jinja2 - Context ID documentation (2 uses)
23. user-controlled-character.jinja2 - Player character indication (1 use)
24. writing-style-instructions.jinja2 - Writing style section (6 uses)

Testing Strategy:
----------------
Common templates are tested indirectly through agent tests. For example:
- When test_narrator_templates.py calls narrator.narrate_scene(), the narrator
  template includes common/extra-context.jinja2, common/scene-context.jinja2, etc.
- If a common template has a bug, the agent tests that use it will fail.

This approach tests the real code path rather than just Jinja2 syntax.
"""

import pytest


class TestCommonTemplatesDocumentation:
    """Documentation tests for common templates.

    These tests verify our understanding of the common template architecture.
    They do NOT test template rendering directly (that's done via agent tests).
    """

    def test_common_templates_are_include_only(self):
        """
        Document that common templates are include-only building blocks.

        Common templates are designed to be included by agent-specific templates.
        They don't have corresponding agent methods that call Prompt.request().

        Instead of testing them directly, we test them through the agent tests:
        - test_narrator_templates.py tests narration which includes common templates
        - test_director_templates.py tests direction which includes common templates
        - test_summarizer_templates.py tests summarization which includes common templates
        - etc.
        """
        # This test documents the architecture
        # Common templates don't need direct tests because:
        # 1. They don't have agent methods that call Prompt.request()
        # 2. They are tested indirectly through agent template tests
        # 3. Direct render_template() tests don't test real code paths
        assert True

    def test_context_id_items_used_by_game_engine(self):
        """
        Document that context_id_items.jinja2 is used via game engine nodes.

        Unlike other common templates which are included via {% include %},
        context_id_items.jinja2 is rendered via Prompt.get() in:
        - src/talemate/game/engine/nodes/context_id.py (RenderContextIDs, ScanContextIDs)

        This is a rendering utility for the game engine, not an agent prompt.
        """
        # Verify the template exists
        from pathlib import Path

        template_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "talemate"
            / "prompts"
            / "templates"
            / "common"
            / "context_id_items.jinja2"
        )
        assert template_path.exists(), "context_id_items.jinja2 should exist"

    def test_all_common_templates_exist(self):
        """Verify all documented common templates exist on disk."""
        from pathlib import Path

        common_dir = (
            Path(__file__).parent.parent.parent
            / "src"
            / "talemate"
            / "prompts"
            / "templates"
            / "common"
        )

        expected_templates = [
            "base.jinja2",
            "building-blocks.jinja2",
            "character-context.jinja2",
            "character-guidance.jinja2",
            "content-classification.jinja2",
            "context_id_items.jinja2",
            "dynamic-instructions.jinja2",
            "extra-context.jinja2",
            "full-scene-context.jinja2",
            "gamestate-context.jinja2",
            "internal-note-help.jinja2",
            "memory-context.jinja2",
            "narrative-patterns.jinja2",
            "response-length.jinja2",
            "scene-context.jinja2",
            "scene-intent-hybrid.jinja2",
            "scene-intent-inline.jinja2",
            "scene-intent.jinja2",
            "scene-intent-technical.jinja2",
            "scene-types.jinja2",
            "task-information.jinja2",
            "useful-context-ids.jinja2",
            "user-controlled-character.jinja2",
            "writing-style-instructions.jinja2",
        ]

        for template_name in expected_templates:
            template_path = common_dir / template_name
            assert template_path.exists(), (
                f"Common template {template_name} should exist"
            )

        # Also verify we haven't missed any templates
        actual_templates = {f.name for f in common_dir.glob("*.jinja2")}
        expected_set = set(expected_templates)

        # Check for unexpected templates
        unexpected = actual_templates - expected_set
        assert not unexpected, f"Unexpected templates found: {unexpected}"

        # Check for missing templates
        missing = expected_set - actual_templates
        assert not missing, f"Expected templates missing: {missing}"
