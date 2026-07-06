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
| [`scene_init`](#scene_init) | Scene Loop |
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
| [`agent.creator.contextual_generate.before`](#agentcreatorcontextual_generatebefore) | Creator Agent |
| [`agent.creator.contextual_generate.after`](#agentcreatorcontextual_generateafter) | Creator Agent |
| [`agent.creator.autocomplete.before`](#agentcreatorautocompletebefore) | Creator Agent |
| [`agent.creator.autocomplete.after`](#agentcreatorautocompleteafter) | Creator Agent |
| [`agent.creator.dialogue_examples.before`](#agentcreatordialogue_examplesbefore) | Creator Agent |
| [`agent.creator.dialogue_examples.after`](#agentcreatordialogue_examplesafter) | Creator Agent |
| [`agent.editor.revision-analysis.before`](#agenteditorrevision-analysisbefore) | Editor Agent |
| [`agent.editor.revision-analysis.after`](#agenteditorrevision-analysisafter) | Editor Agent |
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
| [`agent.world_state.time`](#agentworld_statetime) | World State Agent |
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
| [`agent.tts.prepare.before`](#agentttspreparebefore) | TTS Agent |
| [`agent.tts.prepare.after`](#agentttsprepareafter) | TTS Agent |
| [`agent.tts.generate.before`](#agentttsgeneratebefore) | TTS Agent |
| [`agent.tts.generate.after`](#agentttsgenerateafter) | TTS Agent |
| [`agent.visual.generation.before_generate`](#agentvisualgenerationbefore_generate) | Visual Agent |
| [`agent.visual.generation.after_generate`](#agentvisualgenerationafter_generate) | Visual Agent |
| [`agent.visual.prompt_finalize.before`](#agentvisualprompt_finalizebefore) | Visual Agent |
| [`agent.visual.prompt_finalize.after`](#agentvisualprompt_finalizeafter) | Visual Agent |
| [`asset_saved`](#asset_saved) | Scene Assets |
| [`asset_deleted`](#asset_deleted) | Scene Assets |
| [`scene.backdrop_changed`](#scenebackdrop_changed) | Scene Assets |
| [`scene.cover_image_changed`](#scenecover_image_changed) | Scene Assets |
| [`character.cover_image_changed`](#charactercover_image_changed) | Scene Assets |

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

## World State Agent Events

### agent.world_state.time

Emitted when the world state agent advances the time in the scene.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `WorldStateAgent` | The agent instance |
    | `duration` | `str` | The duration of the time passage (ISO 8601 duration) |
    | `human_duration` | `str` | The human-readable duration of the time passage |
    | `narrative` | `str` | The narrative direction of the time passage |

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

## TTS Agent Events

### agent.tts.prepare.before

Emitted **before** an optional `prepare_fn` runs against an audio chunk (e.g. text normalization, audio-tag rewriting, voice selection). Only fires for chunks that declare a `prepare_fn`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `chunk` | `Chunk` | The TTS chunk about to be prepared |
    | `context` | `GenerationContext` | The full generation context (all chunks for the current request) |
    | `wav_bytes` | `bytes \| None` | Always `None` at this point |

---

### agent.tts.prepare.after

Fires after a chunk's `prepare_fn` has run but before audio generation starts. Handlers can inspect (or mutate) the now-prepared chunk.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `chunk` | `Chunk` | The prepared TTS chunk |
    | `context` | `GenerationContext` | The full generation context |
    | `wav_bytes` | `bytes \| None` | Always `None` at this point |

---

### agent.tts.generate.before

Emitted **immediately before** the chunk is sent to the active TTS backend for synthesis.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `chunk` | `Chunk` | The TTS chunk about to be synthesised |
    | `context` | `GenerationContext` | The full generation context |
    | `wav_bytes` | `bytes \| None` | Always `None` at this point |

---

### agent.tts.generate.after

Fires after the TTS backend returns audio for a chunk and before the audio is played back. Handlers can inspect (or replace) the produced audio via `wav_bytes`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `chunk` | `Chunk` | The TTS chunk that was synthesised |
    | `context` | `GenerationContext` | The full generation context |
    | `wav_bytes` | `bytes \| None` | **Mutable.** The synthesised audio bytes (None if generation failed) |

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