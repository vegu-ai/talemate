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

The section opens with the **Character knowledge effort** slider. One stop sets this group and the Summarizer and Memory knowledge settings together, as an unsaved edit of this page; see [Effort presets](/talemate/user-guide/world-editor/knowledge/#effort-presets) for what each stop turns on and what it asks of your model.

Help characters respond using what they know. In **Standard** mode, use this group to limit memories, remind the AI about unknown facts, and track learning from dialogue. The controls below apply to Standard mode unless stated otherwise. [How character knowledge works](/talemate/user-guide/world-editor/knowledge-how-it-works/) shows what each switch does, with diagrams.

The **Character Knowledge** master switch also supplies **Known facts** and **Unknown recent facts** to the Summarizer's [conversation analysis](/talemate/user-guide/agents/summarizer/settings/#conversation), when Scene Analysis is enabled. These lists apply even if **Limit to character knowledge** or **Remind about unknown facts** is off. Turning the master switch off removes them. Each list uses up to one sixth of the analysis client's context budget, plus headings, reserved from scene history; they add no AI request and are omitted when neither list has facts that fit.

**Character perspectives**, chosen when creating a new story or importing a character card, gives characters separate views of events and memories. It can also be changed in Scene Settings while history and archived history are empty. It replaces the Standard-mode filtering and learning controls, which are hidden while that mode is active. **Refine memories with AI** remains available in either mode. This group does not change the story's mode. See [Knowledge](/talemate/user-guide/world-editor/knowledge/#character-perspectives-opt-in) for setup, cost and retry guidance.

![Conversation agent character knowledge settings](/talemate/img/0.40.0/conversation-character-knowledge-settings.png)

Limiting knowledge, adding reminders and the live character-entry orientation need no extra request. **Brief characters on entry**, **Refine memories with AI** and **Track learning from dialogue** normally add one request when they run and are off by default. A combined entry briefing can add a second request when its Offscreen Life account needs a retry.

##### Limit to character knowledge

Leave out events the character missed and return only memories they know. **Turn on to base replies on their own experience; turn off to use the shared history and memories.** The filter also covers context investigations and world or other-character state notes. The character's own stored state notes and director guidance remain available; neither splits an absence into multiple markers. Missed history is replaced by one gap line, including when it crosses the summarized/live boundary in Best Fit mode. On by default.

##### Remind about unknown facts

Tell the AI which recent facts the character does not know. **Turn on if characters act on information they missed.** These reminders guide the model; they cannot guarantee its response. Nothing is added when there are no facts to list. On by default.

##### Unknown-fact reminders

Limit how many unknown facts are listed for the AI (default 5). **Raise to include more reminders; lower to keep the prompt shorter.** Within the **Recent facts to check** pool, eligible facts are ranked by the Summarizer's [Fact chronology](/talemate/user-guide/agents/summarizer/settings/#fact-chronology) importance and recency score before this limit is applied.

##### Recent facts to check

Choose how many of the newest recorded facts to check for unknown-fact reminders (default 30). **Raise to cover older facts; lower to focus on the newest.** The pool follows original fact creation order; a restatement refreshes a fact's chronology score but does not move it into this pool. Chronology selection and ranking apply within the pool, while **Unknown-fact reminders** limits how many appear.

##### Topic knowledge overview

Give the AI a short overview of which topics the character knows about. **Turn on for topic-level reminders**, and enable [Topics in the Memory agent](/talemate/user-guide/agents/memory/settings/#topics). On by default, with no extra request.

For example: `Edwin knows all of the Sorena, some of the sextant, nothing of the boat`. Only topics with at least three facts count; at most six are listed, largest first. The overview is omitted when no topic qualifies. It describes recorded facts, not everything a character understands.

##### Character entry turns

Keep a private arrival orientation in a character's prompt for this many of their committed lines (default 3). Explicit activation or re-entry starts the window; loading an already active character does not. Only that character's completed lines consume it, so retries and other characters' lines do not. The remaining count survives save and reload.

The orientation is rebuilt before every prompt from what that character currently knows: up to twelve ranked facts about characters present now, the current roster, up to five visible lines since entry, time since entry, and the time since they were last known to be present when returning. The complete block has a fixed prompt-token ceiling. It does not copy the raw scene description or infer a clock time. Player characters receive the same zero-request orientation for context preview and AI-driven turns.

##### Brief characters on entry

Generate a short private perception when a non-player character enters or returns. It replaces the live arrival orientation for the same **Character entry turns** window and uses only that character's known facts, unknown-fact reminders and character-visible history. If generation fails, is cancelled or cannot be read, the entry still succeeds and the live zero-request orientation remains.

Off by default. Normally uses **one World State client request per non-player character activation**. If Narrator **Offscreen Life** also applies to the return, the combined request uses the Narrator client plus its Length and extra instructions to produce both the private briefing and the ordinary offscreen account. A malformed or missing account is retried through the ordinary Offscreen Life path, making that return cost two requests; it never discards a readable briefing. Player characters never trigger the briefing request.

In Standard mode, the generated text is prompt-only state and appears in **Prompt Manager → Scene Context** for that character. In Character perspectives mode, it is a disclosure in **Characters → Knowledge**, where **Regenerate** replaces that briefing and restarts its turn window, and **Remove** deletes only the briefing. Neither action changes a paired Offscreen Life fact.

##### Refine memories with AI

Ask the AI to rewrite and select retrieved memories for the next character reply. **Turn on when memories need a more relevant focus.** The AI drops unhelpful memories and puts useful ones first. With **Limit to character knowledge** on, it also rewrites memories from the character's point of view and drops what they do not know. With that filter off, it only refines relevance. In Character perspectives mode, the memories are already limited to the character's knowledge.

Off by default. Uses **one more request before each generated character reply that has retrieved memories**, through the World State agent's client. The request uses the character's story context within that client's budget. If the answer cannot be read, the original retrieved memories are kept.

When **Cache RAG results** is enabled on Long Term Memory, regenerating a reply can
reuse this refinement together with its cached retrieval when the story before the
reply and the available memory sources are unchanged. Changing the refinement model,
client settings or resolved inference preset runs it again. Standard semantic-only
retrieval does not publish a shared cached result, so there is no refinement to reuse
in that configuration.

##### Track learning from dialogue

Ask the AI what listeners learned from each character message and add those facts to their knowledge. **Turn on to track information shared in dialogue.** It checks recent recorded facts the listeners do not know, so it can recognize retold information rather than discover arbitrary new facts. Learned facts become available in memory and leave the unknown-fact reminders. The speaker does not learn from their own message; player messages are included. Each learning grant takes effect immediately and can be revoked in the character’s **Knowledge** view. The ledger judges with recent dialogue and situational context and errs toward learning when the substance is conveyed, while hints, questions and merely related facts still do not count.

Off by default. Uses **one more request after a character message when a listener has recent facts they do not know**, through the World State agent's client. No request is sent when every listener already knows those facts. Available in Standard mode only.

##### Establish facts from dialogue

Save important facts immediately from a character's latest line, before the next summary. Available only when **Track learning from dialogue** is on, in Standard mode; off by default. A line that establishes nothing worth remembering yields no fact. Facts retain attribution and uncertainty: a character's claim is recorded as a claim.

**Uses the same World State client request as Track learning from dialogue, but runs it after every character line**, including player lines and a speaker talking alone, even when everyone already knows the recent facts. There is no second request per line. Everyone present knows the recorded fact; the named learners describe who learned it rather than restricting its audience.

New facts have an importance level and appear under **Dialogue facts** in [History](/talemate/user-guide/world-editor/history/#facts), where their text and importance can be edited and their source message inspected. The archive pass still extracts facts, including narrator lines and time passages, and merges sufficiently similar restatements into the existing fact. Removing or changing a source message removes the facts it established.

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

--8<-- "docs/snippets/tips.md:character_evidence_guidance"
