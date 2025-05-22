# Events

List of currently supported events.

!!! warning "Events not listed here"
    There are many other events defined in the talemate codebase that are purposefully not listed here yet. 

    The reason for this is that there is an ongoing cleanup process and some of them may not stick around in their current form.

    You can of course still hook into them, but be aware that they may change or be removed in the future.


## Game Loop

### `game_loop_ai_character_iter`

Triggered after the AI character has had a turn.

#### Payload

- `scene`: The scene object
- `character`: The character object

### `game_loop_player_character_iter`

Triggered after the player character has had a turn.

#### Payload

- `scene`: The scene object
- `character`: The character object

## Scene Loop

### `scene_loop_init`

Triggered when the scene loop is initialised.

#### Payload

- `scene`: The scene object

