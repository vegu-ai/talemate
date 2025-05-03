from typing import TYPE_CHECKING
import structlog
import dataclasses
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig,
    AgentEmission,
    AgentTemplateEmission,
)
from talemate.prompts import Prompt
from talemate.util import strip_partial_sentences
import talemate.emit.async_signals
from talemate.agents.conversation import ConversationAgentEmission
from talemate.agents.narrator import NarratorAgentEmission
from talemate.agents.context import active_agent
from talemate.agents.base import RagBuildSubInstructionEmission

if TYPE_CHECKING:
    from talemate.tale_mate import Character

log = structlog.get_logger()


talemate.emit.async_signals.register(
    "agent.summarization.scene_analysis.before",
    "agent.summarization.scene_analysis.after",
    "agent.summarization.scene_analysis.cached",
    "agent.summarization.scene_analysis.before_deep_analysis",
    "agent.summarization.scene_analysis.after_deep_analysis",   
)

@dataclasses.dataclass
class SceneAnalysisEmission(AgentTemplateEmission):
    analysis_type: str | None = None

@dataclasses.dataclass
class SceneAnalysisDeepAnalysisEmission(AgentEmission):
    analysis: str
    analysis_type: str | None = None
    analysis_sub_type: str | None = None
    max_content_investigations: int = 1
    character: "Character" = None


class SceneAnalyzationMixin:
    
    """
    Summarizer agent mixin that provides functionality for scene analyzation.
    """
    
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["analyze_scene"] = AgentAction(
            enabled=False,
            container=True,
            can_be_disabled=True,
            experimental=True,
            quick_toggle=True,
            label="Scene Analysis",
            icon="mdi-lightbulb",
            description="Analyzes the scene, providing extra understanding and context to the other agents.",
            config={
                "analysis_length": AgentActionConfig(
                    type="text",
                    label="Length of analysis",
                    description="The length of the analysis to be performed.",
                    value="1024",
                    choices=[
                        {"label": "Short (256)", "value": "256"},
                        {"label": "Medium (512)", "value": "512"},
                        {"label": "Long (1024)", "value": "1024"}
                    ]
                ),
                "for_conversation": AgentActionConfig(
                    type="bool",
                    label="Conversation",
                    description="Enable scene analysis for the conversation agent.",
                    value=True,
                ),
                "for_narration": AgentActionConfig(
                    type="bool",
                    label="Narration",
                    description="Enable scene analysis for the narration agent.",
                    value=True,
                ),
                "deep_analysis": AgentActionConfig(
                    type="bool",
                    label="Deep analysis",
                    description="Perform a deep analysis of the scene. This will perform one or more context investigations, based on the initial analysis.",
                    value=False,
                    expensive=True,
                ),
                "deep_analysis_max_context_investigations": AgentActionConfig(
                    type="number",
                    label="Max. context investigations",
                    description="The maximum number of context investigations to perform during deep analysis.",
                    value=1,
                    min=1,
                    max=5,
                    step=1,
                ),
                "cache_analysis": AgentActionConfig(
                    type="bool",
                    label="Cache analysis",
                    description="Cache the analysis results for the scene. This means analysis will not be regenerated when regenerating the actor or narrator's output.",
                    value=True,
                    quick_toggle=True,
                ),
            }
        )
    
    # config property helpers
        
    @property
    def analyze_scene(self) -> bool:
        return self.actions["analyze_scene"].enabled
    
    @property
    def analysis_length(self) -> int:
        return int(self.actions["analyze_scene"].config["analysis_length"].value)
    
    @property
    def cache_analysis(self) -> bool:
        return self.actions["analyze_scene"].config["cache_analysis"].value
    
    @property
    def deep_analysis(self) -> bool:
        return self.actions["analyze_scene"].config["deep_analysis"].value
    
    @property
    def deep_analysis_max_context_investigations(self) -> int:
        return self.actions["analyze_scene"].config["deep_analysis_max_context_investigations"].value
    
    @property
    def analyze_scene_for_conversation(self) -> bool:
        return self.actions["analyze_scene"].config["for_conversation"].value
    
    @property
    def analyze_scene_for_narration(self) -> bool:
        return self.actions["analyze_scene"].config["for_narration"].value
    
    # signal connect
        
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("agent.conversation.inject_instructions").connect(
            self.on_inject_instructions
        )
        talemate.emit.async_signals.get("agent.narrator.inject_instructions").connect(
            self.on_inject_instructions
        )
        talemate.emit.async_signals.get("agent.summarization.rag_build_sub_instruction").connect(
            self.on_rag_build_sub_instruction
        )
        
    async def on_inject_instructions(
        self, 
        emission:ConversationAgentEmission | NarratorAgentEmission,
    ):
        """
        Injects instructions into the conversation.
        """
        
        if isinstance(emission, ConversationAgentEmission):
            emission_type = "conversation"
        elif isinstance(emission, NarratorAgentEmission):
            emission_type = "narration"
        else:
            raise ValueError("Invalid emission type.")
        
        if not self.analyze_scene:
            return
        
        analyze_scene_for_type = getattr(self, f"analyze_scene_for_{emission_type}")
        
        if not analyze_scene_for_type:
            return
        
        analysis = None
        
        # self.set_scene_states and self.get_scene_state to store
        # cached analysis in scene states
        
        if self.cache_analysis:
            analysis = await self.get_cached_analysis(emission_type)
            if analysis:
                await talemate.emit.async_signals.get("agent.summarization.scene_analysis.cached").send(
                    SceneAnalysisEmission(agent=self, analysis_type=emission_type, response=analysis, template_vars={
                        "character": emission.character if hasattr(emission, "character") else None,
                    })
                )
        
        if not analysis and self.analyze_scene:
            # analyze the scene for the next action
            analysis = await self.analyze_scene_for_next_action(
                emission_type,
                emission.character if hasattr(emission, "character") else None,
                self.analysis_length
            )
            
            await self.set_cached_analysis(emission_type, analysis)
            
        if not analysis:
            return
        emission.dynamic_instructions.append("\n".join(
            [
                "<|SECTION:SCENE ANALYSIS|>",
                analysis,
                "<|CLOSE_SECTION|>"
            ]
        ))
    
    async def on_rag_build_sub_instruction(self, emission:"RagBuildSubInstructionEmission"):
        """
        Injects the sub instruction into the analysis.
        """
        sub_instruction = await self.analyze_scene_rag_build_sub_instruction()
        
        if sub_instruction:
            emission.sub_instruction = sub_instruction
    
    # helpers
    
    async def get_cached_analysis(self, typ:str) -> str | None:
        """
        Returns the cached analysis for the given type.
        """
        
        cached_analysis = self.get_scene_state(f"cached_analysis_{typ}")
        
        if not cached_analysis:
            return None
        
        fingerprint = self.context_fingerpint()
        
        if cached_analysis.get("fp") == fingerprint:
            return cached_analysis["guidance"]
        
        return None
    
    async def set_cached_analysis(self, typ:str, analysis:str):
        """
        Sets the cached analysis for the given type.
        """
        
        fingerprint = self.context_fingerpint()
        
        self.set_scene_states(
            **{f"cached_analysis_{typ}": {
                "fp": fingerprint,
                "guidance": analysis,
            }}
        )
        
    async def analyze_scene_sub_type(self, analysis_type:str) -> str:
        """
        Analyzes the active agent context to figure out the appropriate sub type
        """
        
        fn = getattr(self, f"analyze_scene_{analysis_type}_sub_type", None)
        
        if fn:
            return await fn()
        
        return ""
    
    async def analyze_scene_narration_sub_type(self) -> str:
        """
        Analyzes the active agent context to figure out the appropriate sub type
        for narration analysis. (progress, query etc.)
        """
        
        active_agent_context = active_agent.get()
        
        if not active_agent_context:
            return "progress"
        
        state = active_agent_context.state
        
        if state.get("narrator__query_narration"):
            return "query"
        
        if state.get("narrator__sensory_narration"):
            return "sensory"

        if state.get("narrator__visual_narration"):
            if state.get("narrator__character"):
                return "visual-character"
            return "visual"
        
        if state.get("narrator__fn_narrate_character_entry"):
            return "progress-character-entry"
        
        if state.get("narrator__fn_narrate_character_exit"):
            return "progress-character-exit"
        
        return "progress"
        
    async def analyze_scene_rag_build_sub_instruction(self):
        """
        Analyzes the active agent context to figure out the appropriate sub type
        for rag build sub instruction.
        """
        
        active_agent_context = active_agent.get()
        
        if not active_agent_context:
            return ""
        
        state = active_agent_context.state
        
        if state.get("narrator__query_narration"):
            query = state["narrator__query"]
            if query.endswith("?"):
                return "Answer the following question: " + query
            else:
                return query
        
        narrative_direction = state.get("narrator__narrative_direction")
        
        if state.get("narrator__sensory_narration") and narrative_direction:
            return "Collect information that aids in describing the following sensory experience: " + narrative_direction
        
        if state.get("narrator__visual_narration") and narrative_direction:
            return "Collect information that aids in describing the following visual experience: " + narrative_direction
        
        if state.get("narrator__fn_narrate_character_entry") and narrative_direction:
            return "Collect information that aids in describing the following character entry: " + narrative_direction
        
        if state.get("narrator__fn_narrate_character_exit") and narrative_direction:
            return "Collect information that aids in describing the following character exit: " + narrative_direction
        
        if state.get("narrator__fn_narrate_progress"):
            return "Collect information that aids in progressing the story: " + narrative_direction
        
        return ""
        

    # actions

    @set_processing
    async def analyze_scene_for_next_action(self, typ:str, character:"Character"=None, length:int=1024) -> str:
        
        """
        Analyzes the current scene progress and gives a suggestion for the next action.
        taken by the given actor.
        """
        
        # deep analysis is only available if the scene has a layered history
        # and context investigation is enabled
        deep_analysis = (self.deep_analysis and self.context_investigation_available)
        analysis_sub_type = await self.analyze_scene_sub_type(typ)
        
        template_vars = {
            "max_tokens": self.client.max_token_length,
            "scene": self.scene,
            "character": character,
            "length": length,
            "deep_analysis": deep_analysis,
            "context_investigation": self.get_scene_state("context_investigation"),
            "max_content_investigations": self.deep_analysis_max_context_investigations,
            "analysis_type": typ,
            "analysis_sub_type": analysis_sub_type,
        }
        
        await talemate.emit.async_signals.get("agent.summarization.scene_analysis.before").send(
            SceneAnalysisEmission(agent=self, template_vars=template_vars, analysis_type=typ)
        )
        
        response = await Prompt.request(
            f"summarizer.analyze-scene-for-next-{typ}",
            self.client,
            f"investigate_{length}",
            vars=template_vars,
        )
        
        response = strip_partial_sentences(response)
        
        if not response.strip():
            return response
        
        if deep_analysis:
            
            emission = SceneAnalysisDeepAnalysisEmission(
                agent=self, 
                analysis=response,
                analysis_type=typ,
                analysis_sub_type=analysis_sub_type,
                character=character,
                max_content_investigations=self.deep_analysis_max_context_investigations
            )
            
            await talemate.emit.async_signals.get("agent.summarization.scene_analysis.before_deep_analysis").send(
                emission
            )
            
            await talemate.emit.async_signals.get("agent.summarization.scene_analysis.after_deep_analysis").send(
                emission
            )
        
        
        await talemate.emit.async_signals.get("agent.summarization.scene_analysis.after").send(
            SceneAnalysisEmission(agent=self, template_vars=template_vars, response=response, analysis_type=typ)
        )
        
        self.set_context_states(scene_analysis=response)
        self.set_scene_states(scene_analysis=response)
        
        return response