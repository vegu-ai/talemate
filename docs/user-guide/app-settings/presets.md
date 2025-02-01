# :material-tune: Presets

Change inference parameters, embedding parameters and global system prompt overrides.

## :material-matrix: Inference

!!! danger "Advanced settings. Use with caution."
    If these settings don't mean anything to you, you probably shouldn't be changing them. They control the way the AI generates text and can have a big impact on the quality of the output.

    This document will NOT explain what each setting does.

![App settings - Application](/talemate/img/0.29.0/app-settings-presets-inference.png)

If you're familiar with editing inference parameters from other similar applications, be aware that there is a significant difference in how TaleMate handles these settings.

Agents take different actions, and based on that action one of the presets is selected. 

That means that ALL presets are relevant and will be used at some point.

For example analysis will use the `Anlytical` preset, which is configured to be less random and more deterministic.

The `Conversation` preset is used by the conversation agent during dialogue gneration.

The other presets are used for various creative tasks.

These are all experimental and will probably change / get merged in the future.

## :material-cube-unfolded: Embeddings

![App settings - Application](/talemate/img/0.29.0/app-settings-presets-embeddings.png)

Allows you to add, remove and manage various embedding models for the memory agent to use via chromadb.

--8<-- "docs/user-guide/agents/memory/embeddings.md:embeddings_setup"

## :material-text-box: System Prompts

![App settings - Application](/talemate/img/0.29.0/app-settings-presets-system-prompts.png)

This allows you to override the global system prompts for the entire application for each overarching prompt kind.

If these are not set the default system prompt will be read from the templates that exist in `src/talemate/prompts/templates/{agent}/system-*.jinja2`.

This is useful if you want to change the default system prompts for the entire application.

The effect these have, varies from model to model.

### Prompt types

- Conversation - Use for dialogue generation.
- Narration - Used for narrative generation.
- Creation - Used for other creative tasks like making new characters, locations etc.
- Direction - Used for guidance prompts and general scene direction.
- Analysis (JSON) - Used for analytical tasks that expect a JSON response.
- Analysis - Used for analytical tasks that expect a text response.
- Editing - Used for post-processing tasks like fixing exposition, adding detail etc.
- World State - Used for generating world state information. (This is sort of a mix of analysis and creation prompts.)
- Summarization - Used for summarizing text.

### Normal / Uncensored

Overrides are maintained for both normal and uncensored modes.

Currently local API clients (koboldcpp, textgenwebui, tabbyapi, llmstudio) will use the uncensored prompts, while the clients targeting official third party APIs will use the normal prompts.

The uncensored prompts are a work-around to prevent the LLM from refusing to generate text based on topic or content.


!!! note "Future plans"
    A toggle to switch between normal and uncensored prompts regardless of the client is planned for a future release.
