# Settings

## General

![Conversation agent general settings](/talemate/img/0.30.0/conversation-general-settings.png)

!!! note "Inference perameters"
    Inference parameters are NOT configured through any individual agent.

    Please see the [Inference presets](/talemate/user-guide/clients/presets) section for more information on how to configure inference parameters.

##### Client

The text-generation client to use for conversation generation.

##### Auto Break Repetition

If checked and talemate detects a repetitive response (based on a threshold), it will automatically re-generate the resposne with increased randomness parameters.

!!! note "Deprecated"
    This will soon be removed in favor of the new [Editor Agent Revision Action](/talemate/user-guide/agents/editor/settings#revision)

!!! note "Natural flow was moved"
    The natural flow settings have been moved to the [Director Agent](/talemate/user-guide/agents/director) settings as part of the auto direction feature.

## Generation

![Conversation agent generation settings](/talemate/img/0.29.0/conversation-generation-settings.png)

##### Format

The dialogue format as the AI will see it.

This currently comes in two choices: 

- `Screenplay`
- `Chat (legacy)`

Visually this will make no difference to what you see, it may however affect how the AI interprets the dialogue.

##### Generation Length

The maximum length of the generated dialogue. (tokens)

##### Jiggle

The amount of randomness to apply to the generation. This can help to avoid repetitive responses.

##### Task Instructions

Extra instructions for the generation. This should be short and generic as it will be applied for all characters. This will be appended to the existing task instrunctions in the conversation prompt BEFORE the conversation history.

##### Actor Instructions

General, broad isntructions for ALL actors in the scene. This will be appended to the existing actor instructions in the conversation prompt AFTER the conversation history.

##### Actor Instructions Offset

If > 0 will offset the instructions for the actor (both broad and character specific) into the history by that many turns. Some LLMs struggle to generate coherent continuations if the scene is interrupted by instructions right before the AI is asked to generate dialogue. This allows to shift the instruction backwards.

## :material-script-text: Content

![Conversation agent content settings](/talemate/img/0.30.0/conversation-content-settings.png)

Enable this setting to apply a writing style to the generated content.

Make sure the a writing style is selected in the [Scene Settings](/talemate/user-guide/world-editor/scene/settings) to apply the writing style to the generated content.

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"