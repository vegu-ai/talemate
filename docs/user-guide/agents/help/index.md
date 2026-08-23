# Overview

The help agent provides an interactive help chat that answers questions about Talemate itself - settings, agents, clients, the world editor, the node editor and everything else the application offers.

It grounds its answers in the documentation that ships with Talemate: it knows the documentation's sections and can look up relevant pages by topic, search the documentation, read whole pages, or read individual sections before answering.

Open the help chat via the :material-help-circle-outline: icon in the app bar. No scene needs to be loaded. The icon is only there while the Help agent is enabled - if you don't see it, enable the agent under **Settings → Connections → Agents → Help**.

![Help chat answering a question about dialogue styling](/talemate/img/0.39.0/help-agent-chat.png)

## What it can and cannot do

- It answers questions and points you to the relevant documentation pages.
- Its answers can include links that navigate you inside the application - to an agent's settings, a world editor tab, or the director console.
- It can read your configuration and, when you ask it to, change settings for you - see [Reading and changing settings](#reading-and-changing-settings) below.
- It can build and change [themes](#themes) for you - see Themes below.
- It **cannot** change anything in your scene itself - its story, characters or world state. If you want to make changes to a scene through chat, use the [director's chat](/talemate/user-guide/agents/director/chat) instead. For questions about your scene's content the director chat is also the better place - the help agent only sees a shallow snapshot of the scene, the director has the full context.

## Reading and changing settings

The help agent can see what you currently have configured, so instead of answering from the documentation alone it can tell you what a setting is *set to* and what your options are. It can look at:

- Any agent's settings - every action and setting with its current value, valid choices, and any per-scene overrides.
- Application settings - the game (general), appearance, creator, inference/embeddings presets, and prompt template group sections of your config.
- Your configured clients - type, model, context length and status.

When you ask it to, it can also **change** settings:

- Agent settings, either globally or as a [per-scene override](/talemate/user-guide/agents/scene-overrides) for the currently loaded scene - it can also remove a scene override so the setting falls back to the global value again.
- Application settings in the game, appearance, and creator sections.

So things like "switch the conversation format to Narrative", "lower the editor revision to only run on dialogue", "turn off auto save" or "override the visualizer style for this scene only" can be done right from the chat. Changes are applied immediately, the chat records exactly what changed (old and new value), and an open settings view picks them up live.

Some things are intentionally out of reach:

- API keys and passwords are never shown to the help agent and it cannot change them - key management stays in the application settings (Connections → API Keys).
- Clients are read-only - client changes (model, context length, etc.) must be made in the client settings.
- Complex settings (tables, weight maps, template pickers) are read-only in chat and must be edited in the settings interface directly.

!!! note "Unsaved settings edits"
    Having the Settings tab open is fine - applied changes show up there live. But while the settings view holds **unsaved edits**, the help agent refuses to change anything - agent settings and application settings alike - and asks you to save or discard them first. That view edits a working copy of your *whole* configuration and saves all of it at once, so its **Save** would push the pre-change values back over whatever the agent just wrote for you. Which page you happen to be on makes no difference.

    Unsaved edits stay pending when you switch to another main tab, and so does the refusal. Save or discard them, then ask again.

## Themes

The help agent can also work on [themes](/talemate/user-guide/templates/themes) — the templates that hold Talemate's colors. Ask for a theme in the chat and you get a real theme template you can apply from **Appearance → Theme**:

- "Create a solarized dark theme for me"
- "Make the narrator text in my theme a bit greener"
- "Copy Talemate Dark into my own group and give it a warmer background"

It can list your themes, read one in full, create one, change the colors, message styling, mode and code editor scheme of one you own, and apply a theme so the app repaints immediately.

A theme it creates is always complete: every one of the 51 color slots is taken from another theme first — the one you are running unless you name a different one — and only what you asked about is changed on top. It goes into a template group you name, creating the group if it does not exist yet; without a preference it uses one called **My Themes**.

### How it judges colors

The agent cannot see the theme it is writing, so what can be computed is handed to it. Reading a theme reports, per slot:

- **A rough name for the color**, such as "muted dark blue" or "vivid red", so it can tell a slate blue from a bright one and notice when two slots hold the same family.
- **The contrast** between that color and the fill it is drawn on, as a WCAG ratio. Four of the theme's own fills carry content — the page background, the card surface, the toolbar band, and the tooltip fill for its own label — and the reported number is the worst of the ones that slot is drawn on, with that fill named. The band only counts for the slots the interface really puts on one. The ratio is arithmetic between two colors of your theme, truncated down to two decimals.
- **The reference** WCAG asks of what that slot paints: 4.5:1 where the slot paints text, 3:1 where it paints chips, icons and other interface marks.

What the theme does **not** know is where a slot is really drawn — that lives in the interface code, not in the palette. Where a slot is known to be drawn somewhere else, it is reported as **unmeasured** with the reason instead of being given a number: the muted color is dimmed by opacity before it is drawn, code spans sit on the toolbar fill, the asset badge fills with its color and puts a white label on top, and the chat bubbles tint themselves with their own color. The agent is told that unmeasured means unknown rather than fine.

Nothing in the result decides whether a slot passes. It reports the measurement and the reference and leaves the judgement to the agent, which names what falls under the reference after every change so you hear about a hard-to-read color in the same conversation. The shipped themes are not exempt: Talemate Dark reports four — its brackets markup at 4.42:1, its primary at 4.37:1 and its error at 4.47:1, all near-misses on text, and its delete at 3.23:1, which is not — and Talemate Light reports eight accents that measure between 3.73:1 and 4.06:1 on the toolbar band, where its Save button label is drawn.

What it will not do:

- Edit a theme that ships with Talemate. Talemate Dark and Talemate Light are locked; the agent offers to copy one into a group of your own instead.
- Delete a theme. That stays in the Templates tab — select the theme and click **Remove template**.

A color you set by hand on the [Appearance → Messages](/talemate/user-guide/app-settings/appearance/#messages) page keeps overriding the theme, so a theme change you cannot see is usually that override. The agent can read your appearance settings and clear the override for you if you ask.

One more thing changes only on apply: the **message styling** — italic, bold, visibility, own color and the backdrop settings. Colors, mode and the code editor scheme of the theme you are running repaint the app the moment the agent writes them, but styling is read from your appearance settings, which a theme writes only when it is [applied](/talemate/user-guide/templates/themes/#applying-a-theme). The agent says so instead of claiming a change you cannot see.

!!! note "Unsaved edits in the Templates tab"
    The same rule as for settings applies: while the Templates tab holds an unsaved theme edit — an open color picker, a notes field you have not left — the agent refuses to write a theme and asks you to let that edit save first. The tab saves the whole template it is on, so its save would overwrite what the agent wrote.

    The refusal is decided from what the tab reported when you sent the message, so a write can still land while you are typing. If it does, the editor shows a warning above the form saying the template was changed elsewhere — your unsaved edits win when they save, so redo the change you asked for if you still want it.

## Chats

Help conversations are multi-turn and you can keep several of them - use the chat selector at the top of the help drawer to switch, create, or delete chats. Chats persist across restarts (they are stored in `chats/help.json` in your Talemate directory, independent of any scene).

The most recent answer can be regenerated via the refresh button next to the message.

## Scene awareness

Each chat has a **Scene Aware** toggle. When enabled and a scene is loaded, the help agent can see the scene title, its characters, and recent scene progress, so you can ask scene-specific questions. When disabled the conversation is completely unaware of your scene.

The help agent also receives a small snapshot of what you are currently looking at in the interface - the active tab, which drawers you have open, whether a scene is loaded and what it is doing, the state of the settings view (the page you are on, whether it has unsaved edits, and which client or agent you have selected there - for an agent, also whether it is in **Global** or **Scene** mode), and the state of the Templates tab (the template you have selected and whether it has unsaved edits). So questions like "what does this setting do?" can be answered in context.

## Non-blocking

Help chat generation runs in the background and does not block the main Talemate loop - you can keep playing a scene while a help response is being generated. If your connected client does not support concurrent requests, the requests will naturally queue up against each other.
