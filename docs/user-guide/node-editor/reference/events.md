# Events

List of currently supported events.

!!! warning "Events not listed here"
    There are some other events defined in the talemate codebase that are purposefully not listed here yet. 

    The reason for this is that there is an ongoing cleanup process and some of them may not stick around in their current form.

    You can of course still hook into them, but be aware that they may change or be removed in the future.

## Event Index

| Event | Category |
|-------|----------|
| [`game_loop`](#game_loop) | Game Loop |
| [`game_loop_actor_iter`](#game_loop_actor_iter) | Game Loop |
| [`game_loop_ai_character_iter`](#game_loop_ai_character_iter) | Game Loop |
| [`game_loop_player_character_iter`](#game_loop_player_character_iter) | Game Loop |
| [`game_loop_new_message`](#game_loop_new_message) | Game Loop |
| [`player_turn_start`](#player_turn_start) | Game Loop |
| [`scene.before_generation`](#scenebefore_generation) | Game Loop |
| [`scene_init`](#scene_init) | Scene Loop |
| [`scene.revision_saved`](#scene-revision-events) | Scene Revisions |
| [`scene.revision_forked`](#scene-revision-events) | Scene Revisions |
| [`scene.revisions_deleted`](#scene-revision-events) | Scene Revisions |
| [`scene.revision_failed`](#scene-revision-events) | Scene Revisions |
| [`scene_loop_init`](#scene_loop_init) | Scene Loop |
| [`scene_loop_init_after`](#scene_loop_init_after) | Scene Loop |
| [`scene_loop_start_cycle`](#scene_loop_start_cycle) | Scene Loop |
| [`scene_loop_end_cycle`](#scene_loop_end_cycle) | Scene Loop |
| [`scene_loop_error`](#scene_loop_error) | Scene Loop |
| [`regenerate.msg.character`](#regeneratemsgcharacter) | Regenerate |
| [`regenerate.msg.narrator`](#regeneratemsgnarrator) | Regenerate |
| [`regenerate.msg.reinforcement`](#regeneratemsgreinforcement) | Regenerate |
| [`regenerate.msg.context_investigation`](#regeneratemsgcontext_investigation) | Regenerate |
| [`agent.conversation.before_generate`](#agentconversationbefore_generate) | Conversation Agent |
| [`agent.conversation.inject_instructions`](#agentconversationinject_instructions) | Conversation Agent |
| [`agent.conversation.generated`](#agentconversationgenerated) | Conversation Agent |
| [`agent.conversation.finalized`](#agentconversationfinalized) | Conversation Agent |
| [`agent.creator.contextual_generate.before`](#agentcreatorcontextual_generatebefore) | Creator Agent |
| [`agent.creator.contextual_generate.after`](#agentcreatorcontextual_generateafter) | Creator Agent |
| [`agent.creator.autocomplete.before`](#agentcreatorautocompletebefore) | Creator Agent |
| [`agent.creator.autocomplete.after`](#agentcreatorautocompleteafter) | Creator Agent |
| [`agent.creator.dialogue_examples.before`](#agentcreatordialogue_examplesbefore) | Creator Agent |
| [`agent.creator.dialogue_examples.after`](#agentcreatordialogue_examplesafter) | Creator Agent |
| [`agent.editor.revision-analysis.before`](#agenteditorrevision-analysisbefore) | Editor Agent |
| [`agent.editor.revision-analysis.after`](#agenteditorrevision-analysisafter) | Editor Agent |
| [`agent.editor.revision.decision-checks.before`](#agenteditorrevisiondecision-checksbefore) | Editor Agent |
| [`agent.editor.revision-revise.before`](#agenteditorrevision-revisebefore) | Editor Agent |
| [`agent.editor.revision-revise.after`](#agenteditorrevision-reviseafter) | Editor Agent |
| [`agent.help.chat.before`](#agenthelpchatbefore) | Help Agent |
| [`agent.help.chat.after`](#agenthelpchatafter) | Help Agent |
| [`agent.narrator.before_generate`](#agentnarratorbefore_generate) | Narrator Agent |
| [`agent.narrator.inject_instructions`](#agentnarratorinject_instructions) | Narrator Agent |
| [`agent.narrator.generated`](#agentnarratorgenerated) | Narrator Agent |
| [`agent.director.guide.before_generate`](#agentdirectorguidebefore_generate) | Director Agent |
| [`agent.director.guide.inject_instructions`](#agentdirectorguideinject_instructions) | Director Agent |
| [`agent.director.guide.generated`](#agentdirectorguidegenerated) | Director Agent |
| [`agent.director.generate_choices.before_generate`](#agentdirectorgenerate_choicesbefore_generate) | Director Agent |
| [`agent.director.generate_choices.inject_instructions`](#agentdirectorgenerate_choicesinject_instructions) | Director Agent |
| [`agent.director.generate_choices.generated`](#agentdirectorgenerate_choicesgenerated) | Director Agent |
| [`agent.director.character_management.before_persist_character`](#agentdirectorcharacter_managementbefore_persist_character) | Director Agent |
| [`agent.director.character_management.after_persist_character`](#agentdirectorcharacter_managementafter_persist_character) | Director Agent |
| [`agent.director.chat.batch_complete`](#agentdirectorchatbatch_complete) | Director Agent |
| [`agent.world_state.time`](#agentworld_statetime) | World State Agent |
| [`agent.world_state.reinforcement.skipped`](#agentworld_statereinforcementskipped) | World State Agent |
| [`agent.world_state.snapshot.entity_added`](#agentworld_statesnapshotentity_added) | World State Agent |
| [`agent.summarization.scene_analysis.before`](#agentsummarizationscene_analysisbefore) | Summarization Agent |
| [`agent.summarization.scene_analysis.cached`](#agentsummarizationscene_analysiscached) | Summarization Agent |
| [`agent.summarization.scene_analysis.before_deep_analysis`](#agentsummarizationscene_analysisbefore_deep_analysis) | Summarization Agent |
| [`agent.summarization.scene_analysis.after_deep_analysis`](#agentsummarizationscene_analysisafter_deep_analysis) | Summarization Agent |
| [`agent.summarization.scene_analysis.after`](#agentsummarizationscene_analysisafter) | Summarization Agent |
| [`agent.summarization.summarize.before`](#agentsummarizationsummarizebefore) | Summarization Agent |
| [`agent.summarization.summarize.after`](#agentsummarizationsummarizeafter) | Summarization Agent |
| [`agent.summarization.before_build_archive`](#agentsummarizationbefore_build_archive) | Summarization Agent |
| [`agent.summarization.after_build_archive`](#agentsummarizationafter_build_archive) | Summarization Agent |
| [`agent.summarization.layered_history.finalize`](#agentsummarizationlayered_historyfinalize) | Summarization Agent |
| [`agent.summarization.rag_build_sub_instruction`](#agentsummarizationrag_build_sub_instruction) | Summarization Agent |
| [`agent.summarization.perceptions.after`](#agentsummarizationperceptionsafter) | Summarization Agent |
| [`agent.summarization.perceptions.failed`](#agentsummarizationperceptionsfailed) | Summarization Agent |
| [`agent.tts.prepare.before`](#agentttspreparebefore) | TTS Agent |
| [`agent.tts.prepare.after`](#agentttsprepareafter) | TTS Agent |
| [`agent.tts.generate.before`](#agentttsgeneratebefore) | TTS Agent |
| [`agent.tts.generate.after`](#agentttsgenerateafter) | TTS Agent |
| [`agent.visual.generation.before_generate`](#agentvisualgenerationbefore_generate) | Visual Agent |
| [`agent.visual.generation.after_generate`](#agentvisualgenerationafter_generate) | Visual Agent |
| [`agent.visual.generation.failed`](#agentvisualgenerationfailed) | Visual Agent |
| [`agent.visual.generation.refused`](#agentvisualgenerationrefused) | Visual Agent |
| [`agent.visual.prompt_finalize.before`](#agentvisualprompt_finalizebefore) | Visual Agent |
| [`agent.visual.prompt_finalize.after`](#agentvisualprompt_finalizeafter) | Visual Agent |
| [`asset_saved`](#asset_saved) | Scene Assets |
| [`asset_deleted`](#asset_deleted) | Scene Assets |
| [`scene.backdrop_changed`](#scenebackdrop_changed) | Scene Assets |
| [`scene.cover_image_changed`](#scenecover_image_changed) | Scene Assets |
| [`character.cover_image_changed`](#charactercover_image_changed) | Scene Assets |
| [`game_state.changed`](#game_statechanged) | Game State |
| [`character.activated`](#characteractivated) | Characters |
| [`character.deactivated`](#characterdeactivated) | Characters |
| [`knowledge.changed`](#knowledgechanged) | Knowledge |
| [`knowledge.visibility_changed`](#knowledgevisibility_changed) | Knowledge |
| [`knowledge.edge_removed`](#knowledgeedge_removed) | Knowledge |
| [`knowledge.disclosure_added`](#knowledgedisclosure_added) | Knowledge |
| [`perspective.view_edited`](#perspectiveview_edited) | Knowledge |
| [`decision.invocation.finished`](#decisioninvocationfinished) | Decision Model |
| [`decision.gate.resolved`](#decisiongateresolved) | Decision Model |
| [`client.enabled`](#clientenabled) | Clients |
| [`client.disabled`](#clientdisabled) | Clients |
| [`client.embeddings_available`](#clientembeddings_available) | Clients |

## Game Loop

---

### game_loop

Triggered at the start of each game loop iteration, before the actor turns are processed. This is the master signal for the per-iteration game loop and runs once per scene loop cycle when the game loop is triggered.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `had_passive_narration` | `bool` | Whether passive narration has already fired this iteration |

---

### game_loop_actor_iter

Triggered after either a player or AI character has had a turn.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `actor` | `Actor` | The actor object |
    | `game_loop` | `GameLoopEvent` | The parent game loop event for this iteration |

---

### game_loop_ai_character_iter

Triggered after the AI character has had a turn.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `character` | `Character` | The character object |
    | `game_loop` | `GameLoopEvent` | The parent game loop event for this iteration |

---

### game_loop_player_character_iter

Triggered after the player character has had a turn.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `character` | `Character` | The character object |
    | `game_loop` | `GameLoopEvent` | The parent game loop event for this iteration |

---

### game_loop_new_message

Triggered when a new message is added to the scene history.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `message` | `SceneMessage` | The message object |

---

### player_turn_start

Triggered when the user turn starts. User input has not yet happened at this point.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |

---

### scene.before_generation

Emitted before a generation that continues the story or acts on it: a narration, a character's line, an editor detail, a regenerated message or a `!` command. In Character perspectives mode the new passages are analyzed here, before the generation starts. A handler that cancels stops the generation.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `trigger` | `str` | `narrator`, `conversation`, `editor`, `regenerate` or `command` |

---

## Scene Loop

### scene_init

Triggered once during scene startup, before the scene loop begins running. Use this to perform one-time setup that needs to happen as soon as a scene is loaded.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |

---

### scene_loop_init

Triggered when the scene loop is initialised. Fires once at the start of the very first scene loop cycle, after agent nodes and commands have been registered.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |

---

### scene_loop_init_after

Fires immediately after [`scene_loop_init`](#scene_loop_init). Use this when you need to react to scene loop initialisation but want to run after handlers attached to `scene_loop_init` have completed.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |

---

### scene_loop_start_cycle

Triggered when the scene loop starts a new cycle.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |

---

### scene_loop_end_cycle

Triggered when the scene loop ends a cycle.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |

---

### scene_loop_error

Triggered when an unhandled exception escapes the scene loop. Internal control-flow exceptions (like `ActedAsCharacter` and `GenerationCancelled`) are handled before this fires, so this signal indicates a real error condition that listeners may want to log or recover from.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |

---

## Regenerate Events

### regenerate.msg.character

Triggered after regeneration replaces a *CharacterMessage*.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene in which regeneration happened |
    | `message` | `CharacterMessage` | The regenerated character message |
    | `character` | `Character` | The character associated with the message |

---

### regenerate.msg.narrator

Triggered after regeneration replaces a *NarratorMessage*.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `message` | `NarratorMessage` | The regenerated narrator message |
    | `character` | `None` | Not applicable (always `None`) |

---

### regenerate.msg.reinforcement

Triggered when a *ReinforcementMessage* is regenerated.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `message` | `ReinforcementMessage` | The regenerated reinforcement message |
    | `character` | `None` | Not applicable |

---

### regenerate.msg.context_investigation

Triggered when a *ContextInvestigationMessage* is regenerated.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `message` | `ContextInvestigationMessage` | The regenerated context investigation message |
    | `character` | `None` | Not applicable |

## Conversation Agent Events

### agent.conversation.before_generate

Emitted **just before** the Conversation agent sends the prompt to the model.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `ConversationAgent` | The agent instance |
    | `actor` | `Actor` | The speaking actor |
    | `character` | `Character` | Shortcut to `actor.character` |

---

### agent.conversation.inject_instructions

Emitted while constructing the prompt, **before** the prompt is sent to the model.  
Handlers can mutate `dynamic_instructions` to inject extra task instructions.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `ConversationAgent` | The agent instance |
    | `character` | `Character` | Target character |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Append strings here to include them near the top of the prompt |

---

### agent.conversation.generated

Emitted **after** the Conversation agent receives the model output but **before** the message is pushed to history.  
Handlers can edit `generation` in-place to clean up or transform the text (the Editor agent does this).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `ConversationAgent` | The agent instance |
    | `actor` | `Actor` | Actor that spoke |
    | `character` | `Character` | The speaking character |
    | `response` | `str` | **Mutable.** Final text lines that will be turned into messages |

---

### agent.conversation.finalized

Emitted once a character's message is in the history, after it is shown to the player and before the new-message listeners (voice preparation, archive summaries) run. In Character perspectives mode its perspectives do not exist yet: they are analyzed before the next generation, which `agent.summarization.perceptions.after` reports.
Handlers can set `avatar` to an asset id to change the portrait shown with the message. The shipped portrait module listens here.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `ConversationAgent` | The agent instance |
    | `actor` | `Actor` | Actor that spoke |
    | `character` | `Character` | The speaking character |
    | `response` | `str` | The final message text |
    | `message_ids` | `list[int]` | The id of the finished message |
    | `avatar` | `str` | **Mutable.** Asset id of the portrait for the message |

## Creator Agent Events

### agent.creator.contextual_generate.before

Contextual generation are things like character attributes, details, scene introductions, etc.

Emitted **before** the Creator agent sends the prompt to the model.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `CreatorAgent` | The agent instance |
    | `character` | `Character` | The character that the contextual generation is for |
    | `template_vars` | `dict` | Variables that will be fed into the prompt – **mutable** |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Push additional `DynamicInstruction` objects to influence generation |

### agent.creator.contextual_generate.after

Emitted **after** the Creator agent receives the model output but **before** the message is pushed to history.  
Handlers can edit `response` in-place to clean up or transform the text (the Editor agent does this).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `CreatorAgent` | The agent instance |
    | `response` | `str` | **Mutable.** Final text lines that will be turned into messages |
    | `template_vars` | `dict` | Variables that were fed into the prompt – **mutable** |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Push additional `DynamicInstruction` objects to influence generation |

### agent.creator.autocomplete.before

Autocomplete generation for character action or narrative text.

Emitted **before** the Creator agent sends the prompt to the model.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `CreatorAgent` | The agent instance |
    | `input` | `str` | The input text that the autocomplete is for |
    | `type` | `str` | The type of autocomplete (e.g. `dialogue`, `narrative`) |
    | `character` | `Character` | The character that the autocomplete is for |
    | `template_vars` | `dict` | Variables that will be fed into the prompt – **mutable** |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Push additional `DynamicInstruction` objects to influence generation |

### agent.creator.autocomplete.after

Emitted **after** the Creator agent receives the model output but **before** the message is pushed to history.  
Handlers can edit `response` in-place to clean up or transform the text (the Editor agent does this).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `CreatorAgent` | The agent instance |
    | `response` | `str` | **Mutable.** Final text lines that will be turned into messages |
    | `input` | `str` | The input text that the autocomplete is for |
    | `type` | `str` | The type of autocomplete (e.g. `dialogue`, `narrative`) |
    | `character` | `Character` | The character that the autocomplete is for |
    | `template_vars` | `dict` | Variables that were fed into the prompt – **mutable** |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Push additional `DynamicInstruction` objects to influence generation |

### agent.creator.dialogue_examples.before

Emitted **before** the Creator agent generates example dialogue for a character (AI-assisted character creation, character card import).

Not emitted when **Fast Character Generation** is on and the consolidated
one-shot produces the examples itself — the events fire on the split flow
and on fill-in-misses regeneration only.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `CreatorAgent` | The agent instance |
    | `character` | `Character` | The character the dialogue examples are for |
    | `text` | `str` | Source text containing dialogue examples / character information |
    | `instructions` | `str` | User-provided guidance for the dialogue examples |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Push additional `DynamicInstruction` objects to influence generation |

### agent.creator.dialogue_examples.after

Emitted **after** the dialogue examples have been generated but **before** they are returned to the caller (and applied to the character).
Handlers can mutate `dialogue_examples` to add, remove or rewrite examples.

Like the `before` event, not emitted when the consolidated one-shot
produces the examples (see above).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `CreatorAgent` | The agent instance |
    | `character` | `Character` | The character the dialogue examples are for |
    | `text` | `str` | Source text containing dialogue examples / character information |
    | `instructions` | `str` | User-provided guidance for the dialogue examples |
    | `dialogue_examples` | `list[str]` | **Mutable.** The generated examples, formatted as `Character Name: ...` |

## Editor Agent Events

### agent.editor.revision-revise.before

Emitted **before** the Editor agent requests the revision-revise prompt.  
Handlers can add extra revise instructions via `dynamic_instructions` or adjust `template_vars`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `EditorAgent` | The agent instance |
    | `template_vars` | `dict` | Variables that will be fed into the prompt – **mutable** |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Push additional `DynamicInstruction` objects to influence generation |
    | `info` | `RevisionInformation` | The text being revised and where it comes from (`text`, `character`, `context_type`, `context_name`) |
    | `issues` | `Issues` | What the revision will fix. With Editor Decision Checks on, `issues.decision_findings` lists the findings (`passage_id`, `text`, `kind`, `instructions`, `p_true`) — **mutable**, remove a finding to leave that passage alone |

---

### agent.editor.revision-revise.after

Emitted **after** the Editor agent receives the model output but **before** the message is pushed to history.  
Handlers can edit `response` in-place to clean up or transform the text (the Editor agent does this).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `EditorAgent` | The agent instance |
    | `response` | `str` | **Mutable.** Final text lines that will be turned into messages |
    | `template_vars` | `dict` | Variables that were fed into the prompt – **mutable** |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Push additional `DynamicInstruction` objects to influence generation |

---
### agent.editor.revision-analysis.before

Emitted **before** the Editor agent requests the revision-rewrite prompt.  
Handlers can add extra analysis instructions via `dynamic_instructions` or adjust `template_vars`.

!!! note

    The signal is named `revision-analysis.*` for historical reasons — it was
    introduced when analysis and rewrite were two separate prompts. They are
    now combined into a single prompt (`editor.revision-rewrite`), but the
    signal name is kept for backward compatibility.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `EditorAgent` | The agent instance |
    | `template_vars` | `dict` | Variables that will be fed into the prompt – **mutable** |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Push additional `DynamicInstruction` objects to influence analysis |

---

### agent.editor.revision-analysis.after

Emitted after the revision-rewrite prompt returns. Intended as a
notification hook for observers of the rewrite flow.

!!! warning

    Historically this signal fired between a separate analysis prompt and a
    rewrite prompt, with `response` carrying the raw analysis text that
    handlers could mutate before the rewrite ran. Analysis and rewrite are
    now combined into a single prompt, so there is no separable "analysis
    text" — `response` is not set on the emission and any mutation is
    discarded. Use [`agent.editor.revision-revise.after`](#agenteditorrevision-reviseafter)
    if you need to inspect or replace the final rewritten text.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `EditorAgent` | The agent instance |
    | `template_vars` | `dict` | Same vars used for the prompt |

---

### agent.editor.revision.decision-checks.before

Emitted before the Editor Decision Checks of one revision run, with the checks of the scene's writing style that are active.
Handlers can add, remove or change checks for this message only; the writing style is not changed. With no checks left, the usual revision detection runs instead.

Example: during the mystery act a module adds a check "Does this passage reveal who the killer is?".

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `EditorAgent` | The agent instance |
    | `info` | `RevisionInformation` | The text being revised |
    | `checks` | `list[DecisionCheck]` | **Mutable.** The checks that will run |
    | `writing_style` | `str` | Template id of the scene's writing style |

## Help Agent Events

!!! note
    The help chat runs in the background and also works without a loaded scene. When no scene loop is running there are no connected listeners, so scene node graphs will only observe help chats that happen while their scene is loaded.

### agent.help.chat.before

Emitted when the Help agent starts generating a response to a help chat, before any documentation lookups run.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `HelpAgent` | The agent instance |
    | `chat_id` | `str` | The help chat's id |
    | `chat` | `HelpChat` | The chat, including all messages so far |

---

### agent.help.chat.after

Emitted after the Help agent has finished generating a response (all documentation lookup rounds completed and the answer appended to the chat).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `HelpAgent` | The agent instance |
    | `chat_id` | `str` | The help chat's id |
    | `chat` | `HelpChat` | The chat, now including the generated answer |

## Narrator Agent Events

### agent.narrator.before_generate

Emitted **before** the Narrator agent sends the prompt to the model.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `NarratorAgent` | The agent instance |

---

### agent.narrator.inject_instructions

Emitted while constructing the prompt, **before** the prompt is sent to the model.  
Handlers can mutate `dynamic_instructions` to inject extra task instructions.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `NarratorAgent` | The agent instance |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Append strings here to include them near the top of the prompt |

---

### agent.narrator.generated

Emitted **after** the Narrator agent receives the model output but **before** the message is pushed to history.  
Handlers can edit `generation` in-place to clean up or transform the text (the Editor agent does this).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `NarratorAgent` | The agent instance |
    | `response` | `str` | **Mutable.** Final text lines that will be turned into messages |

## Director Agent Events

### agent.director.guide.before_generate

Emitted before the Director **guidance** module runs to craft guidance text.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `DirectorAgent` | The agent instance |

---

### agent.director.guide.inject_instructions

Runs just after the previous event. Same payload – gives one more chance to adjust `dynamic_instructions`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `DirectorAgent` | The agent instance |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Add strings to influence the prompt |

---

### agent.director.guide.generated

Fires after guidance text is generated, but before it is cached or written to context.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `DirectorAgent` | The agent instance |
    | `response` | `str` | **Mutable.** The guidance text |

---

### agent.director.generate_choices.before_generate

Emitted before the Director generates player choice actions.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `DirectorAgent` | The agent instance |
    | `character` | `Character` | The character that the choices are for |

---

### agent.director.generate_choices.inject_instructions

Run before the Director generates player choice actions, gives one more chance to adjust `dynamic_instructions`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `DirectorAgent` | The agent instance |
    | `character` | `Character` | The character that the choices are for |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Add strings to influence the prompt |

---

### agent.director.generate_choices.generated

After choices text is ready.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `DirectorAgent` | The agent instance |
    | `response` | `str` | **Mutable.** Text that describes available choices |
    | `choices` | `list[str]` | **Mutable.** List of of generated choices |
    | `character` | `Character` | The character that the choices are for |

---

### agent.director.character_management.before_persist_character

Emitted **before** a new character is persisted into the scene by the director's character management module. The blank `Character` instance has been created and is attached to the emission, but it has not yet been added to the scene as an actor and no attribute / detail / dialogue templates have been applied.

Useful for adjusting the character object (e.g. seeding default attributes, voice assignment hints, color overrides) before the rest of the persist pipeline runs.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `DirectorAgent` | The agent instance |
    | `character` | `Character` | **Mutable.** The character about to be persisted |

---

### agent.director.character_management.after_persist_character

Emitted **after** the character has been fully persisted: actor added, generation templates applied, voice assigned (if enabled), character activated and committed to memory. The default `on-persist-character-generate-visual` module hooks into this signal to optionally generate a portrait.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `DirectorAgent` | The agent instance |
    | `character` | `Character` | The character that was just persisted |

---

### agent.director.chat.batch_complete

Emitted after the Director Chat has handled one batch of proposed actions, including actions the user confirmed or rejected.

Each call is a dict with `function`, `arguments` and `applied`, and when set `reason` (`confirm`, `reject`, `reject_with_instructions`, `over_budget`, `unknown_callback`, `timed_out`, `interrupted`, `failed`, `aborted`), `error`, `instructions` and `subcalls`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `DirectorAgent` | The agent instance |
    | `chat_id` | `str` | The Director Chat |
    | `applied` | `list[dict]` | Calls that were applied |
    | `not_applied` | `list[dict]` | Calls that were not applied |
    | `rejections` | `list[dict]` | Calls the user rejected with a correction (`function`, `arguments`, `reason`, `instructions`) |
    | `applied_count` | `int` | Applied calls, sub-calls included |
    | `not_applied_count` | `int` | Calls not applied, sub-calls included |

## World State Agent Events

### agent.world_state.time

Emitted when the world state agent advances the time in the scene.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `WorldStateAgent` | The agent instance |
    | `duration` | `int` | The duration of the time passage, in seconds |
    | `human_duration` | `str` | The human-readable duration of the time passage |
    | `narrative` | `str` | The narrative direction of the time passage |

---

### agent.world_state.reinforcement.skipped

Emitted when the decision model finds that a tracked state has not changed, so no update request runs. The state keeps its answer until its next interval.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `WorldStateAgent` | The agent instance |
    | `question` | `str` | The tracked state's question |
    | `character` | `str` | The character the state belongs to, or `None` |
    | `answer` | `str` | The answer it keeps |
    | `interval` | `int` | Turns until the next check |

---

### agent.world_state.snapshot.entity_added

Emitted when a person, object or place selected in a message was added to the world snapshot, from the message menu or with the **Add Snapshot Entity** node.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `WorldStateAgent` | The agent instance |
    | `message_id` | `int` | The message the text was selected in |
    | `selection` | `str` | The selected text |
    | `name` | `str` | The entry name in the snapshot |
    | `kind` | `str` | `character`, `item` or `place` |
    | `in_moment` | `bool` | Whether the message is in the snapshot's current moment |
    | `mentions` | `list[str]` | Phrases of the message marked as the entry |

## Summarization Agent Events

### agent.summarization.scene_analysis.before

Emitted just before the summarizer performs a scene analysis prompt. Handlers can tweak `template_vars` or inject `dynamic_instructions` to influence the analysis.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `template_vars` | `dict` | **Mutable.** Variables used in the prompt |
    | `analysis_type` | `str` | `conversation` or `narration` |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable** |

---

### agent.summarization.scene_analysis.cached

Fired when a cached analysis is reused instead of generating a new one. Same payload as above plus `response` containing cached analysis text.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `template_vars` | `dict` | **Mutable.** Variables used in the prompt |
    | `analysis_type` | `str` | `conversation` or `narration` |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable** |
    | `response` | `str` | The cached analysis text |

---

### agent.summarization.scene_analysis.before_deep_analysis

Occurs before running deep analysis passes (context investigations). Payload is `SceneAnalysisDeepAnalysisEmission`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `analysis` | `str` | Current analysis text |
    | `analysis_type` | `str` | Same as above |
    | `analysis_sub_type` | `str` | e.g. `progress`, `query`, etc. |
    | `max_content_investigations` | `int` | Upper bound for investigations |
    | `character` | `Character` | Character in focus (may be None) |

---

### agent.summarization.scene_analysis.after_deep_analysis

Fired immediately after deep analysis completes. Payload identical to previous event; handlers may alter `analysis`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `analysis` | `str` | Current analysis text |
    | `analysis_type` | `str` | Same as above |
    | `analysis_sub_type` | `str` | e.g. `progress`, `query`, etc. |
    | `max_content_investigations` | `int` | Upper bound for investigations |
    | `character` | `Character` | Character in focus (may be None) |

---

### agent.summarization.scene_analysis.after

Emitted after scene analysis is done and stored in scene state. Payload: `SceneAnalysisEmission` with `response` populated.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `template_vars` | `dict` | **Mutable.** Variables used in the prompt |
    | `analysis_type` | `str` | `conversation` or `narration` |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable** |
    | `response` | `str` | The analysis text |

### agent.summarization.summarize.before

Emitted before the summarizer performs a summarize prompt. Handlers can tweak `template_vars` or inject `dynamic_instructions` to influence the summarize.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `text` | `str` | The text to summarize |
    | `template_vars` | `dict` | **Mutable.** Variables used in the prompt |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable** |
    | `extra_instructions` | `str` | **Mutable.** any additional instructions |
    | `generation_options` | `GenerationOptions` | **Mutable.** Generation options |
    | `summarization_history` | `list[str]` | **Mutable.** any previous historical summaries |

---

### agent.summarization.summarize.after

Emitted after the summarizer performs a summarize prompt. Handlers can inspect or replace `response`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `text` | `str` | The text to summarize |
    | `template_vars` | `dict` | **Mutable.** Variables used in the prompt |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable** |
    | `extra_instructions` | `str` | **Mutable.** any additional instructions |
    | `generation_options` | `GenerationOptions` | **Mutable.** Generation options |
    | `summarization_history` | `list[str]` | **Mutable.** any previous historical summaries |
    | `response` | `str` | **Mutable.** The summary text |

---

### agent.summarization.before_build_archive

Fires at the very top of `build_archive`, before the summarizer decides whether new archive entries need to be produced. Handlers can short-circuit or instrument the archive-building pass.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `generation_options` | `GenerationOptions \| None` | Generation options that will be used for any summarization prompts performed during the build |

---

### agent.summarization.after_build_archive

Fires after `build_archive` has finished processing all eligible history entries (whether or not anything was actually summarized this pass).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `generation_options` | `GenerationOptions \| None` | The generation options that were used during the build |

---

### agent.summarization.layered_history.finalize

Emitted while finalizing a layered history archive entry. Handlers can inspect or replace the entry before it is added to the layered history. The emission exposes a `response` property that is a shortcut for `entry.text`, so handlers that only want to rewrite the summary text can mutate `response` directly.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `entry` | `LayeredArchiveEntry \| None` | **Mutable.** The layered archive entry being finalized |
    | `summarization_history` | `list[str]` | **Mutable.** Previous summaries used as context |
    | `response` | `str \| None` | **Mutable.** Shortcut for `entry.text` |

---

### agent.summarization.rag_build_sub_instruction

Fires when the summarizer assembles the additional sub-instruction used when fetching RAG context. Mixins (and external handlers) listen on this signal to append guidance about *how* the retrieved context should be interpreted.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `sub_instruction` | `str \| None` | **Mutable.** Concatenated sub-instruction to attach to the RAG query |

---

### agent.summarization.perceptions.after

Emitted once the characters' views of a passage are stored. New passages are analyzed in one step before a generation, and out-of-sync ones when you choose **Repair**; the event is sent after that step has finished, and the generation waits for the handler. A handler can start a generation or a director action from this event.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `message_id` | `int` | The passage |
    | `views` | `list[PerceptionView]` | One entry per character: `character`, `status` (`ready` or `omitted`), `text` |
    | `analyzed` | `list[str]` | Characters whose view the model wrote |
    | `verbatim` | `list[str]` | Characters who received the full passage without analysis, such as the speaker |

---

### agent.summarization.perceptions.failed

Emitted after the analysis of a passage failed, once the knowledge step has finished.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `SummarizeAgent` | The agent instance |
    | `message_id` | `int` | The passage |
    | `characters` | `list[str]` | The characters whose views were requested |
    | `error` | `str` | Why it failed |

## TTS Agent Events

### agent.tts.prepare.before

Emitted **before** an optional `prepare_fn` runs against an audio chunk (e.g. text normalization, audio-tag rewriting, voice selection). Only fires for chunks that declare a `prepare_fn`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `chunk` | `Chunk` | **Mutable.** The TTS chunk about to be prepared |
    | `context` | `GenerationContext` | The full generation context (all chunks for the current request) |
    | `wav_bytes` | `bytes \| None` | Always `None` at this point |

---

### agent.tts.prepare.after

Fires after a chunk's `prepare_fn` has run but before audio generation starts. Handlers can inspect (or mutate) the now-prepared chunk.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `chunk` | `Chunk` | **Mutable.** The prepared TTS chunk |
    | `context` | `GenerationContext` | The full generation context |
    | `wav_bytes` | `bytes \| None` | Always `None` at this point |

---

### agent.tts.generate.before

Emitted **immediately before** the chunk is sent to the active TTS backend for synthesis.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `chunk` | `Chunk` | **Mutable.** The TTS chunk about to be synthesised |
    | `context` | `GenerationContext` | The full generation context |
    | `wav_bytes` | `bytes \| None` | Always `None` at this point |

The voice agent provides the `Unpack Generation Emission` and `Set Chunk Text` nodes for this event, which read and rewrite the chunk's text without going through `Get` and `Set` — see [Text Manipulation](../../agents/voice/text-manipulation.md).

---

### agent.tts.generate.after

Fires after the TTS backend returns audio for a chunk and before the audio is played back. Handlers can inspect (or replace) the produced audio via `wav_bytes`.

A chunk the backend produced no audio for is skipped: it is logged and neither this event nor the playback happens for it. Handlers therefore always receive audio. A handler that empties `wav_bytes` itself is honoured the same way — the chunk is logged and skipped rather than played, and the rest of the queue continues.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `chunk` | `Chunk` | The TTS chunk that was synthesised (changes no longer affect the audio) |
    | `context` | `GenerationContext` | The full generation context |
    | `wav_bytes` | `bytes` | **Mutable.** The synthesised audio bytes |

## Visual Agent Events

### agent.visual.generation.before_generate

Emitted **before** the visual agent dispatches a generation request to the active backend (text-to-image or image-edit).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `VisualAgent` | The agent instance |
    | `request` | `GenerationRequest` | The request that is about to be sent to the backend |
    | `response` | `GenerationResponse` | A response shell with `id` populated; not yet filled in |

---

### agent.visual.generation.after_generate

Fires after a generation request has completed and the resulting image has been delivered to the frontend (and optionally auto-saved as a scene asset). The same emission instance from `before_generate` is reused, so `response` now carries the generated image data.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `VisualAgent` | The agent instance |
    | `request` | `GenerationRequest` | The original request |
    | `response` | `GenerationResponse` | The completed response, including base64 image data |

---

### agent.visual.generation.failed

Fires when a generation request ends without an image: the backend failed, the user cancelled it, or it could not start (for example no backend is available).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `VisualAgent` | The agent instance |
    | `request` | `GenerationRequest` | The request, including its `purpose` |
    | `error` | `str \| None` | Why it failed; `None` when it was cancelled |
    | `cancelled` | `bool` | `True` when the generation was cancelled |

---

### agent.visual.generation.refused

Fires when the visual agent refuses a generation request without starting it. An automatic request (one with an `automatic_source`) is refused while the Visualizer's **Automatic Generation** setting is off. Nothing is generated, the request never counts as running, and the returned response has `refused` set.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `VisualAgent` | The agent instance |
    | `request` | `GenerationRequest` | The refused request, including `automatic_source` (the feature that started it), `purpose`, `vis_type` and `character_name` |
    | `reason` | `str` | Why it was refused |

---

### agent.visual.prompt_finalize.before

Emitted when prompt finalization runs — right before an image generation prompt is sent to the backend, and when the `agents/visual/FinalizePrompt` node is executed. Fires **before** the configured finalizer actions are applied, and fires even when the Prompt Finalization agent setting is disabled, so listeners can act as their own finalization mechanism.

Handlers can mutate the prompt strings and the finalizer list.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `VisualAgent` | The agent instance |
    | `positive_prompt` | `str \| None` | **Mutable.** The positive prompt before finalization |
    | `negative_prompt` | `str \| None` | **Mutable.** The negative prompt before finalization |
    | `vis_type` | `VIS_TYPE` | The visual type being generated (e.g. `CHARACTER_PORTRAIT`) |
    | `character_name` | `str \| None` | The targeted character, if any |
    | `finalizers` | `list[PromptFinalizer]` | **Mutable.** The finalizer actions about to be applied (agent's first, then character's); empty when finalization is disabled |

---

### agent.visual.prompt_finalize.after

Fires after all finalizer actions have been applied, right before the finalized prompts are returned (and sent to the image generation backend). The same emission instance from `.before` is reused. Handlers can mutate the prompt strings for a final rewrite.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `VisualAgent` | The agent instance |
    | `positive_prompt` | `str \| None` | **Mutable.** The finalized positive prompt |
    | `negative_prompt` | `str \| None` | **Mutable.** The finalized negative prompt |
    | `vis_type` | `VIS_TYPE` | The visual type being generated |
    | `character_name` | `str \| None` | The targeted character, if any |
    | `finalizers` | `list[PromptFinalizer]` | The finalizer actions that were applied |

## Scene Asset Events

### asset_saved

Emitted when an asset is added to the scene's asset library (uploaded, imported, or auto-saved after image generation).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `asset` | `Asset` | The saved asset |
    | `new_asset` | `bool` | `True` when the asset was newly created, `False` when it already existed |
    | `asset_attachment_context` | `AssetAttachmentContext` | How the asset wants to be attached (message attachment, cover image, avatar, ...) |

---

### asset_deleted

Emitted when an asset is removed from the scene's asset library.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `asset` | `Asset` | The deleted asset |

---

### scene.backdrop_changed

Emitted when the scene backdrop state actually changes — a backdrop asset is set, the backdrop is toggled on or off, or the backdrop is cleared (including when the current backdrop asset is deleted). Updates that leave the state unchanged do not fire.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `backdrop` | `str \| None` | The backdrop asset id after the update (`None` when cleared) |
    | `enabled` | `bool` | Whether the backdrop currently renders |

---

### scene.cover_image_changed

Emitted when the scene cover image is set.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `asset` | `Asset` | The new cover image asset |
    | `character_name` | `None` | Always `None` for the scene cover |

---

### character.cover_image_changed

Emitted when a character's cover image is set.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `asset` | `Asset` | The new cover image asset |
    | `character_name` | `str` | The character the cover image belongs to |

## Game State Events

### game_state.changed

Emitted once for each game state value that changes, whoever changes it:

- a control in the scene header, or Debug Tools
- the World Editor's game state editor
- the Director's game state updates
- a node graph: the state nodes in the `game` scope and **Update Game State**
- a scene script or template that calls `game_state.set_var` or `game_state.unset_var`

A nested value has its own event with its full path. A removed value has `value` `None`. A write that leaves a value as it was sends no event, and loading a scene sends none. The new value is already stored, after the control's bounds and choices were applied. The event is sent in a task after the change, without waiting for its handlers, so a handler can start a generation.

A change made in place on the dict from the **Game State** node sends no event. Use **Update Game State** or a state node in the `game` scope.

!!! warning "Handlers that write game state"
    A handler that writes the game state emits this event again. Write only when the value must change, or the handler runs in a loop.

Example: the player switches `stance` from `friendly` to `hostile`, and a module at once adds a director instruction for the next turn.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `scene` | `Scene` | The scene |
    | `path` | `str` | The value's path, e.g. `player/health` |
    | `value` | `any` | The new value, or `None` when it was removed |
    | `previous_value` | `any` | The value before the change, or `None` |

## Character Events

### character.activated

Emitted when a character enters the scene.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `scene` | `Scene` | The scene |
    | `character` | `Character` | The character |
    | `transition` | `CharacterTransitionMessage` | The arrival entry in the history, or `None` when none was written (for example while a scene loads). Read it with **Unpack Character Transition** |

---

### character.deactivated

Emitted when a character leaves the scene.

Example: a module narrates the exit, or notes where the character went.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `scene` | `Scene` | The scene |
    | `character` | `Character` | The character |
    | `transition` | `CharacterTransitionMessage` | The departure entry in the history, or `None` when none was written |

## Knowledge Events

### knowledge.changed

Emitted when what a character knows changes: an entry is learned or blocked (Learn, Never Learn, Known by of static history) or information is shared as a disclosure. It is sent right after the change, without waiting for it.

Example: when the player learns where the key is hidden, a module shows a hint.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `scene` | `Scene` | The scene |
    | `changes` | `list` | One entry per change: `character`, `target` (entry or disclosure id), `kind` (`grant` or `revoke`), `label` |

---

### knowledge.visibility_changed

Emitted when the Known by setting of a world entry or a character sheet entry changes. It is sent right after the change, without waiting for it.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `scene` | `Scene` | The scene |
    | `entry_id` | `str` | The entry, e.g. `Hidden Door` or `Bob.secret` |
    | `kind` | `str` | `world_entry` or `sheet` |
    | `owner` | `str` | The character a sheet entry belongs to |
    | `key` | `str` | The sheet entry key, e.g. `secret` or `detail.the fall` |
    | `previous` | `EntryVisibility` | The setting before (`mode`, `characters`) |
    | `visibility` | `EntryVisibility` | The new setting |

---

### knowledge.edge_removed

Emitted when a Learn or Never Learn rule is removed. It is sent right after the change, without waiting for it.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `scene` | `Scene` | The scene |
    | `edge` | `KnowledgeEdge` | The removed rule (`character`, `target`, `kind`, `source`, `note`) |
    | `changed` | `bool` | Whether the Learn / Never Learn state between the character and the entry changed. The entry's Known by or the character's presence can still give the same access as before |

---

### knowledge.disclosure_added

Emitted when information is shared with characters as a disclosure (Character Perspectives). It is sent right after the change, without waiting for it.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `scene` | `Scene` | The scene |
    | `disclosure_id` | `str` | The disclosure |
    | `text` | `str` | The shared information |
    | `audience` | `list[str]` | Who knows it now |
    | `origin` | `str` | The entry it comes from, or `None` |

---

### perspective.view_edited

Emitted when one character's view of a message is replaced by hand, in the perspective panel or with the **Set Message View** node. It is sent right after the change, without waiting for it.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `scene` | `Scene` | The scene |
    | `message_id` | `int` | The message |
    | `character` | `str` | The character |
    | `status` | `str` | `ready`, or `omitted` for an empty view |
    | `text` | `str` | The new view |
    | `dependents` | `int` | Later views built on this one; they stay valid |

## Decision Model Events

!!! note
    These events report the decision checks Talemate runs itself (editor checks, yes/no queries, pin conditions, tracked states, portraits, character references). A question asked with the **Ask Decision Model** node returns its answer to the node and does not emit them.

    Some checks run while a prompt is put together, for example the character references for memory retrieval. Their events are sent once that prompt is complete, so a handler can start a generation. The handler then runs while the generation that built the prompt continues, so a message it adds can come before the generated line.

### decision.invocation.finished

Emitted when a decision policy has finished.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `invocation_id` | `str` | The Decision Log invocation |
    | `template_uid` | `str` | The policy, e.g. `world_state.decision-query` |
    | `source_group` | `str` | Where the policy template came from, e.g. `scene` for a scene override |
    | `status` | `str` | `completed`: the policy ran; answers the decision model was not sure of still went to the usual request (see `fallback_ids` of `decision.gate.resolved`). `fallback`: the decision model was off or failed and the usual request ran instead. `preserved`: the original result was kept |
    | `requests` | `list` | One entry per decision model request: `request_id`, `label`, `status`, `failure_code`, `answers`, `elapsed_ms` |
    | `actions` | `list[dict]` | The actions the policy ran |

---

### decision.gate.resolved

Emitted when a yes/no decision gate has settled its candidates: queries, pin conditions, tracked states, portraits and character references.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `uid` | `str` | The policy, e.g. `world_state.decision-pin-conditions` |
    | `gate_enabled` | `bool` | Whether the decision model was used |
    | `candidates` | `list[str]` | The candidate ids |
    | `decided` | `dict` | Answers the decision model gave |
    | `fallback_ids` | `list[str]` | Candidates the usual request answered |
    | `result` | `dict` | The final answer for every candidate |

## Client Events

!!! note
    Clients change in the settings, also when no scene is loaded. Scene node graphs only see these events while their scene is loaded.

### client.enabled

Emitted when a client is switched on.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `client` | `ClientBase` | The client (`client.name` is its name) |
    | `enabled` | `bool` | `True` |

---

### client.disabled

Emitted when a client is switched off.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `client` | `ClientBase` | The client |
    | `enabled` | `bool` | `False` |

---

### client.embeddings_available

Emitted when a client reports that it can serve embeddings (KoboldCpp).

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `client` | `ClientBase` | The client |
    | `embedding_name` | `str` | The embedding model name |
    | `seen` | `bool` | **Mutable.** Set by the Memory agent when it offered the embeddings |

## Scene revision events

Use a **Listen** event module to react to saved scene states, and **Get** to read its detached payload. These events describe committed revision storage. Changes made by a listener belong to a later save. Save events run outside the save lock; loading an existing save and read-only previews do not emit them.

For a node with a required `state` input, such as **Set State (Path)** or **Update Game State**, connect the **Event** node's `event` output, or another value from the module, to that input. Pass the event data through the node's separate data inputs; its `state` output passes the activation value through unchanged. **Set State** and **Unset State** have no `state` input.

Every payload identifies the project with `project_path` and the save with `filename`. Revision numbers belong to that save's ancestry; `revision_id` identifies the recorded state independently of its filename.

### scene.revision_saved

Fires after a normal save commits a new revision. Usually the JSON file has also been written. If a later part of the save fails, this event still fires with `error` set: the revision exists even though the save operation reported an error. A save that records no new revision emits no saved event. A save made while character knowledge is being updated sends its event when that update has finished.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `operation` | `str` | `save` |
    | `project_path` | `str` | Project directory |
    | `filename` | `str` | Save filename |
    | `revision` | `int` | Committed revision number |
    | `revision_id` | `str` | Committed revision identity |
    | `parent_id` | `str \| None` | Preceding revision |
    | `error` | `str \| None` | Error after the revision committed, or `None` |

---

### scene.revision_forked

Fires when a fork's file and inherited link are ready. **Save As** also emits this event when its inherited link and new revision commit together, followed by `scene.revision_saved` for the new state. If writing the destination's JSON later fails, both events include `error`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `operation` | `str` | `fork` |
    | `project_path` | `str` | Project directory |
    | `filename` | `str` | New save filename |
    | `source_filename` | `str` | Source save filename |
    | `revision` | `int` | Fork-point revision number |
    | `revision_id` | `str` | Fork-point identity |
    | `parent_id` | `str \| None` | Revision preceding the fork point |
    | `error` | `str \| None` | Later Save As error, or `None` |

---

### scene.revisions_deleted

Fires after removing a save's revision link and collecting content that no remaining save uses. Inherited revisions still used by forks remain available. If damaged content prevents safe collection, unused blobs are retained and `removed_blobs` is zero.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `operation` | `str` | `delete` |
    | `project_path` | `str` | Project directory |
    | `filename` | `str` | Deleted save filename |
    | `removed_revisions` | `int` | Revisions collected |
    | `removed_blobs` | `int` | Unused content items collected |

---

### scene.revision_failed

Fires when saving, forking or deleting revisions fails without committing that revision operation. A save rejected before recording starts, such as a scene without a name, emits no revision event. A committed revision followed by a JSON write error emits `scene.revision_saved` with an error instead. If recording a Save As replacement fails, the destination keeps its previous revisions and no fork event is emitted.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `operation` | `str` | `save`, `fork` or `delete` |
    | `project_path` | `str` | Project directory |
    | `filename` | `str` | Affected save filename |
    | `error` | `str` | Failure reason |

The shared payload also has `source_filename`, revision fields and deletion counts when they are not relevant to an event: unused source and revision fields default to `None`, and counts to zero.
