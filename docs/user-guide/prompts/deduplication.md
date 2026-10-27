# Prompt Deduplication

Talemate can run a line-level fuzzy-dedupe pass over a rendered prompt before sending it to the language model. The pass removes lines longer than 32 characters whose similarity to an earlier line is ≥95% — useful when the same paragraph slips into a prompt from multiple context sources (world info, memories, pins).

## Recommendation: leave it off

Deduplication is **off by default** at the client level and that is the recommended setting for most users.

The feature was useful when 4k–8k context windows made every token expensive. With modern 16k–1M context windows the token savings rarely justify the trade-offs:

- **It breaks prompt caching.** Anthropic, OpenAI, and Google all cache prompt prefixes to cut latency and cost. Dedupe rewrites the prompt body line-by-line, so any time a duplicate appears (or disappears) the cached prefix is invalidated. With **[Optimize for Prompt Caching](volatile-context-placement.md)** enabled, dedupe will often hurt cache hit-rate enough to outweigh the tokens it saves.
- **It can damage structured content.** Beat listings, example tables, or any template that repeats long near-identical lines can collapse under the similarity threshold and reach the model malformed.

Only consider turning dedupe on when **all** of these hold:

- You are operating with a context window of `≤ 8192` tokens.
- RAG, world info, or pins are producing substantial duplication in your prompts.
- You are not using an API backend whose prompt-caching savings matter to you.

## How to enable it

The primary control is the per-client **Deduplicate Prompts** toggle in the **Advanced** section of each client's editor. Flipping this on enables dedupe for every prompt that does not explicitly override it.

Templates and node graphs can still opt out individually after that:

### From inside a template

Call `disable_dedupe()` once at the top of the template (or anywhere before the structured content):

```jinja2
{{ disable_dedupe() }}
<|SECTION:BEATS|>
Beat 1: Alice confronts Bob about the missing ledger.
Beat 2: Alice confronts Bob about the missing ring.
Beat 3: Alice confronts Bob about the missing key.
<|CLOSE_SECTION|>
```

Without this guard, the three beats above are similar enough that dedupe would collapse them into one line. See the [`disable_dedupe()` function reference](../node-editor/reference/template_functions.md#disable_dedupe) for the full function entry.

### From a `Prompt from Template` node

The node has a `dedupe` property that forces the setting on or off for the prompt it produces, regardless of the client-level toggle. See the node's [Properties reference](../node-editor/core-concepts/prompt-templates.md#prompt-from-template) for full details.

## Scope and interactions

- A `disable_dedupe()` call or node property only affects the prompt it is rendered into. It does **not** cascade to other prompts in the same flow.
- Dedupe is separate from the [`condensed`](../node-editor/reference/template_functions.md) template filter. The condensed filter uses its own marker-based mechanism to collapse multi-line context for the dedupe comparison and does not rely on the dedupe pass itself. Toggling dedupe leaves the condensed filter's behavior unchanged.
