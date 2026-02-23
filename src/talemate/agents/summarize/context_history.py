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

from talemate.agents.base import (
    AgentAction,
    AgentActionConditional,
    AgentActionConfig,
    AgentActionNote,
)
from talemate.agents.context import active_agent
from talemate.instance import get_agent
from talemate.scene_message import (
    CharacterMessage,
    ContextInvestigationMessage,
    DirectorMessage,
    NarratorMessage,
    ReinforcementMessage,
)
from talemate.util import count_tokens
from talemate.util.prompt import condensed
import talemate.util as util

if TYPE_CHECKING:
    from talemate.tale_mate import Scene

log = structlog.get_logger("talemate.agents.summarize.context_history")

_PREVIEW_DEFAULT_BUDGET = 8192

# Minimum number of dialogue messages guaranteed in best-fit mode,
# regardless of budget. Set to 0 to disable the guarantee.
_BEST_FIT_MIN_DIALOGUE = 3


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
    best_fit: bool | None = None
    best_fit_min_dialogue: int | None = None
    best_fit_max_dialogue: int | None = None


class _BestFitLevel(pydantic.BaseModel):
    """A single level in the best-fit hierarchy."""

    entries: list[dict]
    formatted: list[str]
    tokens: list[int]
    type: str  # 'layer' or 'archived'
    layer_idx: int | None = None


class _BestFitCollected(pydantic.BaseModel):
    """Intermediate result from the best-fit collection phase."""

    all_dialogue_fits: bool = False
    all_dialogue: list[str] = []
    parts_dialogue: list[str] = []
    expansion_budget: int = 0
    levels: list[_BestFitLevel] = []
    render_ranges: list[tuple[int, int]] = []
    summarized_to: int = 0


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
                "For v0.35 behavior use: best fit off, both ratios 50, budget 0, enforce boundary on."
            ),
            config={
                "max_budget": AgentActionConfig(
                    type="number",
                    label="Max. Budget",
                    description=(
                        "Cap the context budget for scene history (in tokens). "
                        "Set to 0 to use the full available budget dictated by prompt type and client context limits."
                    ),
                    value=8192,
                    min=0,
                    max=262144,
                    step=512,
                ),
                "best_fit": AgentActionConfig(
                    type="bool",
                    label="Best Fit Mode",
                    description=(
                        "Automatically distribute budget across layers to cover "
                        "the full timeline with a detail gradient."
                    ),
                    note_on_value={
                        False: AgentActionNote(
                            icon="mdi-information-outline",
                            color="primary",
                            text=(
                                "Dialogue ratio sets how much budget goes to raw "
                                "messages. Summary detail ratio splits the rest "
                                "across summary layers (archived, layer 0, layer 1, etc.)."
                            ),
                        ),
                        True: AgentActionNote(
                            icon="mdi-information-outline",
                            color="primary",
                            text=(
                                "Ratios are ignored. The algorithm selects the best "
                                "detail level for each time segment — compressed at "
                                "the start, detailed at the end."
                            ),
                        ),
                    },
                    value=True,
                ),
                "best_fit_min_dialogue": AgentActionConfig(
                    type="number",
                    label="Min. Dialogue Messages",
                    description=(
                        "Minimum number of recent dialogue messages guaranteed "
                        "in best-fit mode, regardless of budget. Set to 0 to disable."
                    ),
                    value=5,
                    min=0,
                    max=15,
                    step=1,
                    condition=AgentActionConditional(
                        attribute="manage_scene_history.config.best_fit",
                        value=True,
                    ),
                ),
                "best_fit_max_dialogue": AgentActionConfig(
                    type="number",
                    label="Max. Dialogue Messages",
                    description=(
                        "Maximum number of dialogue messages to consider in "
                        "best-fit mode. Limits how far back the algorithm "
                        "scans, improving performance on large scenes."
                    ),
                    note=AgentActionNote(
                        icon="mdi-information-outline",
                        color="primary",
                        text=(
                            "This caps collection but does not move the summary "
                            "boundary. If only 10 messages exist past the boundary, "
                            "setting this to 100 won't increase dialogue rendered."
                        ),
                    ),
                    value=250,
                    min=10,
                    max=500,
                    step=10,
                    condition=AgentActionConditional(
                        attribute="manage_scene_history.config.best_fit",
                        value=True,
                    ),
                ),
                "dialogue_ratio": AgentActionConfig(
                    type="number",
                    title="Budget Distribution",
                    label="Dialogue Ratio",
                    description="Percentage of context budget allocated to actual scene dialogue",
                    value=50,
                    min=10,
                    max=90,
                    step=5,
                    condition=AgentActionConditional(
                        attribute="manage_scene_history.config.best_fit",
                        value=False,
                    ),
                ),
                "summary_detail_ratio": AgentActionConfig(
                    type="number",
                    label="Summary Detail Ratio",
                    description=(
                        "Percentage of remaining budget allocated to each successive "
                        "summary layer — higher values give more budget to recent, "
                        "detailed summaries."
                    ),
                    value=50,
                    min=10,
                    max=90,
                    step=5,
                    condition=AgentActionConditional(
                        attribute="manage_scene_history.config.best_fit",
                        value=False,
                    ),
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
                    condition=AgentActionConditional(
                        attribute="manage_scene_history.config.best_fit",
                        value=False,
                    ),
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

    @property
    def scene_history_best_fit(self) -> bool:
        return self.actions["manage_scene_history"].config["best_fit"].value

    @property
    def scene_history_best_fit_min_dialogue(self) -> int:
        return (
            self.actions["manage_scene_history"].config["best_fit_min_dialogue"].value
        )

    @property
    def scene_history_best_fit_max_dialogue(self) -> int:
        return (
            self.actions["manage_scene_history"].config["best_fit_max_dialogue"].value
        )

    def _has_layered_history(self, scene: Scene) -> bool:
        """Check if layered history is available for the given scene."""
        return bool(
            scene.layered_history
            and self.layered_history_enabled
            and scene.layered_history[0]
        )

    # --- Shared Primitives ---

    @staticmethod
    def _resolve_override(override_val, config_val):
        """Return override_val if not None, otherwise config_val."""
        return override_val if override_val is not None else config_val

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
    def _is_dialogue_qualifying(message, params: ContextHistoryParams) -> bool:
        """Return True if the message should be included in dialogue output."""
        if message.hidden and not params.show_hidden:
            return False

        if (
            isinstance(message, ReinforcementMessage)
            and not params.include_reinforcements
        ):
            return False

        if isinstance(message, DirectorMessage):
            if not params.keep_director:
                return False
            if not message.character_name:
                return False
            if (
                isinstance(params.keep_director, str)
                and message.character_name != params.keep_director
            ):
                return False

        if (
            isinstance(message, ContextInvestigationMessage)
            and not params.keep_context_investigation
        ):
            return False

        return True

    @staticmethod
    def _context_history_collect_dialogue(
        scene: Scene,
        budget: int,
        params: ContextHistoryParams,
        *,
        boundary: int | None = None,
        assured_count: int = 0,
        max_count: int | None = None,
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
            max_count: If set, stop after collecting this many messages.

        Returns:
            (parts_dialogue, dialogue_start_idx, exhausted) where
            dialogue_start_idx is the lowest message index included in
            the collected dialogue and exhausted is True when the entire
            history was scanned (no early break due to budget, boundary,
            or max_count).
        """
        conversation_format = scene.conversation_format
        actor_direction_mode = get_agent("director").actor_direction_mode
        _is_qualifying = ContextHistoryMixin._is_dialogue_qualifying

        parts_dialogue: list[str] = []
        history_len = len(scene.history)
        dialogue_start_idx = history_len
        dialogue_messages_collected = 0
        exhausted = False

        for i in range(history_len - 1, -1, -1):
            message = scene.history[i]

            # Boundary check (when enforce_boundary is enabled)
            if boundary is not None:
                if i < boundary and dialogue_messages_collected >= assured_count:
                    break

            if not _is_qualifying(message, params):
                continue

            if count_tokens(parts_dialogue) + count_tokens(message) > budget:
                break

            if max_count is not None and len(parts_dialogue) >= max_count:
                break

            parts_dialogue.insert(
                0, message.as_format(conversation_format, mode=actor_direction_mode)
            )
            dialogue_start_idx = i

            if isinstance(message, CharacterMessage):
                dialogue_messages_collected += 1
        else:
            exhausted = True

        return parts_dialogue, dialogue_start_idx, exhausted

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

        parts_dialogue, dialogue_start_idx, _ = self._context_history_collect_dialogue(
            scene,
            budget_dialogue,
            params,
            boundary=boundary,
            assured_count=assured_count,
        )

        log.debug("context_history", dialogue_start_idx=dialogue_start_idx)

        # --- Context Levels ---
        has_layered = self._has_layered_history(scene)

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

        if not parts_context:
            intro = scene.get_intro()
            if intro:
                parts_context.insert(0, intro)

        return self._context_history_finalize(
            parts_context, collected.parts_dialogue, chapter_numbers
        )

    # --- Best-Fit Mode ---

    def _best_fit_build_levels(
        self,
        scene: Scene,
        summarized_to: int = 0,
        params: ContextHistoryParams | None = None,
        *,
        dialogue_exclude: set[str] | None = None,
    ) -> list[_BestFitLevel]:
        """Build the level hierarchy from top (most compressed) to bottom (most detailed).

        Returns a list of ``_BestFitLevel`` objects ordered from highest
        (most compressed) layer to dialogue (most detailed).
        All entries are kept at their original indices so that layer start/end
        references remain valid.

        When *summarized_to* > 0 and *params* is provided, a dialogue level
        is appended at the bottom so the expansion algorithm can unpack
        archived entries into verbatim messages.
        """
        levels: list[_BestFitLevel] = []

        has_layered = self._has_layered_history(scene)

        if has_layered:
            num_layers = len(scene.layered_history)
            for i in range(num_layers - 1, -1, -1):
                layer = scene.layered_history[i]
                if not layer:
                    continue
                formatted: list[str] = []
                tokens: list[int] = []
                for entry in layer:
                    text, _ = self._context_history_format_layered_entry(
                        entry, scene.ts
                    )
                    formatted.append(text)
                    tokens.append(count_tokens(text))
                levels.append(
                    _BestFitLevel(
                        entries=layer,
                        formatted=formatted,
                        tokens=tokens,
                        type="layer",
                        layer_idx=i,
                    )
                )

        if scene.archived_history:
            # Only include summarization entries (those with an "end" index).
            # Entries without "end" are permanent historical notes, not summaries.
            summary_entries = [
                e for e in scene.archived_history if e.get("end") is not None
            ]
            if summary_entries:
                # Ensure every entry has a ``start`` field so the expansion
                # algorithm can map correctly to the dialogue level below.
                enriched: list[dict] = []
                for idx, entry in enumerate(summary_entries):
                    if entry.get("start") is not None:
                        enriched.append(entry)
                    else:
                        computed_start = 0
                        if idx > 0:
                            prev_end = summary_entries[idx - 1].get("end")
                            if prev_end is not None:
                                computed_start = prev_end + 1
                        enriched.append({**entry, "start": computed_start})

                formatted_arch: list[str] = []
                tokens_arch: list[int] = []
                for entry in enriched:
                    text = self._context_history_format_archived_entry(entry, scene.ts)
                    formatted_arch.append(text)
                    tokens_arch.append(count_tokens(text))
                levels.append(
                    _BestFitLevel(
                        entries=enriched,
                        formatted=formatted_arch,
                        tokens=tokens_arch,
                        type="archived",
                    )
                )

        # Dialogue level — the most detailed representation.
        if params is not None and summarized_to > 0:
            dialogue_level = self._best_fit_build_dialogue_level(
                scene, summarized_to, params, exclude=dialogue_exclude
            )
            if dialogue_level is not None:
                levels.append(dialogue_level)

        return levels

    @staticmethod
    def _best_fit_build_dialogue_level(
        scene: Scene,
        summarized_to: int,
        params: ContextHistoryParams,
        *,
        exclude: set[str] | None = None,
    ) -> _BestFitLevel | None:
        """Build a dialogue level for messages 0 to *summarized_to* (inclusive).

        Creates one slot per message index so that archived ``start``/``end``
        references map directly into this level.  Non-qualifying messages
        (and messages already present in *exclude*) get empty formatted
        strings and 0 tokens.

        Returns ``None`` when there is no summarized range to cover.
        """
        if summarized_to <= 0:
            return None

        conversation_format = scene.conversation_format
        actor_direction_mode = get_agent("director").actor_direction_mode
        _is_qualifying = ContextHistoryMixin._is_dialogue_qualifying

        entries: list[dict] = []
        formatted: list[str] = []
        tokens: list[int] = []

        for i in range(summarized_to + 1):
            entries.append({"idx": i})
            if i < len(scene.history):
                message = scene.history[i]
                if _is_qualifying(message, params):
                    text = message.as_format(
                        conversation_format, mode=actor_direction_mode
                    )
                    if exclude and text in exclude:
                        formatted.append("")
                        tokens.append(0)
                        continue
                    formatted.append(text)
                    tokens.append(count_tokens(text))
                    continue
            formatted.append("")
            tokens.append(0)

        return _BestFitLevel(
            entries=entries,
            formatted=formatted,
            tokens=tokens,
            type="dialogue",
        )

    @staticmethod
    def _best_fit_compute_ranges(
        levels: list[_BestFitLevel],
        budget: int,
    ) -> list[tuple[int, int]]:
        """Compute render ranges for each level using greedy expansion.

        Starting with everything at the top (most compressed) level, expands
        the most recent entries to successively more detailed levels until
        the budget is exhausted.

        Returns a list of ``(start_idx, end_idx_exclusive)`` tuples, one per
        level.  Only entries within the range should be rendered for that level.
        """
        if not levels:
            return []

        # Start: everything at the top level, plus "orphan" entries at
        # each lower level that aren't covered by the level above.
        # Orphans are tail entries created by summarisation that hasn't
        # yet been consolidated into the higher layers.
        render_ranges: list[tuple[int, int]] = [(0, len(levels[0].entries))]
        skeleton_tokens = sum(levels[0].tokens)

        for i in range(1, len(levels)):
            n = len(levels[i].entries)
            upper = levels[i - 1]

            # Determine the highest index in this level that the level
            # above covers via its start/end mapping.
            max_covered = -1
            for entry in upper.entries:
                end = entry.get("end", -1)
                if end > max_covered:
                    max_covered = end

            orphan_start = max_covered + 1
            if orphan_start < n:
                render_ranges.append((orphan_start, n))
                skeleton_tokens += sum(levels[i].tokens[orphan_start:n])
            else:
                render_ranges.append((n, n))

        if skeleton_tokens > budget:
            # Even the skeleton doesn't fit — trim from oldest entries
            # at the top level first, preserving orphan entries (which
            # represent the newest content at each level).
            orphan_tokens = skeleton_tokens - sum(levels[0].tokens)
            effective_budget = max(budget - orphan_tokens, 0)
            used = 0
            trim_start = len(levels[0].entries)
            for idx in range(len(levels[0].entries) - 1, -1, -1):
                if used + levels[0].tokens[idx] > effective_budget:
                    break
                used += levels[0].tokens[idx]
                trim_start = idx
            render_ranges[0] = (trim_start, len(levels[0].entries))
            # If still over budget after clearing the top level,
            # fall through to post-expansion enforcement below.
            skeleton_tokens = orphan_tokens + used

        remaining = max(budget - skeleton_tokens, 0)

        # Expand level by level (top → bottom)
        for level_idx in range(len(levels) - 1):
            upper = levels[level_idx]
            lower = levels[level_idx + 1]
            upper_start, upper_end = render_ranges[level_idx]

            # Try expanding from the end (most recent first)
            for entry_idx in range(upper_end - 1, upper_start - 1, -1):
                entry = upper.entries[entry_idx]
                entry_start = entry.get("start", 0)
                entry_end = entry.get("end", 0)

                # Token delta: cost of expanding this entry
                upper_tokens = upper.tokens[entry_idx]
                lower_tokens = sum(lower.tokens[entry_start : entry_end + 1])
                delta = lower_tokens - upper_tokens

                if delta <= remaining:
                    remaining -= delta
                    # Shrink upper level
                    render_ranges[level_idx] = (upper_start, entry_idx)
                    # Extend lower level
                    _, lower_end = render_ranges[level_idx + 1]
                    if lower_end <= entry_start:
                        # Lower was empty or doesn't cover this range yet
                        render_ranges[level_idx + 1] = (
                            entry_start,
                            entry_end + 1,
                        )
                    else:
                        # Extend lower's start backwards
                        render_ranges[level_idx + 1] = (entry_start, lower_end)
                else:
                    break

        # --- Post-expansion budget enforcement ---
        # Gaps in start/end mappings between layers can cause the merged
        # contiguous ranges to include entries whose cost was never tracked
        # in the delta accounting.  Trim from the oldest entries of the
        # lowest non-empty level until we fit.
        total = sum(
            sum(level.tokens[s:e]) for level, (s, e) in zip(levels, render_ranges)
        )
        if total > budget:
            # Walk levels bottom-up, trim oldest (lowest start) entries
            for trim_level in range(len(levels) - 1, -1, -1):
                s, e = render_ranges[trim_level]
                while s < e and total > budget:
                    total -= levels[trim_level].tokens[s]
                    s += 1
                render_ranges[trim_level] = (s, e)
                if total <= budget:
                    break

        return render_ranges

    @staticmethod
    def _best_fit_ensure_min_dialogue(
        scene: Scene,
        parts_dialogue: list[str],
        params: ContextHistoryParams,
        min_count: int = _BEST_FIT_MIN_DIALOGUE,
    ) -> list[str]:
        """Ensure at least *min_count* character/narrator messages.

        Only ``CharacterMessage`` and ``NarratorMessage`` count towards the
        minimum.  If the initial collection came up short (due to boundary),
        walks backwards to top up.  Budget reservation is handled by the
        caller.
        """
        if min_count <= 0:
            return parts_dialogue

        _QUALIFYING = (CharacterMessage, NarratorMessage)

        conversation_format = scene.conversation_format
        actor_direction_mode = get_agent("director").actor_direction_mode

        # Count qualifying messages already collected
        collected = set(parts_dialogue)
        qualifying_count = 0
        for i in range(len(scene.history) - 1, -1, -1):
            message = scene.history[i]
            if not isinstance(message, _QUALIFYING):
                continue
            formatted = message.as_format(
                conversation_format, mode=actor_direction_mode
            )
            if formatted in collected:
                qualifying_count += 1

        if qualifying_count >= min_count:
            return parts_dialogue

        needed = min_count - qualifying_count

        for i in range(len(scene.history) - 1, -1, -1):
            if needed <= 0:
                break
            message = scene.history[i]

            if not isinstance(message, _QUALIFYING):
                continue
            if message.hidden and not params.show_hidden:
                continue

            formatted = message.as_format(
                conversation_format, mode=actor_direction_mode
            )
            if formatted in collected:
                continue

            parts_dialogue.insert(0, formatted)
            collected.add(formatted)
            needed -= 1

        return parts_dialogue

    def _best_fit_collect(
        self,
        scene: Scene,
        budget: int,
        params: ContextHistoryParams,
        *,
        min_count: int,
        max_dialogue: int,
        summarized_to: int,
    ) -> _BestFitCollected:
        """Shared collection phase for best-fit mode.

        Handles the "all dialogue fits" check, mandatory dialogue collection
        with min_dialogue guarantee, and level hierarchy + render range
        computation.  Callers assemble the final output from the returned
        intermediate result.
        """
        result = _BestFitCollected(summarized_to=summarized_to)

        # 1. Try collecting all dialogue — if it fits, prefer it over summaries.
        all_dialogue, _, exhausted = self._context_history_collect_dialogue(
            scene, budget, params, max_count=max_dialogue
        )
        all_dialogue = self._best_fit_ensure_min_dialogue(
            scene, all_dialogue, params, min_count=min_count
        )

        if exhausted and count_tokens(all_dialogue) <= budget:
            result.all_dialogue_fits = True
            result.all_dialogue = all_dialogue
            return result

        # 2. Full dialogue doesn't fit — collect mandatory dialogue
        #    (messages after the summarized boundary).
        boundary = (summarized_to + 1) if summarized_to > 0 else None

        min_dialogue = self._best_fit_ensure_min_dialogue(
            scene, [], params, min_count=min_count
        )
        min_dialogue_tokens = count_tokens(min_dialogue)
        remaining_budget = max(budget - min_dialogue_tokens, 0)

        parts_dialogue, *_ = self._context_history_collect_dialogue(
            scene, remaining_budget, params, boundary=boundary, assured_count=0
        )
        parts_dialogue = self._best_fit_ensure_min_dialogue(
            scene, parts_dialogue, params, min_count=min_count
        )
        result.parts_dialogue = parts_dialogue

        dialogue_tokens = count_tokens(parts_dialogue)
        result.expansion_budget = max(budget - dialogue_tokens, 0)

        if result.expansion_budget <= 0:
            return result

        # 3. Build level hierarchy and compute render ranges.
        levels = self._best_fit_build_levels(
            scene,
            summarized_to=summarized_to,
            params=params,
            dialogue_exclude=set(parts_dialogue),
        )

        if not levels:
            return result

        result.levels = levels
        result.render_ranges = self._best_fit_compute_ranges(
            levels, result.expansion_budget
        )
        return result

    def _context_history_best_fit_build(
        self,
        scene: Scene,
        budget: int,
        params: ContextHistoryParams,
    ) -> list[str]:
        """Best-fit context history builder.

        Delegates collection to ``_best_fit_collect``, then assembles
        the parts into a flat string list.
        """
        summarized_to = self._context_history_compute_summarized_to(scene)

        collected = self._best_fit_collect(
            scene,
            budget,
            params,
            min_count=self.scene_history_best_fit_min_dialogue,
            max_dialogue=self.scene_history_best_fit_max_dialogue,
            summarized_to=summarized_to,
        )

        if collected.all_dialogue_fits:
            parts_context: list[str] = []
            intro = scene.get_intro()
            if intro:
                parts_context.insert(0, intro)
            return self._context_history_finalize(
                parts_context, collected.all_dialogue, []
            )

        if not collected.levels:
            return self._context_history_finalize([], collected.parts_dialogue, [])

        # Assemble context from render ranges — skip empty strings
        # that come from non-qualifying messages in the dialogue level.
        parts_context = []
        for level_idx, level in enumerate(collected.levels):
            start, end = collected.render_ranges[level_idx]
            for i in range(start, end):
                text = level.formatted[i]
                if text:
                    parts_context.append(text)

        if not parts_context:
            intro = scene.get_intro()
            if intro:
                parts_context.insert(0, intro)

        return self._context_history_finalize(
            parts_context, collected.parts_dialogue, []
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

        # Best-fit mode bypasses ratio-based distribution
        if self.scene_history_best_fit:
            return self._context_history_best_fit_build(scene, budget, params)

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
        _r = self._resolve_override
        eff_max_budget = _r(ovr.max_budget, self.scene_history_max_budget)
        eff_dialogue_ratio = _r(ovr.dialogue_ratio, self.scene_history_dialogue_ratio)
        eff_summary_detail_ratio = _r(ovr.summary_detail_ratio, self.scene_history_summary_detail_ratio)
        eff_enforce_boundary = _r(ovr.enforce_boundary, self.scene_history_enforce_boundary)
        eff_best_fit = _r(ovr.best_fit, self.scene_history_best_fit)
        eff_best_fit_min_dialogue = _r(ovr.best_fit_min_dialogue, self.scene_history_best_fit_min_dialogue)
        eff_best_fit_max_dialogue = _r(ovr.best_fit_max_dialogue, self.scene_history_best_fit_max_dialogue)

        if eff_max_budget > 0:
            budget = eff_max_budget
        elif budget is None:
            budget = _PREVIEW_DEFAULT_BUDGET

        summarized_to = self._context_history_compute_summarized_to(scene)

        if eff_best_fit:
            return self._context_history_preview_best_fit(
                scene,
                budget,
                params,
                summarized_to,
                eff_max_budget,
                eff_best_fit_min_dialogue,
                eff_best_fit_max_dialogue,
            )

        dialogue_ratio = eff_dialogue_ratio / 100.0
        summary_detail_ratio = eff_summary_detail_ratio / 100.0

        boundary: int | None = None
        assured_count = 0

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

        # Include scene intro when no summaries are present
        dialogue_entries = list(collected.parts_dialogue)
        context_tokens = sum(s["token_count"] for s in sections)
        if context_tokens == 0:
            intro = scene.get_intro()
            if intro:
                dialogue_entries.insert(0, intro)

        sections.append(
            {
                "type": "dialogue",
                "label": "Dialogue",
                "entries": dialogue_entries,
                "token_count": count_tokens(dialogue_entries),
                "entry_count": len(dialogue_entries),
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
                "best_fit": eff_best_fit,
            },
        }

    def _context_history_preview_best_fit(
        self,
        scene: Scene,
        budget: int,
        params: ContextHistoryParams,
        summarized_to: int,
        eff_max_budget: int,
        eff_best_fit_min_dialogue: int = _BEST_FIT_MIN_DIALOGUE,
        eff_best_fit_max_dialogue: int = 250,
    ) -> dict:
        """Build a best-fit preview with per-section token usage.

        Delegates collection to ``_best_fit_collect``, then formats
        the result as structured data for the frontend.
        """
        collected = self._best_fit_collect(
            scene,
            budget,
            params,
            min_count=eff_best_fit_min_dialogue,
            max_dialogue=eff_best_fit_max_dialogue,
            summarized_to=summarized_to,
        )

        if collected.all_dialogue_fits:
            dialogue_entries = list(collected.all_dialogue)
            intro = scene.get_intro()
            if intro:
                dialogue_entries.insert(0, intro)

            dialogue_tokens = count_tokens(dialogue_entries)
            sections: list[dict] = [
                {
                    "type": "dialogue",
                    "label": "Dialogue",
                    "entries": dialogue_entries,
                    "token_count": dialogue_tokens,
                    "entry_count": len(dialogue_entries),
                }
            ]

            return {
                "budget": {"total": budget, "used": dialogue_tokens},
                "sections": sections,
                "summary": {
                    "total_tokens": dialogue_tokens,
                    "summarized_to": summarized_to,
                    "history_length": len(scene.history),
                    "best_fit": True,
                    "best_fit_min_dialogue": eff_best_fit_min_dialogue,
                    "best_fit_max_dialogue": eff_best_fit_max_dialogue,
                    "max_budget": eff_max_budget,
                },
            }

        # Build sections from render ranges.
        sections = []
        expanded_dialogue: list[str] = []

        for level_idx, level in enumerate(collected.levels):
            start, end = collected.render_ranges[level_idx]
            if level.type == "dialogue":
                expanded_dialogue = [
                    level.formatted[i]
                    for i in range(start, end)
                    if level.formatted[i]
                ]
                continue

            parts = level.formatted[start:end]
            if not parts:
                continue

            section: dict = {
                "type": level.type,
                "label": (
                    f"Layer {level.layer_idx}"
                    if level.type == "layer"
                    else "Base Summarization Layer"
                ),
                "entries": parts,
                "token_count": count_tokens(parts),
                "entry_count": len(parts),
            }
            if level.type == "layer":
                section["layer_index"] = level.layer_idx
            if level_idx == 0 and start > 0:
                section["incomplete"] = True
            sections.append(section)

        # Merge expanded dialogue with mandatory dialogue.
        dialogue_entries = expanded_dialogue + list(collected.parts_dialogue)
        context_tokens = sum(s["token_count"] for s in sections)
        if context_tokens == 0:
            intro = scene.get_intro()
            if intro:
                dialogue_entries.insert(0, intro)

        dialogue_tokens = count_tokens(dialogue_entries)

        sections.append(
            {
                "type": "dialogue",
                "label": "Dialogue",
                "entries": dialogue_entries,
                "token_count": dialogue_tokens,
                "entry_count": len(dialogue_entries),
            }
        )

        total_tokens = sum(s["token_count"] for s in sections)

        return {
            "budget": {
                "total": budget,
                "used": total_tokens,
            },
            "sections": sections,
            "summary": {
                "total_tokens": total_tokens,
                "summarized_to": summarized_to,
                "history_length": len(scene.history),
                "best_fit": True,
                "best_fit_min_dialogue": eff_best_fit_min_dialogue,
                "max_budget": eff_max_budget,
            },
        }
