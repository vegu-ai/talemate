# Layered History

Layered history is Talemate's system for keeping a compressed record of your entire scene history within the AI's context window. As your scene progresses, older dialogue is summarized into archived entries. Those archived entries are then summarized again into increasingly compressed layers, creating a detail gradient: recent events are preserved in full, while older events are condensed down to their essential points.

This means the AI can reference events from much earlier in your story, albeit with less detail the further back it looks.

## How It Works

### Base Layer (Layer 0)

The base layer contains two types of entries:

- **Static entries** -- manually written history entries that predate the scene's starting point (backstory, world events, etc.)
- **Summary entries** -- automatically generated when the scene's dialogue exceeds a token threshold. The [Summarizer Agent](/talemate/user-guide/agents/summarizer/) condenses recent dialogue into an archived summary

### Higher Layers (Layer 1+)

Once the base layer accumulates enough entries, they are summarized again into Layer 1. Layer 1 entries are further compressed into Layer 2, and so on. Each successive layer is more compressed than the last.

In practice, useful compression typically tops out around Layer 3, where individual events may be reduced to single sentences. We have observed diminishing returns at Layer 4 and beyond — further compression yields little meaningful reduction and more work is needed to improve deep layer quality.

### Detail Gradient

The result is a natural detail gradient in the AI's context:

1. **Recent dialogue** -- verbatim, full detail
2. **Base layer summaries** -- moderate compression, recent past
3. **Layer 1** -- higher compression, earlier events
4. **Layer 2+** -- maximum compression, oldest events

## Compression Statistics

The history tools menu displays compression statistics for each layer, showing:

- Number of entries per layer
- Compression rate (how much the content was reduced)
- Token counts

This helps you understand how effectively the layered system is compressing your history and whether your settings are producing good results.

## Configuration

Layered history is managed by the [Summarizer Agent](/talemate/user-guide/agents/summarizer/) and can be enabled or disabled in its [settings](/talemate/user-guide/agents/summarizer/settings/#layered-history). Key settings include:

- **Enable layered history** -- toggle the feature on or off
- **Token threshold** -- how many tokens accumulate in a layer before triggering summarization to the next layer
- **Maximum number of layers** -- caps layer depth (default 3; diminishing returns beyond this)
- **Maximum tokens to process** -- controls chunk splitting for smaller LLMs
- **Chunk size** -- character length of chunks during summarization
- **Enable analyzation** -- adds a relationship analysis step between chunks before summarizing, improving quality at the cost of longer output

## Managing Layered History

History entries across all layers can be viewed and managed in the [History](index.md) panel:

- **Edit** entries by double-clicking their text
- **Regenerate** summary entries to re-run the summarization
- **Inspect** summary entries to see the source entries they were derived from
- **Regenerate all** to rebuild the entire history from scratch (static entries are preserved)

## Layered History in Context

The [Scene Context History Review](/talemate/user-guide/prompts/context-history-review/) panel shows exactly how layered history is rendered into the AI's context, with token counts and budget allocation per section. Use it to tune how much of the context budget goes to compressed history versus recent dialogue.

## Related Documentation

- [Summarizer Agent Settings](/talemate/user-guide/agents/summarizer/settings/#layered-history) -- configuring layered history parameters
- [History](index.md) -- managing history entries
- [Scene Context History Review](/talemate/user-guide/prompts/context-history-review/) -- visualizing context assembly
- [Reset Scene State](/talemate/user-guide/scene-state-reset/) -- resetting history and other scene data
