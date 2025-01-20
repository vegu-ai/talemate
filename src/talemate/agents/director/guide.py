from typing import TYPE_CHECKING
import structlog
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig
)
from talemate.prompts import Prompt
from talemate.emit import emit
from talemate.instance import get_agent
import talemate.emit.async_signals
from talemate.agents.conversation import ConversationAgentEmission
import talemate.game.focal as focal
from talemate.scene_message import ContextInvestigationMessage

if TYPE_CHECKING:
    from talemate.tale_mate import Scene, Character
    from talemate.agents.summarize.analyze_scene import SceneAnalysisEmission

log = structlog.get_logger()

class GuideSceneMixin:
    
    """
    Director agent mixin that provides functionality for automatically guiding
    the actors or the narrator during the scene progression.
    """
    
    @classmethod
    def add_actions(cls, director):
        director.actions["guide_scene"] = AgentAction(
            enabled=False,
            container=True,
            can_be_disabled=True,
            experimental=True,
            label="Guide Scene",
            icon="mdi-lightbulb",
            description="Guide actors and the narrator during the scene progression. This uses the summarizer agent's scene analysis, which needs to be enabled for this to work.",
            config={
                "guide_actors": AgentActionConfig(
                    type="bool",
                    label="Guide actors",
                    description="Whether to guide the actors in the scene. This happens during every actor turn.",
                    value=True
                ),
                "guidance_length": AgentActionConfig(
                    type="text",
                    label="Max. Guidance Length",
                    description="The maximum length of the guidance to provide to the actors. This text will be inserted very close to end of the prompt. Selecting bigger values can have a detremental effect on the quality of generation.",
                    value="384",
                    choices=[
                        {"label": "Tiny (128)", "value": "128"},
                        {"label": "Short (256)", "value": "256"},
                        {"label": "Brief (384)", "value": "384"},
                        {"label": "Medium (512)", "value": "512"},
                        {"label": "Medium Long (768)", "value": "768"},
                        {"label": "Long (1024)", "value": "1024"},
                    ]
                )
            }
        )
    
    # config property helpers
        
    @property
    def guide_scene(self) -> bool:
        return self.actions["guide_scene"].enabled
    
    @property
    def guide_actors(self) -> bool:
        return self.actions["guide_scene"].config["guide_actors"].value
    
    @property
    def guide_scene_guidance_length(self) -> int:
        return int(self.actions["guide_scene"].config["guidance_length"].value)
    
    # signal connect
    
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("agent.summarization.scene_analysis.after").connect(
            self.on_summarization_scene_analysis_after
        )
        talemate.emit.async_signals.get("agent.summarization.scene_analysis.cached").connect(
            self.on_summarization_scene_analysis_after
        )
        
    async def on_summarization_scene_analysis_after(self, emission: "SceneAnalysisEmission"):
        
        log.warning("director.guide_scene.on_summarization_scene_analysis_after", emission=emission)
        
        if not self.guide_scene:
            return
        
        if emission.analysis_type == "narration":
            return # TODO
        
        if emission.analysis_type == "conversation" and self.guide_actors:   
            guidance = await self.guide_actor_off_of_scene_analysis(
                emission.response,
                emission.template_vars.get("character"),
                response_length=self.guide_scene_guidance_length,
            )
            
            if not guidance:
                log.warning("director.guide_scene.conversation: Empty resonse")
                return
            
            self.set_context_states(actor_guidance=guidance)
            
    # methods
    
    @set_processing
    async def guide_actor_off_of_scene_analysis(self, analysis: str, character: "Character", response_length: int = 256):
        """
        Guides the actor based on the scene analysis.
        """
        
        log.debug("director.guide_actor_off_of_scene_analysis", analysis=analysis, character=character)
        
        response = await Prompt.request(
            "director.guide-conversation",
            self.client,
            f"direction_{response_length}",
            vars={
                "analysis": analysis,
                "scene": self.scene,
                "character": character,
                "response_length": response_length,
                "max_tokens": self.client.max_token_length,
            },
        )
        return response.strip()