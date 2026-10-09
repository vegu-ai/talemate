import hashlib
import json
import re
from typing import TYPE_CHECKING

import structlog

from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
    set_processing,
)
from talemate.agents.context import active_agent
from talemate.agents.conversation.response_specs import MEMORY_PASS_SPEC
from talemate.agents.memory.rag import context_history_message_ids
from talemate.agents.memory.schema import MemoryDocument
from talemate.client import presets
from talemate.instance import get_agent
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.mode import (
    character_knowledge_enabled as perception_mode_enabled,
)
from talemate.memory_pass import MemoryPassResult, memory_pass_item
from talemate.prompts import Prompt

if TYPE_CHECKING:
    from talemate.tale_mate import Character

__all__ = [
    "CharacterKnowledgeMixin",
    "pass_items",
]

log = structlog.get_logger("talemate.agents.conversation.knowledge")


def pass_items(blocks: list[dict] | None) -> list[tuple[int, str]]:
    """`(candidate number, rewritten text)` per `<ITEM n="...">` block, in answer order; the first block for a number wins."""
    items: list[tuple[int, str]] = []
    seen: set[int] = set()
    for block in blocks or []:
        number = int(block["n"])
        if number in seen:
            continue
        seen.add(number)
        items.append((number, (block.get("content") or "").strip()))
    return items


class CharacterKnowledgeMixin:
    """
    What the speaking character knows, applied to the conversation prompt.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["character_knowledge"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=True,
            icon="mdi-head-lightbulb-outline",
            label="Character Knowledge",
            description="Help characters respond using what they know. In Standard mode, limit history and memories to their own experience. Choose Character perspectives when creating a story for separate character views of events. Refine memories with AI works in either mode.",
            config={
                "perspective_filter": AgentActionConfig(
                    type="bool",
                    label="Limit to character knowledge",
                    description="Leave out events the character missed and memories they do not know. Turn on to base replies on their own experience; turn off to use the shared history and memories.",
                    value=True,
                ),
                "memory_pass": AgentActionConfig(
                    type="bool",
                    label="Refine memories with AI",
                    description="Ask the AI to rewrite and select retrieved memories for the next character reply. Turn on when memories need a more relevant focus. With Limit to character knowledge on, the AI also rewrites memories from the character's point of view and drops what they do not know.",
                    value=False,
                    note_on_value={
                        True: AgentActionNote(
                            color="primary",
                            text="One more request before each generated character reply that has retrieved memories, using the World State agent's client.",
                        ),
                    },
                ),
            },
        )

    @property
    def sanitized_action_config(self):
        config = super().sanitized_action_config
        if (
            perception_mode_enabled(getattr(self, "scene", None))
            and "character_knowledge" in config
        ):
            action = config["character_knowledge"]
            action["description"] = (
                "Character perspectives is active: characters receive their own views of events and the memories available to them. Turn on Refine memories with AI below to give retrieved memories a more relevant focus."
            )
            action["config"] = {
                key: value
                for key, value in action["config"].items()
                if key in ("memory_pass",)
            }
        return config

    @property
    def character_knowledge_enabled(self) -> bool:
        return self.resolve_enabled("character_knowledge")

    @property
    def knowledge_perspective_filter(self) -> bool:
        return self.character_knowledge_enabled and self.resolve_config(
            "character_knowledge", "perspective_filter"
        )

    @property
    def knowledge_memory_pass(self) -> bool:
        return self.character_knowledge_enabled and bool(
            self.resolve_config("character_knowledge", "memory_pass")
        )

    def clear_memory_pass_record(self):
        self.set_context_states(memory_pass=None)

    def take_memory_pass_record(self) -> MemoryPassResult | None:
        result = self.get_context_state("memory_pass")
        self.set_context_states(memory_pass=None)
        return result

    def _record_memory_pass(self, result: MemoryPassResult):
        self.set_context_states(memory_pass=result)

    async def rag_exclude_context_history(
        self, context: list[str], context_history: list[str]
    ) -> list[str]:
        # the reply's prompt leaves out the views of messages its history
        # already shows; the record must not list them as kept
        result = self.get_context_state("memory_pass")
        if result is not None:
            self._record_memory_pass(
                result.without_messages(context_history_message_ids(context_history))
            )
        return await super().rag_exclude_context_history(context, context_history)

    @property
    def knowledge_analysis_client(self):
        """The client the opt-in requests use (the World State agent's)."""
        return get_agent("world_state").client

    def rag_knowledge_viewer(self, character: "Character | None") -> str | None:
        """
        Perception scenes always use the character's audience. Legacy scenes
        retain the perspective-filter switch; author calls have no viewer.
        """
        if character is not None and perception_mode_enabled(self.scene):
            return character.name
        if character is None or not self.knowledge_perspective_filter:
            return None
        return character.name

    async def knowledge_perspective(self, character: "Character | None") -> str | None:
        """Select the history viewer independently of legacy retrieval filtering."""
        if character is not None and perception_mode_enabled(self.scene):
            return character.name
        return self.rag_knowledge_viewer(character)

    async def history_context(
        self,
        character,
        budget,
        *,
        keep_director=None,
        preview=False,
        diagnostics=None,
    ):
        # Summarizer imports its websocket handler, which imports knowledge.review.
        from talemate.agents.summarize.context_history import ContextHistoryParams

        if keep_director is None:
            if perception_mode_enabled(self.scene):
                guidance = await get_agent("director").get_cached_character_guidance(
                    character.name
                )
            else:
                context = active_agent.get()
                guidance = (
                    context.state.get("director__actor_guidance") if context else None
                )
            keep_director = False if guidance else character.name
        params = ContextHistoryParams(
            stored_views=True,
            perspective=await self.knowledge_perspective(character),
            keep_director=keep_director,
        )
        if preview:
            params._diagnostics = diagnostics
            return get_agent("summarizer").context_history_preview(
                self.scene, budget=budget, params=params
            )
        return self.scene.context_history(budget=budget, **params.model_dump())

    async def rag_process_context(self, character, context):
        if character is None or not context or not self.knowledge_memory_pass:
            return context
        return await self.memory_pass(character, context)

    @set_processing
    async def memory_pass(
        self, character: "Character", candidates: list[str]
    ) -> list[str]:
        """One request that rewrites, drops and orders the retrieved memories for the next character message."""
        candidates = list(candidates)
        client = self.knowledge_analysis_client
        viewer = self.rag_knowledge_viewer(character)
        # the dialogue prompt keeps the speaker's director messages unless
        # director guidance replaces them
        context = active_agent.get()
        guidance = context.state.get("director__actor_guidance") if context else None
        scoped = viewer is not None and perception_mode_enabled(self.scene)
        scene_history = (
            self.rag_projected_history(
                viewer,
                budget=int(client.max_token_length * 0.5),
                keep_director=False if guidance else character.name,
            )
            if scoped
            else self.scene.context_history(
                budget=int(client.max_token_length * 0.5),
                min_dialogue=15,
                sections=False,
                keep_director=False if guidance else character.name,
                perspective=viewer,
            )
        )
        memory_character_context = (
            await get_agent("memory").audience_character_context(
                viewer, [character.name]
            )
            if scoped
            else ""
        )
        prompt_vars = {
            "scene": self.scene,
            "max_tokens": client.max_token_length,
            "character": character,
            "viewer": viewer,
            "candidates": candidates,
            "scene_history": scene_history,
            "knowledge_index": KnowledgeIndex.from_scene(self.scene),
            "character_retrieval": scoped,
            "memory_character_context": memory_character_context,
        }
        rendered = Prompt.get(
            "conversation.memory-pass",
            {**prompt_vars, "decensor": client.decensor_enabled},
        ).render()
        client_config = getattr(client, "client_config", None)
        client_settings = (
            client_config.model_dump(exclude={"api_key"})
            if client_config is not None
            else {}
        )
        inference_settings = presets.configure(
            {}, "analyze_long", client.max_token_length, client
        )
        cache_key = hashlib.sha256(
            json.dumps(
                (
                    rendered,
                    getattr(client, "name", None),
                    getattr(client, "model_name", None),
                    client.max_token_length,
                    client_settings,
                    inference_settings,
                ),
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        rag_cache = (
            self.rag_cache_entry(character) if self.long_term_memory_cache else None
        )
        processed = rag_cache.get("processed", {}) if rag_cache is not None else {}
        if cache_key in processed:
            log.debug("Using cached memory pass", character=character.name)
            passed, result = processed[cache_key]
            self._record_memory_pass(result)
            return list(passed)

        _, extracted = await Prompt.request(
            "conversation.memory-pass",
            client,
            "analyze_long",
            vars=prompt_vars,
            response_spec=MEMORY_PASS_SPEC,
        )
        items = pass_items(extracted.get("items"))
        answer = (extracted.get("answer") or "").strip()
        # an answer that names an item but yields no readable block is
        # unreadable, not none
        if (
            not items
            and "<ITEM" not in answer.upper()
            and re.match(r"^none\b", answer, re.IGNORECASE)
        ):
            log.debug("memory pass: none", character=character.name)
            result = MemoryPassResult(
                status="none",
                candidates=len(candidates),
                dropped=[memory_pass_item(candidate) for candidate in candidates],
            )
            self._record_memory_pass(result)
            current_cache = (
                self.rag_cache_entry(character) if self.long_term_memory_cache else None
            )
            if current_cache is rag_cache and current_cache is not None:
                current_cache.setdefault("processed", {})[cache_key] = ([], result)
            return []
        # the number alone says keep and where
        passed = []
        kept = {}
        for number, text in items:
            if not 1 <= number <= len(candidates):
                continue
            candidate = candidates[number - 1]
            kept[number] = memory_pass_item(candidate, text)
            if text and isinstance(candidate, MemoryDocument):
                passed.append(
                    MemoryDocument(
                        text,
                        candidate.meta,
                        candidate.id,
                        candidate.raw,
                        distance=candidate.distance,
                        embedding=candidate.embedding,
                    )
                )
            else:
                passed.append(text or candidate)
        if not passed:
            log.warning(
                "memory pass: answer not readable, keeping the candidates as retrieved",
                character=character.name,
                answer=answer,
                items=items,
            )
            passed = candidates
            result = MemoryPassResult(
                status="fallback",
                candidates=len(candidates),
                kept=[memory_pass_item(candidate) for candidate in candidates],
            )
        else:
            result = MemoryPassResult(
                status="kept",
                candidates=len(candidates),
                kept=list(kept.values()),
                dropped=[
                    memory_pass_item(candidate)
                    for number, candidate in enumerate(candidates, start=1)
                    if number not in kept
                ],
            )
        self._record_memory_pass(result)
        log.debug(
            "memory pass",
            character=character.name,
            viewer=viewer,
            candidates=len(candidates),
            kept=len(passed),
        )
        current_cache = (
            self.rag_cache_entry(character) if self.long_term_memory_cache else None
        )
        if current_cache is rag_cache and current_cache is not None:
            current_cache.setdefault("processed", {})[cache_key] = (
                list(passed),
                result,
            )
        return passed
