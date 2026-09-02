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
from talemate.agents.conversation.response_specs import (
    KNOWLEDGE_GATE_SPEC,
    KNOWLEDGE_LEDGER_SPEC,
    MEMORY_RERANK_SPEC,
)
from talemate.instance import get_agent
from talemate.knowledge.absence import (
    ABSENCE_LIMIT,
    ABSENCE_WINDOW,
    absence_facts,
    render_absence_lines,
)
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.schema import KnowledgeEdge
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage
from talemate.util.data import extract_json
import talemate.emit.async_signals as async_signals

if TYPE_CHECKING:
    from talemate.events import GameLoopNewMessageEvent
    from talemate.tale_mate import Character

__all__ = [
    "CharacterKnowledgeMixin",
    "parse_index_list",
    "parse_ledger",
]

log = structlog.get_logger("talemate.agents.conversation.knowledge")

LEDGER_FACTS_PER_CHARACTER = 20


def parse_index_list(text: str | None) -> list[int] | None:
    """
    1-based candidate numbers from a `<KEEP>` or `<ORDER>` answer, in the
    order given, without repeats. "none" is an empty list; no numbers and
    no "none" is None (the answer could not be read).
    """
    if text is None:
        return None
    text = text.strip()
    if not text or text.lower().startswith("none"):
        return [] if text else None
    numbers: list[int] = []
    for match in re.findall(r"\d+", text):
        value = int(match)
        if value >= 1 and value not in numbers:
            numbers.append(value)
    return numbers or None


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
        try:
            data, _ = extract_json(text)
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
        ledger[str(name)] = [str(i).strip() for i in ids if str(i).strip()]
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
            description="Build the prompt from the speaking character's point of view: drop what they were not present for, retrieve only what they know, and tell the model what they do not know. The items marked +1 request are off by default.",
            config={
                "perspective_filter": AgentActionConfig(
                    type="bool",
                    label="Perspective filter",
                    description="Drop spans of the history the character was not present for (replaced by a one-line gap) and filter long term memory by their knowledge.",
                    value=True,
                ),
                "absence_block": AgentActionConfig(
                    type="bool",
                    label="Absence block",
                    description="List the recent facts the character does not know, so the model does not let them act on those.",
                    value=True,
                ),
                "absence_limit": AgentActionConfig(
                    type="number",
                    label="Absence block lines",
                    description="At most this many facts in the absence block.",
                    value=ABSENCE_LIMIT,
                    min=1,
                    max=20,
                    step=1,
                ),
                "absence_window": AgentActionConfig(
                    type="number",
                    label="Absence block window",
                    description="How many of the most recent facts are considered for the block.",
                    value=ABSENCE_WINDOW,
                    min=5,
                    max=200,
                    step=5,
                ),
                "llm_gate": AgentActionConfig(
                    type="bool",
                    label="AI knowledge gate",
                    description="Ask the AI which of the retrieved memories the character would actually know, and keep only those.",
                    value=False,
                    note_on_value={
                        True: AgentActionNote(
                            color="primary",
                            text="+1 request per line. Handled by the World State agent's client.",
                        ),
                    },
                ),
                "llm_rerank": AgentActionConfig(
                    type="bool",
                    label="AI memory rerank",
                    description="Ask the AI to order the retrieved memories by how useful they are for the next line, and keep the best few.",
                    value=False,
                    note_on_value={
                        True: AgentActionNote(
                            color="primary",
                            text="+1 request per line. Handled by the World State agent's client.",
                        ),
                    },
                ),
                "llm_rerank_keep": AgentActionConfig(
                    type="number",
                    label="AI memory rerank: keep",
                    description="How many memories the rerank keeps.",
                    value=5,
                    min=1,
                    max=20,
                    step=1,
                ),
                "ledger": AgentActionConfig(
                    type="bool",
                    label="Learned-this-turn ledger",
                    description="After each line, ask the AI which of the facts the listeners did not know the line revealed to them; each becomes a grant.",
                    value=False,
                    note_on_value={
                        True: AgentActionNote(
                            color="primary",
                            text="+1 request per line, only when a listener has facts they do not know. Handled by the World State agent's client.",
                        ),
                    },
                ),
            },
        )

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
    def knowledge_llm_gate(self) -> bool:
        return self.character_knowledge_enabled and bool(
            self.resolve_config("character_knowledge", "llm_gate")
        )

    @property
    def knowledge_llm_rerank(self) -> bool:
        return self.character_knowledge_enabled and bool(
            self.resolve_config("character_knowledge", "llm_rerank")
        )

    @property
    def knowledge_llm_rerank_keep(self) -> int:
        return int(self.resolve_config("character_knowledge", "llm_rerank_keep"))

    @property
    def knowledge_ledger(self) -> bool:
        return self.character_knowledge_enabled and bool(
            self.resolve_config("character_knowledge", "ledger")
        )

    @property
    def knowledge_analysis_client(self):
        """The client the opt-in requests use (the World State agent's)."""
        return get_agent("world_state").client

    def connect(self, scene):
        super().connect(scene)
        # the ledger runs on every character line the scene records, the
        # player's included: listeners learn from what is said to them
        async_signals.get("game_loop_new_message").connect(self.on_new_message)

    async def on_new_message(self, event: "GameLoopNewMessageEvent"):
        if not self.knowledge_ledger or event.scene is not self.scene:
            return
        message = event.message
        if not isinstance(message, CharacterMessage):
            return
        character = self.scene.get_character(message.character_name)
        if character is None:
            return
        await self.record_learned_facts(character, str(message))

    def rag_knowledge_viewer(self, character: "Character | None") -> str | None:
        """
        The name every filter site uses (sheets, pins, the context history,
        retrieval and the analysis prompts), or None when the perspective
        filter is off: the shared record for every character.
        """
        if character is None or not self.knowledge_perspective_filter:
            return None
        return character.name

    async def knowledge_perspective(self, character: "Character | None") -> str | None:
        """Template access to `rag_knowledge_viewer` (templates await agent actions)."""
        return self.rag_knowledge_viewer(character)

    async def absence_block(self, character: "Character | None") -> list[str]:
        if character is None or not self.knowledge_absence_block:
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
        lines = render_absence_lines(facts)
        log.debug("absence_block", character=character.name, lines=len(lines))
        return lines

    # opt-in requests

    async def rag_build(self, character: "Character | None" = None, **kwargs):
        context = await super().rag_build(character=character, **kwargs)
        if character is None or not context:
            return context
        if self.knowledge_llm_gate:
            context = await self.knowledge_gate(character, context)
        if self.knowledge_llm_rerank and context:
            context = await self.memory_rerank(character, context)
        return context

    async def knowledge_gate(self, character: "Character", candidates: list) -> list:
        """Keep the retrieved memories the character would know (+1 request)."""
        candidates = list(candidates)
        _, extracted = await Prompt.request(
            "conversation.knowledge-gate",
            self.knowledge_analysis_client,
            "analyze_freeform",
            vars={
                "scene": self.scene,
                "max_tokens": self.knowledge_analysis_client.max_token_length,
                "character": character,
                "candidates": candidates,
                "knowledge_index": KnowledgeIndex.from_scene(self.scene),
            },
            response_spec=KNOWLEDGE_GATE_SPEC,
        )
        keep = parse_index_list(extracted.get("keep"))
        if keep is None:
            log.warning(
                "knowledge gate: answer not readable, keeping every candidate",
                character=character.name,
                answer=extracted.get("keep"),
            )
            return candidates
        kept = [candidates[i - 1] for i in keep if i <= len(candidates)]
        log.debug(
            "knowledge gate",
            character=character.name,
            candidates=len(candidates),
            kept=len(kept),
        )
        return kept

    async def memory_rerank(self, character: "Character", candidates: list) -> list:
        """Order the retrieved memories for the next line and keep the best few (+1 request)."""
        candidates = list(candidates)
        keep = self.knowledge_llm_rerank_keep
        recent = [
            str(message)
            for message in self.scene.collect_messages(
                max_iterations=100,
                max_messages=self.long_term_memory_num_messages,
                typ=["character", "narrator", "director"],
            )
        ]
        _, extracted = await Prompt.request(
            "conversation.memory-rerank",
            self.knowledge_analysis_client,
            "analyze_freeform",
            vars={
                "scene": self.scene,
                "max_tokens": self.knowledge_analysis_client.max_token_length,
                "character": character,
                "candidates": candidates,
                "recent_lines": recent,
                "keep": keep,
            },
            response_spec=MEMORY_RERANK_SPEC,
        )
        order = parse_index_list(extracted.get("order"))
        if order is None:
            log.warning(
                "memory rerank: answer not readable, keeping the merge order",
                character=character.name,
                answer=extracted.get("order"),
            )
            return candidates
        ordered = [candidates[i - 1] for i in order if i <= len(candidates)]
        log.debug(
            "memory rerank",
            character=character.name,
            candidates=len(candidates),
            kept=min(len(ordered), keep),
        )
        return ordered[:keep]

    # the signal path (a player line) has no active agent; the request needs one
    @set_processing
    async def record_learned_facts(
        self, character: "Character", line: str
    ) -> dict[str, list[str]]:
        """
        Which facts the listeners learned from the character's new line;
        each becomes an inferred grant (+1 request). The speaker does not
        learn from their own line.
        """
        if not self.knowledge_ledger or not line or not line.strip():
            return {}

        scene = self.scene
        listeners = [name for name in scene.active_characters if name != character.name]
        if not listeners:
            return {}

        absence: dict[str, list] = {}
        for name in listeners:
            facts = await absence_facts(
                scene,
                name,
                limit=LEDGER_FACTS_PER_CHARACTER,
                window=self.knowledge_absence_window,
            )
            if facts:
                absence[name] = facts

        if not absence:
            log.debug("ledger skipped: every listener knows the recent facts")
            return {}

        _, extracted = await Prompt.request(
            "conversation.knowledge-ledger",
            self.knowledge_analysis_client,
            "analyze_freeform",
            vars={
                "scene": scene,
                "max_tokens": self.knowledge_analysis_client.max_token_length,
                "line": line,
                "speaker": character.name,
                "listeners": ", ".join(absence.keys()),
                "absence": absence,
            },
            response_spec=KNOWLEDGE_LEDGER_SPEC,
        )
        ledger = parse_ledger(extracted.get("ledger"))
        if ledger is None:
            log.warning(
                "ledger: answer not readable, no grants made",
                speaker=character.name,
                answer=extracted.get("ledger"),
            )
            return {}

        learned: dict[str, list[str]] = {}
        for name, fact_ids in ledger.items():
            offered = {fact.id: fact for fact in absence.get(name, [])}
            for fact_id in fact_ids:
                fact = offered.get(fact_id)
                if fact is None:
                    continue
                fact.known_by[name] = "inferred"
                scene.world_state.knowledge.append(
                    KnowledgeEdge(
                        character=name,
                        target=fact.id,
                        kind="grant",
                        source="inferred",
                        ts=scene.ts,
                        note=f"learned from {character.name}",
                    )
                )
                learned.setdefault(name, []).append(fact.id)

        log.debug("ledger", speaker=character.name, learned=learned)
        return learned
