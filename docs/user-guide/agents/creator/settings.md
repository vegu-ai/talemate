# Settings

Open by clicking the **Creator** agent in the agent list.

![Creator agent item](/talemate/img/0.30.0/creator-agent-item.png)

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