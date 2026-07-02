# Settings

The `Settings` tab allows you to configure various settings for the scene.

![World editor scene settings 1](/talemate/img/0.38.0/world-editor-scene-settings-1.png)

### Writing Style

If you have any [writing style templates](/talemate/user-guide/templates/writing-style/) set up, you can select one here. Some agents may use this to influence their output.

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

### Agent settings file

This setting controls how the scene uses [per-scene agent overrides](/talemate/user-guide/agents/scene-overrides) — agent settings that apply to this scene only, without changing your global configuration.

Overrides are stored in a JSON file inside an `agent-settings/` folder in the scene's project directory. The **Agent settings file** dropdown decides which file (if any) the scene is linked to:

- **Auto-link (default)** — the scene automatically uses `agent-settings/agent-settings.json` if it exists in the project folder. This is the normal behavior. If you haven't set any overrides yet, the first one you create in the agent modal will create this file.
- **None (opt out)** — disable per-scene overrides for this scene. It uses your global agent configuration only and will not auto-link to a default file.
- **A specific file** — link the scene to a particular overrides file in the project's `agent-settings/` folder. Any additional override files in that folder appear in the list, letting a project keep more than one set of overrides and switch between them.

Once a file is linked, you edit the actual overrides in the agent modal under the **Scene** tab. See [Per-Scene Agent Overrides](/talemate/user-guide/agents/scene-overrides) for the full workflow.

!!! note
    Overrides are project-level, so every save file in the same project — including **Save As** copies and restore points — shares the same `agent-settings/` folder. Scene exports include this folder, so overrides travel with the scene when shared.