# Settings

## General

![Conversation agent general settings](/talemate/img/0.29.0/conversation-general-settings.png)

!!! note "Inference perameters"
    Inference parameters are NOT configured through any individual agent.

    Please see the [Inference presets](/talemate/user-guide/clients/presets) section for more information on how to configure inference parameters.

##### Client

The text-generation client to use for conversation generation.

##### Auto Break Repetition

If checked and talemate detects a repetitive response (based on a threshold), it will automatically re-generate the resposne with increased randomness parameters.

##### Natural Flow

When there are multiple characters in the scene, this will help the AI to keep the conversation flowing naturally, making sure turns are somewhat evenly distributed, and also checking that the most relevant character gets the next turn, based on the context.

##### Max. Auto turns

Maximum turns the AI gets in succession, before the player gets a turn no matter what.

##### Max. Idle turns

The maximum number of turns a character can go without speaking before the AI will force them to speak.

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

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"