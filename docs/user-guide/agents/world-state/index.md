# Overview

The world state agent handles the world state snapshot generation and reinforcement of tracked states.

It requires a text-generation client to be configured and assigned.

--8<-- "docs/snippets/tips.md:what_is_a_tracked_state"

### :material-earth: World State

The world state is a snapshot of the current state of the world. This can include things like the current location, the time of day, the weather, the state of the characters, etc.

### :material-account-switch: Character Progression

The world state agent can be used to regularly check progression of the scene against old character information and then propose changes to a character's description and attributes based on how the story has progressed.