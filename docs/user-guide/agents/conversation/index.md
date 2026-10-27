# Overview

Also known as the **Actor** agent it is responsible for generating character driven dialogue and actions.

It requires a text-generation client to be configured and assigned.

## Character knowledge

In **Standard** stories, **Limit to character knowledge** filters the speaking character's history and retrieved memories by what they know. Events they missed are replaced by a one-line gap. The [Character Knowledge settings group](/talemate/user-guide/agents/conversation/settings/#character-knowledge) holds that switch and **Refine memories with AI**, an optional extra request that selects and rewrites retrieved memories. Turning off Limit to character knowledge restores shared history and retrieval. See [World Editor -- Knowledge](/talemate/user-guide/world-editor/knowledge/) for presence, visibility settings and Learn rules.

In opted-in **Character perspectives** stories, stored audience views and disclosures supply character history and retrieval. Character views replace presence-only history filtering. This mode is chosen before play and is not controlled by the legacy settings switches. See [Knowledge](/talemate/user-guide/world-editor/knowledge/#character-perspectives-opt-in) for setup, analysis cost and retry behavior.
