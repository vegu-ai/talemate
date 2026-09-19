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

The section opens with the **Character knowledge effort** slider. One stop sets this group and the Summarizer knowledge settings together, as an unsaved edit of this page; see [Effort presets](/talemate/user-guide/world-editor/knowledge/#effort-presets) for what each stop turns on and what it asks of your model.

Help characters respond using what they know. In **Standard** mode, use this group to filter history and memories by character knowledge. The controls below apply to Standard mode unless stated otherwise. [Character knowledge: flow reference](/talemate/user-guide/world-editor/knowledge-how-it-works/) shows what each switch does, with diagrams.

**Character perspectives**, chosen when creating a new story or importing a character card, gives characters separate views of events and memories. It can also be changed in Scene Settings while history and archived history are empty. It replaces Standard-mode history filtering; **Limit to character knowledge** is hidden while that mode is active. **Refine memories with AI** remains available in either mode. This group does not change the story's mode. See [Knowledge](/talemate/user-guide/world-editor/knowledge/#character-perspectives-opt-in) for setup, cost and retry guidance.

Limiting knowledge and character return transitions need no extra request. **Refine memories with AI** adds a request when it runs and is off by default.

![Conversation agent character knowledge settings](/talemate/img/0.40.0/conversation-character-knowledge-settings.png)

##### Limit to character knowledge

Leave out events the character missed and return only memories they know. **Turn on to base replies on their own experience; turn off to use the shared history and memories.** The filter also covers context investigations and world or other-character state notes. The character's own stored state notes and director guidance remain available; neither splits an absence into multiple markers. Missed history is replaced by one gap line, including when it crosses the summarized/live boundary in Best Fit mode. On by default.

##### Return transitions

With **Limit to character knowledge** enabled in Standard mode, or in Character perspectives mode, an actual return adds a statement at that point in the character's context: they have returned after being away, with the duration when scene time records one. Building it adds no model request. In Standard mode the absence is marked where the character left. Scene history shows the return as an **[Name] activated** chip; click the chip to add an **Arrival Note**. The chips appear in every scene, but without this setting they add nothing to any prompt. Derived timing updates automatically. The transition stays protected until the first completed reply and does not replay the departure exchange.

##### Refine memories with AI

Ask the AI to rewrite and select retrieved memories for the next character reply. **Turn on when memories need a more relevant focus.** The AI drops unhelpful memories and puts useful ones first. With **Limit to character knowledge** on, it also rewrites memories from the character's point of view and drops what they do not know. With that filter off, it only refines relevance. In Character perspectives mode, the memories are already limited to the character's knowledge.

Off by default. Uses **one more request before each generated character reply that has retrieved memories**, through the World State agent's client. The request uses the character's story context within that client's budget. If the answer cannot be read, the original retrieved memories are kept.

When **Cache RAG results** is enabled on Long Term Memory, regenerating a reply can
reuse this refinement together with its cached retrieval when the story before the
reply and the available memory sources are unchanged. Changing the refinement model,
client settings or resolved inference preset runs it again. Standard semantic-only
retrieval does not publish a shared cached result, so there is no refinement to reuse
in that configuration.

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

--8<-- "docs/snippets/tips.md:character_evidence_guidance"
