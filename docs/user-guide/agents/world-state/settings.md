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

## Character Portraits

!!! info "New in 0.35.0"
    Character portrait features allow automatic portrait selection and generation based on scene context.

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
