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

![Conversation agent character knowledge settings](/talemate/img/0.40.0/conversation-character-knowledge-settings.png)

Builds the prompt from the speaking character's point of view. The first five settings add no request; the items marked +1 request are off by default. See [World Editor -- Knowledge](/talemate/user-guide/world-editor/knowledge/) for how a character's knowledge is worked out.

##### Perspective filter

Drop the spans of the history the character was not present for, replaced by a one-line gap, and return only what the character knows from long term memory. Off restores the shared record for every character.

##### Absence block

Add a section to the prompt that lists the recent facts the character does not know, so the model does not let them act on those. The section is only rendered when it has content.

##### Absence block lines

At most this many facts in the block (default 5). The most restated facts come first, then the newest.

##### Absence block window

How many of the most recent facts are considered for the block (default 30).

##### Awareness line

One line in the prompt naming which topics the character knows all, some or nothing of, from the [Memory agent's topics](/talemate/user-guide/agents/memory/settings/#topics): `Edwin knows all of the Sorena, some of the sextant, nothing of the boat`. Only topics with at least three facts count, largest first, six at most; the line is left out when no topic qualifies. On by default, no request.

##### AI memory pass

One request that reads the retrieved memories together with the story context the character's prompt shows (the same perspective-filtered history, within the World State client's budget), and returns them rewritten for the character's next line: what adds nothing is dropped, the rest is ordered most useful first. With the *Perspective filter* on, each memory becomes what the character knows of it, from their own point of view, and a memory they know nothing of is dropped. With the filter off the pass only rewrites for relevance, drops what adds nothing and orders. +1 request per line, handled by the World State agent's client. Off by default. An answer that cannot be read keeps the memories as retrieved.

##### Learned-this-turn ledger

After each line, asks the AI which of the facts the listeners did not know the line revealed to them. Each becomes a grant with the source `inferred`, so the listener retrieves the fact from then on and it leaves their absence block. The speaker does not learn from their own line, and no request is sent when every listener already knows the recent facts. +1 request per line, handled by the World State agent's client. Off by default.

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

--8<-- "docs/snippets/tips.md:character_evidence_guidance"
