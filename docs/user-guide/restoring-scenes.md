# Restoring Scenes

Talemate provides two ways to return a scene to a previous state:

- **Timeline** — use the automatic version history to browse every previous revision and fork from any point (covered on this page)
- **Restore from Restore Point** — reset to a specific save file you've designated as a baseline in the [scene settings](/talemate/user-guide/world-editor/scene/settings#restoration-settings)

!!! warning "The timeline only forks in this version"
    Rolling a scene back in place and opening a revision directly are both disabled in this version. Forking a revision into a new save is the one action the timeline applies — it writes a new save alongside the scene and leaves every existing save untouched.

## The timeline

Every time you save, Talemate records the changes as a delta in the scene's [changelog directory](/talemate/user-guide/scene-directory#changelog). The timeline lets you browse this version history: drag the slider to any revision to preview the scene's messages as they were at that point, then fork that revision into a new save. Browsing and previewing change nothing on disk.

![Timeline dialog](/talemate/img/0.39.0/timeline-dialog.png)

### Opening the timeline

The timeline can be opened from four places:

- **While playing a scene** — click the :material-content-save: **Save** button in the [Scene tools](/talemate/user-guide/scenario-tools) toolbar and select :material-history: **Timeline**
- **From a message** — click the :material-source-fork: **Fork** button underneath any message; the timeline opens positioned at that message's revision
- **From the main screen** — click the three-dot menu (⋯) beneath a scene card in the **Quick load** section and select :material-history: **Timeline**
- **From the Scene Library** — click the three-dot menu (⋮) on any save file row and select :material-history: **Timeline**

### Forking a revision

Once you've found the point you want to return to, click **Fork to new save**. It creates a new save file in the same project directory from the selected revision, and asks for a name. The scene you are playing is not modified, and a name an existing save already uses is refused rather than written over.

!!! info
    Forking never destroys your version history. Every revision is kept, so you can open the timeline again and scrub to any other point.

!!! warning
    Scenes connected to a shared world context are disconnected from it when forked, since shared context cannot be reconstructed to a specific revision.

## Restore from restore point

If you've configured a restore point in the [scene settings](/talemate/user-guide/world-editor/scene/settings#restoration-settings), you can reset the scene to that baseline state using the **:material-backup-restore: Restore Scene** button. This is useful for scenes you want to replay from a fixed starting point, such as testing a scene during development.

Unlike the timeline, which uses the automatic version history, restore points use a specific save file you've chosen as the baseline. See the [restoration settings documentation](/talemate/user-guide/world-editor/scene/settings#restoration-settings) for setup details.
