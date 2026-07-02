# Settings

## Update World State

![World state agent update world state settings](/talemate/img/0.38.0/world-state-update-world-state-settings.png)

##### Update world state

Will attempt to update the [world state snapshot](/talemate/user-guide/world-state/) based on the current scene. Runs automatically every N character turns.

###### When a new scene is started

Whether to generate an initial snapshot as soon as a scene is loaded. On by default.

###### Turns

How many character turns to wait before the snapshot is refreshed. Each player or AI turn counts (not full rounds), so on a scene with several characters the snapshot refreshes more often than the number alone might suggest. Defaults to 10.

###### Lines in the moment

How many of the most recent messages count as the "current moment". These are the lines the snapshot anchors to, and they are the messages that can show inline entity highlights. Keeping this small keeps the highlights tied to the active beat while the rest of the scene is still used as background context.

###### Include Look at / Add Detail

When on, **Look at** and **Add Detail** results also count as part of the current moment and can receive inline highlights. Off by default.

###### Custom instructions

Free-form instructions that steer what the snapshot focuses on. Use this to nudge the agent toward (or away from) certain kinds of detail. Empty by default.

###### Add Detail length

How long an **Add Detail** result can be. Shorter lengths keep the generated description tighter; longer lengths allow more elaboration.

###### Pin to context

When on, the snapshot is pinned into the conversation, narrator, and scene-analysis prompts as live scene notes, so the tracked entities can inform dialogue, narration, and planning. Off by default. See [Pinning the snapshot to the scene](/talemate/user-guide/world-state/#pinning-the-snapshot-to-the-scene).

###### Durable snapshot

When on (the default), each refresh updates only what has changed and carries the rest of the snapshot forward, instead of rebuilding it from scratch every time. This lets the snapshot accumulate detail over the course of a scene. When off, every refresh starts fresh. See [How the snapshot carries forward](/talemate/user-guide/world-state/#how-the-snapshot-carries-forward).

The two settings below only apply when **Durable snapshot** is on.

###### Max items tracked

The maximum number of items the snapshot can hold at once. When a refresh would exceed this, the stalest items are dropped first. Set to `0` for no limit.

###### Auto-evict stale entries

Automatically drops a snapshot entry that the agent leaves unchanged for this many refreshes in a row. This guards against stale entries lingering when the agent fails to remove them on its own. Set to `0` to disable.

##### Update state reinforcements

Will attempt to update any due tracked states

This is checked every turn and if there are any state reinforcements that are due, they will be updated.

--8<-- "docs/snippets/tips.md:what_is_a_tracked_state"

##### Update conditional context pins

Will attempt to evaluate and update any due [conditional context pins](/talemate/user-guide/world-editor/pins/#automatically-pinning-entries).

###### Turns

How many turns to wait before the conditional context pins are updated.

## Character Progression

![World state agent character progression settings](/talemate/img/0.29.0/world-state-character-progression-settings.png)

##### Frquency of checks

How often ot check for character progression.

This is in terms of full rounds, not individual turns.

##### Propose as suggestions

If enabled, the proposed changes will be presented as suggestions to the player.

--8<-- "docs/snippets/tips.md:character_change_proposals"

##### Player character

Enable this to have the player character be included in the progression checks.

## Character Portraits

![World state agent character portraits settings](/talemate/img/0.35.0/world-state-character-portraits-settings.png)

The Character Portraits settings control how character avatars are displayed alongside dialogue messages and whether they should change automatically based on the scene context.

### Portrait Selection

##### Selection Frequency

Controls how often the World State Agent evaluates which portrait to use for a character based on the current scene context.

- **0**: Never automatically select portraits (portraits must be changed manually)
- **1**: Evaluate with every new message
- **2-10**: Evaluate every N messages

When a message is generated, the agent examines the content and context of the scene, then compares it against the tags associated with each portrait to find the best match.

!!! note "Minimum Portraits Required"
    A character needs at least 2 portraits in their visual configuration for automatic selection to activate. You can manage portraits in the [World Editor under Character > Visuals > Portrait](/talemate/user-guide/world-editor/characters/visuals/#portrait).

!!! tip "Tag Your Portraits"
    The selection algorithm relies on portrait tags to make decisions. Portraits without tags cannot be intelligently selected. Add descriptive tags like "happy", "sad", "angry", "combat", "formal" to each portrait using the Visual Library.

### Generate New Portraits

##### Generate New Portraits

When enabled, the World State Agent can request the Director to generate new portraits when no suitable portrait is found for the current scene context.

For example, if a character is described as wearing formal attire at a party but no existing portrait shows them in formal wear, the system can automatically commission a new portrait showing the appropriate appearance.

!!! warning "Prerequisites"
    This feature requires:

    - The Director's **Character Management > Generate Visuals** setting to be enabled
    - A Visual Agent with an image generation backend configured

When a new portrait is generated, it is automatically added to the character's portrait collection and tagged based on the scene context.

## Long Term Memory

When generating the [world state snapshot](/talemate/user-guide/world-state/), the agent pulls in relevant long-term memory so the snapshot can build on established lore and earlier scene history. Semantic recall is always used and is on by default.

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"
