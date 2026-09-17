# Overview

Also known as the **Actor** agent it is responsible for generating character driven dialogue and actions.

It requires a text-generation client to be configured and assigned.

## Character knowledge

In legacy scenes, the conversation prompt can use the speaking character's presence. Spans of the history the character was not present for are dropped and replaced by a one-line gap, long term memory retrieval only returns what the character knows, and an absence block tells the model which recent facts the character has not learned. The [Character Knowledge settings group](/talemate/user-guide/agents/conversation/settings/#character-knowledge) holds the switches for the perspective filter and the absence block; the whole treatment can be turned off there. See [World Editor -- Knowledge](/talemate/user-guide/world-editor/knowledge/) for presence, visibility settings and Learn rules.

In opted-in **Character perspectives** stories, stored audience views and disclosures supply character history and retrieval. The presence-only filter, absence block, topic-awareness assertions and separate learned-this-turn pass are retired. This mode is chosen before play and is not controlled by the legacy settings switches. See [Knowledge](/talemate/user-guide/world-editor/knowledge/#character-perspectives-opt-in) for setup, analysis cost and retry behavior.
