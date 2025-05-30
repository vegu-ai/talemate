# Events

List of currently supported events.

!!! warning "Events not listed here"
    There are many other events defined in the talemate codebase that are purposefully not listed here yet. 

    The reason for this is that there is an ongoing cleanup process and some of them may not stick around in their current form.

    You can of course still hook into them, but be aware that they may change or be removed in the future.

## Event Index

| Event | Category |
|-------|----------|
| [`game_loop_actor_iter`](#game_loop_actor_iter) | Game Loop |
| [`game_loop_ai_character_iter`](#game_loop_ai_character_iter) | Game Loop |
| [`game_loop_player_character_iter`](#game_loop_player_character_iter) | Game Loop |
| [`game_loop_new_message`](#game_loop_new_message) | Game Loop |
| [`player_turn_start`](#player_turn_start) | Game Loop |
| [`scene_loop_init`](#scene_loop_init) | Scene Loop |
| [`scene_loop_start_cycle`](#scene_loop_start_cycle) | Scene Loop |
| [`scene_loop_end_cycle`](#scene_loop_end_cycle) | Scene Loop |
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
| [`agent.editor.revision-analysis.before`](#agenteditorrevision-analysisbefore) | Editor Agent |
| [`agent.editor.revision-analysis.after`](#agenteditorrevision-analysisafter) | Editor Agent |
| [`agent.editor.revision-revise.before`](#agenteditorrevision-revisebefore) | Editor Agent |
| [`agent.editor.revision-revise.after`](#agenteditorrevision-reviseafter) | Editor Agent |
| [`agent.narrator.before_generate`](#agentnarratorbefore_generate) | Narrator Agent |
| [`agent.narrator.inject_instructions`](#agentnarratorinject_instructions) | Narrator Agent |
| [`agent.narrator.generated`](#agentnarratorgenerated) | Narrator Agent |
| [`agent.director.guide.before_generate`](#agentdirectorguidebefore_generate) | Director Agent |
| [`agent.director.guide.inject_instructions`](#agentdirectorguideinject_instructions) | Director Agent |
| [`agent.director.guide.generated`](#agentdirectorguidegenerated) | Director Agent |
| [`agent.director.generate_choices.before_generate`](#agentdirectorgenerate_choicesbefore_generate) | Director Agent |
| [`agent.director.generate_choices.inject_instructions`](#agentdirectorgenerate_choicesinject_instructions) | Director Agent |
| [`agent.director.generate_choices.generated`](#agentdirectorgenerate_choicesgenerated) | Director Agent |
| [`agent.world_state.time`](#agentworld_statetime) | World State Agent |
| [`agent.summarization.scene_analysis.before`](#agentsummarizationscene_analysisbefore) | Summarization Agent |
| [`agent.summarization.scene_analysis.cached`](#agentsummarizationscene_analysiscached) | Summarization Agent |
| [`agent.summarization.scene_analysis.before_deep_analysis`](#agentsummarizationscene_analysisbefore_deep_analysis) | Summarization Agent |
| [`agent.summarization.scene_analysis.after_deep_analysis`](#agentsummarizationscene_analysisafter_deep_analysis) | Summarization Agent |
| [`agent.summarization.scene_analysis.after`](#agentsummarizationscene_analysisafter) | Summarization Agent |

## Game Loop

---

### game_loop_actor_iter

Triggered after either a player or AI character has had a turn.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `actor` | `Actor` | The actor object |

---

### game_loop_ai_character_iter

Triggered after the AI character has had a turn.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `character` | `Character` | The character object |

---

### game_loop_player_character_iter

Triggered after the player character has had a turn.

!!! payload "Payload"

    | Name | Type | Description |
    |------|------|-------------|
    | `scene` | `Scene` | The scene object |
    | `character` | `Character` | The character object |

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

### scene_loop_init

Triggered when the scene loop is initialised.

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

Emitted **before** the Editor agent requests the revision-analysis prompt.  
Handlers can add extra analysis instructions via `dynamic_instructions` or adjust `template_vars`.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `EditorAgent` | The agent instance |
    | `template_vars` | `dict` | Variables that will be fed into the prompt – **mutable** |
    | `dynamic_instructions` | `list[DynamicInstruction]` | **Mutable.** Push additional `DynamicInstruction` objects to influence analysis |

---

### agent.editor.revision-analysis.after

Emitted after the revision-analysis prompt returns but **before** the rewrite is requested.  
Handlers may inspect or replace the `response` string.

!!! payload "Payload"

    | Field | Type | Notes |
    |-------|------|-------|
    | `agent` | `EditorAgent` | The agent instance |
    | `template_vars` | `dict` | Same vars used for the prompt |
    | `response` | `str` | **Mutable.** Raw analysis text returned by the model |

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
