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

log = structlog.get_logger()

class SceneAnalyzationMixin:
    
    """
    Director agent mixin that provides functionality for scene analyzation.
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
            description="Analyzes the scene and provides guidance to the actors or the narrator.",
            config={
                "guide_actors": AgentActionConfig(
                    type="bool",
                    label="Guide actors",
                    description="Whether to guide the actors in the scene. This happens during every actor turn.",
                    value=True
                ),
                "analyze_scene": AgentActionConfig(
                    type="bool",
                    label="Analyze Scene",
                    description="Whether to perform an analysis of the scene.",
                    value=True
                ),
                "deep_analysis": AgentActionConfig(
                    type="bool",
                    label="Deep analysis",
                    description="Whether to perform a deep analysis of the scene. This will perform a context investigation. The `Analyze Scene` option must be enabled for this to work.",
                    value=True,
                    expensive=True,
                ),
                "deep_analysis_max_chapter_queries": AgentActionConfig(
                    type="number",
                    label="Deep analyss - Max chapter queries",
                    description="The maximum number of chapter queries to perform during deep analysis.",
                    value=1,
                    min=1,
                    max=5
                ),
                "cache_analysis": AgentActionConfig(
                    type="bool",
                    label="Cache analysis",
                    description="Whether to cache the analysis results for the scene. This means analysis will not be regenerated when regenerating the actor or narrator's output.",
                    value=True
                ),
                "analysis_length": AgentActionConfig(
                    type="text",
                    label="Length of analysis",
                    description="The length of the analysis to be performed.",
                    value="long",
                    choices=[
                        {"label": "Short", "value": "short"},
                        {"label": "Medium", "value": "medium"},
                        {"label": "Long", "value": "long"}
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
    def analysis_length(self) -> str:
        return self.actions["guide_scene"].config["analysis_length"].value
    
    @property
    def cache_analysis(self) -> bool:
        return self.actions["guide_scene"].config["cache_analysis"].value
    
    @property
    def deep_analysis(self) -> bool:
        return self.actions["guide_scene"].config["deep_analysis"].value
    
    @property
    def deep_analysis_max_chapter_queries(self) -> int:
        return self.actions["guide_scene"].config["deep_analysis_max_chapter_queries"].value
    
    @property
    def analyze_scene(self) -> bool:
        return self.actions["guide_scene"].config["analyze_scene"].value
    
    # signal connect
        
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("agent.conversation.inject_instructions").connect(
            self.on_conversation_inject_instructions
        )
        talemate.emit.async_signals.get("agent.conversation.inject_instructions").connect(
            self.on_conversation_inject_context_investigation
        )
        
    async def on_conversation_inject_instructions(self, emission:ConversationAgentEmission):
        """
        Injects instructions into the conversation.
        """
        
        if not self.guide_scene:
            return
        
        analysis = None
        
        if self.cache_analysis:
            # check if the analysis is already cached
            scene:Scene = self.scene
            
            cached_analysis = getattr(self, "cached_analysis", None)
            if cached_analysis and cached_analysis.get("fp") == scene.history[-1].fingerprint:
                analysis = cached_analysis["guidance"]
        
        
        if not analysis and self.analyze_scene:
            # analyze the scene for the next action
            analysis = await self.analyze_scene_for_next_action(emission.character, self.analysis_length)
            
            if self.cache_analysis:
                self.cached_analysis = {
                    "fp": scene.history[-1].fingerprint,
                    "guidance": analysis
                }
            
        if not analysis:
            return
            
        emission.dynamic_instructions.append("\n".join(
            [
                "<|SECTION:SCENE ANALYSIS|>",
                analysis,
                "<|CLOSE_SECTION|>"
            ]
        ))
        
    async def on_conversation_inject_context_investigation(self, emission:ConversationAgentEmission):
        """
        Injects context investigation into the conversation.
        """
        
        context_investigation = self.get_scene_state("context_investigation")
        if context_investigation:
            emission.dynamic_instructions.append("\n".join(
                [
                    "<|SECTION:HISTORIC CONTEXT|>",
                    context_investigation,
                    "<|CLOSE_SECTION|>"
                ]
            ))
    
    # actions

    @set_processing
    async def analyze_scene_for_next_action(self, character:"Character", length:str="medium") -> str:
        
        """
        Analyzes the current scene progress and gives a suggestion for the next action.
        taken by the given actor.
        """
        
        response = await Prompt.request(
            "director.analyze-scene-for-next-action",
            self.client,
            f"direction_{length}",
            vars={
                "max_tokens": self.client.max_token_length,
                "scene": self.scene,
                "character": character,
                "length": length,
                "context_investigation": self.get_scene_state("context_investigation"),
                "max_chapter_queries": 3,
            },
        )
        
        if not response.strip():
            log.warning("analyze_scene_for_next_action.empty_response")
            return response
        
        summarizer = get_agent("summarizer")
        
        ci_calls:list[focal.Call] = await summarizer.request_context_investigations(response)
        
        log.debug("analyze_scene_for_next_action", ci_calls=ci_calls)
        
        # append call queries and answers to the response
        ci_text = []
        for ci_call in ci_calls:
            ci_text.append(f"{ci_call.arguments['query']}\n{ci_call.result}")
        
        context_investigation="\n\n".join(ci_text if ci_text else [])
        current_context_investigation = self.get_scene_state("context_investigation")
        if current_context_investigation and context_investigation:
            context_investigation = await summarizer.update_context_investigation(
                current_context_investigation, ci_text, response
            )
        
        self.set_scene_states(context_investigation=context_investigation)
        
        return response