from typing import TYPE_CHECKING
import structlog
from functools import wraps
import dataclasses
from talemate.agents.base import (
    set_processing as _set_processing,
    AgentAction,
    AgentActionConfig,
    AgentEmission,
)
from talemate.agents.context import active_agent
from talemate.prompts import Prompt
import talemate.emit.async_signals
from talemate.util import strip_partial_sentences

if TYPE_CHECKING:
    from talemate.tale_mate import Character
    from talemate.agents.summarize.analyze_scene import SceneAnalysisEmission

log = structlog.get_logger()

talemate.emit.async_signals.register(
    "agent.director.guide.before_generate", 
    "agent.director.guide.inject_instructions",
    "agent.director.guide.generated",
)


@dataclasses.dataclass
class DirectorGuidanceEmission(AgentEmission):
    generation: str = ""
    dynamic_instructions: list[str] = dataclasses.field(default_factory=list)


def set_processing(fn):
    """
    Custom decorator that emits the agent status as processing while the function
    is running and then emits the result of the function as a DirectorGuidanceEmission
    """

    @_set_processing
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        emission: DirectorGuidanceEmission = DirectorGuidanceEmission(agent=self)
        
        await talemate.emit.async_signals.get("agent.director.guide.before_generate").send(emission)
        await talemate.emit.async_signals.get("agent.director.guide.inject_instructions").send(emission)
        
        agent_context = active_agent.get()
        agent_context.state["dynamic_instructions"] = emission.dynamic_instructions
        
        response = await fn(self, *args, **kwargs)
        emission.generation = [response]
        await talemate.emit.async_signals.get("agent.director.guide.generated").send(emission)
        return emission.generation[0]

    return wrapper



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
            quick_toggle=True,
            experimental=True,
            label="Guide Scene",
            icon="mdi-lightbulb",
            description="Guide actors and the narrator during the scene progression. This uses the summarizer agent's scene analysis, which needs to be enabled for this to work.",
            config={
                "guide_actors": AgentActionConfig(
                    type="bool",
                    label="Guide actors",
                    description="Guide the actors in the scene. This happens during every actor turn.",
                    value=False
                ),
                "guide_narrator": AgentActionConfig(
                    type="bool",
                    label="Guide narrator",
                    description="Guide the narrator during the scene. This happens during the narrator's turn.",
                    value=False
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
    def guide_narrator(self) -> bool:
        return self.actions["guide_scene"].config["guide_narrator"].value
    
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
        
        if not self.guide_scene:
            return
        
        guidance = None
        
        if emission.analysis_type == "narration" and self.guide_narrator:
            guidance = await self.guide_narrator_off_of_scene_analysis(
                emission.response,
                response_length=self.guide_scene_guidance_length,
            )
            
            if not guidance:
                log.warning("director.guide_scene.narration: Empty resonse")
                return
            
            self.set_context_states(narrator_guidance=guidance)
        
        elif emission.analysis_type == "conversation" and self.guide_actors:   
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
        return strip_partial_sentences(response).strip()
    
    @set_processing
    async def guide_narrator_off_of_scene_analysis(
        self, 
        analysis: str,
        response_length: int = 256
    ):
        """
        Guides the narrator based on the scene analysis.
        """
        
        log.debug("director.guide_narrator_off_of_scene_analysis", analysis=analysis)
        
        response = await Prompt.request(
            "director.guide-narration",
            self.client,
            f"direction_{response_length}",
            vars={
                "analysis": analysis,
                "scene": self.scene,
                "response_length": response_length,
                "max_tokens": self.client.max_token_length,
            },
        )
        return strip_partial_sentences(response).strip()