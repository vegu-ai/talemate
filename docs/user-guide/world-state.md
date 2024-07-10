# World State

!!! info "AI with good JSON response handling required"
    Some older (llama-2 and older) models have difficulty generating sane json. This can cause the world state snapshot to be incomplete or missing information, or not be available at all. If you are experiencing issues, please try a newer model.

The world state snapshot is a summary of the current scene state. It will contain characters and objects mentioned in the scene.

If there are [tracked states](/user-guide/tracking-a-state) in the scene, they will also be displayed here.

![world state 1](/img/0.26.0/world-state-snapshot-1.png)

Characters are indicated by the :material-account: icon, objects by the :material-cube: icon.

You can click on each entry to expand it and see more information.

## :material-account: Characters

Each character entry will display the current emotional state next to the character's name.

When expanded it will also show a description of what the character is currently doing.

![world state 2](/img/0.26.0/world-state-snapshot-2.png)

### Action shortcuts

Beneath the description there are additional shortcuts.

:material-eye: **Look at** Will cause the [Narrator Agent](/user-guide/agents/narrator/) to describe the character.

:material-account-details: **Character Sheet** will take you to the character sheet, which provides more detailed information about the character.

:material-book-open-page-variant: **Manage Character** will take you to the [character editor](/user-guide/world-editor/characters) for that character.

:material-human-greeting: **Make real** If the world state has picked up a character that is not yet an interactive character, this will allow you to convert them into an interactive character.

### :material-image-auto-adjust: Character State

If the character has [tracked states](/user-guide/tracking-a-state) they will be displayed at the bottom of the expanded character entry.

Mouse over to show the current value of the state.

![world state 3](/img/0.26.0/world-state-snapshot-3.png)

## :material-cube: Objects

Objects currently do not have an active managed state in Talemate, however the snapshot will still show objects that have been mentioned in the scene.

Like characters you can click on the object to expand it and see more information.

![world state 4](/img/0.26.0/world-state-snapshot-4.png)

### Action shortcuts

Beneath the description there are additional shortcuts.

:material-eye: **Look at** Will cause the [Narrator Agent](/user-guide/agents/narrator/) to describe the object.

## :material-earth: Tracked world states

If there are [tracked states](/user-guide/tracking-a-state) in the scene, that track objects or other non-character entities, they will be displayed at the bottom of the world state snapshot in a separate section.

![world state 5](/img/0.26.0/world-state-snapshot-5.png)

## :material-refresh: Force Update

While the [World State Agent](/user-guide/agents/world-state/) will automatically update the world state snapshot, you can also force an update by clicking the refresh icon in the top right of the world state snapshot.