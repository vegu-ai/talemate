# Redefining Response Extraction

!!! info "Advanced Feature"
    This guide is intended for power users who want to customize how Talemate extracts content from LLM responses. Familiarity with the [Prompt Manager](index.md) and Jinja2 templates is recommended.

By default, most templates use an `AsIsExtractor` -- the entire LLM response is used as-is. However, you can redefine how response content is extracted by instructing the LLM to wrap its output in XML-like tags and then telling Talemate which tag to extract from.

This is useful when you want the LLM to produce structured output -- for example, separating the actual content from internal reasoning, analysis, or planning.

## How It Works

Every template declares one or more **extractors** in its header comment. For example, the conversation dialogue template declares:

```jinja2
{#-
Extractors:
  - response: AsIsExtractor()
-#}
```

This means the full LLM response is returned under the field name `response`. You can override this by calling extractor functions inside the template body. When the template is rendered, these functions register new extractors that replace the defaults.

### Available Extractor Functions

| Function | Description |
|----------|-------------|
| `set_anchor_extractor(name, left, right, ...)` | Extract content between two tags (e.g., `<DIALOGUE>...</DIALOGUE>`) |
| `set_as_is_extractor(name)` | Return the full response without modification |
| `set_after_anchor_extractor(name, start, ...)` | Extract everything after a marker |

The `set_anchor_extractor` function also accepts a `tracked_tags` parameter for nesting-aware extraction when the response contains multiple tag types (see the practical example below).

## Practical Example: Conversation Dialogue with Analysis

This example shows how to override the conversation dialogue template so that:

1. The LLM wraps its actual dialogue in a `<DIALOGUE>` tag
2. The LLM provides an `<ANALYSIS>` tag with its reasoning and plan before writing the dialogue
3. Talemate extracts only the `<DIALOGUE>` content for the scene, discarding the analysis

### Step 1: Open the Template

Open the Prompt Manager, find `conversation/dialogue-movie_script.jinja2`, and select it to open it in the editor.

### Step 2: Add the Extractor Override

Near the top of the template body (after the header comment block), add the extractor call:

```jinja2
{{ set_anchor_extractor("response", "<DIALOGUE>", "</DIALOGUE>", tracked_tags=["ANALYSIS", "DIALOGUE"]) }}
```

This tells Talemate:

- Extract the field named `response` from between `<DIALOGUE>` and `</DIALOGUE>` tags
- Be aware of both `ANALYSIS` and `DIALOGUE` tags so nesting is handled correctly
- Since `tracked_tags` is specified, a `ComplexAnchorExtractor` is used internally, which only extracts root-level `<DIALOGUE>` blocks

### Step 3: Add Instructions to the Prompt

In the task section of the template, add instructions telling the LLM about the expected response format. For example, inside the `{% block task_main_text %}` block, add:

```jinja2
Structure your response as follows:

First, provide your analysis and planning in an <ANALYSIS> tag. Consider the character's
current emotional state, their relationship with other characters, recent events,
and what would be a natural next action or response. This section will NOT be shown
to the user.

Then, provide the actual dialogue contribution in a <DIALOGUE> tag using the
screenplay format described above.

Example structure:
<ANALYSIS>
The character is feeling frustrated after the recent argument. They would likely
try to change the subject or make a sarcastic remark to mask their discomfort.
</ANALYSIS>
<DIALOGUE>
CHARACTER_NAME
Actions and "dialogue" here.
END-OF-LINE
</DIALOGUE>
```

### Step 4: Save

Save the template. Since this is a default template, saving will automatically create an override in the target group (e.g., **user**).

### What Happens at Runtime

When the LLM responds, it might produce something like:

```
<ANALYSIS>
Jane has been quiet for a while and Bob just made an insensitive comment about her
work. Given Jane's established personality -- sharp-witted but non-confrontational --
she would deflect with humor rather than engage directly. The scene has been building
tension, so a lighter moment would provide good pacing.
</ANALYSIS>
<DIALOGUE>
JANE
Pauses mid-sip of her coffee, eyebrow raised "Oh, is that what we're calling
constructive feedback now?" Sets the mug down with exaggerated care "Because I have
some constructive feedback about your tie."
END-OF-LINE
</DIALOGUE>
```

Talemate's extractor will pull out only the content between the `<DIALOGUE>` tags. The analysis is consumed by the LLM's reasoning process but never appears in your scene.

## Key Considerations

### Extraction Is Case-Insensitive

Tag matching is case-insensitive -- `<DIALOGUE>`, `<dialogue>`, and `<Dialogue>` are all equivalent.

### Fallback Behavior

If the LLM fails to produce the expected tags (which can happen with weaker models), the extracted content will be `None`. For more resilient extraction, you can enable `fallback_to_full`:

```jinja2
{{ set_anchor_extractor("response", "<DIALOGUE>", "</DIALOGUE>", fallback_to_full=True, tracked_tags=["ANALYSIS", "DIALOGUE"]) }}
```

With this, if no `<DIALOGUE>` tag is found, the entire response is returned instead -- ensuring the scene still progresses even if the model didn't follow the format.

### Token Cost

Asking the LLM to produce an analysis section increases the response token count. The analysis content is generated and billed for, even though it is discarded. The trade-off is potentially higher quality output from the structured reasoning.

### Use `tracked_tags` When Mixing Multiple Tags

When your prompt asks for multiple tagged sections, always use the `tracked_tags` parameter. This prevents the extractor from accidentally capturing content from other tags that happen to be nested inside or adjacent to your target tag.

```jinja2
{# Without tracked_tags -- simple extraction, fine for a single tag #}
{{ set_anchor_extractor("response", "<DIALOGUE>", "</DIALOGUE>") }}

{# With tracked_tags -- nesting-aware, required when multiple tags are present #}
{{ set_anchor_extractor("response", "<DIALOGUE>", "</DIALOGUE>", tracked_tags=["ANALYSIS", "DIALOGUE"]) }}
```

## Related Documentation

- [Prompt Manager](index.md) -- managing and editing templates
- [Volatile Context Placement](volatile-context-placement.md) -- optimizing prompt structure for caching
