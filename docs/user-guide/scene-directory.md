# Scene Directory Structure

When you create a scene in Talemate, a dedicated project directory is created to hold everything related to that scene. This directory is derived from the scene name and is created immediately when you name the scene, ensuring no assets are lost before the first save.

## Location

Scene directories are stored under the `scenes/` folder in your Talemate data directory:

```
scenes/
└── my-adventure/
    ├── my-adventure.json
    ├── my-adventure-chapter-2.json
    ├── assets/
    ├── changelog/
    ├── nodes/
    ├── templates/
    ├── shared-context/
    └── info/
```

## Directory contents

### Save files (`.json`)

All save files for a scene live together in the project directory. Each `.json` file at the root of the directory is a save file. You can have multiple saves for the same scene — for example, one for the initial state and others for different branches or checkpoints.

See [Saving](/talemate/user-guide/saving) for more on how saves work.

### `assets/`

Stores media assets associated with the scene, such as generated images and TTS audio files. Assets are managed automatically by Talemate and linked from the scene save files.

### `changelog/`

Contains the automatic version history that powers the [Restore from Backup](/talemate/user-guide/restoring-scenes) feature. Every time you save, Talemate records the changes as a delta, allowing you to restore the scene to any previous revision.

This directory includes:

- **Base snapshot** — the initial scene state (revision 0)
- **Latest snapshot** — a cached copy of the most recent state for fast access
- **Delta logs** — incremental change records between revisions

You generally don't need to interact with these files directly.

### `nodes/`

Stores [node editor](/talemate/user-guide/node-editor/) graphs for the scene, such as the scene loop and creative loop.

### `templates/`

Scene-specific [templates](/talemate/user-guide/world-editor/templates/writing-style/) that override or extend the default templates. These are organized into `scene/`, `common/`, and agent-specific subdirectories.

### `shared-context/`

Contains [shared context](/talemate/user-guide/world-editor/scene/shared-context) files (`.json`) that enable sharing characters, world entries, and history across multiple scenes in the same project.

### `info/`

Stores scene metadata and supplementary information files.

## Why this matters

Understanding the directory structure is helpful for:

- **Troubleshooting** — knowing where files are stored helps when something goes wrong
- **Manual backups** — you can copy the entire project directory to back up a scene and all its associated data
- **Sharing scenes** — the project directory contains everything needed to share a scene with others
- **Understanding saves** — all saves for a scene are grouped together in one directory, making it clear which files belong together
