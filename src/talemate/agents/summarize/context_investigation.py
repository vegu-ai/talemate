from typing import TYPE_CHECKING
import structlog
import re
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

from .analyze_scene import SceneAnalysisDeepAnalysisEmission

class ContextInvestigationMixin:
    
    """
    Summarizer agent mixin that provides functionality for context investigation
    through the layered history of the scene.
    """
    
    @classmethod
    def add_actions(cls, summarizer):
        return
        summarizer.actions["context_investigation"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            experimental=True,
            label="Context Investigation",
            icon="mdi-layers-search",
            description="Investigates the layered history to augment the context with additional information.",
            config={
            }
        )
    
    # config property helpers
    
    # signal connect
    
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("agent.conversation.inject_instructions").connect(
            self.on_conversation_inject_context_investigation
        )
        talemate.emit.async_signals.get("agent.summarization.scene_analysis.before_deep_analysis").connect(
            self.on_summarization_scene_analysis_before_deep_analysis
        )
        
    async def on_summarization_scene_analysis_before_deep_analysis(self, emission:SceneAnalysisDeepAnalysisEmission):
        """
        Handles context investigation for deep scene analysis.
        """
        
        response = emission.analysis
                    
        ci_calls:list[focal.Call] = await self.request_context_investigations(response)
        
        log.debug("analyze_scene_for_next_action", ci_calls=ci_calls)
        
        # append call queries and answers to the response
        ci_text = []
        for ci_call in ci_calls:
            ci_text.append(f"{ci_call.arguments['query']}\n{ci_call.result}")
        
        context_investigation="\n\n".join(ci_text if ci_text else [])
        current_context_investigation = self.get_scene_state("context_investigation")
        if current_context_investigation and context_investigation:
            context_investigation = await self.update_context_investigation(
                current_context_investigation, ci_text, response
            )
        
        self.set_scene_states(context_investigation=context_investigation)
            
    
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
    
    # methods
        
    async def _investigate_context(self, chapter_number:str, query:str) -> str:
        # look for \d.\d in the chapter number, extract as layer and index
        match = re.match(r"(\d+)\.(\d+)", chapter_number)
        if not match:
            log.error("summarizer.investigate_context", error="Invalid chapter number", chapter_number=chapter_number)
            return ""
        
        layer = int(match.group(1))
        index = int(match.group(2))
        
        # index comes in 1-based, convert to 0-based
        index -= 1
        
        return await self.investigate_context(layer, index, query)
    
    @set_processing
    async def investigate_context(self, layer:int, index:int, query:str, analysis:str="") -> str:
        """
        Processes a context investigation.
        
        Arguments:
        
        - layer: The layer to investigate
        - index: The index in the layer to investigate
        - query: The query to investigate
        """
        
        log.debug("summarizer.investigate_context", layer=layer, index=index, query=query)
        entry = self.scene.layered_history[layer-1][index]  
        
        if layer == 1:
            entries = self.scene.archived_history[entry["start"]:entry["end"]+1]
        else:
            entries = self.scene.layered_history[layer-2][entry["start"]:entry["end"]+1]    
        
        async def answer(query:str, instructions:str) -> str:
            log.debug("Answering context investigation", query=query, instructions=answer)
            
            world_state = get_agent("world_state")
            
            return await world_state.analyze_history_and_follow_instructions(
                entries,
                f"{query}\n{instructions}",
                analysis=analysis
            )
            
            
        async def abort():
            log.debug("Aborting context investigation")
        
        focal_handler: focal.Focal = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="investigate_context",
                    arguments = [ 
                        focal.Argument(name="chapter_number", type="str"),
                        focal.Argument(name="query", type="str")
                    ],
                    fn=self._investigate_context
                ),
                focal.Callback(
                    name="answer",
                    arguments = [ 
                        focal.Argument(name="instructions", type="str"),
                        focal.Argument(name="query", type="str")
                    ],
                    fn=answer
                ),
                focal.Callback(
                    name="abort",
                    fn=abort
                )
            ],
            max_calls=3,
            scene=self.scene,
            layer=layer,
            index=index,
            query=query,
            entries=entries,
            analysis=analysis,
        )
        
        await focal_handler.request(
            "summarizer.investigate-context",
        )
        
        log.debug("summarizer.investigate_context", calls=focal_handler.state.calls)
        
        return focal_handler.state.calls    

    @set_processing
    async def request_context_investigations(self, analysis:str) -> list[focal.Call]:
        
        """
        Requests context investigations for the given analysis.
        """
        
        async def abort():
            log.debug("Aborting context investigations")
        
        async def investigate_context(chapter_number:str, query:str) -> str:
            # look for \d.\d in the chapter number, extract as layer and index
            match = re.match(r"(\d+)\.(\d+)", chapter_number)
            if not match:
                log.error("summarizer.request_context_investigations.investigate_context", error="Invalid chapter number", chapter_number=chapter_number)
                return ""

            layer = int(match.group(1))
            index = int(match.group(2))
            
            # index comes in 1-based, convert to 0-based
            index -= 1
            
            return await self.investigate_context(layer, index, query, analysis)
        
        focal_handler: focal.Focal = focal.Focal(
            self.client,
            callbacks=[
                focal.Callback(
                    name="investigate_context",
                    arguments = [ 
                        focal.Argument(name="chapter_number", type="str"),
                        focal.Argument(name="query", type="str")
                    ],
                    fn=investigate_context
                ),
                focal.Callback(
                    name="abort",
                    fn=abort
                )
            ],
            scene=self.scene,
            text=analysis
        )
        
        await focal_handler.request(
            "summarizer.request-context-investigation",
        )
        
        log.debug("summarizer.request_context_investigations", calls=focal_handler.state.calls)
        
        return focal.collect_calls(
            focal_handler.state.calls,
            nested=True,
            filter=lambda c: c.name == "answer"
        )
        
        # return focal_handler.state.calls    
    
    @set_processing
    async def update_context_investigation(
        self,
        current_context_investigation:str,
        new_context_investigation:str,
        analysis:str,
    ):
        response = await Prompt.request(
            "summarizer.update-context-investigation",
            self.client,
            "analyze_freeform",
            vars={
                "current_context_investigation": current_context_investigation,
                "new_context_investigation": new_context_investigation,
                "analysis": analysis,
                "scene": self.scene,
                "max_tokens": self.client.max_token_length,
            },
        )
        
        return response.strip()