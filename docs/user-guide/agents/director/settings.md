# Settings

## General

![Director agent settings](/talemate/img/0.29.0/director-general-settings.png)

##### Direct

If enabled the director will attempt to direct the scene.

This is currently only relevant if the scene loaded comes with a script file. For the scenes that are currently included that is only true for the **Simulation Suite**.

###### Turns

How many turns to wait before the director makes a decision.

##### Direct Scene

If enabled the director will attempt to direct the scene through narration.

##### Direct Actors

Enables the director to direct the actors in the scene.

Right now this is only triggered manually by the player when the players uses the `Direct actor` toolset from the [Scenario tools](/talemate/user-guide/scenario-tools).

###### Actor Direction Mode

When an actor is given a direction, how is it to be injected into the context

- `Direction`
- `Inner Monologue`

If `Direction` is selected, the actor will be given the direction as a direct instruction, by the director.

If `Inner Monologue` is selected, the actor will be given the direction as a thought.

###### Direction Stickiness

!!! info "New in 0.35.0"

Controls how many scene messages the system looks back when retrieving character directions. This determines how long directions "stick" and continue to influence character behavior.

- **Range**: 1 to 20
- **Default**: 5

When you direct an actor, that direction doesn't just apply to their next response—it persists across multiple turns based on this setting. For example, with a stickiness of 5, a direction to "act suspiciously" will continue to influence the character's behavior for up to 5 relevant scene messages.

!!! note "Time passage clears directions"
    Directions are automatically cleared when time passes in the scene. This ensures that directions given in one scene segment don't inappropriately carry over into a new time period.

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

## Dynamic Actions

Dynamic actions are introduced in `0.28.0` and allow the director to generate a set of clickable choices for the player to choose from.

![Director agent dynamic actions settings](/talemate/img/0.29.0/director-dynamic-actions-settings.png)

##### Enable Dynamic Actions

If enabled the director will generate a set of clickable choices for the player to choose from.

##### Chance

The chance that the director will generate a set of dynamic actions when its the players turn.

This ranges from `0` to `1`. `0` means the director will never generate dynamic actions, `1` means the director will always generate dynamic actions.

##### Number of Actions

The number of actions to generate.

##### Never auto progress on action selection

If this is checked and you pick an action, the scene will NOT automatically pass the turn to the next actor.

##### Instructions

Allows you to provide extra specific instructions to director on how to generate the dynamic actions.

For example you could provide a list of actions to choose from, or a list of actions to avoid. Or specify that you always want a certain action to be included.

## Guide Scene

![Director agent guide scene settings](/talemate/img/0.29.0/director-guide-scene-settings.png)

The director can use the summarizer agent's scene analysis to guide characters and the narrator for the next generation, hopefully improving the quality of the generated content.

!!! danger "This may break dumber models"
    The guidance generated is inserted **after** the message history and **right before** the next generation. Some older models may struggle with this and generate incoherent responses.

##### Guide Actors

If enabled the director will guide the actors in the scene.

##### Guide Narrator

If enabled the director will guide the narrator in the scene.

##### Max. Guidance Length

The maximum number of tokens for the guidance. (e.g., how long should the guidance be).

## Scene Direction

!!! info "New in 0.35.0"
    Scene Direction replaces the previous Auto Direction feature with significantly enhanced capabilities.

Autonomous Scene Direction allows the director to progress scenes automatically using the same actions available in Director Chat.

For detailed information, see the dedicated [Autonomous Scene Direction](/talemate/user-guide/agents/director/scene-direction) documentation page.

![Director Scene Direction Settings](/talemate/img/0.35.0/director-scene-direction-settings.png)

##### Enable Scene Direction

Toggle to enable or disable autonomous scene direction. This feature is disabled by default.

!!! warning "Strong LLM Required"
    A strong language model (100B+) with reasoning capabilities is highly recommended. See [Reasoning Model Support](/talemate/user-guide/clients/reasoning/).

##### Enable Analysis Step

When enabled, the director performs an internal analysis step before deciding on actions.

##### Response Token Budget

Maximum tokens for director reasoning and response generation. Default is 2048.

##### Max Actions Per Turn

Maximum number of actions the director can execute per turn. Default is 5.

##### Retries

Retry count for malformed responses. Default is 1.

##### Scene Context Ratio

Balance between scene context and direction history in the token budget. Default is 0.30 (30% scene, 70% history).

##### Stale History Share

When compacting direction history, this fraction is summarized versus kept verbatim. Default is 0.70.

##### Maintain Turn Balance

Track character and narrator participation to encourage variety in scene direction.

##### Custom Instructions

Custom instructions included in all scene direction prompts to guide the director's behavior.

## Character Management

The Character Management settings control how the director handles character creation and related tasks.

![Director Character Management Settings](/talemate/img/0.35.0/director-character-management-settings.png)

### Character Creation

!!! info "New in 0.35.0"
    The **Limit character attributes** setting is new in version 0.35.0.

##### Limit character attributes

Controls the maximum number of attributes that will be generated when creating or updating character sheets. This applies when the director creates new characters or when character sheets are generated through templates.

- **0** (default): No limit - attributes are generated without restriction
- **1-40**: Limits the character sheet to this many attributes

When a limit is set, the AI is instructed to generate no more than the specified number of attributes, and any excess attributes are trimmed during processing.

This setting is useful when you want to keep character sheets concise, or when working with characters that might otherwise generate an excessive number of attributes.

### Persisting Characters

##### Assign Voice (TTS)

If enabled, the director will automatically assign a text-to-speech voice when creating a new character. This requires the TTS agent to be enabled and configured with available voices.

### Generating Visuals

##### Generate Visuals

If enabled, the director is allowed to generate visual assets (portraits, cover images) for characters when requested.

## Director Chat

!!! example "Experimental"
    Currently experimental and may change substantially in the future.

The [Director Chat](/talemate/user-guide/agents/director/chat) feature allows you to interact with the director through a conversational interface where you can ask questions, make changes to your scene, and direct story progression.

![Director Chat Settings](/talemate/img/0.33.0/director-agent-chat-settings.png)

##### Enable Analysis Step

When enabled, the director performs an internal analysis step before responding. This helps the director think through complex requests and plan actions more carefully.

!!! tip "Recommended for complex tasks"
    Enable this when working on complex scene modifications or when you want more thoughtful responses. Disable it for simple queries to get faster responses.

##### Response token budget

Controls the maximum number of tokens the director can use for generating responses. Higher values allow for more detailed responses but use more tokens. Default is 2048.

##### Auto-iteration limit

The maximum number of action-response cycles the director can perform in a single interaction. For example, if set to 10, the director can execute actions and generate follow-up responses up to 10 times before requiring your input again. Default is 10.

##### Retries

The number of times the director will retry if it encounters an error during response generation. Default is 1.

##### Scene context ratio

Controls the fraction of the remaining token budget (after fixed context and instructions) that is reserved for scene context. The rest is allocated to chat history.

- **Lower values** (e.g., 0.30): 30% for scene context, 70% for chat history
- **Higher values** (e.g., 0.70): 70% for scene context, 30% for chat history

Default is 0.30.

##### Stale history share

When the chat history needs to be compacted (summarized), this controls what fraction of the chat history budget is treated as "stale" and should be summarized. The remaining portion is kept verbatim as recent messages.

- **Lower values** (e.g., 0.50): Summarize less (50%), keep more recent messages verbatim
- **Higher values** (e.g., 0.90): Summarize more (90%), keep fewer recent messages verbatim

Default is 0.70 (70% will be summarized when compaction is triggered).

##### Custom instructions

Add custom instructions that will be included in all director chat prompts. Use this to customize the director's behavior for your specific scene or storytelling style.

For example, you might add instructions to maintain a particular tone, follow specific genre conventions, or handle certain types of requests in a particular way.