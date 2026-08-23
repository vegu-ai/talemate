# Game State

The Game State tab in the World Editor allows you to view and edit the game state variables for your scene. These variables persist with your scene save file and are commonly used by node modules to track game progress.

![Game State Tab](/talemate/img/0.40.0/world-editor-gamestate-tab.png)

## Overview

The Game State editor is split into two panels:

- **Left panel**: A JSON editor showing all current game state variables
- **Right panel**: The Pinned Variables manager

## JSON Editor

The JSON editor displays the complete game state as a JSON object. You can directly edit values here:

1. Click in the editor to make changes
2. Click outside the editor to save your changes
3. If the JSON is invalid, an error message will appear and changes will not be saved

This is useful for:

- Adding new variables
- Editing complex nested objects or arrays
- Making bulk changes to multiple values

## Pinned Variables

The Pinned Variables panel lets you expose selected game state paths in [Debug Tools Vars](/talemate/user-guide/debug-tools/#vars), the scene toolbar, or both. Each target is independent:

- **Debug Vars** shows the path in the Debug Tools drawer for monitoring and editing.
- **Scene toolbar** adds a compact, type-matched control above the normal scene tools.

Each pinned path can also have an optional label. The scene toolbar uses the label instead of the path. Debug Vars uses the label as the control title and shows the path underneath as a subtitle. When a labeled container expands into child controls, each title combines the label with the child key (for example, `Hero / health`). Leaving the label blank preserves the path-only display.

The scene toolbar appears only while it has pinned paths and is hidden during playthrough mode.

### Adding a Pinned Path

1. Select a path from the game state dropdown.
2. Optionally enter a short label.
3. Select the **Debug Vars**, **Scene toolbar**, or both target chips.
4. Click **Add**.

Adding a new Debug Vars target automatically opens the Debug Tools drawer to its Vars tab.

![Add a pinned game state path](/talemate/img/0.40.0/gamestate-add-watch.png)

### Changing or Removing Targets

Edit a path's optional label directly in its table row; clear the field to return to the path-only display. Use the two checkboxes beside a pinned path to change where it appears. Turning off both **Debug Vars** and **Scene toolbar** removes the path and its label from the table.

![Game state controls pinned above the scene tools](/talemate/img/0.40.0/gamestate-knob-toolbar.png)

## Relationship to Node Modules

Game state variables correspond to the "game" scope in the node editor's state management system. When a node module uses `SetState` with `scope=game`, the value is stored in the game state and will appear in this editor.

See the [State Management](/talemate/user-guide/node-editor/core-concepts/states/) documentation for more information about state scopes.

## Related

- [Debug Tools](/talemate/user-guide/debug-tools/) - Monitor Debug Vars and use pinned scene-toolbar controls
- [State Management](/talemate/user-guide/node-editor/core-concepts/states/) - How to use state nodes in the node editor
- [Context Pins](/talemate/user-guide/world-editor/pins/#game-state-conditions) - Use game state values to control pin activation
