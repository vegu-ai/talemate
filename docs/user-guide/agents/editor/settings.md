# Settings

## General

![Editor agent settings](/talemate/img/0.29.0/editor-agent-settings.png)

##### Fix exposition

If enabled the editor will attempt to fix exposition in the generated dialogue.

It will do this based on the selected format. 

###### Fix narrator messages

Applies the same rules as above to the narrator messages.

###### Fix user input

Applies the same rules as above to the user input messages.

##### Add detail

Will take the generate message and attempt to add more detail to it.

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

## Revision

![Editor agent revision settings](/talemate/img/0.38.0/editor-revision-settings-dedupe.png)

When :material-typewriter: revision is enabled the editor will analyze and attempt to fix character messages, narrator messages, and contextual generation (such as character attributes, details, world context, etc.).

Currently it can detect the following issues:

- Repetition of phrases / concepts
- Unwanted prose as defined in the writing style

The revision action is split into three parts:

- Find any issues through fuzzy, regex and semantic similarity (embeddings) matching
- Analyze the issues and plan a fix
- Apply the fix

This means it comes at a noticable delay IF it finds issues, but the improvements may be worth it.

##### Enable Revision

Check this to enable revision.

##### Automatic Revision

Check this to enable automatic revision - this will analyze each incoming actor or narrator message and attempt to fix it if there are issues.

##### Automatic Revision Targets

When automatic revision is enabled, you can choose which types of messages to automatically revise:

- **Character Messages** - Automatically revise actor actions and dialogue
- **Narration Messages** - Automatically revise narrator actions and descriptions  
- **Context Investigations** - Automatically revise context-investigation messages (the results of **Look at**, **Investigate**, and **Query** actions). Off by default.
- **Contextual generation** - Automatically revise generated context such as character attributes, details, world context, scene intros, etc.
- **Summarization** - Automatically revise dialogue summaries.

By default, both Character Messages and Narration Messages are enabled. You can enable or disable each type independently based on your preferences.

!!! note "Context investigations always feed the repetition check"
    Whether or not **Context Investigations** is enabled as an automatic target, context-investigation messages are always included in the text the editor compares against when looking for repetition. This means nearby character and narrator messages will avoid repeating phrases that already appeared in a recent **Look at**, **Investigate**, or **Query** result.

##### Revision Method

Which method to use to fix issues. 

- `Dedupe (Fast and dumb)` - this is the default
- `Unslop (AI assisted)` - calls 1 additional prompt after generation to remove repetition, purple prose, unnatural dialogue, and over-description
- `Targeted Rewrite (AI assisted)` - analyzes text for specific issues and rewrites only problematic parts

**Dedupe (Fast and dumb)**

![Editor agent revision settings - Dedupe](/talemate/img/0.38.0/editor-revision-settings-dedupe.png)

When **Dedupe** is active it will be restricted to finding repetition and removing it without replacing it with something else, nor understanding the intent or context, so it may sometimes cause disjointed dialogue. This method is much faster as it will never prompt the AI for analysis and fixes. (If repetition detection is set to semantic similarity, it will still use the embedding function to find repetition, but it will not prompt the AI for analysis and fixes.)

**Unslop (AI assisted)**

![Editor agent revision settings - Unslop](/talemate/img/0.38.0/editor-revision-settings-unslop.png)

When **Unslop** is active, it calls 1 additional prompt after a generation and will attempt to remove repetition, purple prose, unnatural dialogue, and over-description. May cause details to be lost. This is a general-purpose cleanup method that can also use unwanted prose detection when enabled.

**Targeted Rewrite (AI assisted)**

![Editor agent revision settings - Targeted Rewrite](/talemate/img/0.38.0/editor-revision-settings-rewrite.png)

When **Targeted Rewrite** is active, unwanted prose detection becomes available and when issues are detected the AI will attempt to rewrite the message to fix the issues. This method checks for specific problems first, then only rewrites if enough issues are found.

#### Repetition

##### Repetition Detection Method

How is repetition detected.

- `Fuzzy` - fuzzy matching will match based on character-level similarity, finding text that is approximately the same with small differences (like typos, missing letters, or minor variations). This is faster but less context-aware than semantic matching.
- `Semantic Similarity` - will match based on the semantic meaning of the text using the Memory Agent's embedding function. (default)

!!! warning "Semantic Similarity"
    Uses the memory agent's embedding function to compare the text. Will use batching when available, but has the potential to do A LOT of calls to the embedding model.

##### Similarity Threshold

How similar does the text need to be to be considered repetitive. (50 - 100%)

You want to keep this relatively high.

##### Repetition Range

This is the number of **MESSAGES** to consider in the history when checking for repetition.

At its default of `15` it means the last 15 messages will be considered.

##### Repetition Min. Length

The minimum length of a phrase (in characters) to be considered for repetition. Shorter phrases will be ignored.

### AI-Assisted Methods (Unslop & Targeted Rewrite)

Once switched to either **Unslop** or **Targeted Rewrite** mode, additional settings become available.

#### Repetition handling

Controls what the AI-assisted revision does when it detects repetition. (Available for both **Unslop** and **Targeted Rewrite**.)

- **Remove** (default) - flagged repetitions are deleted from the text. This is the safer choice for weaker models, which often struggle to substitute genuinely different content and end up rephrasing the same idea, re-introducing the very repetition the rule is meant to fix.
- **Attempt rewrite** - the editor asks the model to replace flagged repetitions with genuinely different content rather than deleting them. Because matches are based on meaning (not just wording), simply rephrasing the same idea is not enough - the underlying beat has to change. When the model cannot produce a meaningful rewrite, it falls back to removing the repetition. This works best with stronger models.

#### Preferences for Rewriting (Targeted Rewrite only)

##### Test parts of sentences, split on commas

If active this means that when a sentence doesn't produce a hit, if it has one or more commas it will split the sentence on the commas and test each part individually.

##### Minimum issues

The minimum amount of issues that need to be detected to trigger a rewrite.

#### Unwanted Prose (Both Unslop & Targeted Rewrite)

##### Detect Unwanted Prose

Check this to enable unwanted prose detection. Available for both **Unslop** and **Targeted Rewrite** methods.

--8<-- "docs/snippets/common.md:editor-revision-unwanted-prose-requirement"

##### Unwanted Prose Threshold

Similarity threshold for unwanted prose detection. (0.4 - 1.0)

You want to keep this relatively high.
