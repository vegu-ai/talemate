# Templates

Click the **:material-cube-scan: Templates** tab in the top navigation bar to manage templates.

These templates are used to facilitate the generation of content for your game. They can be used to define character attributes, character details, writing styles, and automated world or character state tracking.

Templates are managed in groups. Each group can contain multiple templates. When starting out, start by creating a new group and then add templates to it.

Templates are stored outside of individual games and will be available for all games you run.

## Template types

### :material-badge-account: Character Attribute
Character attribute templates are used to define attributes that a character can have. They can be used to define character traits, skills, or other properties. The AI will use this template to generate content that matches the attribute, based on the current progression of the scene or their backstory.

### :material-account-details: Character Detail
Character detail templates are used to define details about a character. They generally are longer form questions or statements that can be used to flesh out a character's backstory or personality. The AI will use this template to generate content that matches the detail, based on the current progression of the scene or their backstory.

### :material-chili-mild: Spices
Spice collections are used to define a set of instructions that can be applied during the generation of character attributes or details. They can be used to add a bit of randomness or unexpectedness. A template must explicitly support spice to be able to use a spice collection.

### :material-script-text: Writing Style
Writing style templates are used to define a writing style that can be applied to the generated content. They can be used to add a specific flavor or tone. A template must explicitly support writing styles to be able to use a writing style template.

### :material-image-auto-adjust: State Reinforcement
State reinforcement templates are used to quickly (or even automatically) setup common attribues and states you want to track for characters or the world itself. They revolve around a question, statement or attribute name that you want to track for a character. The AI will use this template to generate content that matches the query, based on the current progression of the scene.

### :material-movie-open: Scene Type
Scene type templates are used to define different types of scenes that can be played in your game. Each scene type has different rules and constraints that guide the generation and flow of the scene.

### :material-palette: Visual Style
Visual style templates define how image generation prompts are constructed — positive and negative prompt prefixes and suffixes, and the prompting type (keywords vs. descriptive). Select a style in the [visualizer agent's Styles settings](/talemate/user-guide/agents/visualizer/settings/#styles).

### :material-auto-fix: Visual Prompt Finalizer
Visual prompt finalizer templates define a reusable set of post-processing actions (exact, fuzzy or regex match and replace, or an AI instruction) applied to image generation prompts. See [Visual Prompt Finalizer](/talemate/user-guide/templates/visual-finalizer).

### :material-account-voice: Agent Persona
Agent persona templates define how an agent should present and behave in prompts — tone, perspective, style. Assign a persona per agent in the [Scene Settings](/talemate/user-guide/world-editor/scene/settings). (Currently used by the director.)

### :material-lightning-bolt: Scene Tool Shortcut
Scene tool shortcut templates package a [scene tool shortcut](/talemate/user-guide/scenario-tools#shortcuts) — an agent action with a label, an icon and canned instructions. Installing one adds the shortcut to the scene tools menu it belongs to. See [Scene Tool Shortcuts](/talemate/user-guide/templates/scene-tool-shortcut).

### :material-palette-swatch: Theme
Theme templates define Talemate's colors — the interface surfaces, the general interface, the scene messages and the chats — together with the message text styling, which color scheme the in-app code editors use and whether the theme is light or dark. Applying one makes it the active theme. See [Themes](/talemate/user-guide/templates/themes).

## Asking the help chat for a template

The [help agent](/talemate/user-guide/agents/help/) can build and change templates for you, once you grant it the **Allow changes to templates** [permission](/talemate/user-guide/agents/help/#permissions) — it starts off, and until it is on the agent reads your templates and walks you through the change instead. With it on, ask for what you want — "make me a character attribute template for a fighting style", "add a state reinforcement that tracks where everyone is, checked every five turns" — and it writes a real template into a template group you name, creating the group if it does not exist yet. It can also read a template of yours and change individual fields of it.

Applying a template, installing a scene tool shortcut and deleting a template stay yours: applying writes into your scene, which the help agent does not touch. The groups Talemate ships are read-only to the agent, and so is any template marked locked; it offers to copy one into a group of your own instead of editing it. See [what the help agent can do with templates](/talemate/user-guide/agents/help/#world-state-templates).

!!! note "Unsaved edits in the Templates tab"
    While this tab holds an unsaved template edit, the help agent refuses to write and asks you to let that edit save first. The tab saves the whole template it is on, so its save would push your copy back over whatever the agent had written.

    The refusal is decided from what the tab reported when you sent the message, so a write can still land while you are typing. If it does, the editor shows a warning above the form saying the template was changed elsewhere — your unsaved edits win when they save, so redo the change you asked for if you still want it.

