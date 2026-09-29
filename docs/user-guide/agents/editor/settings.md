# Settings

## General

![Editor agent settings](/talemate/img/0.40.0/editor-agent-settings.png)

##### Client

The text-generation client to use for editor generations.

##### Optimize for Prompt Caching

Places volatile context (long term memory, dynamic notes) after the scene history so that the stable part of the prompt can be cached by API backends. May confuse weaker models. `Auto` defers to the client setting.

##### Cleanup content

If enabled the editor will automatically clean up formatting, exposition and emotes in AI and user messages.

It will do this based on the selected format. 

###### Fix narrator messages

Applies the same rules as above to the narrator messages.

###### Fix user input

Applies the same rules as above to the user input messages.

###### Allow incomplete sentences

If enabled, user input and user-edited messages will not have incomplete sentences stripped from the end.

##### Add detail

Will take the generate message and attempt to add more detail to it.

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

## Revision

![Editor agent revision settings](/talemate/img/0.40.0/editor-revision-settings-dedupe.png)

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

![Editor agent revision settings - Dedupe](/talemate/img/0.40.0/editor-revision-settings-dedupe.png)

When **Dedupe** is active it will be restricted to finding repetition and removing it without replacing it with something else, nor understanding the intent or context, so it may sometimes cause disjointed dialogue. This method is much faster as it will never prompt the AI for analysis and fixes. (If repetition detection is set to semantic similarity, it will still use the embedding function to find repetition, but it will not prompt the AI for analysis and fixes.)

**Unslop (AI assisted)**

![Editor agent revision settings - Unslop](/talemate/img/0.40.0/editor-revision-settings-unslop.png)

Example configuration using Unslop with Decision Checks enabled and Fuzzy matching
selected. Decision Checks defaults to off, and repetition detection defaults to
Semantic similarity.

When **Unslop** is active, it calls 1 additional prompt after a generation and will attempt to remove repetition, purple prose, unnatural dialogue, and over-description. May cause details to be lost. This is a general-purpose cleanup method that can also use unwanted prose detection when enabled.

**Targeted Rewrite (AI assisted)**

![Editor agent revision settings - Targeted Rewrite](/talemate/img/0.40.0/editor-revision-settings-rewrite.png)

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
Decision Checks uses this same setting for its preceding story context. The current
message is excluded; narration, character and context-investigation messages count.

##### Repetition Min. Length

The minimum length of a phrase (in characters) to be considered for repetition. Shorter phrases will be ignored.

### AI-Assisted Methods (Unslop & Targeted Rewrite)

Once switched to either **Unslop** or **Targeted Rewrite** mode, additional settings become available.

#### Repetition handling

Controls what the AI-assisted revision does when it detects repetition. (Available for both **Unslop** and **Targeted Rewrite**.)

- **Remove** (default) - flagged repetitions are deleted from the text. This is the safer choice for weaker models, which often struggle to substitute genuinely different content and end up rephrasing the same idea, re-introducing the very repetition the rule is meant to fix.
- **Attempt rewrite** - the editor asks the model to replace flagged repetitions with genuinely different content rather than deleting them. Because matches are based on meaning (not just wording), simply rephrasing the same idea is not enough - the underlying beat has to change. When the model cannot produce a meaningful rewrite, it falls back to removing the repetition. This works best with stronger models.

With Decision Checks, these choices apply to repeated beats. A reused description
of a new event instead receives fresh wording while preserving the event, even
when repetition handling is **Remove**.

#### Preferences for Rewriting (Targeted Rewrite only)

##### Test parts of sentences, split on commas

If active this means that when a sentence doesn't produce a hit, if it has one or more commas it will split the sentence on the commas and test each part individually.

##### Minimum issues

The minimum amount of issues that need to be detected to trigger a rewrite.

With Decision Checks enabled, this counts distinct flagged passages and also
applies to Unslop. A passage flagged for a repeated beat, reused description and/or
style counts once. Without Decision Checks, this setting has no effect on Unslop.

#### Unwanted Prose (Both Unslop & Targeted Rewrite)

##### Detect Unwanted Prose

Check this to enable unwanted prose detection. Available for both **Unslop** and **Targeted Rewrite** methods.

--8<-- "docs/snippets/common.md:editor-revision-unwanted-prose-requirement"

##### Unwanted Prose Threshold

Similarity threshold for unwanted prose detection. (0.4 - 1.0)

You want to keep this relatively high.

## Decision Checks

![Editor Decision Checks settings](/talemate/img/0.40.0/editor-decision-checks.png)

Decision Checks is an experimental Editor option, **off by default**. Enable the
[Decision Model](../../app-settings/decision-model.md), enable **Revision**, choose
**Targeted Rewrite** or **Unslop**, then switch on **Decision checks** inside
**Revision**. Select a [writing style with decision checks](../../templates/writing-style.md#decision-checks)
in the scene settings. This does not
enable automatic revision or change its selected targets. Automatic revision
continues to exclude player input. Dedupe is unchanged.

Each eligible invocation sends one decision request containing the complete current
text, numbered passages, preceding story messages from **Repetition Range** (15 by
default), and the
applicable writing style and active prose rules. Generated context includes its
existing task instructions and source information; summaries use their supplied
source history. This does not generate additional context with an LLM.

The writing style owns the list of checks, their questions, true/false criteria,
correction instructions and probability thresholds. Open its template editor to
change them. **Add default checks** adds four common checks in one click, including
to a new writing style:

- **Repeated beats and description reuse** asks separately about a redundant story
  beat and reused distinctive wording or imagery. The description question can
  flag a reused description of a new event; its correction preserves the event.
- **Writing style and unwanted prose** checks the style instructions and active
  prose rules.
- **Repeated dialogue and behavioural tics** asks separately about a line or
  catchphrase and about a gesture or mannerism that the same character keeps
  repeating (from the third use on).
- **Overdescription and filler prose** looks for padded description and filler
  sentences. It judges only the prose, not the dialogue.

Each default check starts at **0.80**, except **Overdescription and filler prose**
at **0.50**. Values at or above a check's threshold
select a finding; probability describes uncertainty, not severity. Edit each
threshold separately in the writing style.

New and existing styles without checks use the usual Editor detection until you
add checks. The same applies when no scene style is selected, the list is empty,
or all checks are inactive or inapplicable. No decision request is made on these
paths. A style check marked as requiring instructions or prose rules is omitted
when neither is available.

Revision uses the scene's writing style and active prose rules, including when
revising contextual generation. A style selected just for generating that content
does not replace the scene's revision style.

Successful checks **replace** fuzzy, embedding and phrase detection for that
invocation. All selected findings go into one call to the configured revision
method. If no passages qualify, or fewer than **Minimum issues** qualify, the text
stays unchanged—even with Unslop. For example, a repeated observation in the first
sentence and an unwanted phrase in the second can both be addressed by one rewrite.

When checks are off, the Decision Model is unavailable, or evaluation fails before
revision starts, the Editor uses its usual detection and revision path. The
Decision Log records failures and the fallback's outcome. A failure after a revision
starts never launches another rewrite. Cancellation or a changed scene/message
stops the operation. Oversize requests fail visibly; text is not silently truncated
or split into extra requests.

Inspect **Decision Log** in Debug Tools or the Prompt Manager to see the submitted
passages and questions, probabilities, the selected action or skip reason, and
separate decision and action durations. One successful action does not necessarily
mean the text changed: the existing response and length checks still apply.

The `editor.decision-checks` prompt renders the writing style's questions and
applies its thresholds. Prompt overrides remain subject to Revision enablement,
the selected method and the one-revision-call limit.
