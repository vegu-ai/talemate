# Settings

The `Settings` tab allows you to configure various settings for the scene.

![World editor scene settings 1](/talemate/img/0.29.0/world-editor-scene-settings-1.png)

### Writing Style

If you have any [writing style templates](/talemate/user-guide/world-editor/templates/writing-style/) set up, you can select one here. Some agents may use this to influence their output.

### Locked save file

When the save file is locked, then the scene cannot be save while playing it. This is useful for ensuring that progress isn't saved while testing the scene.

The user (or you) will be forced to save a new copy of the scene if they want to save their progress.

### Experimental

This is simply a tag that lets the user know that this scene is experimental, and may take a strong LLM to perform well.

### Restoration Settings

A restore point lets you designate another save file from the same [project directory](/talemate/user-guide/scene-directory) as a baseline state. Once configured, you can use the **:material-backup-restore: Restore Scene** button to reset the scene back to that state at any time.

#### Typical workflow

1. **Save an initial state** — set up your scene the way you want the starting point to be, then use **Save As** to create a dedicated save file (e.g., `initial.json`)
2. **Set it as the restore point** — in the Restoration Settings, select that save file as the restoration source
3. **Play and experiment** — make progress, test different paths, or let users play through the scene
4. **Restore when needed** — click the **:material-backup-restore: Restore Scene** button to return to the baseline

Restoring creates a **new, unsaved scene** based on the restore point. Your current save file and the restore point file both remain unchanged, so you can restore as many times as you want without losing anything.

!!! tip
    This is especially useful for scene creators who want to test their scenes repeatedly, or for creating replayable scenarios where players always start from the same point. Combine this with a [locked save file](#locked-save-file) to prevent accidental overwrites of your baseline.

See also: [Restoring Scenes from Backups](/talemate/user-guide/restoring-scenes) for restoring to any previous revision using the automatic backup history.