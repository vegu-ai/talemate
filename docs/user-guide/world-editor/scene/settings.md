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

Allows you to specific another save file of the same project to serve as a restoration point. Once set you can use the **:material-backup-restore: Restore Scene** button to restore the scene to that point.

This will create a new copy of the scene with the restoration point as the base.