# Restoring Scenes

Talemate provides two ways to return a scene to a previous state:

- **Timeline** — use the automatic version history to browse every previous revision and roll back or fork from any point (covered on this page)
- **Restore from Restore Point** — reset to a specific save file you've designated as a baseline in the [scene settings](/talemate/user-guide/world-editor/scene/settings#restoration-settings)

## The timeline

Every time you save, Talemate records the changes as a delta in the scene's [changelog directory](/talemate/user-guide/scene-directory#changelog). The timeline lets you browse this version history: drag the slider to any revision to preview the scene's messages as they were at that point, then decide what to do with it.

![Timeline dialog](/talemate/img/0.39.0/timeline-dialog.png)

### Opening the timeline

The timeline can be opened from four places:

- **While playing a scene** — click the :material-content-save: **Save** button in the [Scene tools](/talemate/user-guide/scenario-tools) toolbar and select :material-history: **Timeline**
- **From a message** — click the :material-source-fork: **Fork** button underneath any message; the timeline opens positioned at that message's revision
- **From the main screen** — click the three-dot menu (⋯) beneath a scene card in the **Quick load** section and select :material-history: **Timeline**
- **From the Scene Library** — click the three-dot menu (⋮) on any save file row and select :material-history: **Timeline**

### Applying a revision

Once you've found the point you want to return to, you have the following options:

- **Roll back** *(while playing a scene)* — rolls the current scene back to the selected revision, in place. A backup of the current state is saved to the scene's [backups directory](/talemate/user-guide/scene-directory) first, and the rollback itself is recorded on the timeline — so you can open the timeline again and scrub forward to where you were.
- **Open at this revision** *(from the main screen)* — opens the revision as a new, unsaved scene. The original scene file is not modified; save it manually if you want to keep it.
- **Fork to new save** — creates a new save file in the same project directory from the selected revision. The current scene is not modified.

!!! info
    Rolling back never destroys your version history. Because every revision is kept, a rollback simply becomes the next entry on the timeline — you can always scrub forward again to the state you rolled back from.

!!! warning
    Scenes connected to a shared world context are disconnected from it when rolled back or forked, since shared context cannot be reconstructed to a specific revision.

## Restore from restore point

If you've configured a restore point in the [scene settings](/talemate/user-guide/world-editor/scene/settings#restoration-settings), you can reset the scene to that baseline state using the **:material-backup-restore: Restore Scene** button. This is useful for scenes you want to replay from a fixed starting point, such as testing a scene during development.

Unlike the timeline, which uses the automatic version history, restore points use a specific save file you've chosen as the baseline. See the [restoration settings documentation](/talemate/user-guide/world-editor/scene/settings#restoration-settings) for setup details.
