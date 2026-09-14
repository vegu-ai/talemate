# Settings

## :material-cog: General
![Narrator agent settings](/talemate/img/0.40.0/narrator-general-settings.png)

##### Client

The text-generation client to use for narration generation.

##### Optimize for Prompt Caching

Places volatile context (long term memory, dynamic notes) after the scene history so that the stable part of the prompt can be cached by API backends. May confuse weaker models. `Auto` defers to the client setting.

##### Generation

Generation settings for the narrator agent.

###### Jiggle

The amount of randomness to apply to the generation. This can help to avoid repetitive responses.

###### Instructions

Extra instructions for the generation. This should be short and generic as it will be applied for all narration.

###### Generation Length Per Narration Type

Generation length is configurable per narration type. Each type of narration can have its own maximum token length, allowing you to control how verbose different types of narration are:

- **Progress Story** -- general story progression narration
- **Scene Narration** -- environment and scene descriptions
- **Query Narration** -- responses to player queries
- **Character Narration** -- character-focused narration (look at character)
- **Time Passage** -- narration during time jumps
- **After Dialogue** -- automatic narration after character speech
- **Character Entry** -- narration when a character enters the scene
- **Character Exit** -- narration when a character leaves the scene

## :material-script-text: Content

![Narrator agent content settings](/talemate/img/0.40.0/narrator-content-settings.png)

Content settings control what contextual information is included in the prompts sent to the AI when generating narration.

##### Use Scene Intent

When enabled (default), the [scene intent](/talemate/user-guide/world-editor/scene/direction) (overall intention) will be included in the narration prompt. This helps the AI generate narrative content that aligns with your story goals and the current scene direction.

Disable this if you want the AI to generate narration without being influenced by the scene direction settings.

##### Use Writing Style

When enabled (default), the writing style selected in the [Scene Settings](/talemate/user-guide/world-editor/scene/settings) will be applied to the generated narration.

Disable this if you want the AI to generate narration without following the scene's writing style template.

## :material-clock-fast: Narrate time passage

![Narrator agent time passage settings](/talemate/img/0.40.0/narrator-narrate-time-passage-settings.png)

The narrator can automatically narrate the passage of time when you indicate it using the [Scene tools](/talemate/user-guide/scenario-tools).

##### Guide time narration via prompt

Wheneever you indicate a passage of time using the [Scene tools](/talemate/user-guide/scenario-tools), the narrator will wait for a prompt from you before narrating the passage of time.

This allows you to explain what happens during the passage of time.

## :material-script-text-play: Auto Narration

!!! info "New in 0.37.0"

    Replaces the **Narrate after Dialogue** action. The old auto-trigger fired a single, fixed narration type after every character turn; Auto Narration is a probability-gated dispatcher that can fire any one of three narration types — including the same post-dialogue narration that the old action ran.

Container action that fires narration on its own during the scene loop. Disabled by default; quick toggle available next to the agent's General settings.

See [Auto Narration](/talemate/user-guide/agents/narrator/auto-narration) for the full description, weights breakdown, and gating rules.

##### Chance

Master probability that anything fires on a given actor turn. Range `0.0`–`1.0`, step `0.05`. `0` never fires; `1` fires every turn. The chance roll is the last gate — feature-disabled, scene-direction suppression, and zero weights all skip the roll entirely.

##### Action Weights

Relative likelihood of each action when auto narration fires. Three sliders that auto-rebalance to always sum to `1.0`:

- **Progress Story** — moves the story forward (uses `progress_story`).
- **Narrate Scene** — visually-focused description of what is currently happening (uses `narrate_scene`).
- **Narrate Environment** — post-dialogue ambience and reactions, focused on sensory information (uses `narrate_after_dialogue` internally; the response length budget for it lives under [Generation Length Per Narration Type](#generation-length-per-narration-type) → **After dialogue**).

Drag any slider to set its weight; the other two redistribute proportionally to make the total stay at `1.0`. The slider you released last is "pinned" (a small :material-pin: icon appears next to its label) so you can adjust a third slider without disturbing the value you just set. A weight of `0` removes that action from the pool entirely — the chance roll still happens, but the action is not eligible to be picked.

##### Disable during scene direction

Default on. When the [director's Scene Direction](/talemate/user-guide/agents/director/scene-direction) is enabled — either via the agent toggle or a scene-level always-on override — Auto Narration is skipped. Turn this off if you want both systems running at once.

## :material-account-clock-outline: Offscreen Life

Requires **Limit to character knowledge** in Standard mode; Character perspectives always uses character context.

When enabled, an actual return with intervening story or recorded scene time adds one Narrator request about what the character did while away. It does not wait for a summary. The request reads the character's permitted context and any established arrival constraints; it does not launch extra fact extraction or perspective repairs. A new character or an immediate leave and return with nothing in between gets no account.

The result becomes one private offscreen fact, referenced by the collapsed return entry in scene history. Edit the arrival note in that entry and the account in the Facts editor. A failed or cancelled account leaves the zero-request transition usable, with an explicit retry while that return is current. There is no automatic fallback request.

Off by default. The character knowledge effort slider enables it at **Thorough** and Standard **Ultra**, and disables it at **Off**, **Minimal**, **Light**, and **Balanced**. Balanced stays the new-story default. Loading a scene neither enables it nor generates an account.

##### Length

Token length for the offscreen life narration (default 192).

## :material-brain: Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"
