import structlog

from .schema import VIS_TYPE, VisualPrompt, VisualPromptPart

from talemate.agents.base import AgentAction, AgentActionConfig, AgentActionNote
from talemate.world_state.manager import WorldStateManager
from talemate.world_state.templates import Collection
from talemate.world_state.templates.visual import VisualStyle

__all__ = [
    "StyleMixin",
]

log = structlog.get_logger("talemate.agents.visual.style")


class StyleMixin:
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["_styles"] = AgentAction(
            enabled=True,
            container=True,
            label="Styles",
            icon="mdi-palette",
            description="Style configuration",
            config={
                "art_style": AgentActionConfig(
                    type="wstemplate",
                    value="visual_styles__digital_art",
                    wstemplate_type="visual_style",
                    wstemplate_filter={"visual_type": "STYLE"},
                    label="Art Style",
                    description="The default art style to use for visual prompt generation. Can be overridden in scene settings.",
                    choices=[],
                ),
                "character_card_style": AgentActionConfig(
                    type="wstemplate",
                    value="visual_styles__character_card",
                    wstemplate_type="visual_style",
                    wstemplate_filter={"visual_type": "CHARACTER_CARD"},
                    label="Character Card",
                    description="The style to use for character card visual prompt generation",
                    choices=[],
                ),
                "character_portrait_style": AgentActionConfig(
                    type="wstemplate",
                    value="visual_styles__character_portrait",
                    wstemplate_type="visual_style",
                    wstemplate_filter={"visual_type": "CHARACTER_PORTRAIT"},
                    label="Character Portrait",
                    description="The style to use for character portrait visual prompt generation",
                    choices=[],
                ),
                "scene_card_style": AgentActionConfig(
                    type="wstemplate",
                    value="visual_styles__scene_card",
                    wstemplate_type="visual_style",
                    wstemplate_filter={"visual_type": "SCENE_CARD"},
                    label="Scene Card",
                    description="The style to use for scene card visual prompt generation",
                    choices=[],
                ),
                "scene_background_style": AgentActionConfig(
                    type="wstemplate",
                    value="visual_styles__scene_background",
                    wstemplate_type="visual_style",
                    wstemplate_filter={"visual_type": "SCENE_BACKGROUND"},
                    label="Scene Background",
                    description="The style to use for scene background visual prompt generation",
                    choices=[],
                ),
                "scene_illustration_style": AgentActionConfig(
                    type="wstemplate",
                    value="visual_styles__scene_illustration",
                    wstemplate_type="visual_style",
                    wstemplate_filter={"visual_type": "SCENE_ILLUSTRATION"},
                    label="Scene Illustration",
                    description="The style to use for scene illustration visual prompt generation",
                    choices=[],
                    note=AgentActionNote(
                        title="Manage styles",
                        text="Additional styles can be created in the Templates manager.",
                        icon="mdi-cube-scan",
                    ),
                ),
            },
        )
        return actions

    # helpers

    def style_template_id(self, vis_type: VIS_TYPE) -> str:
        if vis_type == VIS_TYPE.UNSPECIFIED:
            return self.actions["_styles"].config["art_style"].value
        else:
            return (
                self.actions["_styles"].config[f"{vis_type.value.lower()}_style"].value
            )

    def style_template(self, vis_type: VIS_TYPE) -> VisualStyle | None:
        scene = getattr(self, "scene", None)
        if not scene:
            return None

        manager: WorldStateManager = scene.world_state_manager
        templates: Collection = manager.template_collection

        # Check for scene-level override for art style (UNSPECIFIED) only
        template_id = None
        if vis_type == VIS_TYPE.UNSPECIFIED and scene.visual_style_template:
            template_id = scene.visual_style_template
        else:
            template_id = self.style_template_id(vis_type)

        if not template_id:
            return None

        try:
            group_uid, template_uid = template_id.split("__")
        except ValueError:
            return None
        return templates.find_template(group_uid, template_uid)

    def _get_current_art_style_name(self) -> str | None:
        """Get the name of the currently active art style template"""
        if not getattr(self, "scene", None):
            return None
        template = self.style_template(VIS_TYPE.UNSPECIFIED)
        if template:
            return template.name
        return None

    def _get_current_art_style_source(self) -> str | None:
        """Get the source of the currently active art style: 'scene' or 'agent'"""
        scene = getattr(self, "scene", None)
        if not scene:
            return None
        if scene.visual_style_template:
            return "scene"
        return "agent"

    # actions

    def apply_style(
        self, prompt: VisualPrompt, template_id: str
    ) -> VisualPromptPart | None:
        template = self.style_template(template_id)
        part = None
        if template:
            part = VisualPromptPart(**template.model_dump())
            prompt.parts.insert(0, part)
        return part

    def apply_styles(self, prompt: VisualPrompt, vis_type: VIS_TYPE) -> VisualPrompt:
        template_art_style: VisualStyle | None = self.style_template(
            VIS_TYPE.UNSPECIFIED
        )
        template_subject_style: VisualStyle | None = self.style_template(vis_type)

        log.debug(
            "apply_styles",
            template_art_style=template_art_style,
            template_subject_style=template_subject_style,
        )

        if template_subject_style:
            prompt.parts.insert(
                0,
                VisualPromptPart(
                    positive_keywords_raw=template_subject_style.positive_keywords,
                    negative_keywords_raw=template_subject_style.negative_keywords,
                    positive_descriptive=template_subject_style.positive_descriptive,
                    negative_descriptive=template_subject_style.negative_descriptive,
                    instructions=template_subject_style.instructions,
                ),
            )

        if template_art_style:
            prompt.parts.insert(
                0,
                VisualPromptPart(
                    positive_keywords_raw=template_art_style.positive_keywords,
                    negative_keywords_raw=template_art_style.negative_keywords,
                    positive_descriptive=template_art_style.positive_descriptive,
                    negative_descriptive=template_art_style.negative_descriptive,
                    instructions=template_art_style.instructions,
                ),
            )

        return prompt
