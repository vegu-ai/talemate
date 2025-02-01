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

The narrator agent is the first agent that can be influenced by one of your writing style templates.

Enable this setting to apply a writing style to the generated content.

Make sure the a writing style is selected in the [Scene Settings](/talemate/user-guide/world-editor/scene/settings) to apply the writing style to the generated content.

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