import json
import re
from typing import TYPE_CHECKING

import structlog

from talemate.agents.context import active_agent
from talemate.agents.base import (
    AgentAction,
    AgentActionConfig,
    AgentActionNote,
    set_processing,
)
from talemate.agents.conversation.response_specs import (
    KNOWLEDGE_LEDGER_SPEC,
    MEMORY_PASS_SPEC,
)
from talemate.instance import get_agent
from talemate.knowledge.absence import (
    ABSENCE_LIMIT,
    ABSENCE_WINDOW,
    absence_facts,
    render_absence_lines,
)
from talemate.knowledge.bucket import KnowledgeIndex
from talemate.knowledge.changes import KnowledgeChange, emit_knowledge_changes
from talemate.knowledge.schema import KnowledgeEdge
from talemate.knowledge.mode import (
    character_knowledge_enabled as perception_mode_enabled,
)
from talemate.knowledge.topics import awareness_line as topic_awareness_line
from talemate.prompts import Prompt
from talemate.scene_message import CharacterMessage
from talemate.util.data import extract_json
import talemate.emit.async_signals as async_signals

if TYPE_CHECKING:
    from talemate.events import GameLoopNewMessageEvent
    from talemate.tale_mate import Character

__all__ = [
    "CharacterKnowledgeMixin",
    "pass_items",
    "parse_ledger",
    "normalize_fact_id",
]

log = structlog.get_logger("talemate.agents.conversation.knowledge")

LEDGER_FACTS_PER_CHARACTER = 20


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
                if key == "memory_pass"
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
        lines = render_absence_lines(facts)
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

    async def memory_pass(
        self, character: "Character", candidates: list[str]
    ) -> list[str]:
        """One request that rewrites, drops and orders the retrieved memories for the next line."""
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
        _, extracted = await Prompt.request(
            "conversation.memory-pass",
            client,
            "analyze_long",
            vars={
                "scene": self.scene,
                "max_tokens": client.max_token_length,
                "character": character,
                "viewer": viewer,
                "candidates": candidates,
                "scene_history": scene_history,
                "knowledge_index": KnowledgeIndex.from_scene(self.scene),
                "character_retrieval": scoped,
                "memory_character_context": await get_agent(
                    "memory"
                ).audience_character_context(viewer, [character.name])
                if scoped
                else "",
            },
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
            return []
        # the number alone says keep and where
        passed = [
            text or candidates[number - 1]
            for number, text in items
            if 1 <= number <= len(candidates)
        ]
        if not passed:
            log.warning(
                "memory pass: answer not readable, keeping the candidates as retrieved",
                character=character.name,
                answer=answer,
                items=items,
            )
            return candidates
        log.debug(
            "memory pass",
            character=character.name,
            viewer=viewer,
            candidates=len(candidates),
            kept=len(passed),
        )
        return passed

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

        if not absence:
            log.debug("ledger skipped: every listener knows the recent facts")
            return {}

        recent = self._recent_lines()
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
