# Settings

## General

![World state agent settings](/talemate/img/0.29.0/world-state-general-settings.png)

##### Update world state

Will attempt to update the [world state snapshot](/talemate/user-guide/world-state/) based on the current scene. Runs automatically every N turns.

###### Turns

How many turns to wait before the world state is updated.

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
