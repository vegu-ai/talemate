import structlog
from typing import TYPE_CHECKING, Callable
from talemate.agents.base import (
    set_processing,
    AgentAction,
    AgentActionConfig
)
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

class SummaryLongerThanOriginalError(ValueError):
    def __init__(self, original_length:int, summarized_length:int):
        self.original_length = original_length
        self.summarized_length = summarized_length
        super().__init__(f"Summarized text is longer than original text: {summarized_length} > {original_length}")


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
                    ]
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
        return self.layered_history_enabled and self.scene.layered_history and self.scene.layered_history[0]
    
    
    # signals
    
    def connect(self, scene):
        super().connect(scene)
        talemate.emit.async_signals.get("agent.summarization.after_build_archive").connect(
            self.on_after_build_archive
        )
    
    
    async def on_after_build_archive(self, emission:"BuildArchiveEmission"):
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
            while current_chunk and util.count_tokens("\n\n".join(chunk['text'] for chunk in partial_chunk)) < max_process_tokens:
                partial_chunk.append(current_chunk.pop(0))
            
            text_to_summarize = "\n\n".join(chunk['text'] for chunk in partial_chunk)
            
            log.debug("_split_and_summarize_chunks", 
                     tokens_in_chunk=util.count_tokens(text_to_summarize), 
                     max_process_tokens=max_process_tokens)
            
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
        
        log.debug("_validate_summary_length", 
                 original_length=original_length, 
                 summarized_length=summarized_length)
    
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
            
        ts = chunk[0].get('ts', 'PT1S')
        ts_start = chunk[0].get('ts_start', ts)
        ts_end = chunk[-1].get('ts_end', chunk[-1].get('ts', ts))
        
        return ts, ts_start, ts_end
    
    # methods

    def compile_layered_history(
        self, 
        for_layer_index:int = None, 
        as_objects:bool=False, 
        include_base_layer:bool=False,
        max:int = None,
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
            
            for layered_history_entry in layered_history[i][next_layer_start if next_layer_start is not None else 0:]:
                
                if base_layer_end_id:
                    contained = entry_contained(self.scene, base_layer_end_id, HistoryEntry(
                        index=0,
                        layer=i+1,
                        **layered_history_entry)
                    )
                    if contained:
                        log.debug("compile_layered_history", contained=True, base_layer_end_id=base_layer_end_id)
                        break
                
                text = f"{layered_history_entry['text']}"
                
                if for_layer_index == i and max is not None and max <= layered_history_entry["end"]:
                    break
                
                if as_objects:
                    compiled.append({
                        "text": text,
                        "start": layered_history_entry["start"],
                        "end": layered_history_entry["end"],
                        "layer": i,
                        "layer_r": len_layered_history - i,
                        "ts_start": layered_history_entry["ts_start"],
                        "index": entry_num,
                    })
                    entry_num += 1
                else:
                    compiled.append(text)
            
                next_layer_start = layered_history_entry["end"] + 1
            
        if i == 0 and include_base_layer:
            # we are are at layered history layer zero and inclusion of base layer (archived history) is requested
            # so we append the base layer to the compiled list, starting from
            # index `next_layer_start`
            
            entry_num = 1
            
            for ah in self.scene.archived_history[next_layer_start or 0:]:
                
                if base_layer_end_id and ah["id"] == base_layer_end_id:
                    break
                
                text = f"{ah['text']}"
                if as_objects:
                    compiled.append({
                        "text": text,
                        "start": ah["start"],
                        "end": ah["end"],
                        "layer": -1,
                        "layer_r": 1,
                        "ts": ah["ts"],
                        "index": entry_num,
                    })
                    entry_num += 1
                else:
                    compiled.append(text)
            
        return compiled
    
    @set_processing
    async def summarize_to_layered_history(self, generation_options: GenerationOptions | None = None):
        
        """
        The layered history is a summarized archive with dynamic layers that
        will get less and less granular as the scene progresses.
        
        The most granular is still self.scene.archived_history, which holds
        all the base layer summarizations.
        
        self.scene.layered_history = [
            # first layer after archived_history
            [
                {
                    "start": 0, # index in self.archived_history
                    "end": 10, # index in self.archived_history
                    "ts": "PT5M",
                    "text": "A summary of the first 10 entries"
                },
                ...
            ],
            
            # second layer
            [
                {
                    "start": 0, # index in self.scene.layered_history[0]
                    "end": 5, # index in self.scene.layered_history[0]
                    "ts": "PT2M",
                    "text": "A summary of the first 5 entries"
                },
                ...
            ],
            
            # additional layers
            ...
        ]
        
        The same token threshold as for the base layer will be used for the
        layers.
        
        The same summarization function will be used for the layers.
        
        The next level layer will be generated automatically when the token
        threshold is reached.
        """
        
        if not self.scene.archived_history:
            return  # No base layer summaries to work with
        
        token_threshold = self.layered_history_threshold
        max_layers = self.layered_history_max_layers

        if not hasattr(self.scene, 'layered_history'):
            self.scene.layered_history = []
            
        layered_history = self.scene.layered_history

        async def summarize_layer(source_layer, next_layer_index, start_from) -> bool:
            current_chunk = []
            current_tokens = 0
            start_index = start_from
            noop = True
            
            total_tokens_in_previous_layer = util.count_tokens([
                entry['text'] for entry in source_layer
            ])
            estimated_entries = total_tokens_in_previous_layer // token_threshold

            for i in range(start_from, len(source_layer)):
                entry = source_layer[i]
                entry_tokens = util.count_tokens(entry['text'])
                
                log.debug("summarize_to_layered_history", entry=entry["text"][:100]+"...", tokens=entry_tokens, current_layer=next_layer_index-1)
                
                if current_tokens + entry_tokens > token_threshold:
                    if current_chunk:
                        
                        try:
                            # check if the next layer exists
                            next_layer = layered_history[next_layer_index]
                        except IndexError:
                            # create the next layer
                            layered_history.append([])
                            log.debug("summarize_to_layered_history", created_layer=next_layer_index)
                            next_layer = layered_history[next_layer_index]
                                
                        ts, ts_start, ts_end = self._lh_extract_timestamps(current_chunk)
                        
                        extra_context = self._lh_build_extra_context(next_layer_index)

                        text_length = util.count_tokens("\n\n".join(chunk['text'] for chunk in current_chunk))

                        num_entries_in_layer = len(layered_history[next_layer_index])

                        emit("status", status="busy", message=f"Updating layered history - layer {next_layer_index} - {num_entries_in_layer} / {estimated_entries}", data={"cancellable": True})
                        
                        summaries = await self._lh_split_and_summarize_chunks(
                            current_chunk,
                            extra_context,
                            generation_options=generation_options,
                        )
                        noop = False
                            
                        # validate summary length
                        self._lh_validate_summary_length(summaries, text_length)
                        
                        next_layer.append(LayeredArchiveEntry(**{
                            "start": start_index,
                            "end": i,
                            "ts": ts,
                            "ts_start": ts_start,
                            "ts_end": ts_end,
                            "text": "\n\n".join(summaries),
                        }).model_dump(exclude_none=True))
                        
                        emit("status", status="busy", message=f"Updating layered history - layer {next_layer_index} - {num_entries_in_layer+1} / {estimated_entries}")
                            
                        current_chunk = []
                        current_tokens = 0
                        start_index = i

                current_chunk.append(entry)
                current_tokens += entry_tokens
                
            log.debug("summarize_to_layered_history", tokens=current_tokens, threshold=token_threshold, next_layer=next_layer_index)
            
            return not noop
                
        
        # First layer (always the base layer)
        has_been_updated = False
        
        try:
        
            if not layered_history:
                layered_history.append([])
                log.debug("summarize_to_layered_history", layer="base", new_layer=True)
                has_been_updated = await summarize_layer(self.scene.archived_history, 0, 0)
            elif layered_history[0]:
                # determine starting point by checking for `end` in the last entry
                last_entry = layered_history[0][-1]
                end = last_entry["end"]
                log.debug("summarize_to_layered_history", layer="base", start=end)
                has_been_updated = await summarize_layer(self.scene.archived_history, 0, end)
            else:
                log.debug("summarize_to_layered_history", layer="base", empty=True)
                has_been_updated = await summarize_layer(self.scene.archived_history, 0, 0)
                
        except SummaryLongerThanOriginalError as exc:
            log.error("summarize_to_layered_history", error=exc, layer="base")
            emit("status", status="error", message="Layered history update failed.")
            return
        except GenerationCancelled as e:
            log.info("Generation cancelled, stopping rebuild of historical layered history")
            emit("status", message="Rebuilding of layered history cancelled", status="info")
            handle_generation_cancelled(e)
            return
            
        # process layers
        async def update_layers() -> bool:
            noop = True
            for index in range(0, len(layered_history)):
                
                # check against max layers
                if index + 1 > max_layers:
                    return False
                
                try:
                    # check if the next layer exists
                    next_layer = layered_history[index + 1]
                except IndexError:
                    next_layer = None
                
                end = next_layer[-1]["end"] if next_layer else 0
                
                log.debug("summarize_to_layered_history", layer=index, start=end)
                summarized = await summarize_layer(layered_history[index], index + 1, end if end else 0)
                
                if summarized:
                    noop = False
                    
            return not noop
        
        try:
            while await update_layers():
                has_been_updated = True
            if has_been_updated:
                emit("status", status="success", message="Layered history updated.")
            
        except SummaryLongerThanOriginalError as exc:
            log.error("summarize_to_layered_history", error=exc, layer="subsequent")
            emit("status", status="error", message="Layered history update failed.")
            return
        except GenerationCancelled as e:
            log.info("Generation cancelled, stopping rebuild of historical layered history")
            emit("status", message="Rebuilding of layered history cancelled", status="info")
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
        Summarizes a list of entries into layered history entries.
        
        This method is used for regenerating specific history entries by processing
        their source entries. It chunks the entries based on the token threshold and
        summarizes each chunk into a LayeredArchiveEntry.
        
        Args:
            entries: List of dictionaries containing the text entries to summarize.
                    Each entry should have at least a 'text' field and optionally
                    'ts', 'ts_start', and 'ts_end' fields.
            next_layer_index: The index of the layer where the summarized entries
                            will be placed.
            start_index: The starting index in the source layer that these entries
                        correspond to.
            end_index: The ending index in the source layer that these entries
                      correspond to.
            generation_options: Optional generation options to pass to the summarization
                              process.
        
        Returns:
            List of LayeredArchiveEntry objects containing the summarized text along
            with timestamp and index information. Currently returns a list with a
            single entry, but the structure supports multiple entries if needed.
        
        Notes:
            - The method respects the layered_history_threshold for chunking
            - Uses helper methods for timestamp extraction, context building, and
              chunk summarization
            - Validates that summaries are not longer than the original text
            - The last entry is always included in the final chunk if it doesn't
              exceed the token threshold
        """
        
        token_threshold = self.layered_history_threshold
                            
        archive_entries = []
        summaries = []
        current_chunk = []
        current_tokens = 0
        
        ts = "PT1S"
        ts_start = "PT1S"
        ts_end = "PT1S"
        
        
        for entry_index, entry in enumerate(entries):
            is_last_entry = entry_index == len(entries) - 1
            entry_tokens = util.count_tokens(entry['text'])
            
            log.debug("summarize_entries_to_layered_history", entry=entry["text"][:100]+"...", entry_tokens=entry_tokens, current_layer=next_layer_index-1, current_tokens=current_tokens)
            
            if current_tokens + entry_tokens > token_threshold or is_last_entry:
                
                if is_last_entry and current_tokens + entry_tokens <= token_threshold:
                    # if we are here because this is the last entry and adding it to
                    # the current chunk would not exceed the token threshold, we will
                    # add it to the current chunk
                    current_chunk.append(entry)
                
                if current_chunk:
                    ts, ts_start, ts_end = self._lh_extract_timestamps(current_chunk)

                    extra_context = self._lh_build_extra_context(next_layer_index)

                    text_length = util.count_tokens("\n\n".join(chunk['text'] for chunk in current_chunk))

                    summaries = await self._lh_split_and_summarize_chunks(
                        current_chunk,
                        extra_context,
                        generation_options=generation_options,
                    )
                        
                    # validate summary length
                    self._lh_validate_summary_length(summaries, text_length)
                    
                    archive_entry = LayeredArchiveEntry(**{
                        "start": start_index,
                        "end": end_index,
                        "ts": ts,
                        "ts_start": ts_start,
                        "ts_end": ts_end,
                        "text": "\n\n".join(summaries),
                    })
                    
                    archive_entries.append(archive_entry)

            current_chunk.append(entry)
            current_tokens += entry_tokens
            
        return archive_entries