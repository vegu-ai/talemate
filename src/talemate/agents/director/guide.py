from typing import TYPE_CHECKING, Any
import structlog
from functools import wraps
from inspect import signature
from talemate.exceptions import GenerationCancelled
from talemate.knowledge.memory import audience_documents
from talemate.knowledge.perspectives import PerspectiveReadContext
from talemate.knowledge.mode import character_knowledge_enabled
from talemate.knowledge.advice import (
    KnowledgeAnalysisType,
    advice_record_is_current,
    advice_record_metadata,
    advice_character,
    advice_context,
    advice_fingerprint,
    emission_character,
    require_current_advice,
)
from talemate.agents.base import (
    set_processing as _set_processing,
    AgentAction,
    AgentActionConfig,
    AgentTemplateEmission,
    DynamicInstruction,
)
from talemate.agents.context import active_agent
from talemate.prompts import Prompt
import talemate.emit.async_signals
from talemate.util import strip_partial_sentences
from talemate.agents.director.response_specs import GUIDANCE_SPEC

if TYPE_CHECKING:
    from talemate.tale_mate import Character
    from talemate.agents.summarize.analyze_scene import SceneAnalysisEmission

log = structlog.get_logger()

talemate.emit.async_signals.register(
    "agent.director.guide.before_generate",
    "agent.director.guide.inject_instructions",
    "agent.director.guide.generated",
)


class DirectorGuidanceEmission(AgentTemplateEmission):
    pass


def set_processing(*, analysis_type: KnowledgeAnalysisType):
    def decorate(fn):
        """
        Custom decorator that emits the agent status as processing while the function
        is running and then emits the result of the function as a DirectorGuidanceEmission
        """

        @_set_processing
        @wraps(fn)
        async def wrapper(self, *args, **kwargs):
            arguments = signature(fn).bind(self, *args, **kwargs).arguments
            character = advice_character(
                self.scene, arguments.get("character"), typ=analysis_type
            )
            scene = self.scene
            fingerprint = advice_fingerprint(scene, character)
            emission: DirectorGuidanceEmission = DirectorGuidanceEmission(
                agent=self,
                template_vars={"character": character, "analysis_type": analysis_type},
            )

            await talemate.emit.async_signals.get(
                "agent.director.guide.before_generate"
            ).send(emission)
            await talemate.emit.async_signals.get(
                "agent.director.guide.inject_instructions"
            ).send(emission)

            agent_context = active_agent.get()
            agent_context.state["dynamic_instructions"] = emission.dynamic_instructions

            response = await fn(self, *args, **kwargs)
            emission.response = response
            await talemate.emit.async_signals.get(
                "agent.director.guide.generated"
            ).send(emission)
            if character_knowledge_enabled(scene):
                require_current_advice(self, scene, character, fingerprint)
            return emission.response

        return wrapper

    return decorate


class GuideSceneMixin:
    """
    Director agent mixin that provides functionality for automatically guiding
    the actors or the narrator during the scene progression.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["guide_scene"] = AgentAction(
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
                    value=True,
                ),
                "guide_narrator": AgentActionConfig(
                    type="bool",
                    label="Guide narrator",
                    description="Guide the narrator during the scene. This happens during the narrator's turn.",
                    value=True,
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
                    ],
                ),
                "cache_guidance": AgentActionConfig(
                    type="bool",
                    label="Cache guidance",
                    description="Will not regenerate the guidance until the scene moves forward or the analysis changes.",
                    value=False,
                    quick_toggle=True,
                ),
            },
        )

    # config property helpers

    @property
    def guide_scene(self) -> bool:
        return self.resolve_enabled("guide_scene")

    @property
    def guide_actors(self) -> bool:
        return self.resolve_config("guide_scene", "guide_actors")

    @property
    def guide_narrator(self) -> bool:
        return self.resolve_config("guide_scene", "guide_narrator")

    @property
    def guide_scene_guidance_length(self) -> int:
        return int(self.resolve_config("guide_scene", "guidance_length"))

    @property
    def guide_scene_cache_guidance(self) -> bool:
        return self.resolve_config("guide_scene", "cache_guidance")

    # signal connect

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get(
            "agent.summarization.scene_analysis.after"
        ).connect(self.on_summarization_scene_analysis_after)
        talemate.emit.async_signals.get(
            "agent.summarization.scene_analysis.cached"
        ).connect(self.on_summarization_scene_analysis_after)
        talemate.emit.async_signals.get(
            "agent.editor.revision-analysis.before"
        ).connect(self.on_editor_revision_analysis_before)

    async def on_summarization_scene_analysis_after(
        self, emission: "SceneAnalysisEmission"
    ):
        if not self.guide_scene:
            return

        guidance = None

        character = advice_character(
            self.scene,
            emission.template_vars.get("character"),
            typ=emission.analysis_type,
        )
        fingerprint = advice_fingerprint(self.scene, character)
        cached_guidance = await self.get_cached_guidance(
            emission.response, character=character, analysis_type=emission.analysis_type
        )

        if emission.analysis_type == "narration" and self.guide_narrator:
            if cached_guidance:
                guidance = cached_guidance
            else:
                guidance = await self.guide_narrator_off_of_scene_analysis(
                    emission.response,
                    response_length=self.guide_scene_guidance_length,
                )

            if not guidance:
                log.warning("director.guide_scene.narration: Empty resonse")
                return

            self.set_context_states(narrator_guidance=guidance)

        elif emission.analysis_type == "conversation" and self.guide_actors:
            if cached_guidance:
                guidance = cached_guidance
            else:
                guidance = await self.guide_actor_off_of_scene_analysis(
                    emission.response,
                    emission.template_vars.get("character"),
                    response_length=self.guide_scene_guidance_length,
                )

            if not guidance:
                log.warning("director.guide_scene.conversation: Empty resonse")
                return

            self.set_context_states(actor_guidance=guidance)

        if guidance:
            await self.set_cached_guidance(
                emission.response,
                guidance,
                emission.analysis_type,
                character,
                evidence_fp=fingerprint,
            )

    async def on_editor_revision_analysis_before(self, emission: AgentTemplateEmission):
        character = emission_character(self.scene, emission)
        cached_guidance = await self.get_cached_guidance(
            emission.response,
            character=character,
            analysis_type="conversation" if character else "narration",
        )
        if cached_guidance:
            emission.dynamic_instructions.append(
                DynamicInstruction(title="Guidance", content=cached_guidance)
            )

    # helpers

    def _cache_key(self) -> str:
        return "cached_guidance"

    async def get_cached_guidance(
        self,
        analysis: str | None = None,
        *,
        character: "Character | None" = None,
        analysis_type: KnowledgeAnalysisType | None = None,
    ) -> str | None:
        """Return enabled cached guidance.

        Without analysis, legacy mode ignores the generation fingerprint.
        Perception mode always validates audience, type, context and evidence.
        """
        if not self.guide_scene_cache_guidance:
            return None

        key = self._cache_key()
        cached_guidance = self.get_scene_state(key)

        if cached_guidance:
            if character_knowledge_enabled(self.scene):
                if not advice_record_is_current(
                    self, cached_guidance, character, analysis_type
                ):
                    return None
            if not analysis:
                return cached_guidance.get("guidance")
            elif cached_guidance.get("fp") == self.context_fingerprint(
                extra=[analysis]
            ):
                return cached_guidance.get("guidance")

        return None

    async def set_cached_guidance(
        self,
        analysis: str,
        guidance: str,
        analysis_type: KnowledgeAnalysisType,
        character: "Character | None" = None,
        *,
        evidence_fp: str | None = None,
    ):
        """
        Sets the cached guidance for the given analysis.
        """
        key = self._cache_key()
        self.set_scene_states(
            **{
                key: {
                    "fp": self.context_fingerprint(extra=[analysis]),
                    **advice_record_metadata(
                        self, character, analysis_type, evidence_fp=evidence_fp
                    ),
                    "guidance": guidance,
                }
            }
        )

    async def get_cached_character_guidance(self, character_name: str) -> str | None:
        """
        Returns the cached guidance for the given character.
        """
        key = self._cache_key()
        cached_guidance = self.get_scene_state(key)

        if not cached_guidance:
            return None

        if character_knowledge_enabled(self.scene):
            character = advice_character(self.scene, character_name)
            if not advice_record_is_current(
                self, cached_guidance, character, "conversation"
            ):
                return None
        if (
            cached_guidance.get("character") == character_name
            and cached_guidance.get("analysis_type") == "conversation"
        ):
            return cached_guidance.get("guidance")

        return None

    async def guidance_context(
        self, character: "Character | str | None" = None, budget: int = 4096
    ) -> list[dict[str, Any]]:
        """Collect active-cast planning evidence in one synchronous read batch."""
        if not character_knowledge_enabled(self.scene):
            return []
        characters = (
            [advice_character(self.scene, character)]
            if character is not None
            else [
                self.scene.character_data[name]
                for name in self.scene.active_characters
                if name in self.scene.character_data
            ]
        )
        per_character = max(1, budget // max(1, len(characters)))
        result = []
        read = PerspectiveReadContext(self.scene)
        documents = audience_documents(self.scene, groups={("authored",)}, read=read)
        for item in characters:
            try:
                result.append(
                    advice_context(
                        self.scene, item, per_character, read=read, documents=documents
                    )
                )
            except GenerationCancelled:
                if character is not None:
                    raise
                result.append({"character": item.name, "unavailable": True})
        return result

    # methods

    @set_processing(analysis_type="conversation")
    async def guide_actor_off_of_scene_analysis(
        self, analysis: str, character: "Character", response_length: int = 256
    ):
        """
        Guides the actor based on the scene analysis.
        """

        log.debug(
            "director.guide_actor_off_of_scene_analysis",
            analysis=analysis,
            character=character,
        )
        response, extracted = await Prompt.request(
            "director.guide-conversation",
            self.client,
            f"direction_{response_length}",
            vars={
                "analysis": analysis,
                "scene": self.scene,
                "character": character,
                "evidence": advice_context(
                    self.scene, character, self.client.max_token_length // 2
                )
                if character_knowledge_enabled(self.scene)
                else None,
                "response_length": response_length,
                "max_tokens": self.client.max_token_length,
            },
            response_spec=GUIDANCE_SPEC,
        )

        # Use extracted guidance or fall back to full response
        guidance = extracted.get("guidance") or response
        guidance = guidance.strip()

        await self.emit_message(
            "Actor Guidance",
            guidance,
            meta={
                "action": "actor guidance",
                "character": character.name,
            },
        )

        return strip_partial_sentences(guidance).strip()

    @set_processing(analysis_type="narration")
    async def guide_narrator_off_of_scene_analysis(
        self, analysis: str, response_length: int = 256
    ):
        """
        Guides the narrator based on the scene analysis.
        """

        log.debug("director.guide_narrator_off_of_scene_analysis", analysis=analysis)

        character = advice_character(self.scene, typ="narration")
        response, extracted = await Prompt.request(
            "director.guide-narration",
            self.client,
            f"direction_{response_length}",
            vars={
                "analysis": analysis,
                "scene": self.scene,
                "character": character,
                "response_length": response_length,
                "max_tokens": self.client.max_token_length,
            },
            response_spec=GUIDANCE_SPEC,
        )

        # Use extracted guidance or fall back to full response
        guidance = extracted.get("guidance") or response
        guidance = guidance.strip()

        await self.emit_message(
            "Narrator Guidance",
            guidance,
            meta={
                "action": "narrator guidance",
            },
        )

        return strip_partial_sentences(guidance).strip()
