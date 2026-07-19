# Home Screen & Scene Library

The :material-home: **Home** screen is Talemate's landing page. It is where you load, import, create, and manage your scenes.

![Home screen](/talemate/img/0.39.0/getting-started-load-screen.png)

It is made up of four areas:

- **Quick load** — cards for your most recently played scenes
- **Scene Library** — a file browser of every scene project on disk
- **Import** — drag-and-drop import for scenes and character cards
- **Create new scene** — start a blank scene

## Quick load

The **Quick load** row shows your most recently saved scenes as cards. Click a card to load that scene.

Each card has a three-dot menu (⋮) with additional actions:

- :material-history: **Timeline** — browse and restore the scene's version history, see [Restoring Scenes](/talemate/user-guide/restoring-scenes)
- **Remove from Quick Load** — remove the card without deleting any files
- **Delete** — delete the scene file itself

## Scene Library

The **Scene Library** lists every scene project found in your `scenes/` directory as an expandable tree. Each project row shows its cover image, the number of save files it contains, and when it was last saved.

![Scene library](/talemate/img/0.39.0/scene-browser-library.png)

Expanding a project reveals:

- An information row summarizing the project's contents — how many media assets and [node modules](/talemate/user-guide/node-editor/) it holds
- The project's save files, each with its scene name, last-modified date, and file size

Click a save file to load it.

!!! tip "Filtering"
    The **Filter scenes** field narrows the tree to matching projects, save files, and character cards. Matching projects expand automatically so you can see the hits.

Projects with many save files show only the ten most recent — click **Show all N saves** to expand the rest.

### Character cards

Character card files stored in `scenes/characters/` are listed in their own **Character Cards** section at the bottom of the library. Image cards display a thumbnail of the card art.

Clicking a card starts a [character card import](/talemate/user-guide/character-card-import), letting you create a new scene from the card.

### Deleting scenes and projects

Each row in the library has a delete action:

- :material-file-remove-outline: on a **save file** or **character card** deletes that single file after a confirmation prompt.
- :material-folder-remove-outline: on a **project** deletes the entire scene project — all of its save files, assets, node modules, and version history.

Deleting a project is irreversible, so the confirmation dialog requires typing the project name before the delete button becomes available:

![Delete scene project dialog](/talemate/img/0.39.0/scene-browser-delete-project.png)

!!! warning
    Deleting a scene project removes its whole directory from disk — see [Scene Directory Structure](/talemate/user-guide/scene-directory) for what that includes. There is no undo.

## Import

The **Import** dropzone accepts:

- **Talemate scenes** — `.json` save files, or `.zip` archives [exported from the world editor](/talemate/user-guide/world-editor/scene/export) (a complete scene including its assets and node modules)
- **Character cards** — `.png`, `.webp`, or `.json` card files

Drag a file onto the dropzone or click it to browse. Character cards open the [import options dialog](/talemate/user-guide/character-card-import); Talemate scene files load directly.

## Create new scene

**Create new scene** starts a blank scene. After choosing a name and optional writing style and director persona, the scene opens in the [world editor](/talemate/user-guide/world-editor/) where you can add characters and scene details.
