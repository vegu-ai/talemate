import structlog
import re
from typing import TYPE_CHECKING
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig
)
from talemate.prompts import Prompt
from talemate.instance import get_agent
import talemate.emit.async_signals
from talemate.agents.conversation import ConversationAgentEmission
from talemate.agents.narrator import NarratorAgentEmission
import talemate.game.focal as focal

from .analyze_scene import SceneAnalysisDeepAnalysisEmission

if TYPE_CHECKING:
    from talemate.tale_mate import Character

log = structlog.get_logger()



class ContextInvestigationMixin:
    
    """
    Summarizer agent mixin that provides functionality for context investigation
    through the layered history of the scene.
    """
    
    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["context_investigation"] = AgentAction(
            enabled=False,
            container=True,
            can_be_disabled=True,
            experimental=True,
            quick_toggle=True,
            label="Context Investigation",
            icon="mdi-layers-search",
            description="Investigates the layered history to augment the context with additional information.",
            warning="This can potentially send many extra prompts depending on the depth of the layered history.",
            config={
                "answer_length": AgentActionConfig(
                    type="text",
                    label="Answer Length",
                    description="The maximum length of the answer to return, per investigation.",
                    value="512",
                    choices=[
                        {"label": "Short (256)", "value": "256"},
                        {"label": "Medium (512)", "value": "512"},
                        {"label": "Long (1024)", "value": "1024"},
                    ]
                ),
                "update_method": AgentActionConfig(
                    type="text",
                    label="Update Method",
                    description="The method to use to update exsiting context investigation.",
                    value="replace",
                    choices=[
                        {"label": "Replace", "value": "replace"},
                        {"label": "Smart Merge", "value": "merge"},
                    ]
                )
            }
        )
    
    # config property helpers
    
    @property
    def context_investigation_enabled(self):
        return self.actions["context_investigation"].enabled
    
    @property
    def context_investigation_available(self):
        return (
            self.context_investigation_enabled and
            self.layered_history_available
        )
    
    @property
    def context_investigation_answer_length(self) -> int:
        return int(self.actions["context_investigation"].config["answer_length"].value)
    
    @property
    def context_investigation_update_method(self) -> str:
        return self.actions["context_investigation"].config["update_method"].value
    
    # signal connect
    
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("agent.conversation.inject_instructions").connect(
            self.on_inject_context_investigation
        )
        talemate.emit.async_signals.get("agent.narrator.inject_instructions").connect(
            self.on_inject_context_investigation
        )
        talemate.emit.async_signals.get("agent.director.guide.inject_instructions").connect(
            self.on_inject_context_investigation
        )
        talemate.emit.async_signals.get("agent.summarization.scene_analysis.before_deep_analysis").connect(
            self.on_summarization_scene_analysis_before_deep_analysis
        )
        
    async def on_summarization_scene_analysis_before_deep_analysis(self, emission:SceneAnalysisDeepAnalysisEmission):
        """
        Handles context investigation for deep scene analysis.
        """
        
        if not self.context_investigation_enabled:
            return
        
        suggested_investigations = await self.suggest_context_investigations(
            emission.analysis,
            emission.analysis_type,
            emission.analysis_sub_type,
            max_calls=emission.max_content_investigations,
            character=emission.character,
        )
        
        response = emission.analysis
                    
        ci_calls:list[focal.Call] = await self.request_context_investigations(
            suggested_investigations, 
            max_calls=emission.max_content_investigations
        )
        
        log.debug("analyze_scene_for_next_action", ci_calls=ci_calls)
        
        # append call queries and answers to the response
        ci_text = []
        for ci_call in ci_calls:
            try:
                ci_text.append(f"{ci_call.arguments['query']}\n{ci_call.result}")
            except KeyError as e:
                log.error("analyze_scene_for_next_action", error="Missing key in call", ci_call=ci_call)
        
        context_investigation="\n\n".join(ci_text if ci_text else [])
        current_context_investigation = self.get_scene_state("context_investigation")
        if current_context_investigation and context_investigation:
            if self.context_investigation_update_method == "merge":
                context_investigation = await self.update_context_investigation(
                    current_context_investigation, context_investigation, response
                )
        
        self.set_scene_states(context_investigation=context_investigation)
        self.set_context_states(context_investigation=context_investigation)
        
            
    
    async def on_inject_context_investigation(self, emission:ConversationAgentEmission | NarratorAgentEmission):
        """
        Injects context investigation into the conversation.
        """
        
        if not self.context_investigation_enabled:
            return
        
        context_investigation = self.get_scene_state("context_investigation")
        log.debug("summarizer.on_inject_context_investigation", context_investigation=context_investigation, emission=emission)
        if context_investigation:
            emission.dynamic_instructions.append("\n".join(
                [
                    "<|SECTION:CONTEXT INVESTIGATION|>",
                    context_investigation,
                    "<|CLOSE_SECTION|>"
                ]
            ))
    
    # methods
    
    @set_processing
    async def suggest_context_investigations(
        self,
        analysis:str,
        analysis_type:str,
        analysis_sub_type:str="",
        max_calls:int=3,
        character:"Character"=None,
    ) -> str:
        
        template_vars = {
            "max_tokens": self.client.max_token_length,
            "scene": self.scene,
            "character": character,
            "response_length": 512,
            "context_investigation": self.get_scene_state("context_investigation"),
            "max_content_investigations": max_calls,
            "analysis": analysis,
            "analysis_type": analysis_type,
            "analysis_sub_type": analysis_sub_type,
        }
        
        if not analysis_sub_type:
            template = f"summarizer.suggest-context-investigations-for-{analysis_type}"
        else:
            template = f"summarizer.suggest-context-investigations-for-{analysis_type}-{analysis_sub_type}"
        
        log.debug("summarizer.suggest_context_investigations", template=template, template_vars=template_vars)
        
        response = await Prompt.request(
            template,
            self.client,
            "investigate_512",
            vars=template_vars,
        )
        
        return response.strip()
        

    @set_processing
    async def investigate_context(
        self, 
        layer:int, 
        index:int, 
        query:str, 
        analysis:str="", 
        max_calls:int=3,
        pad_entries:int=5,
    ) -> str:
        """
        Processes a context investigation.
        
        Arguments:
        
        - layer: The layer to investigate
        - index: The index in the layer to investigate
        - query: The query to investigate
        - analysis: Scene analysis text
        - pad_entries: if > 0 will pad the entries with the given number of entries before and after the start and end index
        """
        
        log.debug("summarizer.investigate_context", layer=layer, index=index, query=query)
        entry = self.scene.layered_history[layer][index]
        
        layer_to_investigate = layer - 1
        
        start = max(entry["start"] - pad_entries, 0)
        end = entry["end"] + pad_entries + 1
        
        if layer_to_investigate == -1:
            entries = self.scene.archived_history[start:end]
        else:
            entries = self.scene.layered_history[layer_to_investigate][start:end]
            
        async def answer(query:str, instructions:str) -> str:
            log.debug("Answering context investigation", query=query, instructions=answer)
            
            world_state = get_agent("world_state")
            
            return await world_state.analyze_history_and_follow_instructions(
                entries,
                f"{query}\n{instructions}",
                analysis=analysis,
                response_length=self.context_investigation_answer_length
            )
            

        async def investigate_context(chapter_number:str, query:str) -> str:
            # look for \d.\d in the chapter number, extract as layer and index
            match = re.match(r"(\d+)\.(\d+)", chapter_number)
            if not match:
                log.error("summarizer.investigate_context", error="Invalid chapter number", chapter_number=chapter_number)
                return ""
            
            layer = int(match.group(1))
            index = int(match.group(2))
            
            return await self.investigate_context(layer-1, index-1, query, analysis=analysis, max_calls=max_calls)
        

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
                    fn=investigate_context
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
            max_calls=max_calls,
            scene=self.scene,
            layer=layer_to_investigate + 1,
            layer_to_investigate=layer_to_investigate,
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
    async def request_context_investigations(
        self, 
        analysis:str,
        max_calls:int=3,
    ) -> list[focal.Call]:
        
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
            
            num_layers = len(self.scene.layered_history)
            
            return await self.investigate_context(num_layers - layer, index-1, query, analysis, max_calls=max_calls)
        
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
            max_calls=max_calls,
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