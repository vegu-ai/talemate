# Make or Unmark a Player Character

Every scene can have one character that is controlled by you, the player. All other characters are controlled by the AI. From the character editor you can change which character is the player at any time, without having to recreate anyone.

A character's current role is shown next to their name in the character list:

- A :material-label: **Player** chip marks the character you are controlling.
- A :material-label: **AI** chip marks a character controlled by the AI.

## Make a character the player

To promote a character to the player, first select the character on the left hand side in the :material-earth-box: **World Editor** under the :material-account-group: **Characters** tab.

Then click on the :material-account-star: **Make Player Character** button, beneath the character's image.

This does two things at once:

- The selected character becomes the player character.
- If another character was already the player, they are demoted to an AI actor. They stay in the scene and simply continue as an AI controlled character.

If the character you promote is currently [deactivated](/talemate/user-guide/world-editor/characters/deactivate), they are automatically activated and brought into the scene as the player.

Only one character can be the player at a time, so there is never any need to unmark the previous player yourself.

## Unmark the player character

To turn the current player into an AI controlled character, select that character under the :material-account-group: **Characters** tab.

Then click on the :material-account-off-outline: **Unmark as Player** button, beneath the character's image.

The character remains in the scene and keeps all of their details; they are simply handed over to the AI. After this, the scene has no player character until you promote one.

!!! note
    Whether a character is the player can also be set when you first [create a character](/talemate/user-guide/world-editor/characters/create) using the **Controlled by Player** switch.
