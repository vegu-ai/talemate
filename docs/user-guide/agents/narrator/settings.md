# Settings

## :material-cog: General
![Narrator agent settings](/talemate/img/0.29.0/narrator-general-settings.png)

##### Client

The text-generation client to use for conversation generation.

##### Generation Override

Checkbox that exposes further settings to configure the conversation agent generation.

###### Instructions

Extra instructions for the generation. This should be short and generic as it will be applied for all narration.

##### Auto Break Repetition

If checked and talemate detects a repetitive response (based on a threshold), it will automatically re-generate the resposne with increased randomness parameters.

## :material-script-text: Content

![Narrator agent content settings](/talemate/img/0.29.0/narrator-content-settings.png)

Content settings control what contextual information is included in the prompts sent to the AI when generating narration.

##### Use Scene Intent

When enabled (default), the [scene intent](/talemate/user-guide/world-editor/scene/direction) (overall intention) will be included in the narration prompt. This helps the AI generate narrative content that aligns with your story goals and the current scene direction.

Disable this if you want the AI to generate narration without being influenced by the scene direction settings.

##### Use Writing Style

When enabled (default), the writing style selected in the [Scene Settings](/talemate/user-guide/world-editor/scene/settings) will be applied to the generated narration.

Disable this if you want the AI to generate narration without following the scene's writing style template.

## :material-clock-fast: Narrate time passage

![Narrator agent time passage settings](/talemate/img/0.29.0/narrator-narrate-time-passage-settings.png)

The narrator can automatically narrate the passage of time when you indicate it using the [Scene tools](/talemate/user-guide/scenario-tools).

##### Guide time narration via prompt

Wheneever you indicate a passage of time using the [Scene tools](/talemate/user-guide/scenario-tools), the narrator will wait for a prompt from you before narrating the passage of time.

This allows you to explain what happens during the passage of time.

## :material-forum-plus-outline: Narrate after dialogue

![Narrator agent after dialogue settings](/talemate/img/0.29.0/narrator-narrate-after-dialogue-settings.png)

Whenever a character speaks, the narrator will automatically narrate the scene after.

## :material-brain: Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"