# Overview

The help agent provides an interactive help chat that answers questions about Talemate itself - settings, agents, clients, the world editor, the node editor and everything else the application offers.

It grounds its answers in the documentation that ships with Talemate: it receives an index of all documentation pages and can search the documentation, read whole pages, or read individual sections before answering.

Open the help chat via the :material-help-circle-outline: icon in the app bar. It is available at any time - no scene needs to be loaded.

## What it can and cannot do

- It answers questions and points you to the relevant documentation pages.
- Its answers can include links that navigate you inside the application - to an agent's settings, a world editor tab, or the director console.
- It **cannot** change anything in the application or in your scene. If you want to make changes to a scene through chat, use the [director's chat](/talemate/user-guide/agents/director/chat) instead. For questions about your scene's content the director chat is also the better place - the help agent only sees a shallow snapshot of the scene, the director has the full context.

## Chats

Help conversations are multi-turn and you can keep several of them - use the chat selector at the top of the help drawer to switch, create, or delete chats. Chats persist across restarts (they are stored in `chats/help.json` in your Talemate directory, independent of any scene).

## Scene awareness

Each chat has a **Scene Aware** toggle. When enabled and a scene is loaded, the help agent can see the scene title, its characters, and recent scene progress, so you can ask scene-specific questions. When disabled the conversation is completely unaware of your scene.

The help agent also receives a small snapshot of what you are currently looking at in the interface (active tab, open panels, and any open client or agent settings dialog including its selected tab), so questions like "what does this setting do?" can be answered in context.

## Non-blocking

Help chat generation runs in the background and does not block the main Talemate loop - you can keep playing a scene while a help response is being generated. If your connected client does not support concurrent requests, the requests will naturally queue up against each other.
