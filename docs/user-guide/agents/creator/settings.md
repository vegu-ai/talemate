# Settings

Open by clicking the **Creator** agent in the agent list.

![Creator agent item](/talemate/img/0.30.0/creator-agent-item.png)

## Character Creation

These settings control how AI-assisted character creation generates characters —
this applies everywhere characters are created with AI assistance: the world
editor, the scene tools character introduction and character card import.
The `Generate Character` node follows these settings as well.

##### Fast Character Generation

When enabled, character generation is consolidated into a **single prompt**
instead of one prompt per aspect. This is much faster (one request instead
of several), but note that less detail in the individual aspects is a
possible failure mode of this approach, and the model needs a large context
window and reliable structured output. Keep this off for older or smaller
models.

Off by default. Can also be flipped quickly via the quick-toggle chip.

When the scene has a writing style template configured, the consolidated
prompt applies it.

##### Consolidate

Visible when **Fast Character Generation** is enabled. Selects which
aspects the consolidated prompt generates: *Name*, *Description*,
*Attributes*, *Dialogue instructions* and/or *Example dialogue*. Aspects not
selected are still generated with their individual prompts.

The additional *Attribute templates* entry folds attribute world-state
templates selected during character creation into the consolidated prompt as
per-attribute instructions, instead of running one prompt per template. It
requires *Attributes* to be selected as well — otherwise the templates apply
per-template as before. `{character_name}` placeholders in the template text
are formatted with the character's name, or "the character" while the name
is still being determined.

Defaults to everything (all aspects and *Attribute templates*).

Note that when the one-shot produces the example dialogue itself, the
`agent.creator.dialogue_examples` node-graph events are not emitted (they
fire on the split flow and on fill-in-misses regeneration only).

##### One-shot token budget

Visible when **Fast Character Generation** is enabled. The maximum response
tokens for the consolidated prompt (1024–8192, default 4096). All
consolidated aspects share this budget — if the response is truncated,
later sections come out missing and are regenerated individually when
**Fill in misses** is on.

##### Fill in misses

Visible when **Fast Character Generation** is enabled. When the
consolidated response misses an aspect entirely, that aspect's individual
request is run to fill it in. When disabled, missed aspects are left empty.

A completely unparseable consolidated response is always a hard error,
regardless of this setting.

On by default.

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

## Autocomplete

These settings control the [Autocomplete](/talemate/user-guide/agents/creator/autocomplete) feature.

![Conversation agent autocomplete settings](/talemate/img/0.38.0/creator-autocomplete-settings.png)

##### Dialogue Suggestion Length

How many tokens to generate (max.) when autocompleting character actions.

##### Narrative Suggestion Length

How many tokens to generate (max.) when autocompleting narrative text.

##### Enable Hints

When enabled (the default), a trailing `{...}` block at the end of your input is treated as a hint that steers the continuation, and is stripped from the field once the suggestion is accepted.

When disabled, any trailing `{...}` is treated as ordinary text and sent as part of your input.

See [Steering the continuation with hints](/talemate/user-guide/agents/creator/autocomplete/#steering-the-continuation-with-hints) for details.