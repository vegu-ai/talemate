# Game State

The Game State tab in the World Editor allows you to view and edit the game state variables for your scene. These variables persist with your scene save file and are commonly used by node modules to track game progress.

![Game State Tab](/talemate/img/0.35.0/world-editor-gamestate-tab.png)

## Overview

The Game State editor is split into two panels:

- **Left panel**: A JSON editor showing all current game state variables
- **Right panel**: The Watched Variables manager

## JSON Editor

The JSON editor displays the complete game state as a JSON object. You can directly edit values here:

1. Click in the editor to make changes
2. Click outside the editor to save your changes
3. If the JSON is invalid, an error message will appear and changes will not be saved

This is useful for:

- Adding new variables
- Editing complex nested objects or arrays
- Making bulk changes to multiple values

## Watched Variables

The Watched Variables panel lets you select specific paths to monitor in the [Debug Tools](/talemate/user-guide/debug-tools/#vars) panel. Watched variables appear in the Debug Tools Vars tab where you can see their values update in real time and edit simple values directly.

### Adding a Watch

1. Use the dropdown to select from available paths in your game state
2. Click the :material-plus: button or select a path to add it to your watch list

When you add a watched path, the Debug Tools panel will automatically open to show the Vars tab.

### Removing a Watch

Click the :material-close-circle-outline: button next to any watched path to remove it from monitoring.

## Relationship to Node Modules

Game state variables correspond to the "game" scope in the node editor's state management system. When a node module uses `SetState` with `scope=game`, the value is stored in the game state and will appear in this editor.

See the [State Management](/talemate/user-guide/node-editor/core-concepts/states/) documentation for more information about state scopes.

## Related

- [Debug Tools](/talemate/user-guide/debug-tools/) - Monitor and edit watched variables in real time
- [State Management](/talemate/user-guide/node-editor/core-concepts/states/) - How to use state nodes in the node editor
- [Context Pins](/talemate/user-guide/world-editor/pins/#game-state-conditions) - Use game state values to control pin activation
