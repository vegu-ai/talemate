import hashlib
import json
import re
import weakref
from typing import TYPE_CHECKING

import structlog

import talemate.emit.async_signals as async_signals
from talemate.agents.base import (
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
    AgentActionNote,
    set_processing,
)
from talemate.agents.context import active_agent
from talemate.agents.conversation.response_specs import (
    ENTRY_BRIEFING_SPEC,
    KNOWLEDGE_LEDGER_FACTS_SPEC,
    KNOWLEDGE_LEDGER_SPEC,
    MEMORY_PASS_SPEC,
)
from talemate.agents.memory.schema import MemoryDocument
from talemate.client import presets
from talemate.context import scene_is_loading
from talemate.emit import emit
from talemate.exceptions import GenerationCancelled
from talemate.instance import get_agent
from talemate.knowledge.absence import (
    ABSENCE_LIMIT,
    ABSENCE_WINDOW,
    absence_facts,
    render_absence_lines,
)
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.changes import KnowledgeChange, emit_knowledge_changes
from talemate.knowledge.chronology import ranked_facts, render_fact
from talemate.knowledge.facts import parse_facts, previous_facts, store_facts
from talemate.knowledge.mode import (
    character_knowledge_enabled as perception_mode_enabled,
)
from talemate.knowledge.perspective_models import content_digest
from talemate.knowledge.processing import evidence_writer
from talemate.knowledge.schema import KnowledgeEdge
from talemate.knowledge.topics import awareness_line as topic_awareness_line
from talemate.knowledge.topics import known_bucket, refresh_topics
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage
from talemate.util.data import extract_json

if TYPE_CHECKING:
    from talemate.events import CharacterActivatedEvent, GameLoopNewMessageEvent
    from talemate.tale_mate import Character

__all__ = [
    "CharacterKnowledgeMixin",
    "pass_items",
    "parse_ledger",
    "normalize_fact_id",
]

log = structlog.get_logger("talemate.agents.conversation.knowledge")

LEDGER_FACTS_PER_CHARACTER = 20
HISTORICAL_UNSET = object()


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


def normalize_fact_id(value: str) -> str:
    """`f12`, `[F12]`, `12` and `F12` all name fact F12."""
    cleaned = str(value).strip().strip("[]()").strip().upper()
    if cleaned.isdigit():
        cleaned = f"F{cleaned}"
    return cleaned


def parse_ledger(text: str | None) -> dict[str, list[str]] | None:
    """`{"Name": ["F3", ...]}` from a `<LEDGER>` answer; None when unreadable."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    fenced = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    data = None
    try:
        data = json.loads(text)
    except ValueError:
        # prose around the JSON: extract_json returns (string, object)
        try:
            _, data = extract_json(text)
        except Exception:
            data = None
    if not isinstance(data, dict):
        return None
    ledger: dict[str, list[str]] = {}
    for name, ids in data.items():
        if isinstance(ids, str):
            ids = [ids]
        if not isinstance(ids, list):
            continue
        ledger[str(name)] = [normalize_fact_id(i) for i in ids if str(i).strip()]
    return ledger


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
            description="Help characters respond using what they know. In Standard mode, use the controls below to limit memories, remind the AI about unknown facts, and track learning from dialogue. Choose Character perspectives when creating a story for separate character views of events. Refine memories with AI works in either mode.",
            config={
                "perspective_filter": AgentActionConfig(
                    type="bool",
                    label="Limit to character knowledge",
                    description="Leave out events the character missed and memories they do not know. Turn on to base replies on their own experience; turn off to use the shared history and memories.",
                    value=True,
                ),
                "absence_block": AgentActionConfig(
                    type="bool",
                    label="Remind about unknown facts",
                    description="Tell the AI which recent facts the character does not know. Turn on if characters act on information they missed.",
                    value=True,
                ),
                "absence_limit": AgentActionConfig(
                    type="number",
                    label="Unknown-fact reminders",
                    description="Limit how many unknown facts are listed for the AI. Raise to include more reminders; lower to keep the prompt shorter.",
                    value=ABSENCE_LIMIT,
                    min=1,
                    max=20,
                    step=1,
                ),
                "absence_window": AgentActionConfig(
                    type="number",
                    label="Recent facts to check",
                    description="Choose how many recent facts to check for unknown-fact reminders. Raise to cover older facts; lower to focus on the newest.",
                    value=ABSENCE_WINDOW,
                    min=5,
                    max=200,
                    step=5,
                ),
                "awareness_line": AgentActionConfig(
                    type="bool",
                    label="Topic knowledge overview",
                    description="Give the AI a short overview of which topics the character knows about. Turn on for topic-level reminders; requires Topics in the Memory agent.",
                    value=True,
                ),
                "character_entry_turns": AgentActionConfig(
                    type="number",
                    label="Character entry turns",
                    description="Keep a private arrival orientation in the character's prompt for this many of their committed lines. Prompt retries do not consume a turn.",
                    value=3,
                    min=1,
                    max=10,
                    step=1,
                ),
                "brief_characters_on_entry": AgentActionConfig(
                    type="bool",
                    label="Brief characters on entry",
                    description="Generate a short private perception when a non-player character enters or returns.",
                    value=False,
                    note_on_value={
                        True: AgentActionNote(
                            color="primary",
                            text="Normally one request per non-player character activation. When Narrator Offscreen Life also applies, an unreadable account section is retried and adds one request.",
                        ),
                    },
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
                "ledger": AgentActionConfig(
                    type="bool",
                    label="Track learning from dialogue",
                    description="Ask the AI what listeners learned from each character message and add those facts to their knowledge. Turn on to track information shared in dialogue.",
                    value=False,
                    note_on_value={
                        True: AgentActionNote(
                            color="primary",
                            text="One more request after a character message when a listener has recent facts they do not know, using the World State agent's client.",
                        ),
                    },
                ),
                "establish_facts": AgentActionConfig(
                    type="bool",
                    label="Establish facts from dialogue",
                    description="Save important facts as soon as a character says or establishes them, before the next summary. Routine dialogue can yield no facts.",
                    value=False,
                    condition=AgentActionConditional(
                        attribute="character_knowledge.config.ledger",
                        value=True,
                    ),
                    note_on_value={
                        True: AgentActionNote(
                            color="primary",
                            text="Uses the same World State client request as Track learning from dialogue, but runs it after every character line, including player lines, even when everyone knows the recent facts. No second request per line.",
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
                if key
                in (
                    "character_entry_turns",
                    "brief_characters_on_entry",
                    "memory_pass",
                )
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
    def knowledge_absence_block(self) -> bool:
        return self.character_knowledge_enabled and self.resolve_config(
            "character_knowledge", "absence_block"
        )

    @property
    def knowledge_absence_limit(self) -> int:
        return int(self.resolve_config("character_knowledge", "absence_limit"))

    @property
    def knowledge_absence_window(self) -> int:
        return int(self.resolve_config("character_knowledge", "absence_window"))

    @property
    def knowledge_awareness_line(self) -> bool:
        return self.character_knowledge_enabled and bool(
            self.resolve_config("character_knowledge", "awareness_line")
        )

    @property
    def knowledge_character_entry_turns(self) -> int:
        return int(self.resolve_config("character_knowledge", "character_entry_turns"))

    def character_entry_context(self, character: "Character") -> str | None:
        from talemate.agents.conversation.entry_context import (
            render_entry_orientation,
        )

        return render_entry_orientation(self, character)

    @property
    def knowledge_brief_characters_on_entry(self) -> bool:
        return self.character_knowledge_enabled and bool(
            self.resolve_config("character_knowledge", "brief_characters_on_entry")
        )

    async def awareness_line(self, character: "Character | None") -> str | None:
        """Which topics the character knows all, some or nothing of; None when nothing qualifies."""
        if (
            perception_mode_enabled(self.scene)
            or character is None
            or not self.knowledge_awareness_line
        ):
            return None
        line = topic_awareness_line(self.scene, character.name)
        log.debug("awareness line", character=character.name, line=line)
        return line

    @property
    def knowledge_memory_pass(self) -> bool:
        return self.character_knowledge_enabled and bool(
            self.resolve_config("character_knowledge", "memory_pass")
        )

    @property
    def knowledge_ledger(self) -> bool:
        if perception_mode_enabled(self.scene):
            return False
        return self.character_knowledge_enabled and bool(
            self.resolve_config("character_knowledge", "ledger")
        )

    @property
    def knowledge_analysis_client(self):
        """The client the opt-in requests use (the World State agent's)."""
        return get_agent("world_state").client

    @property
    def knowledge_establish_facts(self) -> bool:
        return self.knowledge_ledger and bool(
            self.resolve_config("character_knowledge", "establish_facts")
        )

    def connect(self, scene):
        super().connect(scene)
        # the ledger runs on every character line the scene records, the
        # player's included: listeners learn from what is said to them
        async_signals.get("game_loop_new_message").connect(self.on_new_message)
        async_signals.get("character.activated").connect(self.on_character_activated)

    async def on_character_activated(self, event: "CharacterActivatedEvent"):
        if event.scene is not self.scene:
            return
        if scene_is_loading.get() is event.scene:
            return
        from talemate.agents.conversation.entry_context import start_entry_window

        character = event.character
        narrator = get_agent("narrator")
        window = start_entry_window(
            self,
            character,
            away_scene_time=narrator.away_scene_time(character),
        )
        if (
            window is None
            or character.is_player
            or not self.knowledge_brief_characters_on_entry
        ):
            return
        coordination = narrator.coordinate_entry_briefing(character)
        if coordination.deferred:
            return
        await self.generate_entry_briefing(
            character,
            missed=list(coordination.missed),
            elapsed=coordination.elapsed,
        )

    async def on_new_message(self, event: "GameLoopNewMessageEvent"):
        if event.scene is not self.scene:
            return
        message = event.message
        if not isinstance(message, CharacterMessage):
            return
        from talemate.agents.conversation.entry_context import consume_entry_turn

        consume_entry_turn(self, message.character_name)
        if not self.knowledge_ledger:
            return
        character = self.scene.get_character(message.character_name)
        if character is None:
            return
        kwargs = {}
        if message.history_dispatch_pending:
            from talemate.knowledge.revision_refresh import _historical_context

            recent, present, ts = _historical_context(self.scene, message)
            kwargs = {
                "recent_lines_override": recent,
                "present_override": present,
                "ts_override": ts,
            }
        await self.record_learned_facts(
            character, str(message), message=message, **kwargs
        )

    @set_processing
    @evidence_writer
    async def generate_entry_briefing(
        self,
        character: "Character",
        *,
        missed: list[dict] | None = None,
        elapsed: str = "",
        replace_disclosure_id: str | None = None,
    ) -> str | None:
        """Generate one scoped briefing, optionally with an offscreen account."""

        from talemate.agents.conversation.entry_context import (
            ENTRY_BRIEFING_TOKEN_ALLOWANCE,
            ENTRY_FACT_LIMIT,
            bind_entry_disclosure,
            build_entry_orientation,
            clear_entry_briefing,
            entry_windows,
            perspective_entry_briefing,
            remove_perspective_entry_briefing,
            render_entry_block,
            set_entry_briefing,
            store_perspective_entry_briefing,
        )

        clear_entry_briefing(self, character.name)
        if character.is_player:
            return None
        perspectives = perception_mode_enabled(self.scene)

        def fail_entry_briefing(error: Exception | str) -> None:
            clear_entry_briefing(self, character.name)
            if perspectives:
                if replace_disclosure_id is not None:
                    remove_perspective_entry_briefing(
                        self.scene,
                        character.name,
                        replace_disclosure_id,
                    )
                bind_entry_disclosure(self, character.name, None)
            log.warning(
                "entry briefing failed",
                character=character.name,
                error=str(error),
            )
            emit(
                "status",
                status="error",
                message=f"Character entry briefing for {character.name} failed.",
            )

        if (
            replace_disclosure_id is not None
            and perspective_entry_briefing(
                self.scene, character.name, replace_disclosure_id
            )
            is None
        ):
            raise ValueError("Character entry briefing disclosure does not exist")
        try:
            orientation = build_entry_orientation(self, character)
            if orientation is None:
                return None
            window = entry_windows(self)[character.name]
            narrator = get_agent("narrator") if missed else None
            client = (
                narrator.client
                if narrator is not None
                else self.knowledge_analysis_client
            )
            if client is None:
                fail_entry_briefing("no client configured")
                return None
            length = narrator.offscreen_life_length if narrator is not None else None
            known = known_bucket(self.scene, character.name)
            known = (
                ranked_facts(
                    self.scene,
                    known,
                    character=character.name,
                    superseders=known,
                    limit=ENTRY_FACT_LIMIT,
                )
                if known
                else []
            )
            history_budget = max(256, int(client.max_token_length * 0.35))
            history = (
                await self.history_context(
                    character, budget=history_budget, keep_director=False
                )
                if perspectives
                else self.scene.context_history(
                    budget=history_budget,
                    perspective=character.name,
                    keep_director=False,
                )
            )
            request_vars = {
                "max_tokens": client.max_token_length,
                "character": character,
                "arrival": render_entry_block(orientation),
                "character_facts": [
                    render_fact(self.scene, fact, include_id=False) for fact in known
                ],
                "unknown_fact_reminders": await self.absence_block(character),
                "perceived_history": history,
                "combined_offscreen": bool(missed),
                "elapsed": elapsed or orientation.away_elapsed or orientation.elapsed,
            }
            if narrator is not None:
                request_vars.update(
                    {
                        "scene": self.scene,
                        "knowledge_index": KnowledgeIndex.from_scene(self.scene),
                        "extra_instructions": narrator.extra_instructions,
                        "response_length": length,
                    }
                )
        except GenerationCancelled as exc:
            fail_entry_briefing(exc)
            return None

        request_error = None
        try:
            _, extracted = await Prompt.request(
                "conversation.character-entry-briefing",
                client,
                (
                    f"narrate_{length + ENTRY_BRIEFING_TOKEN_ALLOWANCE}"
                    if narrator is not None
                    else "analyze_freeform"
                ),
                vars=request_vars,
                response_spec=ENTRY_BRIEFING_SPEC,
            )
        except Exception as exc:
            request_error = exc
            extracted = {}

        briefing = (extracted.get("briefing") or "").strip().strip("*").strip()
        offscreen = (extracted.get("offscreen") or "").strip().strip("*").strip()
        if narrator is not None and not isinstance(request_error, GenerationCancelled):
            offscreen = narrator.clean_result(
                offscreen,
                ensure_dialog_format=False,
                force_narrative=False,
            )
            try:
                if offscreen:
                    await narrator.store_offscreen_life(character, offscreen, missed)
                else:
                    log.warning(
                        "combined offscreen response unreadable; retrying standalone",
                        character=character.name,
                    )
                    await narrator._offscreen_life_if_enough(character, missed)
            except Exception as exc:
                log.warning(
                    "offscreen life fallback failed",
                    character=character.name,
                    error=str(exc),
                )
                emit(
                    "status",
                    status="error",
                    message=f"Offscreen life for {character.name} failed.",
                )

        if not briefing:
            fail_entry_briefing(request_error or "response was unreadable")
            return None

        if character.name not in entry_windows(self):
            log.debug(
                "entry briefing window expired before storage",
                character=character.name,
            )
            return None
        try:
            if perspectives:
                disclosure = store_perspective_entry_briefing(
                    self.scene,
                    character.name,
                    briefing,
                    window=window,
                    disclosure_id=replace_disclosure_id,
                )
                bind_entry_disclosure(self, character.name, disclosure.id)
            elif not set_entry_briefing(self, character.name, briefing):
                log.debug(
                    "entry briefing window expired before storage",
                    character=character.name,
                )
                return None
        except (TypeError, ValueError) as exc:
            fail_entry_briefing(exc)
            return None
        log.debug(
            "entry briefing",
            character=character.name,
            combined_offscreen=bool(missed),
        )
        return briefing

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
        overrides=None,
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
                self.scene, budget=budget, overrides=overrides, params=params
            )
        return self.scene.context_history(budget=budget, **params.model_dump())

    async def absence_block(self, character: "Character | None") -> list[str]:
        if (
            perception_mode_enabled(self.scene)
            or character is None
            or not self.knowledge_absence_block
        ):
            log.debug(
                "absence_block skipped",
                character=character.name if character else None,
                enabled=self.knowledge_absence_block,
            )
            return []
        dedupe = get_agent("summarizer").archive_fact_dedupe_distance
        facts = await absence_facts(
            self.scene,
            character.name,
            limit=self.knowledge_absence_limit,
            window=self.knowledge_absence_window,
            dedupe_distance=dedupe,
        )
        lines = render_absence_lines(facts, self.scene)
        log.debug("absence_block", character=character.name, lines=len(lines))
        return lines

    # opt-in requests

    async def rag_process_context(self, character, context):
        if character is None or not context or not self.knowledge_memory_pass:
            return context
        return await self.memory_pass(character, context)

    def _recent_lines(self) -> list[str]:
        """The last few scene lines, oldest first (collect_messages yields newest first)."""
        lines = [
            str(message)
            for message in self.scene.collect_messages(
                max_iterations=100,
                max_messages=self.long_term_memory_num_messages,
                typ=["character", "narrator", "director"],
            )
        ]
        lines.reverse()
        return lines

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
            return list(processed[cache_key])

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
            passed = []
            current_cache = (
                self.rag_cache_entry(character) if self.long_term_memory_cache else None
            )
            if current_cache is rag_cache and current_cache is not None:
                current_cache.setdefault("processed", {})[cache_key] = passed
            return passed
        # the number alone says keep and where
        passed = []
        for number, text in items:
            if not 1 <= number <= len(candidates):
                continue
            candidate = candidates[number - 1]
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
            current_cache.setdefault("processed", {})[cache_key] = list(passed)
        return passed

    # the signal path (a player line) has no active agent; the request needs one
    @set_processing
    @evidence_writer
    async def record_learned_facts(
        self,
        character: "Character",
        line: str,
        *,
        message: CharacterMessage | None = None,
        present_override=HISTORICAL_UNSET,
        recent_lines_override: list[str] | None = None,
        ts_override: int | None = None,
        establish_override: bool | None = None,
        still_current=None,
        replace_message_evidence: bool = False,
        replace_facts: bool = True,
        require_validated_result: bool = False,
    ) -> dict[str, list[str]] | None:
        """
        Track listener learning and optionally establish sourced dialogue facts.
        Both outputs share one request; fact extraction runs on every character line.
        """
        if not self.knowledge_ledger or not line or not line.strip():
            return {}

        scene = self.scene
        establish = (
            self.knowledge_establish_facts
            if establish_override is None
            else establish_override
        )
        if establish and (
            message is None or scene.get_message(message.id) is not message
        ):
            return {}
        present = (
            present_override
            if present_override is not HISTORICAL_UNSET
            else (
                list(
                    dict.fromkeys(
                        [
                            character.name,
                            *(
                                message.present
                                if message.present is not None
                                else scene.active_characters
                            ),
                        ]
                    )
                )
                if establish
                else scene.active_characters
            )
        )
        witnesses = present if present is not None else scene.active_characters
        listeners = [name for name in witnesses if name != character.name]
        if not listeners and not establish:
            if still_current is not None and not still_current():
                raise GenerationCancelled(
                    "The selected version changed during fact learning"
                )
            if replace_message_evidence and message is not None:
                from talemate.knowledge.revision_refresh import (
                    _remove_message_evidence,
                )

                _remove_message_evidence(scene, message, facts=replace_facts)
            return {}
        ts = scene.ts if ts_override is None else ts_override
        digest = content_digest(message.perception_text) if establish else None
        if establish:
            message._knowledge_scene = weakref.ref(scene)

            def source_current():
                return (
                    self.scene is scene
                    and self.knowledge_establish_facts
                    and scene.get_message(message.id) is message
                    and content_digest(message.perception_text) == digest
                    and (still_current is None or still_current())
                )

        dedupe = get_agent("summarizer").archive_fact_dedupe_distance
        absence: dict[str, list] = {}
        for name in listeners:
            facts = await absence_facts(
                scene,
                name,
                limit=LEDGER_FACTS_PER_CHARACTER,
                window=self.knowledge_absence_window,
                dedupe_distance=dedupe,
            )
            if facts:
                absence[name] = facts

        if not absence and not establish:
            log.debug("ledger skipped: every listener knows the recent facts")
            if still_current is not None and not still_current():
                raise GenerationCancelled(
                    "The selected version changed during fact learning"
                )
            if replace_message_evidence and message is not None:
                from talemate.knowledge.revision_refresh import (
                    _remove_message_evidence,
                )

                _remove_message_evidence(scene, message, facts=replace_facts)
            return {}

        recent = (
            list(recent_lines_override)
            if recent_lines_override is not None
            else self._recent_lines()
        )
        # the line is already in the history when the signal arrives
        if recent and recent[-1] == line:
            recent = recent[:-1]
        _, extracted = await Prompt.request(
            "conversation.knowledge-ledger",
            self.knowledge_analysis_client,
            "analyze_freeform",
            vars={
                "scene": scene,
                "max_tokens": self.knowledge_analysis_client.max_token_length,
                "line": line,
                "recent_lines": recent,
                "speaker": character.name,
                "listeners": (
                    (", ".join(listeners) or "no listeners")
                    if establish
                    else ", ".join(absence.keys())
                ),
                "absence": absence,
                **(
                    {"establish_facts": True, "previous_facts": previous_facts(scene)}
                    if establish
                    else {}
                ),
            },
            response_spec=(
                KNOWLEDGE_LEDGER_FACTS_SPEC if establish else KNOWLEDGE_LEDGER_SPEC
            ),
        )
        if still_current is not None and not still_current():
            raise GenerationCancelled(
                "The selected version changed during fact learning"
            )
        ledger = parse_ledger(extracted.get("ledger"))
        facts_valid = not establish or parse_facts(extracted.get("facts")) is not None
        if require_validated_result and (ledger is None or not facts_valid):
            log.warning(
                "ledger: answer not readable, no grants made",
                speaker=character.name,
                answer=extracted.get("ledger"),
            )
            return None
        if replace_message_evidence and message is not None:
            from talemate.knowledge.revision_refresh import _remove_message_evidence

            removed = _remove_message_evidence(scene, message, facts=replace_facts)
            if removed:
                get_agent("summarizer").queue_fact_memory(scene, removed)
        if establish and not await self._store_dialogue_facts(
            scene,
            message,
            extracted.get("facts"),
            present,
            listeners,
            ts,
            digest,
            dedupe,
            source_current,
        ):
            return {}
        if ledger is None:
            log.warning(
                "ledger: answer not readable, no grants made",
                speaker=character.name,
                answer=extracted.get("ledger"),
            )
            return {}
        from talemate.knowledge.revision_refresh import capture_revision_mutations

        learned: dict[str, list[str]] = {}
        with capture_revision_mutations(scene):
            for name, fact_ids in ledger.items():
                offered = {fact.id: fact for fact in absence.get(name, [])}
                for fact_id in fact_ids:
                    fact = (
                        scene.world_state.facts.get(fact_id)
                        if fact_id in offered
                        else None
                    )
                    if fact is None:
                        log.warning(
                            "ledger: fact id not among the listener's unknown facts",
                            listener=name,
                            fact_id=fact_id,
                            offered=list(offered),
                        )
                        continue
                    fact.known_by[name] = "inferred"
                    scene.world_state.knowledge.append(
                        KnowledgeEdge(
                            character=name,
                            target=fact.id,
                            kind="grant",
                            source="inferred",
                            message_id=message.id if message is not None else None,
                            ts=scene.ts,
                            note=f"learned from {character.name}",
                        )
                    )
                    learned.setdefault(name, []).append(fact.id)

        emit_knowledge_changes(
            scene,
            [
                KnowledgeChange(character=name, target=fact_id)
                for name, fact_ids in learned.items()
                for fact_id in fact_ids
            ],
        )
        log.debug("ledger", speaker=character.name, learned=learned)
        return learned

    async def _store_dialogue_facts(
        self,
        scene,
        message,
        raw,
        present,
        listeners,
        ts,
        digest,
        dedupe,
        source_current,
    ):
        if not source_current():
            return False
        parsed = parse_facts(raw)
        if parsed is None:
            log.warning("dialogue facts: answer not readable", message_id=message.id)
            return source_current()
        parsed = [
            item.model_copy(
                update={
                    "known_by": [name for name in item.known_by if name in listeners]
                }
            )
            for item in parsed
        ]
        stored = await store_facts(
            scene,
            None,
            present,
            ts,
            parsed,
            dedupe,
            notify=True,
            message_id=message.id,
            message_digest=digest,
            still_current=source_current,
        )
        if not source_current():
            return False
        if stored:
            await refresh_topics(scene)
            scene.emit_status()
        return source_current()
