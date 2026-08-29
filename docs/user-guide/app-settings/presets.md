# :material-tune: Presets

Change inference parameters, embedding parameters and global system prompt overrides. The **Presets** group in the settings sidebar holds three pages: **Inference**, **Embeddings** and **System Prompts**.

## :material-matrix: Inference

!!! danger "Advanced settings. Use with caution."
    If these settings don't mean anything to you, you probably shouldn't be changing them. They control the way the AI generates text and can have a big impact on the quality of the output.

    This document will NOT explain what each setting does.

![App settings - Presets - Inference](/talemate/img/0.39.0/app-settings-presets-inference.png)

If you're familiar with editing inference parameters from other similar applications, be aware that there is a significant difference in how TaleMate handles these settings.

Agents take different actions, and based on that action one of the presets is selected. 

That means that ALL presets are relevant and will be used at some point.

For example analysis will use the `Anlytical` preset, which is configured to be less random and more deterministic.

The `Conversation` preset is used by the conversation agent during dialogue gneration.

The other presets are used for various creative tasks.

These are all experimental and will probably change / get merged in the future.

## :material-cube-unfolded: Embeddings

![App settings - Presets - Embeddings](/talemate/img/0.39.0/app-settings-presets-embeddings.png)

Allows you to add, remove and manage various embedding models for the memory agent to use via chromadb.

--8<-- "docs/user-guide/agents/memory/embeddings.md:embeddings_setup"

## :material-text-box: System Prompts

![App settings - Presets - System Prompts](/talemate/img/0.39.0/app-settings-presets-system-prompts.png)

This panel lets you override the global system prompts for the entire application for each prompt kind (Conversation, Narration, Creation, and so on). Per-client overrides live on the **System Prompts** tab of each client's [configuration dialog](../clients/client-configuration.md).

See [System Prompt Overrides](system-prompts.md) for the full reference, including:

- Which prompt kinds exist and what they are used for.
- How Normal and Uncensored variants are selected.
- The pencil icon that marks entries with an active override (added in 0.37.0).
- How to include the default prompt inside your override with `{{ system_prompt }}` (added in 0.37.0).
