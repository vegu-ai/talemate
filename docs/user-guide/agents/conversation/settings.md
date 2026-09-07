# Settings

## General

![Conversation agent general settings](/talemate/img/0.40.0/conversation-general-settings.png)

!!! note "Inference perameters"
    Inference parameters are NOT configured through any individual agent.

    Please see the [Inference presets](/talemate/user-guide/clients/presets) section for more information on how to configure inference parameters.

##### Client

The text-generation client to use for conversation generation.

##### Optimize for Prompt Caching

Places volatile context (long term memory, dynamic notes) after the scene history so that the stable part of the prompt can be cached by API backends. May confuse weaker models. `Auto` defers to the client setting.

!!! note "Natural flow was moved"
    The natural flow settings have been moved to the [Director Agent](/talemate/user-guide/agents/director) settings as part of the auto direction feature.

## Generation

![Conversation agent generation settings](/talemate/img/0.40.0/conversation-generation-settings.png)

##### Format

The dialogue format as the AI will see it.

This currently comes in four choices:

- `Narrative` -- dialogue is woven into narrative prose
- `Screenplay` -- traditional screenplay-style dialogue formatting
- `Chat (legacy)` -- simple chat-style formatting
- `AI Aware` -- characters are aware they are AI personas conversing with the user

!!! info "AI Aware mode"
    The **AI Aware** mode is a special conversation format where characters know they are AI personas. In this mode, characters acknowledge their artificial nature when interacting with the user, enabling more meta-aware conversations. This can be useful for experimental scenarios or when you want characters to engage in discussions about their own nature.

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

##### Include character names in stop tokens

Some models may generate the names of other characters during internal reasoning, which can cause generation to stop early. If you experience sudden generation stops, try disabling this option.

## :material-script-text: Content

![Conversation agent content settings](/talemate/img/0.40.0/conversation-content-settings.png)

Content settings control what contextual information is included in the prompts sent to the AI when generating character dialogue.

##### Use Scene Intent

When enabled (default), the [scene intent](/talemate/user-guide/world-editor/scene/direction) (overall intention) will be included in the conversation prompt. This helps the AI generate dialogue that aligns with your story goals and the current scene direction.

Disable this if you want the AI to generate dialogue without being influenced by the scene direction settings.

##### Use Writing Style

When enabled (default), the writing style selected in the [Scene Settings](/talemate/user-guide/world-editor/scene/settings) will be applied to the generated dialogue.

Disable this if you want the AI to generate dialogue without following the scene's writing style template.

## :material-head-lightbulb-outline: Character Knowledge

Help characters respond using what they know. In **Standard** mode, use this group to limit memories, remind the AI about unknown facts, and track learning from dialogue. The controls below apply to Standard mode unless stated otherwise.

**Character perspectives**, chosen when creating a new story, gives characters separate views of events and memories. It replaces the Standard-mode filtering and learning controls, which are hidden while that mode is active. **Refine memories with AI** remains available in either mode. This group does not change the story's mode. See [Knowledge](/talemate/user-guide/world-editor/knowledge/#character-perspectives-opt-in) for setup, cost and retry guidance.

![Conversation agent character knowledge settings](/talemate/img/0.40.0/conversation-character-knowledge-settings.png)

Limiting knowledge and adding reminders need no extra request. **Refine memories with AI** and **Track learning from dialogue** each add a request when they run and are off by default.

##### Limit to character knowledge

Leave out events the character missed and return only memories they know. **Turn on to base replies on their own experience; turn off to use the shared history and memories.** Missed history is replaced by a one-line gap. On by default.

##### Remind about unknown facts

Tell the AI which recent facts the character does not know. **Turn on if characters act on information they missed.** These reminders guide the model; they cannot guarantee its response. Nothing is added when there are no facts to list. On by default.

##### Unknown-fact reminders

Limit how many unknown facts are listed for the AI (default 5). **Raise to include more reminders; lower to keep the prompt shorter.** The most repeated facts come first, then the newest.

##### Recent facts to check

Choose how many recent facts to check for unknown-fact reminders (default 30). **Raise to cover older facts; lower to focus on the newest.** This changes the pool to check, while **Unknown-fact reminders** limits how many appear.

##### Topic knowledge overview

Give the AI a short overview of which topics the character knows about. **Turn on for topic-level reminders**, and enable [Topics in the Memory agent](/talemate/user-guide/agents/memory/settings/#topics). On by default, with no extra request.

For example: `Edwin knows all of the Sorena, some of the sextant, nothing of the boat`. Only topics with at least three facts count; at most six are listed, largest first. The overview is omitted when no topic qualifies. It describes recorded facts, not everything a character understands.

##### Refine memories with AI

Ask the AI to rewrite and select retrieved memories for the next character reply. **Turn on when memories need a more relevant focus.** The AI drops unhelpful memories and puts useful ones first. With **Limit to character knowledge** on, it also rewrites memories from the character's point of view and drops what they do not know. With that filter off, it only refines relevance. In Character perspectives mode, the memories are already limited to the character's knowledge.

Off by default. Uses **one more request before each generated character reply that has retrieved memories**, through the World State agent's client. The request uses the character's story context within that client's budget. If the answer cannot be read, the original retrieved memories are kept.

##### Track learning from dialogue

Ask the AI what listeners learned from each character message and add those facts to their knowledge. **Turn on to track information shared in dialogue.** It checks recent recorded facts the listeners do not know, so it can recognize retold information rather than discover arbitrary new facts. Learned facts become available in memory and leave the unknown-fact reminders. The speaker does not learn from their own message; player messages are included.

Off by default. Uses **one more request after a character message when a listener has recent facts they do not know**, through the World State agent's client. No request is sent when every listener already knows those facts. Available in Standard mode only.

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

--8<-- "docs/snippets/tips.md:character_evidence_guidance"
