# Overview

The help agent provides an interactive help chat that answers questions about Talemate itself - settings, agents, clients, the world editor, the node editor and everything else the application offers.

It grounds its answers in the documentation that ships with Talemate: it knows the documentation's sections and can look up relevant pages by topic, search the documentation, read whole pages, or read individual sections before answering.

Open the help chat via the :material-help-circle-outline: icon in the app bar. No scene needs to be loaded. The icon is only there while the Help agent is enabled - if you don't see it, enable the agent under **Settings → Connections → Agents → Help**.

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

So things like "switch the conversation format to Narrative", "lower the editor revision to only run on dialogue", "turn off auto save" or "override the visualizer style for this scene only" can be done right from the chat. Changes are applied immediately, the chat records exactly what changed (old and new value), and an open settings view picks them up live.

Some things are intentionally out of reach:

- API keys and passwords are never shown to the help agent and it cannot change them - key management stays in the application settings (Connections → API Keys).
- Clients are read-only - client changes (model, context length, etc.) must be made in the client settings.
- Complex settings (tables, weight maps, template pickers) are read-only in chat and must be edited in the settings interface directly.

!!! note "Unsaved settings edits"
    Having the Settings tab open is fine - applied changes show up there live. But while the settings view holds **unsaved edits**, the help agent refuses to change anything - agent settings and application settings alike - and asks you to save or discard them first. That view edits a working copy of your *whole* configuration and saves all of it at once, so its **Save** would push the pre-change values back over whatever the agent just wrote for you. Which page you happen to be on makes no difference.

    Unsaved edits stay pending when you switch to another main tab, and so does the refusal. Save or discard them, then ask again.

## Chats

Help conversations are multi-turn and you can keep several of them - use the chat selector at the top of the help drawer to switch, create, or delete chats. Chats persist across restarts (they are stored in `chats/help.json` in your Talemate directory, independent of any scene).

The most recent answer can be regenerated via the refresh button next to the message.

## Scene awareness

Each chat has a **Scene Aware** toggle. When enabled and a scene is loaded, the help agent can see the scene title, its characters, and recent scene progress, so you can ask scene-specific questions. When disabled the conversation is completely unaware of your scene.

The help agent also receives a small snapshot of what you are currently looking at in the interface - the active tab, which drawers you have open, whether a scene is loaded and what it is doing, and the state of the settings view: the page you are on, whether it has unsaved edits, and which client or agent you have selected there (for an agent, also whether it is in **Global** or **Scene** mode). So questions like "what does this setting do?" can be answered in context.

## Non-blocking

Help chat generation runs in the background and does not block the main Talemate loop - you can keep playing a scene while a help response is being generated. If your connected client does not support concurrent requests, the requests will naturally queue up against each other.
