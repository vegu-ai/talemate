# Overview

The help agent provides an interactive help chat that answers questions about Talemate itself - settings, agents, clients, the world editor, the node editor and everything else the application offers.

It grounds its answers in the documentation that ships with Talemate: it receives an index of all documentation pages and can search the documentation, read whole pages, or read individual sections before answering.

Open the help chat via the :material-help-circle-outline: icon in the app bar. It is available at any time - no scene needs to be loaded.

![Help chat answering a question about dialogue styling](/talemate/img/0.39.0/help-agent-chat.png)

## What it can and cannot do

- It answers questions and points you to the relevant documentation pages.
- Its answers can include links that navigate you inside the application - to an agent's settings, a world editor tab, or the director console.
- It can read your configuration and, when you ask it to, change settings for you - see [Reading and changing settings](#reading-and-changing-settings) below.
- It **cannot** change anything in your scene itself - its story, characters or world state. If you want to make changes to a scene through chat, use the [director's chat](/talemate/user-guide/agents/director/chat) instead. For questions about your scene's content the director chat is also the better place - the help agent only sees a shallow snapshot of the scene, the director has the full context.

## Reading and changing settings

The help agent can see what you currently have configured, so instead of answering from the documentation alone it can tell you what a setting is *set to* and what your options are. It can look at:

- Any agent's settings - every action and setting with its current value, valid choices, and any per-scene overrides.
- Application settings - the game (general), appearance, creator, inference/embeddings presets, and prompt template group sections of your config.
- Your configured clients - type, model, context length and status.

When you ask it to, it can also **change** settings:

- Agent settings, either globally or as a [per-scene override](/talemate/user-guide/agents/scene-overrides) for the currently loaded scene - it can also remove a scene override so the setting falls back to the global value again.
- Application settings in the game, appearance, and creator sections.

So things like "switch the conversation format to Narrative", "lower the editor revision to only run on dialogue", "turn off auto save" or "override the visualizer style for this scene only" can be done right from the chat. Changes are applied immediately, the chat records exactly what changed (old and new value), and any open settings dialogs refresh live.

Some things are intentionally out of reach:

- API keys and passwords are never shown to the help agent and it cannot change them - key management stays in the settings dialog.
- Clients are read-only - client changes (model, context length, etc.) must be made in the client settings.
- Complex settings (tables, weight maps, template pickers) are read-only in chat and must be edited in their settings dialog.

!!! note "Open settings dialogs"
    If the settings dialog of the agent you want to change is currently open, the help agent will ask you to close it first. The dialog holds its own copy of the settings - it would not show the change, and closing it could overwrite it.

## Chats

Help conversations are multi-turn and you can keep several of them - use the chat selector at the top of the help drawer to switch, create, or delete chats. Chats persist across restarts (they are stored in `chats/help.json` in your Talemate directory, independent of any scene).

The most recent answer can be regenerated via the refresh button next to the message.

## Scene awareness

Each chat has a **Scene Aware** toggle. When enabled and a scene is loaded, the help agent can see the scene title, its characters, and recent scene progress, so you can ask scene-specific questions. When disabled the conversation is completely unaware of your scene.

The help agent also receives a small snapshot of what you are currently looking at in the interface (active tab, open panels, and any open client or agent settings dialog including its selected tab), so questions like "what does this setting do?" can be answered in context.

## Non-blocking

Help chat generation runs in the background and does not block the main Talemate loop - you can keep playing a scene while a help response is being generated. If your connected client does not support concurrent requests, the requests will naturally queue up against each other.
