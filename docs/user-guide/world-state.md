# World State

!!! info "AI with good JSON response handling required"
    Some older (llama-2 and older) models have difficulty generating sane json. This can cause the world state snapshot to be incomplete or missing information, or not be available at all. If you are experiencing issues, please try a newer model.

The world state snapshot is a summary of the current scene state. It will contain characters and objects mentioned in the scene.

The snapshot is generated and maintained by the [World State Agent](/talemate/user-guide/agents/world-state/), which refreshes it automatically as the scene plays out. To build the snapshot the agent looks at the whole scene so far together with the most recent lines (the "current moment"), and it can also pull in relevant entries from [long-term memory](/talemate/user-guide/agents/world-state/settings/#long-term-memory) so the snapshot can build on established lore and earlier scene history.

If there are [tracked states](/talemate/user-guide/tracking-a-state) in the scene, they will also be displayed here.

![world state 1](/talemate/img/0.26.0/world-state-snapshot-1.png)

Characters are indicated by the :material-account: icon, objects by the :material-cube: icon.

You can click on each entry to expand it and see more information.

## :material-cursor-default-click-outline: Entity Highlights in scene messages

Alongside the snapshot panel, Talemate also highlights notable characters, items, and places directly inside the most recent scene message. Highlighted entities appear with a subtle dotted underline, marking them as clickable.

These highlights are produced by the same world state snapshot, so they refresh whenever the snapshot updates. Only the most recent part of the scene — the "current moment" — receives highlights; older messages are left as plain text.

### Examining an entity

Click a highlighted entity to open a small popover. The popover shows:

- The entity's name and its kind (character, item, or place).
- For characters, the current emotional state, when known.
- A short description of the entity as it stands in the current moment.

From the popover you can take two actions:

:material-eye: **Look at** asks the [Narrator Agent](/talemate/user-guide/agents/narrator/) for a fresh description of the entity, added to the scene as a context-investigation message.

:material-plus: **Add Detail** expands the short description shown in the popover into a longer, grounded passage, also added to the scene as a context-investigation message. This action is available for items, places, and background characters mentioned in the narrative. It is hidden for characters that already exist in the scene, since those have their own detail surfaces in the [character editor](/talemate/user-guide/world-editor/characters).

:material-cog-outline: **Configure highlights** opens the [World State Agent settings](/talemate/user-guide/agents/world-state/settings/) where the highlight behavior is controlled.

### Controlling the highlights

Entity highlighting follows the world state snapshot, so it shares the snapshot's settings in the [World State Agent configuration](/talemate/user-guide/agents/world-state/settings/):

- **Lines in the moment** sets how many of the most recent messages count as the current moment and can therefore show highlights.
- **Include Look at / Add Detail** controls whether context-investigation messages (the results of the actions above) also count as part of the current moment and can receive their own highlights.
- **Add Detail length** controls how long an **Add Detail** result can be.

You can change the color of the highlights, or turn the inline styling off entirely, under **Settings → Appearance → Messages → Entity Highlights**. See [Appearance settings](/talemate/user-guide/app-settings/appearance/#text-markup-styling).

## :material-account: Characters

Each character entry will display the current emotional state next to the character's name.

When expanded it will also show a description of what the character is currently doing.

![world state 2](/talemate/img/0.38.0/world-state-snapshot-2.png)

### Action shortcuts

Beneath the description there are additional shortcuts.

:material-eye: **Look at** Will cause the [Narrator Agent](/talemate/user-guide/agents/narrator/) to describe the character.

:material-book-open-page-variant: **Manage Character** will take you to the [character editor](/talemate/user-guide/world-editor/characters) for that character, where you can view and edit all of the character's details.

:material-human-greeting: **Make real** If the world state has picked up a character that is not yet an interactive character, this will allow you to convert them into an interactive character.

### :material-image-auto-adjust: Character State

If the character has [tracked states](/talemate/user-guide/tracking-a-state) they will be displayed at the bottom of the expanded character entry.

Mouse over to show the current value of the state.

![world state 3](/talemate/img/0.26.0/world-state-snapshot-3.png)

## :material-cube: Objects

Objects currently do not have an active managed state in Talemate, however the snapshot will still show objects that have been mentioned in the scene.

Like characters you can click on the object to expand it and see more information.

![world state 4](/talemate/img/0.26.0/world-state-snapshot-4.png)

### Action shortcuts

Beneath the description there are additional shortcuts.

:material-eye: **Look at** Will cause the [Narrator Agent](/talemate/user-guide/agents/narrator/) to describe the object.

## :material-earth: Tracked world states

If there are [tracked states](/talemate/user-guide/tracking-a-state) in the scene, that track objects or other non-character entities, they will be displayed at the bottom of the world state snapshot in a separate section.

![world state 5](/talemate/img/0.26.0/world-state-snapshot-5.png)

## :material-refresh: Refreshing the snapshot

While the [World State Agent](/talemate/user-guide/agents/world-state/) will automatically update the world state snapshot as the scene progresses, you can also refresh it on demand by clicking the refresh icon in the top right of the world state snapshot.

### How the snapshot carries forward

By default the snapshot is **durable**: each refresh updates only what has changed and drops entities that are no longer relevant, rather than rebuilding the whole snapshot from scratch. This lets the snapshot build up over time, so details an entity has accumulated earlier in the scene are not lost on the next refresh.

To keep the snapshot from collecting stale entries, an entity that the agent leaves untouched for several refreshes in a row is automatically removed. Durability (and the related limits) can be turned off or tuned in the [World State Agent settings](/talemate/user-guide/agents/world-state/settings/#durable-snapshot).

When you move to a new point in time (a [time jump](/talemate/user-guide/time-passage/)), the snapshot is treated as a clean scene cut and rebuilt fresh, since the previous moment no longer applies.

### Wiping the snapshot

If you want to discard everything the snapshot has accumulated and start over, hold **Ctrl** (or **Cmd** on macOS) while clicking the refresh icon. This wipes the current snapshot and regenerates it from scratch.

### Cancelling a refresh

While a refresh is in progress a :material-close: cancel icon is shown in place of the refresh icon. Click it to stop the generation. This is useful if a refresh is taking longer than you want or you started one by mistake.

## :material-cog-clockwise: Automatic refreshing and the scene input

The snapshot refreshes automatically every several character turns (each player or AI turn counts), on a cadence you can set in the [World State Agent settings](/talemate/user-guide/agents/world-state/settings/#turns).

If the agent's text-generation client supports running more than one request at a time, the snapshot is generated quietly in the background and you can keep playing while it works. Otherwise it runs in the foreground so it doesn't compete with your other actions on the same client. Either way, manual refreshes behave the same and can be cancelled mid-generation.

## :material-pin: Pinning the snapshot to the scene

The world state snapshot can optionally be **pinned into the prompts** that drive dialogue, narration, and scene planning. When pinning is enabled, the snapshot's tracked characters, items, and places are shared with the [Conversation Agent](/talemate/user-guide/agents/conversation/), the [Narrator Agent](/talemate/user-guide/agents/narrator/), and scene analysis, so what the snapshot is tracking can inform what those agents produce.

This is **off by default**. You can enable it with the [Pin to context](/talemate/user-guide/agents/world-state/settings/#pin-to-context) setting in the World State Agent settings.