from typing import TYPE_CHECKING
from types import EllipsisType
import structlog
import pydantic
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig,
    AgentEmission,
    AgentTemplateEmission,
    DynamicInstruction,
)
from talemate.prompts import Prompt
from talemate.knowledge.processing import wait_for_evidence_writers
from talemate.prompts.response import ResponseSpec, AnchorExtractor
from talemate.util import strip_partial_sentences
import talemate.emit.async_signals
from talemate.agents.conversation import ConversationAgentEmission
from talemate.agents.narrator import NarratorAgentEmission
from talemate.agents.context import active_agent
from talemate.agents.base import RagBuildSubInstructionEmission
from contextvars import ContextVar
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.standard_analysis import (
    standard_analysis_context,
    standard_analysis_enabled,
    standard_analysis_fingerprint,
)
from talemate.knowledge.advice import (
    KnowledgeAnalysisType,
    advice_record_is_current,
    advice_record_metadata,
    advice_character,
    advice_context,
    advice_fingerprint,
    deep_analysis_fingerprint,
    StaleAdvice,
    emission_character,
    emission_analysis_type,
    require_current_advice,
)

if TYPE_CHECKING:
    from talemate.tale_mate import Character

log = structlog.get_logger()

## CONTEXT

scene_analysis_disabled_context = ContextVar("scene_analysis_disabled", default=False)


class SceneAnalysisDisabled:
    """
    Context manager to disable scene analysis during specific agent actions.
    """

    def __enter__(self):
        self.token = scene_analysis_disabled_context.set(True)

    def __exit__(self, _exc_type, _exc_value, _traceback):
        scene_analysis_disabled_context.reset(self.token)


talemate.emit.async_signals.register(
    "agent.summarization.scene_analysis.before",
    "agent.summarization.scene_analysis.after",
    "agent.summarization.scene_analysis.cached",
    "agent.summarization.scene_analysis.before_deep_analysis",
    "agent.summarization.scene_analysis.after_deep_analysis",
)


SCENE_ANALYSIS_SPEC = ResponseSpec(
    extractors={
        "analysis": AnchorExtractor(left="<ANALYSIS>", right="</ANALYSIS>"),
        "investigate": AnchorExtractor(left="<INVESTIGATE>", right="</INVESTIGATE>"),
    },
    required=["analysis"],
)


class SceneAnalysisEmission(AgentTemplateEmission):
    analysis_type: str | None = None


class SceneAnalysisDeepAnalysisEmission(AgentEmission):
    analysis: str = ""
    analysis_type: str | None = None
    analysis_sub_type: str | None = None
    max_content_investigations: int = 0  # backwards compat, will be dropped
    character: "Character | None" = None
    investigate: str = ""
    deep_analysis_context: str = ""
    dynamic_instructions: list[DynamicInstruction] = pydantic.Field(
        default_factory=list
    )


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
                        {"label": "Long (1024)", "value": "1024"},
                    ],
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
                    description="Performs targeted memory retrieval based on the initial analysis, surfacing additional relevant context for other agents.",
                    value=False,
                ),
                "cache_analysis": AgentActionConfig(
                    type="bool",
                    label="Cache analysis",
                    description="Cache the analysis results for the scene. This means analysis will not be regenerated when regenerating the actor or narrator's output.",
                    value=True,
                    quick_toggle=True,
                ),
            },
        )

    # config property helpers

    @property
    def analyze_scene(self) -> bool:
        return self.resolve_enabled("analyze_scene")

    @property
    def analysis_length(self) -> int:
        return int(self.resolve_config("analyze_scene", "analysis_length"))

    @property
    def cache_analysis(self) -> bool:
        return self.resolve_config("analyze_scene", "cache_analysis")

    @property
    def deep_analysis(self) -> bool:
        return self.resolve_config("analyze_scene", "deep_analysis")

    @property
    def analyze_scene_for_conversation(self) -> bool:
        return self.resolve_config("analyze_scene", "for_conversation")

    @property
    def analyze_scene_for_narration(self) -> bool:
        return self.resolve_config("analyze_scene", "for_narration")

    # signal connect

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get(
            "agent.conversation.inject_instructions"
        ).connect(self.on_inject_instructions)
        talemate.emit.async_signals.get("agent.narrator.inject_instructions").connect(
            self.on_inject_instructions
        )
        talemate.emit.async_signals.get(
            "agent.director.guide.inject_instructions"
        ).connect(self.on_inject_deep_analysis_context)
        talemate.emit.async_signals.get(
            "agent.summarization.rag_build_sub_instruction"
        ).connect(self.on_rag_build_sub_instruction)
        talemate.emit.async_signals.get(
            "agent.editor.revision-analysis.before"
        ).connect(self.on_editor_revision_analysis_before)

    async def on_inject_instructions(
        self,
        emission: ConversationAgentEmission | NarratorAgentEmission,
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

        try:
            if scene_analysis_disabled_context.get():
                log.debug(
                    "on_inject_instructions: scene analysis disabled through context",
                    emission=emission,
                )
                return
        except LookupError:
            pass

        analyze_scene_for_type = getattr(self, f"analyze_scene_for_{emission_type}")

        if not analyze_scene_for_type:
            return

        scene = self.scene
        await wait_for_evidence_writers(scene, agent=self)
        character = emission_character(scene, emission)
        boundary, evidence_budget = self._analysis_evidence_key(
            scene, character, emission_type
        )
        fingerprint = advice_fingerprint(
            scene,
            character,
            boundary=boundary,
            budget=evidence_budget,
        )
        standard_fp = standard_analysis_fingerprint(
            scene, character, emission_type, self._analysis_evidence_budget
        )
        analysis = None

        # self.set_scene_states and self.get_scene_state to store
        # cached analysis in scene states

        if self.cache_analysis:
            analysis = await self.get_cached_analysis(
                emission_type,
                character,
                evidence_key=(boundary, evidence_budget, fingerprint),
            )
            if analysis:
                cached = self.get_scene_state(f"cached_analysis_{emission_type}") or {}
                deep = cached.get("deep_analysis") or {}
                if (
                    self.deep_analysis
                    and self.long_term_memory_enabled
                    and deep.get("pending")
                ):
                    await self._complete_deep_analysis(
                        scene,
                        emission_type,
                        character,
                        analysis,
                        cached,
                        emission.dynamic_instructions,
                        (boundary, evidence_budget, fingerprint),
                    )
                await talemate.emit.async_signals.get(
                    "agent.summarization.scene_analysis.cached"
                ).send(
                    SceneAnalysisEmission(
                        agent=self,
                        analysis_type=emission_type,
                        response=analysis,
                        template_vars={
                            "character": character,
                            "analysis_type": emission_type,
                        },
                        dynamic_instructions=emission.dynamic_instructions,
                    )
                )

        if not analysis and self.analyze_scene:
            # analyze the scene for the next action
            analysis = await self.analyze_scene_for_next_action(
                emission_type,
                character,
                self.analysis_length,
                evidence_key=(boundary, evidence_budget, fingerprint),
                standard_fp=standard_fp,
            )

        if not analysis:
            return
        if character_knowledge_enabled(scene):
            require_current_advice(
                self,
                scene,
                character,
                fingerprint,
                boundary=boundary,
                budget=evidence_budget,
            )
        emission.dynamic_instructions.append(
            DynamicInstruction(title="Scene Analysis", content=analysis)
        )

        self._inject_deep_analysis_context(
            emission, evidence_key=(boundary, evidence_budget, fingerprint)
        )

    async def on_inject_deep_analysis_context(self, emission):
        """
        Injects deep analysis context into the director.
        """
        self._inject_deep_analysis_context(emission)

    def _inject_deep_analysis_context(self, emission, *, evidence_key=None):
        """
        Injects deep analysis context into the emission if available.
        """
        if not self.deep_analysis:
            return

        deep_analysis_context = self.get_scene_state("deep_analysis_context")
        if not deep_analysis_context:
            return
        if character_knowledge_enabled(self.scene):
            character = emission_character(self.scene, emission)
            record = self.get_scene_state("deep_analysis_evidence") or {}
            typ = emission_analysis_type(emission, character)
            if not self._analysis_record_is_current(
                record, character, typ, evidence_key
            ):
                return
            if record.get("retrieval_fp") != deep_analysis_fingerprint(
                self.scene, character, record.get("evidence_boundary")
            ):
                return
        emission.dynamic_instructions.append(
            DynamicInstruction(
                title="Deep Analysis Context", content=deep_analysis_context
            )
        )

    async def on_rag_build_sub_instruction(
        self, emission: "RagBuildSubInstructionEmission"
    ):
        """
        Injects the sub instruction into the analysis.
        """
        sub_instruction = await self.analyze_scene_rag_build_sub_instruction()

        if sub_instruction:
            emission.sub_instruction = sub_instruction

    async def on_editor_revision_analysis_before(self, emission: AgentTemplateEmission):
        if character_knowledge_enabled(self.scene):
            character = emission_character(self.scene, emission)
            last_analysis = await self.get_cached_analysis(
                "conversation" if character else "narration", character
            )
        else:
            last_analysis = self.get_scene_state("scene_analysis")
        if last_analysis:
            emission.dynamic_instructions.append(
                DynamicInstruction(title="Scene Analysis", content=last_analysis)
            )

    # helpers

    @property
    def _analysis_evidence_budget(self):
        return self.client.max_token_length // 2

    def _analysis_evidence_key(self, scene, character, typ):
        boundary = (
            [message.id for message in scene.history]
            if character_knowledge_enabled(scene)
            and character is not None
            and typ == "conversation"
            else None
        )
        return boundary, self._analysis_evidence_budget

    def _analysis_record_is_current(self, record, character, typ, evidence_key=None):
        # Share an already computed fingerprint only for an identical key in this
        # synchronous step. Never memoize across awaits or scene mutations.
        fingerprint = ...
        if evidence_key is not None:
            boundary, budget, computed = evidence_key
            if (record.get("evidence_boundary"), record.get("evidence_budget")) == (
                boundary,
                budget,
            ):
                fingerprint = computed
        return advice_record_is_current(
            self, record, character, typ, evidence_fp=fingerprint
        )

    async def get_cached_analysis(
        self,
        typ: KnowledgeAnalysisType,
        character: "Character | None" = None,
        *,
        evidence_key=None,
    ) -> str | None:
        """
        Returns the cached analysis for the given type.
        """

        cached_analysis = self.get_scene_state(f"cached_analysis_{typ}")

        if not cached_analysis:
            return None

        if (
            cached_analysis.get("evidence_boundary") is not None
            and cached_analysis.get("evidence_budget") != self._analysis_evidence_budget
        ):
            return None

        if cached_analysis.get(
            "standard_knowledge_fp"
        ) != standard_analysis_fingerprint(
            self.scene, character, typ, self._analysis_evidence_budget
        ):
            return None

        if character_knowledge_enabled(self.scene):
            character = advice_character(self.scene, character, typ=typ)
            if not self._analysis_record_is_current(
                cached_analysis, character, typ, evidence_key
            ):
                return None
        fingerprint = self.context_fingerprint()

        log.debug(
            "get_cached_analysis",
            fingerprint=fingerprint,
            cached_analysis_fp=cached_analysis.get("fp"),
            match=cached_analysis.get("fp") == fingerprint,
        )

        if cached_analysis.get("fp") == fingerprint:
            return cached_analysis["guidance"]

        return None

    async def set_cached_analysis(
        self,
        typ: KnowledgeAnalysisType,
        analysis: str,
        character: "Character | None" = None,
        *,
        evidence_fp: str | None = None,
        standard_fp: str | None | EllipsisType = ...,
        boundary: list[int] | None = None,
        evidence_budget: int | None = None,
    ):
        """
        Sets the cached analysis for the given type.
        """

        fingerprint = self.context_fingerprint()
        if evidence_budget is None:
            current_boundary, evidence_budget = self._analysis_evidence_key(
                self.scene, character, typ
            )
            if boundary is None:
                boundary = current_boundary
        # Preserve a captured disabled-state fingerprint if settings change mid-request.
        if standard_fp is ...:
            standard_fp = standard_analysis_fingerprint(
                self.scene, character, typ, self._analysis_evidence_budget
            )

        self.set_scene_states(
            **{
                f"cached_analysis_{typ}": {
                    "fp": fingerprint,
                    "guidance": analysis,
                    "standard_knowledge_fp": standard_fp,
                    **advice_record_metadata(
                        self,
                        character,
                        typ,
                        evidence_fp=evidence_fp,
                        boundary=boundary,
                        budget=evidence_budget,
                    ),
                }
            }
        )

    async def analyze_scene_sub_type(self, analysis_type: str) -> str:
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
            return (
                "Collect information that aids in describing the following sensory experience: "
                + narrative_direction
            )

        if state.get("narrator__visual_narration") and narrative_direction:
            return (
                "Collect information that aids in describing the following visual experience: "
                + narrative_direction
            )

        if state.get("narrator__fn_narrate_character_entry") and narrative_direction:
            return (
                "Collect information that aids in describing the following character entry: "
                + narrative_direction
            )

        if state.get("narrator__fn_narrate_character_exit") and narrative_direction:
            return (
                "Collect information that aids in describing the following character exit: "
                + narrative_direction
            )

        if state.get("narrator__fn_narrate_progress"):
            return (
                "Collect information that aids in progressing the story: "
                + narrative_direction
            )

        return ""

    # actions

    async def _complete_deep_analysis(
        self, scene, typ, character, result, cached, dynamic_instructions, evidence_key
    ):
        boundary, evidence_budget, fingerprint = evidence_key
        scoped = boundary is not None
        deep = cached["deep_analysis"]
        investigate = deep["investigate"]
        deep_context = ""
        retrieval_fp = None

        if investigate:
            deep_emission = SceneAnalysisDeepAnalysisEmission(
                agent=self,
                analysis=result,
                analysis_type=typ,
                analysis_sub_type=deep["analysis_sub_type"],
                character=character,
                investigate=investigate,
                dynamic_instructions=dynamic_instructions,
            )

            await talemate.emit.async_signals.get(
                "agent.summarization.scene_analysis.before_deep_analysis"
            ).send(deep_emission)

            rag_options = dict(
                sub_instruction=investigate,
                retrieval_method="questions",
                include_raw_semantic=False,
            )
            if character_knowledge_enabled(scene):
                retrieval_fp = deep_analysis_fingerprint(scene, character, boundary)
            if scoped:
                rag_results = await self.rag_build(character=character, **rag_options)
            else:
                rag_results = await self.rag_build_for_author(
                    prompt=result, **rag_options
                )

            if rag_results:
                deep_analysis_context = "\n---\n".join(str(r) for r in rag_results)
                deep_emission.deep_analysis_context = deep_analysis_context
                deep_context = deep_analysis_context

            await talemate.emit.async_signals.get(
                "agent.summarization.scene_analysis.after_deep_analysis"
            ).send(deep_emission)

        if character_knowledge_enabled(scene):
            require_current_advice(
                self,
                scene,
                character,
                fingerprint,
                boundary=boundary,
                budget=evidence_budget,
            )
            if deep_context and retrieval_fp != deep_analysis_fingerprint(
                scene, character, boundary
            ):
                raise StaleAdvice(
                    "Deep analysis sources changed during retrieval; retry"
                )
            self.set_scene_states(
                deep_analysis_context=deep_context,
                deep_analysis_evidence={
                    **advice_record_metadata(
                        self,
                        character,
                        typ,
                        evidence_fp=fingerprint,
                        boundary=boundary,
                        budget=evidence_budget,
                    ),
                    "retrieval_fp": retrieval_fp,
                },
            )

        else:
            self.set_scene_states(deep_analysis_context=deep_context)
            self.set_context_states(deep_analysis_context=deep_context)
        deep["pending"] = False

    @set_processing
    async def analyze_scene_for_next_action(
        self,
        typ: KnowledgeAnalysisType,
        character: "Character | None" = None,
        length: int = 1024,
        *,
        evidence_key=None,
        standard_fp: str | None | EllipsisType = ...,
    ) -> str:
        """
        Analyzes the current scene progress and gives a suggestion for the next action.
        taken by the given actor.
        """

        scene = self.scene
        if evidence_key is None:
            await wait_for_evidence_writers(scene, agent=self)
        character = advice_character(scene, character, typ=typ)
        if evidence_key is None:
            boundary, evidence_budget = self._analysis_evidence_key(
                scene, character, typ
            )
            fingerprint = advice_fingerprint(
                scene, character, boundary=boundary, budget=evidence_budget
            )
        else:
            boundary, evidence_budget, fingerprint = evidence_key
        if standard_fp is ...:
            standard_fp = standard_analysis_fingerprint(
                scene, character, typ, self._analysis_evidence_budget
            )
        scoped = boundary is not None
        deep_analysis = self.deep_analysis and self.long_term_memory_enabled
        analysis_sub_type = await self.analyze_scene_sub_type(typ)

        template_vars = {
            "max_tokens": self.client.max_token_length,
            "scene": self.scene,
            "character": character,
            "standard_knowledge": await standard_analysis_context(
                scene, character, self._analysis_evidence_budget
            )
            if standard_analysis_enabled(scene, character, typ)
            else None,
            "evidence": advice_context(scene, character, self._analysis_evidence_budget)
            if scoped
            else None,
            "length": length,
            "deep_analysis": deep_analysis,
            "analysis_type": typ,
            "analysis_sub_type": analysis_sub_type,
        }

        emission = SceneAnalysisEmission(
            agent=self, template_vars=template_vars, analysis_type=typ
        )

        await talemate.emit.async_signals.get(
            "agent.summarization.scene_analysis.before"
        ).send(emission)

        template_vars["dynamic_instructions"] = emission.dynamic_instructions

        response, extracted = await Prompt.request(
            f"summarizer.analyze-scene-for-next-{typ}",
            self.client,
            f"investigate_{length}",
            vars=template_vars,
            response_spec=SCENE_ANALYSIS_SPEC,
        )

        result = extracted.get("analysis") or response
        result = strip_partial_sentences(result)

        if not result.strip():
            return result

        if character_knowledge_enabled(scene):
            require_current_advice(
                self,
                scene,
                character,
                fingerprint,
                boundary=boundary,
                budget=evidence_budget,
            )
        await self.set_cached_analysis(
            typ,
            result,
            character,
            evidence_fp=fingerprint,
            standard_fp=standard_fp,
            boundary=boundary,
            evidence_budget=evidence_budget,
        )
        self.set_scene_states(deep_analysis_context="", deep_analysis_evidence={})
        cached = self.get_scene_state(f"cached_analysis_{typ}")
        cached["deep_analysis"] = {
            "investigate": (extracted.get("investigate") or "").strip()
            if deep_analysis
            else "",
            "analysis_sub_type": analysis_sub_type,
            "pending": True,
        }
        await self._complete_deep_analysis(
            scene,
            typ,
            character,
            result,
            cached,
            emission.dynamic_instructions,
            (boundary, evidence_budget, fingerprint),
        )

        await talemate.emit.async_signals.get(
            "agent.summarization.scene_analysis.after"
        ).send(
            SceneAnalysisEmission(
                agent=self,
                template_vars=template_vars,
                response=result,
                analysis_type=typ,
                dynamic_instructions=emission.dynamic_instructions,
            )
        )

        if character_knowledge_enabled(scene):
            require_current_advice(
                self,
                scene,
                character,
                fingerprint,
                boundary=boundary,
                budget=evidence_budget,
            )
        self.set_context_states(scene_analysis=result)
        self.set_scene_states(scene_analysis=result)

        await self.emit_message(
            "Scene Analysis",
            result,
            meta={
                "action": "scene analysis",
            },
        )

        return result
