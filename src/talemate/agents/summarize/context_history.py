"""
Summarizer agent mixin for context history assembly.

Builds the context window from a Scene's archived_history, layered_history,
and live dialogue history. Scene is always passed as a parameter (not accessed
via self.scene) because some callers construct standalone scenes.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

import pydantic
import structlog

from talemate.agents.base import AgentAction, AgentActionConfig, AgentActionNote
from talemate.agents.context import active_agent
from talemate.instance import get_agent
from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    DirectorMessage,
    ReinforcementMessage,
)
from talemate.util import count_tokens
from talemate.util.prompt import condensed
import talemate.util as util

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.agents.summarize.context_history")

_PREVIEW_DEFAULT_BUDGET = 8192


class _CollectedHistory(pydantic.BaseModel):
    """Intermediate result from the shared collection phase."""

    budget: int
    budget_dialogue: int
    level_budgets: list[int]  # [archived, layer0, layer1, ...]
    parts_dialogue: list[str]
    dialogue_start_idx: int
    parts_archived: list[str]
    archived_boundary: int
    parts_layers: list[list[str]]
    layer_chapters: list[list[str]]
    layer_boundaries: list[int]
    has_layered: bool


class ContextHistoryPreviewOverrides(pydantic.BaseModel):
    """Optional overrides for context_history_preview.

    Allows the frontend to test different configurations without
    changing the saved action settings. None values fall back to
    the current action config.
    """

    dialogue_ratio: int | None = None
    summary_detail_ratio: int | None = None
    max_budget: int | None = None
    enforce_boundary: bool | None = None


class ContextHistoryParams(pydantic.BaseModel):
    """Validated parameters for context_history().

    Accepts all known kwargs including dead ones (min_dialogue, sections)
    that are passed by Jinja templates but have no effect. Unknown kwargs
    are silently dropped via extra="ignore".
    """

    keep_director: bool | str = False
    keep_context_investigation: bool = True
    show_hidden: bool = False
    include_reinforcements: bool = True
    assured_dialogue_num: int = 5
    chapter_labels: bool = False

    # Dead kwargs — templates pass these but code never uses them.
    min_dialogue: int | None = None
    sections: bool | None = None

    model_config = pydantic.ConfigDict(extra="ignore")


class ContextHistoryMixin:
    """Summarizer agent mixin providing context history assembly logic.

    Uses a budget-aware layered detail gradient strategy via
    ``_context_history_build``. Dialogue ratio, max budget, and boundary
    enforcement are controlled by always-visible action settings.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["manage_scene_history"] = AgentAction(
            enabled=True,
            container=True,
            can_be_disabled=False,
            icon="mdi-arrow-split-vertical",
            label="Scene History",
            description=(
                "Controls how scene history is split between actual "
                "dialogue and summarized content when generating context for "
                "AI prompts. The dialogue ratio determines how much of the context "
                "budget is allocated to raw dialogue messages versus summarized content. "
                "The summary detail ratio controls how the remaining budget is "
                "distributed across summary layers. "
                "For v0.35 behavior use: both ratios 50, budget 0, enforce boundary on."
            ),
            config={
                "dialogue_ratio": AgentActionConfig(
                    type="number",
                    title="Budget Distribution",
                    label="Dialogue Ratio",
                    description="Percentage of context budget allocated to actual scene dialogue",
                    value=50,
                    min=10,
                    max=90,
                    step=5,
                ),
                "summary_detail_ratio": AgentActionConfig(
                    type="number",
                    label="Summary Detail Ratio",
                    description="Percentage of remaining budget allocated to each successive summary layer",
                    note=AgentActionNote(
                        icon="mdi-information-outline",
                        color="primary",
                        text=(
                            "These two ratios control how the context budget is "
                            "distributed. Dialogue ratio sets how much budget goes "
                            "to raw dialogue messages. Summary detail ratio controls "
                            "how the remaining budget is split across summary layers "
                            "(archived history, layer 0, layer 1, etc.) — higher "
                            "values give more budget to recent, detailed summaries."
                        ),
                    ),
                    value=50,
                    min=10,
                    max=90,
                    step=5,
                ),
                "max_budget": AgentActionConfig(
                    type="number",
                    label="Max Budget Override",
                    description="Override the context budget for scene history (in tokens)",
                    note=AgentActionNote(
                        icon="mdi-information-outline",
                        color="primary",
                        text=(
                            "Set this to ensure the scene history budget never exceeds "
                            "a certain length. Set to 0 to use the full available budget, "
                            "which varies by prompt type and client context limits."
                        ),
                    ),
                    value=8192,
                    min=0,
                    max=262144,
                    step=512,
                ),
                "enforce_boundary": AgentActionConfig(
                    type="bool",
                    label="Enforce Summary Boundary",
                    description=(
                        "When enabled, dialogue will not expand into content that "
                        "has already been summarized, producing the most compact "
                        "context rendering at the cost of detail."
                    ),
                    note_on_value={
                        False: AgentActionNote(
                            icon="mdi-information-outline",
                            color="primary",
                            text=(
                                "Older messages may reappear in full as dialogue "
                                "expands into previously summarized content. This "
                                "is normal and means the AI can see the original "
                                "messages instead of a summary."
                            ),
                        ),
                        True: AgentActionNote(
                            icon="mdi-alert-circle-outline",
                            color="warning",
                            text=(
                                "Dialogue will stop at the summary boundary, "
                                "producing a more compact context at the cost "
                                "of detail."
                            ),
                        ),
                    },
                    value=False,
                ),
            },
            tools=[],
        )

    # --- Properties ---

    @property
    def scene_history_enforce_boundary(self) -> bool:
        return self.actions["manage_scene_history"].config["enforce_boundary"].value

    @property
    def scene_history_dialogue_ratio(self) -> int:
        return self.actions["manage_scene_history"].config["dialogue_ratio"].value

    @property
    def scene_history_summary_detail_ratio(self) -> int:
        return self.actions["manage_scene_history"].config["summary_detail_ratio"].value

    @property
    def scene_history_max_budget(self) -> int:
        return self.actions["manage_scene_history"].config["max_budget"].value

    # --- Shared Primitives ---

    @staticmethod
    def _context_history_extract_params(kwargs: dict) -> ContextHistoryParams:
        """Extract and validate context history parameters from kwargs."""
        return ContextHistoryParams(**kwargs)

    @staticmethod
    def _context_history_compute_summarized_to(scene: Scene) -> int:
        """Compute the message index up to which history has been summarized.

        Returns 0 if no archived history exists or if archived history
        points beyond current history length (recovery mode).
        """
        history_len = len(scene.history)
        try:
            summarized_to = (
                scene.archived_history[-1]["end"] if scene.archived_history else 0
            )
            if summarized_to is None:
                summarized_to = 0
        except KeyError:
            summarized_to = 0

        if summarized_to and summarized_to >= history_len:
            log.warning(
                "context_history",
                message="summarized_to is greater than history length - may want to regenerate history",
            )
            summarized_to = 0

        log.debug(
            "context_history", summarized_to=summarized_to, history_len=history_len
        )
        return summarized_to

    @staticmethod
    def _context_history_collect_dialogue(
        scene: Scene,
        budget: int,
        params: ContextHistoryParams,
        *,
        boundary: int | None = None,
        assured_count: int = 0,
    ) -> tuple[list[str], int]:
        """Collect dialogue messages backwards from end of history.

        Args:
            scene: The scene to collect from.
            budget: Token budget for dialogue.
            params: Validated context history parameters.
            boundary: If set, stop collecting once we cross this message index
                AND have collected at least ``assured_count`` CharacterMessages.
                Used when boundary enforcement is enabled. If None, collect
                purely on budget.
            assured_count: Minimum CharacterMessages before boundary takes effect.
                Only meaningful when boundary is not None.

        Returns:
            (parts_dialogue, dialogue_start_idx) where dialogue_start_idx is the
            lowest message index included in the collected dialogue.
        """
        conversation_format = scene.conversation_format
        actor_direction_mode = get_agent("director").actor_direction_mode

        parts_dialogue: list[str] = []
        history_len = len(scene.history)
        dialogue_start_idx = history_len
        dialogue_messages_collected = 0

        for i in range(history_len - 1, -1, -1):
            message = scene.history[i]

            # Boundary check (when enforce_boundary is enabled)
            if boundary is not None:
                if i < boundary and dialogue_messages_collected >= assured_count:
                    break

            if message.hidden and not params.show_hidden:
                continue

            if (
                isinstance(message, ReinforcementMessage)
                and not params.include_reinforcements
            ):
                continue

            elif isinstance(message, DirectorMessage):
                if not params.keep_director:
                    continue
                if not message.character_name:
                    continue
                elif (
                    isinstance(params.keep_director, str)
                    and message.character_name != params.keep_director
                ):
                    continue

            elif (
                isinstance(message, ContextInvestigationMessage)
                and not params.keep_context_investigation
            ):
                continue

            if count_tokens(parts_dialogue) + count_tokens(message) > budget:
                break

            parts_dialogue.insert(
                0, message.as_format(conversation_format, mode=actor_direction_mode)
            )
            dialogue_start_idx = i

            if isinstance(message, CharacterMessage):
                dialogue_messages_collected += 1

        return parts_dialogue, dialogue_start_idx

    @staticmethod
    def _context_history_format_archived_entry(entry: dict, scene_ts: str) -> str:
        """Format a single archived history entry with relative timestamp."""
        try:
            time_message = util.iso8601_diff_to_human(entry["ts"], scene_ts)
            text = f"{time_message}: {entry['text']}"
        except Exception as e:
            log.error("context_history", error=e, traceback=traceback.format_exc())
            text = entry["text"]

        return condensed(text)

    @staticmethod
    def _context_history_format_layered_entry(
        entry: dict,
        scene_ts: str,
        chapter_info: tuple[int, int] | None = None,
    ) -> tuple[str, str | None]:
        """Format a single layered history entry with relative timestamps.

        Args:
            entry: Dict with 'text', 'ts_start', 'ts_end' keys.
            scene_ts: Current scene timestamp.
            chapter_info: Optional (chapter_layer_num, entry_index) for labeling.

        Returns:
            (formatted_text, chapter_number or None)
        """
        time_message_start = util.iso8601_diff_to_human(entry["ts_start"], scene_ts)
        time_message_end = util.iso8601_diff_to_human(entry["ts_end"], scene_ts)

        if time_message_start == time_message_end:
            time_message = time_message_start
        else:
            time_message = f"Start:{time_message_start}, End:{time_message_end}"

        text = f"{time_message} {entry['text']}"

        chapter_number = None
        if chapter_info is not None:
            chapter_layer_num, entry_idx = chapter_info
            chapter_number = f"{chapter_layer_num}.{entry_idx + 1}"
            text = f"### Chapter {chapter_number}\n{text}"

        return text, chapter_number

    @staticmethod
    def _context_history_collect_archived(
        scene: Scene,
        budget: int,
        dialogue_start_idx: int,
    ) -> tuple[list[str], int]:
        """Collect archived history entries backwards, skipping those fully
        covered by dialogue.

        Args:
            scene: The scene.
            budget: Token budget for archived entries.
            dialogue_start_idx: Lowest message index in dialogue — entries whose
                entire range is >= this index are skipped.

        Returns:
            (parts_archived, archived_boundary) where archived_boundary is the
            archived_history array index of the earliest included entry.
        """
        parts_archived: list[str] = []
        archived_boundary = 0
        archived_tokens = 0

        for i in range(len(scene.archived_history) - 1, -1, -1):
            entry = scene.archived_history[i]
            end = entry.get("end")
            if end is None:
                continue

            # Determine entry start in message index space
            if i == 0:
                entry_start = 0
            else:
                prev_end = scene.archived_history[i - 1].get("end")
                entry_start = 0 if prev_end is None else prev_end + 1

            # Skip entries fully covered by dialogue
            if entry_start >= dialogue_start_idx:
                continue

            text = ContextHistoryMixin._context_history_format_archived_entry(
                entry, scene.ts
            )

            text_tokens = count_tokens(text)
            if archived_tokens + text_tokens > budget:
                archived_boundary = i + 1
                break

            parts_archived.insert(0, text)
            archived_tokens += text_tokens
            archived_boundary = i

        log.debug(
            "context_history",
            archived_boundary=archived_boundary,
            archived_entries=len(parts_archived),
        )

        return parts_archived, archived_boundary

    @staticmethod
    def _context_history_collect_layer(
        layer: list[dict],
        scene_ts: str,
        budget: int,
        prev_boundary: int,
        *,
        chapter_labels: bool = False,
        chapter_layer_num: int | None = None,
    ) -> tuple[list[str], int, list[str]]:
        """Collect entries from a single layered history layer backwards,
        skipping entries fully covered by the more-detailed level below.

        Args:
            layer: List of layered history entry dicts.
            scene_ts: Current scene timestamp.
            budget: Token budget for this layer.
            prev_boundary: Index in the layer below of earliest included entry.
                Entries whose start >= prev_boundary are skipped.
            chapter_labels: Whether to prepend chapter labels.
            chapter_layer_num: Layer number for chapter labeling.

        Returns:
            (layer_parts, layer_boundary, chapter_numbers) where layer_boundary
            is the index in this layer of the earliest included entry.
        """
        layer_parts: list[str] = []
        layer_tokens = 0
        layer_boundary = 0
        chapter_numbers: list[str] = []

        for j in range(len(layer) - 1, -1, -1):
            entry = layer[j]

            entry_start = entry.get("start", 0)
            if entry_start is not None and entry_start >= prev_boundary:
                continue

            chapter_info = None
            if chapter_labels and chapter_layer_num is not None:
                chapter_info = (chapter_layer_num, j)

            text, chapter_number = (
                ContextHistoryMixin._context_history_format_layered_entry(
                    entry, scene_ts, chapter_info=chapter_info
                )
            )

            if chapter_number:
                chapter_numbers.append(chapter_number)

            text_tokens = count_tokens(text)
            if layer_tokens + text_tokens > budget:
                layer_boundary = j + 1
                break

            layer_parts.insert(0, text)
            layer_tokens += text_tokens
            layer_boundary = j

        return layer_parts, layer_boundary, chapter_numbers

    @staticmethod
    def _context_history_finalize(
        parts_context: list[str],
        parts_dialogue: list[str],
        chapter_numbers: list[str],
    ) -> list[str]:
        """Set chapter_numbers on active_agent state and join context + dialogue."""
        active_agent_ctx = active_agent.get()
        if active_agent_ctx:
            active_agent_ctx.state["chapter_numbers"] = chapter_numbers

        return list(map(str, parts_context)) + list(map(str, parts_dialogue))

    # --- Shared Collection ---

    def _context_history_collect_all(
        self,
        scene: Scene,
        budget: int,
        dialogue_ratio: float,
        summary_detail_ratio: float,
        params: ContextHistoryParams,
        *,
        boundary: int | None = None,
        assured_count: int = 0,
    ) -> _CollectedHistory:
        """Collect all context history parts without assembly.

        Shared collection phase used by both ``_context_history_build`` and
        ``context_history_preview``.  Computes budgets, collects dialogue,
        archived history, and layered history, returning everything in a
        ``_CollectedHistory`` dataclass.
        """
        # --- Dialogue ---
        budget_dialogue = int(dialogue_ratio * budget)
        budget_remaining = budget - budget_dialogue

        parts_dialogue, dialogue_start_idx = self._context_history_collect_dialogue(
            scene,
            budget_dialogue,
            params,
            boundary=boundary,
            assured_count=assured_count,
        )

        log.debug("context_history", dialogue_start_idx=dialogue_start_idx)

        # --- Context Levels ---
        has_layered = bool(
            scene.layered_history
            and self.layered_history_enabled
            and scene.layered_history[0]
        )

        num_context_levels = (1 + len(scene.layered_history)) if has_layered else 1

        # Compute budget for each level using recursive ratio application
        # Level 0 = archived, Level 1 = layer 0, Level 2 = layer 1, etc.
        level_budgets: list[int] = []
        remaining = budget_remaining
        for level_idx in range(num_context_levels):
            if level_idx == num_context_levels - 1:
                level_budgets.append(remaining)
            else:
                level_budget = int(summary_detail_ratio * remaining)
                level_budgets.append(level_budget)
                remaining -= level_budget

        log.debug(
            "context_history",
            num_context_levels=num_context_levels,
            level_budgets=level_budgets,
            budget_remaining=budget_remaining,
        )

        # --- Level 0: Archived History ---
        budget_archived = level_budgets[0] if level_budgets else 0
        parts_archived, archived_boundary = self._context_history_collect_archived(
            scene, budget_archived, dialogue_start_idx
        )

        # --- Layered History Levels ---
        parts_layers: list[list[str]] = []
        layer_chapters: list[list[str]] = []
        layer_boundaries: list[int] = []

        if has_layered:
            num_layers = len(scene.layered_history)
            prev_boundary = archived_boundary

            for layer_idx in range(num_layers):
                layer = scene.layered_history[layer_idx]
                if not layer:
                    parts_layers.append([])
                    layer_chapters.append([])
                    layer_boundaries.append(0)
                    continue

                budget_idx = layer_idx + 1
                layer_budget = (
                    level_budgets[budget_idx] if budget_idx < len(level_budgets) else 0
                )

                chapter_layer_num = num_layers - layer_idx

                layer_parts, layer_boundary, chapters = (
                    self._context_history_collect_layer(
                        layer,
                        scene.ts,
                        layer_budget,
                        prev_boundary,
                        chapter_labels=params.chapter_labels,
                        chapter_layer_num=chapter_layer_num,
                    )
                )

                parts_layers.append(layer_parts)
                layer_chapters.append(chapters)
                layer_boundaries.append(layer_boundary)
                prev_boundary = layer_boundary

        return _CollectedHistory(
            budget=budget,
            budget_dialogue=budget_dialogue,
            level_budgets=level_budgets,
            parts_dialogue=parts_dialogue,
            dialogue_start_idx=dialogue_start_idx,
            parts_archived=parts_archived,
            archived_boundary=archived_boundary,
            parts_layers=parts_layers,
            layer_chapters=layer_chapters,
            layer_boundaries=layer_boundaries,
            has_layered=has_layered,
        )

    # --- Core Builder ---

    def _context_history_build(
        self,
        scene: Scene,
        budget: int,
        dialogue_ratio: float,
        summary_detail_ratio: float,
        params: ContextHistoryParams,
        *,
        boundary: int | None = None,
        assured_count: int = 0,
    ) -> list[str]:
        """Budget-aware layered detail gradient context history.

        Delegates collection to ``_context_history_collect_all``, then
        assembles the parts into a flat string list.

        Assembly order: [highest layer] + … + [layer 0] + [archived] + [dialogue]
        """
        collected = self._context_history_collect_all(
            scene,
            budget,
            dialogue_ratio,
            summary_detail_ratio,
            params,
            boundary=boundary,
            assured_count=assured_count,
        )

        chapter_numbers: list[str] = []
        for chapters in collected.layer_chapters:
            chapter_numbers.extend(chapters)

        # --- Assembly ---
        parts_context: list[str] = []

        if collected.has_layered:
            has_any_layered_content = any(parts for parts in collected.parts_layers)

            for layer_parts in reversed(collected.parts_layers):
                parts_context.extend(layer_parts)

            if (
                has_any_layered_content
                and params.chapter_labels
                and collected.parts_archived
            ):
                parts_context.append("### Current\n")

        parts_context.extend(collected.parts_archived)

        if count_tokens(parts_context) < 128:
            intro = scene.get_intro()
            if intro:
                parts_context.insert(0, intro)

        return self._context_history_finalize(
            parts_context, collected.parts_dialogue, chapter_numbers
        )

    # --- Entry Point ---

    def context_history(self, scene: Scene, budget: int, **kwargs) -> list[str]:
        """Build context history using configured settings.

        Applies max_budget override, dialogue ratio, and optional boundary
        enforcement from the action config.
        """
        params = self._context_history_extract_params(kwargs)

        # Apply max_budget override
        if self.scene_history_max_budget > 0:
            budget = min(self.scene_history_max_budget, budget)

        dialogue_ratio = self.scene_history_dialogue_ratio / 100.0
        summary_detail_ratio = self.scene_history_summary_detail_ratio / 100.0

        if self.scene_history_enforce_boundary:
            summarized_to = self._context_history_compute_summarized_to(scene)
            return self._context_history_build(
                scene,
                budget,
                dialogue_ratio,
                summary_detail_ratio,
                params,
                boundary=summarized_to,
                assured_count=params.assured_dialogue_num,
            )

        return self._context_history_build(
            scene, budget, dialogue_ratio, summary_detail_ratio, params
        )

    # --- Preview ---

    def context_history_preview(
        self,
        scene: Scene,
        budget: int | None = None,
        overrides: ContextHistoryPreviewOverrides | None = None,
    ) -> dict:
        """Build a structured preview of context history for visualization.

        Delegates collection to ``_context_history_collect_all``, then
        formats the result as structured data with per-section entries and
        token counts for the frontend.

        Optional ``overrides`` allow the frontend to test different
        configurations without changing the saved action settings.
        """
        params = ContextHistoryParams()
        ovr = overrides or ContextHistoryPreviewOverrides()

        # Resolve effective values: override > action config
        eff_max_budget = (
            ovr.max_budget
            if ovr.max_budget is not None
            else self.scene_history_max_budget
        )
        eff_dialogue_ratio = (
            ovr.dialogue_ratio
            if ovr.dialogue_ratio is not None
            else self.scene_history_dialogue_ratio
        )
        eff_summary_detail_ratio = (
            ovr.summary_detail_ratio
            if ovr.summary_detail_ratio is not None
            else self.scene_history_summary_detail_ratio
        )
        eff_enforce_boundary = (
            ovr.enforce_boundary
            if ovr.enforce_boundary is not None
            else self.scene_history_enforce_boundary
        )

        if eff_max_budget > 0:
            budget = eff_max_budget
        elif budget is None:
            budget = _PREVIEW_DEFAULT_BUDGET

        dialogue_ratio = eff_dialogue_ratio / 100.0
        summary_detail_ratio = eff_summary_detail_ratio / 100.0

        boundary: int | None = None
        assured_count = 0
        summarized_to = self._context_history_compute_summarized_to(scene)

        if eff_enforce_boundary:
            boundary = summarized_to
            assured_count = params.assured_dialogue_num

        collected = self._context_history_collect_all(
            scene,
            budget,
            dialogue_ratio,
            summary_detail_ratio,
            params,
            boundary=boundary,
            assured_count=assured_count,
        )

        # --- Assemble sections in display order ---
        sections: list[dict] = []

        if collected.has_layered:
            num_layers = len(collected.parts_layers)
            highest_active = max(
                (i for i in range(num_layers) if collected.parts_layers[i]),
                default=None,
            )
            for layer_idx in reversed(range(num_layers)):
                parts = collected.parts_layers[layer_idx]
                layer_num = layer_idx
                budget_idx = layer_idx + 1
                layer_budget = (
                    collected.level_budgets[budget_idx]
                    if budget_idx < len(collected.level_budgets)
                    else 0
                )
                layer_boundary = (
                    collected.layer_boundaries[layer_idx]
                    if layer_idx < len(collected.layer_boundaries)
                    else 0
                )
                section: dict = {
                    "type": "layer",
                    "layer_index": layer_num,
                    "label": f"Layer {layer_num}",
                    "entries": parts,
                    "token_count": count_tokens(parts),
                    "entry_count": len(parts),
                    "budget": layer_budget,
                }
                if layer_idx == highest_active:
                    section["incomplete"] = layer_boundary > 0
                sections.append(section)

        budget_archived = collected.level_budgets[0] if collected.level_budgets else 0

        sections.append(
            {
                "type": "archived",
                "label": "Base Summarization Layer",
                "entries": collected.parts_archived,
                "token_count": count_tokens(collected.parts_archived),
                "entry_count": len(collected.parts_archived),
                "budget": budget_archived,
            }
        )

        sections.append(
            {
                "type": "dialogue",
                "label": "Dialogue",
                "entries": collected.parts_dialogue,
                "token_count": count_tokens(collected.parts_dialogue),
                "entry_count": len(collected.parts_dialogue),
                "budget": collected.budget_dialogue,
            }
        )

        total_tokens = sum(s["token_count"] for s in sections)

        return {
            "budget": {
                "total": budget,
                "dialogue": collected.budget_dialogue,
                "archived": budget_archived,
                "layers": [
                    collected.level_budgets[i + 1]
                    for i in range(len(collected.level_budgets) - 1)
                ]
                if len(collected.level_budgets) > 1
                else [],
            },
            "sections": sections,
            "summary": {
                "total_tokens": total_tokens,
                "summarized_to": summarized_to,
                "history_length": len(scene.history),
                "enforce_boundary": eff_enforce_boundary,
                "dialogue_ratio": eff_dialogue_ratio,
                "summary_detail_ratio": eff_summary_detail_ratio,
                "max_budget": eff_max_budget,
            },
        }
