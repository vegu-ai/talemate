"""
Plan mixin — provides arc generation configuration and expand pipeline methods
to the director agent.
"""

import structlog

from talemate.agents.base import AgentAction, AgentActionConfig
from talemate.emit import emit
import talemate.emit.async_signals
from talemate.agents.narrator import NarratorAgentEmission
from talemate.prompts import Prompt
from talemate.scene_message import NarratorMessage, CharacterMessage

from .expand import (
    compute_chunks,
    compute_arc_info,
    has_leaked_tags,
)
from .schema import Beat
from .util import complete_task, emit_plan_updated, get_plan

log = structlog.get_logger("talemate.agents.director.plan.mixin")


class PlanMixin:
    """
    Agent mixin for arc generation planning and expansion.

    Provides:
    - Configuration for expand chunk size, dialogue ratio, critique toggles
    - The expand pipeline: chunked expansion with arc metadata
    - Post-expansion critique pass
    """

    @classmethod
    def add_plan_actions(cls, actions: dict[str, AgentAction]):
        actions["plan"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            label="Arc Generation",
            icon="mdi-movie-open",
            description="Settings for the arc generation pipeline.",
            config={
                "dialogue_ratio": AgentActionConfig(
                    type="number",
                    label="Dialogue beat ratio",
                    description="Target fraction of beats that should be dialogue during arc generation. 0.4 = 40% dialogue beats.",
                    value=0.4,
                    step=0.1,
                    min=0.0,
                    max=1.0,
                ),
                "expand_chunk_size": AgentActionConfig(
                    type="number",
                    label="Expand chunk size",
                    description="Maximum number of beats per expansion chunk in expand mode. Larger chunks produce more cohesive prose but use more context.",
                    value=5,
                    step=1,
                    min=3,
                    max=12,
                ),
                "outline_critique": AgentActionConfig(
                    type="bool",
                    label="Outline critique",
                    description="Run a critique pass on the generated outline to improve beat quality before expansion.",
                    value=True,
                ),
                "expand_critique": AgentActionConfig(
                    type="bool",
                    label="Expansion critique",
                    description="Run a post-expansion critique pass to fix cross-beat redundancy and intensity monotony. Adds ~10s per generation.",
                    value=True,
                ),
            },
        )

    # === Config property helpers ===

    @property
    def plan_dialogue_ratio(self) -> float:
        return float(self.resolve_config("plan", "dialogue_ratio"))

    @property
    def plan_expand_chunk_size(self) -> int:
        return int(self.resolve_config("plan", "expand_chunk_size"))

    @property
    def plan_outline_critique(self) -> bool:
        return bool(self.resolve_config("plan", "outline_critique"))

    @property
    def plan_expand_critique(self) -> bool:
        return bool(self.resolve_config("plan", "expand_critique"))

    # === Expand pipeline methods ===

    async def _plan_revise_narrator_content(self, narrator, content: str) -> str:
        """Send narrator generated signal so automatic revision can process the content."""
        emission = NarratorAgentEmission(agent=narrator, response=content)
        await talemate.emit.async_signals.get("agent.narrator.generated").send(emission)
        return emission.response

    async def _plan_push_and_emit_block(self, scene, block: dict, narrator) -> int:
        """
        Push a single extracted block to scene history and emit to frontend.

        Runs automatic revision on narrator blocks. Returns word count of the block,
        or 0 if the block was empty/skipped.
        """
        content = block.get("content", "").strip()
        if not content:
            return 0

        if block["type"] == "narrator":
            content = await self._plan_revise_narrator_content(narrator, content)
            msg = NarratorMessage(content)
            await scene.push_history(msg)
            emit("narrator", msg)
        elif block["type"] == "character":
            char_name = block.get("name", "Unknown")
            msg = CharacterMessage(f"{char_name}: {content}")
            await scene.push_history(msg)
            character = scene.get_character(char_name)
            emit("character", message=msg, character=character)
        else:
            return 0

        return len(content.split())

    async def _plan_critique_expanded_blocks(
        self, blocks: list[dict], narrator, close_arc: bool = False
    ) -> list[dict]:
        """
        Run a post-expansion critique pass on all blocks to fix cross-beat
        redundancy, intensity monotony, and repeated vocabulary.
        """
        log.info("expand.critique", block_count=len(blocks), close_arc=close_arc)

        response, extracted = await Prompt.request(
            "narrator.arc-expand-critique",
            narrator.client,
            "narrate_4096",
            vars={
                "blocks": blocks,
                "max_tokens": narrator.client.max_token_length,
                "response_length": 4096,
                "close_arc": close_arc,
            },
        )

        revised = extracted.get("response", [])
        if not revised:
            log.warning(
                "expand.critique.no_blocks_returned", fallback="using originals"
            )
            return blocks

        log.info("expand.critique.done", original=len(blocks), revised=len(revised))
        return revised

    async def plan_expand_beats(
        self,
        scene,
        narrator,
        beats: list[Beat],
        plan_id: str,
        perspective: str,
        director_notes: str = "",
        chunk_size: int | None = None,
        chat_id: str | None = None,
        critique: bool | None = None,
        close_arc: bool = False,
    ) -> tuple[int, int]:
        """
        Expand beats into prose in chunks and push to scene history.

        Chunks are split at tension valleys when possible (deliberate chunking),
        falling back to max chunk_size. Each chunk receives arc-position metadata
        to guide pacing.

        Returns (total_blocks, total_words).
        """
        if chunk_size is None:
            chunk_size = self.plan_expand_chunk_size

        total_words = 0
        total_blocks = 0
        preceding_text = ""
        all_blocks: list[dict] = []

        log.info("plan.expand.mode", close_arc=close_arc, plan_id=plan_id)

        # Compute chunks and arc metadata
        chunks = compute_chunks(beats, chunk_size)
        arc_infos = compute_arc_info(chunks, beats, close_arc=close_arc)

        # Build a flat index to find following beats across chunk boundaries
        beat_offset = 0

        for chunk_num, (chunk_beats, arc_info) in enumerate(
            zip(chunks, arc_infos), start=1
        ):
            # Following beats: first 2 beats from the next chunk
            following_beats = []
            next_offset = beat_offset + len(chunk_beats)
            if next_offset < len(beats):
                following_beats = beats[next_offset : next_offset + 2]

            log.info(
                "expand.chunk",
                chunk=chunk_num,
                beats=f"{beat_offset + 1}-{beat_offset + len(chunk_beats)}",
                total=len(beats),
                position=arc_info.position,
                tension=f"{arc_info.tension_range[0]:.1f}-{arc_info.tension_range[1]:.1f}",
            )

            # Call the expansion template with retry on malformed output
            max_attempts = 3
            blocks = []
            prompt_vars = {
                "scene": scene,
                "max_tokens": narrator.client.max_token_length,
                "beats": chunk_beats,
                "following_beats": following_beats,
                "preceding_text": preceding_text[-2000:] if preceding_text else "",
                "perspective": perspective,
                "director_notes": director_notes,
                "extra_instructions": narrator.extra_instructions,
                "response_length": 4096,
                "arc_info": arc_info,
                "close_arc": close_arc,
            }

            for attempt in range(1, max_attempts + 1):
                response, extracted = await Prompt.request(
                    "narrator.arc-expand",
                    narrator.client,
                    "narrate_4096",
                    vars=prompt_vars,
                    dedupe_enabled=False,
                )

                blocks = extracted.get("response", [])
                if not blocks:
                    log.warning("expand.no_blocks", chunk=chunk_num, attempt=attempt)
                    continue

                # Validate: check for leaked block tags in content
                if not has_leaked_tags(blocks):
                    break

                log.warning("expand.leaked_tags", chunk=chunk_num, attempt=attempt)
                blocks = []

            if not blocks:
                raise RuntimeError(
                    f"Expansion failed for chunk {chunk_num} after {max_attempts} attempts. "
                    f"The model produced malformed output with leaked block tags. "
                    f"This may indicate the model is too weak for structured generation — "
                    f"consider using a more capable model."
                )

            all_blocks.extend(blocks)

            # Accumulate preceding text for next chunk
            chunk_text = "\n\n".join(b.get("content", "") for b in blocks)
            preceding_text += "\n\n" + chunk_text

            beat_offset += len(chunk_beats)

        # Post-expansion critique pass
        do_critique = critique if critique is not None else self.plan_expand_critique
        if do_critique and len(chunks) > 1 and all_blocks:
            all_blocks = await self._plan_critique_expanded_blocks(
                all_blocks, narrator, close_arc=close_arc
            )

        # Push all blocks to scene history and emit to frontend
        for block in all_blocks:
            words = await self._plan_push_and_emit_block(scene, block, narrator)
            if words:
                total_blocks += 1
                total_words += words

        # Mark all beats as completed
        for beat in beats:
            complete_task(scene, beat.id, plan_id=plan_id)

        # Emit plan update
        plan = get_plan(scene, plan_id)
        if plan:
            emit_plan_updated(plan, chat_id=chat_id)

        return total_blocks, total_words
