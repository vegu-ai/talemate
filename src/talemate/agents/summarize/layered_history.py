import structlog
from typing import TYPE_CHECKING
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig,
    AgentEmission,
)
import dataclasses
import talemate.emit.async_signals
from talemate.exceptions import GenerationCancelled
from talemate.world_state.templates import GenerationOptions
from talemate.emit import emit
from talemate.context import handle_generation_cancelled
from talemate.history import LayeredArchiveEntry, HistoryEntry, entry_contained
import talemate.util as util

if TYPE_CHECKING:
    from talemate.agents.summarize import BuildArchiveEmission

log = structlog.get_logger()

talemate.emit.async_signals.register(
    "agent.summarization.layered_history.finalize",
)


@dataclasses.dataclass
class LayeredHistoryFinalizeEmission(AgentEmission):
    entry: LayeredArchiveEntry | None = None
    summarization_history: list[str] = dataclasses.field(default_factory=lambda: [])

    @property
    def response(self) -> str | None:
        return self.entry.text if self.entry else None

    @response.setter
    def response(self, value: str):
        if self.entry:
            self.entry.text = value


class SummaryLongerThanOriginalError(ValueError):
    def __init__(self, original_length: int, summarized_length: int):
        self.original_length = original_length
        self.summarized_length = summarized_length
        super().__init__(
            f"Summarized text is longer than original text: {summarized_length} > {original_length}"
        )


class LayeredHistoryMixin:
    """
    Summarizer agent mixin that provides functionality for maintaining a layered history.
    """

    @classmethod
    def add_actions(cls, actions: dict[str, AgentAction]):
        actions["layered_history"] = AgentAction(
            enabled=True,
            container=True,
            icon="mdi-layers",
            can_be_disabled=True,
            experimental=True,
            label="Layered history",
            description="Generate a layered history with multiple levels of summarization",
            config={
                "threshold": AgentActionConfig(
                    type="number",
                    label="Token Threshold",
                    description="Will summarize when the number of tokens in previous layer exceeds this threshold",
                    min=256,
                    max=8192,
                    step=128,
                    value=1536,
                ),
                "max_layers": AgentActionConfig(
                    type="number",
                    label="Maximum number of layers",
                    description="The maximum number of layers to generate",
                    min=1,
                    max=5,
                    step=1,
                    value=3,
                ),
                "max_process_tokens": AgentActionConfig(
                    type="number",
                    label="Maximum tokens to process",
                    description="The maximum number of tokens to process at once.",
                    note="Smaller LLMs may struggle with accurately summarizing long texts. This setting will split the text into chunks and summarize each chunk separately, then stich them together in the next layer. If you're using a strong LLM (70B+), you can try setting this to be the same as the threshold.",
                    min=256,
                    max=8192,
                    step=128,
                    value=768,
                ),
                "chunk_size": AgentActionConfig(
                    type="number",
                    label="Chunk size",
                    description="Within the tokens to process this will further split the text into chunks. Allowing each chunk to be treated individually. This will help retain details in the summarization. This is number of characters, NOT tokens.",
                    value=1280,
                    min=512,
                    max=2048,
                    step=128,
                ),
                "analyze_chunks": AgentActionConfig(
                    type="bool",
                    label="Enable analysation",
                    description="Anlyse chunks to improve the quality of the summarization. Each chunk will be analysed individually.",
                    value=True,
                ),
                "response_length": AgentActionConfig(
                    type="text",
                    label="Maximum response length",
                    description="The maximum length of the summarization response. When analysing chunks, make sure this is big enough to hold the entire response.",
                    value="2048",
                    choices=[
                        {"label": "Short (256)", "value": "256"},
                        {"label": "Medium (512)", "value": "512"},
                        {"label": "Long (1024)", "value": "1024"},
                        {"label": "Exhaustive (2048)", "value": "2048"},
                    ],
                ),
            },
        )

    # config property helpers

    @property
    def layered_history_enabled(self):
        return self.actions["layered_history"].enabled

    @property
    def layered_history_threshold(self):
        return self.actions["layered_history"].config["threshold"].value

    @property
    def layered_history_max_process_tokens(self):
        return self.actions["layered_history"].config["max_process_tokens"].value

    @property
    def layered_history_max_layers(self):
        return self.actions["layered_history"].config["max_layers"].value

    @property
    def layered_history_chunk_size(self) -> int:
        return self.actions["layered_history"].config["chunk_size"].value

    @property
    def layered_history_analyze_chunks(self) -> bool:
        return self.actions["layered_history"].config["analyze_chunks"].value

    @property
    def layered_history_response_length(self) -> int:
        return int(self.actions["layered_history"].config["response_length"].value)

    @property
    def layered_history_available(self):
        return (
            self.layered_history_enabled
            and self.scene.layered_history
            and self.scene.layered_history[0]
        )

    # signals

    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get(
            "agent.summarization.after_build_archive"
        ).connect(self.on_after_build_archive)

    async def on_after_build_archive(self, emission: "BuildArchiveEmission"):
        """
        After the archive has been built, we will update the layered history.
        """

        if self.layered_history_enabled:
            await self.summarize_to_layered_history(
                generation_options=emission.generation_options
            )

    # helpers

    async def _lh_split_and_summarize_chunks(
        self,
        chunks: list[dict],
        extra_context: str,
        generation_options: GenerationOptions | None = None,
    ) -> list[str]:
        """
        Split chunks based on max_process_tokens and summarize each part.
        Returns a list of summary texts.
        """
        summaries = []
        current_chunk = chunks.copy()

        while current_chunk:
            partial_chunk = []
            max_process_tokens = self.layered_history_max_process_tokens

            # Build partial chunk up to max_process_tokens
            while (
                current_chunk
                and util.count_tokens(
                    "\n\n".join(chunk["text"] for chunk in partial_chunk)
                )
                < max_process_tokens
            ):
                partial_chunk.append(current_chunk.pop(0))

            text_to_summarize = "\n\n".join(chunk["text"] for chunk in partial_chunk)

            log.debug(
                "_split_and_summarize_chunks",
                tokens_in_chunk=util.count_tokens(text_to_summarize),
                max_process_tokens=max_process_tokens,
            )

            summary_text = await self.summarize_events(
                text_to_summarize,
                extra_context=extra_context + "\n\n".join(summaries),
                generation_options=generation_options,
                response_length=self.layered_history_response_length,
                analyze_chunks=self.layered_history_analyze_chunks,
                chunk_size=self.layered_history_chunk_size,
            )
            summaries.append(summary_text)

        return summaries

    def _lh_validate_summary_length(self, summaries: list[str], original_length: int):
        """
        Validates that the summarized text is not longer than the original.
        Raises SummaryLongerThanOriginalError if validation fails.
        """
        summarized_length = util.count_tokens(summaries)
        if summarized_length > original_length:
            raise SummaryLongerThanOriginalError(original_length, summarized_length)

        log.debug(
            "_validate_summary_length",
            original_length=original_length,
            summarized_length=summarized_length,
        )

    def _lh_build_extra_context(self, layer_index: int) -> str:
        """
        Builds extra context from compiled layered history for the given layer.
        """
        return "\n\n".join(self.compile_layered_history(layer_index))

    def _lh_extract_timestamps(self, chunk: list[dict]) -> tuple[str, str, str]:
        """
        Extracts timestamps from a chunk of entries.
        Returns (ts, ts_start, ts_end)
        """
        if not chunk:
            return "PT1S", "PT1S", "PT1S"

        ts = chunk[0].get("ts", "PT1S")
        ts_start = chunk[0].get("ts_start", ts)
        ts_end = chunk[-1].get("ts_end", chunk[-1].get("ts", ts))

        return ts, ts_start, ts_end

    async def _lh_finalize_archive_entry(
        self,
        entry: LayeredArchiveEntry,
        summarization_history: list[str] | None = None,
    ) -> LayeredArchiveEntry:
        """
        Finalizes an archive entry by summarizing it and adding it to the layered history.
        """

        emission = LayeredHistoryFinalizeEmission(
            agent=self,
            entry=entry,
            summarization_history=summarization_history,
        )

        await talemate.emit.async_signals.get(
            "agent.summarization.layered_history.finalize"
        ).send(emission)

        return emission.entry

    # layer building helpers

    def _lh_determine_start_from(self, layer_index: int) -> int:
        """
        Determine the starting index for summarizing into
        layered_history[layer_index].

        If the layer exists and has entries, returns last_entry["end"] + 1.
        Otherwise returns 0.
        """
        layered_history = self.scene.layered_history
        if layer_index < len(layered_history) and layered_history[layer_index]:
            return layered_history[layer_index][-1]["end"] + 1
        return 0

    async def _lh_commit_chunk(
        self,
        chunk: list[dict],
        next_layer_index: int,
        start_index: int,
        end_index: int,
        estimated_entries: int,
        generation_options: GenerationOptions | None = None,
    ) -> dict:
        """
        Summarize a chunk of entries and append the result to the target layer.

        Gets or creates the target layer, summarizes the chunk via
        _lh_split_and_summarize_chunks, validates, creates a LayeredArchiveEntry,
        and appends it.

        Returns the created entry dict.
        """
        layered_history = self.scene.layered_history

        # Get or create target layer
        if next_layer_index >= len(layered_history):
            layered_history.append([])
            log.debug("_lh_commit_chunk", created_layer=next_layer_index)
        next_layer = layered_history[next_layer_index]

        ts, ts_start, ts_end = self._lh_extract_timestamps(chunk)
        extra_context = self._lh_build_extra_context(next_layer_index)
        text_length = util.count_tokens("\n\n".join(c["text"] for c in chunk))

        num_entries_in_layer = len(next_layer)

        emit(
            "status",
            status="busy",
            message=f"Updating layered history - layer {next_layer_index} - {num_entries_in_layer} / {estimated_entries}",
            data={"cancellable": True},
        )

        summaries = await self._lh_split_and_summarize_chunks(
            chunk,
            extra_context,
            generation_options=generation_options,
        )

        self._lh_validate_summary_length(summaries, text_length)

        entry = LayeredArchiveEntry(
            start=start_index,
            end=end_index,
            ts=ts,
            ts_start=ts_start,
            ts_end=ts_end,
            text="\n\n".join(summaries),
        ).model_dump(exclude_none=True)

        next_layer.append(entry)

        emit(
            "status",
            status="busy",
            message=f"Updating layered history - layer {next_layer_index} - {num_entries_in_layer + 1} / {estimated_entries}",
        )

        return entry

    async def _lh_summarize_layer(
        self,
        source_layer: list[dict],
        next_layer_index: int,
        start_from: int,
        generation_options: GenerationOptions | None = None,
    ) -> bool:
        """
        Iterate source_layer entries from start_from, accumulating into chunks.
        When the token threshold is exceeded and the chunk has >= 2 entries,
        commit via _lh_commit_chunk. After the loop, commit any remaining
        chunk with >= 2 entries.

        Returns True if any chunk was committed.
        """
        token_threshold = self.layered_history_threshold
        current_chunk = []
        current_tokens = 0
        start_index = start_from
        committed = False

        total_tokens = util.count_tokens([entry["text"] for entry in source_layer])
        estimated_entries = total_tokens // token_threshold

        for i in range(start_from, len(source_layer)):
            entry = source_layer[i]

            # Skip static entries (manually added history without start/end)
            if entry.get("end") is None:
                continue

            entry_tokens = util.count_tokens(entry["text"])

            log.debug(
                "summarize_to_layered_history",
                entry=entry["text"][:100] + "...",
                tokens=entry_tokens,
                current_layer=next_layer_index - 1,
            )

            if current_tokens + entry_tokens > token_threshold:
                if len(current_chunk) >= 2:
                    await self._lh_commit_chunk(
                        current_chunk,
                        next_layer_index,
                        start_index,
                        i - 1,
                        estimated_entries,
                        generation_options=generation_options,
                    )
                    committed = True
                    current_chunk = []
                    current_tokens = 0
                    start_index = i

            current_chunk.append(entry)
            current_tokens += entry_tokens

        # Final chunk: require >= 2 entries AND sufficient tokens to avoid
        # premature summarization from too little content. Entries below
        # the threshold are deferred until the next call brings more data.
        if (
            current_chunk
            and len(current_chunk) >= 2
            and current_tokens >= token_threshold
        ):
            await self._lh_commit_chunk(
                current_chunk,
                next_layer_index,
                start_index,
                len(source_layer) - 1,
                estimated_entries,
                generation_options=generation_options,
            )
            committed = True

        log.debug(
            "summarize_to_layered_history",
            tokens=current_tokens,
            threshold=token_threshold,
            next_layer=next_layer_index,
        )

        return committed

    async def _lh_update_layers(
        self,
        max_layers: int,
        generation_options: GenerationOptions | None = None,
    ) -> bool:
        """
        One pass over all existing layers, summarizing each into the next.
        Returns True if any layer was updated.
        """
        layered_history = self.scene.layered_history
        any_updated = False

        for index in range(len(layered_history)):
            if index + 1 > max_layers:
                return False

            start_from = self._lh_determine_start_from(index + 1)

            log.debug("summarize_to_layered_history", layer=index, start=start_from)

            updated = await self._lh_summarize_layer(
                layered_history[index],
                index + 1,
                start_from,
                generation_options=generation_options,
            )

            if updated:
                any_updated = True

        return any_updated

    # methods

    def compile_layered_history(
        self,
        for_layer_index: int = None,
        as_objects: bool = False,
        include_base_layer: bool = False,
        max: int = None,
        base_layer_end_id: str | None = None,
    ) -> list[str]:
        """
        Starts at the last layer and compiles the layered history into a single
        list of events.

        We are iterating backwards, so the last layer will be the most granular.

        Each preceeding layer starts from the end of the the next layer.
        """

        layered_history = self.scene.layered_history
        compiled = []
        next_layer_start = None

        len_layered_history = len(layered_history)

        for i in range(len_layered_history - 1, -1, -1):
            if for_layer_index is not None:
                if i < for_layer_index:
                    break

            log.debug("compilelayered history", i=i, next_layer_start=next_layer_start)

            if not layered_history[i]:
                continue

            entry_num = 1

            for layered_history_entry in layered_history[i][
                next_layer_start if next_layer_start is not None else 0 :
            ]:
                if base_layer_end_id:
                    contained = entry_contained(
                        self.scene,
                        base_layer_end_id,
                        HistoryEntry(index=0, layer=i + 1, **layered_history_entry),
                    )
                    if contained:
                        log.debug(
                            "compile_layered_history",
                            contained=True,
                            base_layer_end_id=base_layer_end_id,
                        )
                        break

                text = f"{layered_history_entry['text']}"

                if (
                    for_layer_index == i
                    and max is not None
                    and max <= layered_history_entry["end"]
                ):
                    break

                if as_objects:
                    compiled.append(
                        {
                            "text": text,
                            "start": layered_history_entry["start"],
                            "end": layered_history_entry["end"],
                            "layer": i,
                            "layer_r": len_layered_history - i,
                            "ts_start": layered_history_entry["ts_start"],
                            "index": entry_num,
                        }
                    )
                    entry_num += 1
                else:
                    compiled.append(text)

                next_layer_start = layered_history_entry["end"] + 1

        if i == 0 and include_base_layer:
            # we are are at layered history layer zero and inclusion of base layer (archived history) is requested
            # so we append the base layer to the compiled list, starting from
            # index `next_layer_start`

            entry_num = 1

            for ah in self.scene.archived_history[next_layer_start or 0 :]:
                if base_layer_end_id and ah["id"] == base_layer_end_id:
                    break

                text = f"{ah['text']}"
                if as_objects:
                    compiled.append(
                        {
                            "text": text,
                            "start": ah["start"],
                            "end": ah["end"],
                            "layer": -1,
                            "layer_r": 1,
                            "ts": ah["ts"],
                            "index": entry_num,
                        }
                    )
                    entry_num += 1
                else:
                    compiled.append(text)

        return compiled

    @set_processing
    async def summarize_to_layered_history(
        self, generation_options: GenerationOptions | None = None
    ):
        """
        Build and maintain the layered history — a summarized archive with
        dynamic layers that get progressively less granular.

        Layer 0 summarizes archived_history, layer 1 summarizes layer 0, etc.
        Each entry's start/end are inclusive indices into the source layer.
        """

        if not self.scene.archived_history:
            return

        max_layers = self.layered_history_max_layers

        if not hasattr(self.scene, "layered_history"):
            self.scene.layered_history = []

        layered_history = self.scene.layered_history

        # Ensure layer 0 exists
        if not layered_history:
            layered_history.append([])

        # Base layer: archived_history -> layer 0
        has_been_updated = False

        try:
            start_from = self._lh_determine_start_from(0)
            log.debug("summarize_to_layered_history", layer="base", start=start_from)
            has_been_updated = await self._lh_summarize_layer(
                self.scene.archived_history,
                0,
                start_from,
                generation_options=generation_options,
            )
        except SummaryLongerThanOriginalError as exc:
            log.error("summarize_to_layered_history", error=exc, layer="base")
            emit("status", status="error", message="Layered history update failed.")
            return
        except GenerationCancelled as e:
            log.info(
                "Generation cancelled, stopping rebuild of historical layered history"
            )
            emit(
                "status",
                message="Rebuilding of layered history cancelled",
                status="info",
            )
            handle_generation_cancelled(e)
            return

        # Higher layers: iterate until no more work is produced
        try:
            while await self._lh_update_layers(max_layers, generation_options):
                has_been_updated = True
            if has_been_updated:
                emit("status", status="success", message="Layered history updated.")
        except SummaryLongerThanOriginalError as exc:
            log.error("summarize_to_layered_history", error=exc, layer="subsequent")
            emit("status", status="error", message="Layered history update failed.")
            return
        except GenerationCancelled as e:
            log.info(
                "Generation cancelled, stopping rebuild of historical layered history"
            )
            emit(
                "status",
                message="Rebuilding of layered history cancelled",
                status="info",
            )
            handle_generation_cancelled(e)
            return

    async def summarize_entries_to_layered_history(
        self,
        entries: list[dict],
        next_layer_index: int,
        start_index: int,
        end_index: int,
        generation_options: GenerationOptions | None = None,
    ) -> list[LayeredArchiveEntry]:
        """
        Re-summarize source entries for regeneration of a specific layered
        history entry.

        The caller provides the exact source entries and the start/end indices
        of the entry being regenerated. This method summarizes them into a new
        LayeredArchiveEntry (handling max_process_tokens splitting internally
        via _lh_split_and_summarize_chunks).

        Returns a single-element list containing the new LayeredArchiveEntry.
        """

        if not entries:
            return []

        ts, ts_start, ts_end = self._lh_extract_timestamps(entries)
        extra_context = self._lh_build_extra_context(next_layer_index)

        text_length = util.count_tokens("\n\n".join(e["text"] for e in entries))

        summaries = await self._lh_split_and_summarize_chunks(
            entries,
            extra_context,
            generation_options=generation_options,
        )

        self._lh_validate_summary_length(summaries, text_length)

        archive_entry = LayeredArchiveEntry(
            start=start_index,
            end=end_index,
            ts=ts,
            ts_start=ts_start,
            ts_end=ts_end,
            text="\n\n".join(summaries),
        )

        archive_entry = await self._lh_finalize_archive_entry(
            archive_entry, extra_context.split("\n\n")
        )

        return [archive_entry]
