# Saving

## How saves work

Scenes are saved as `.json` files inside the scene's [project directory](/talemate/user-guide/scene-directory). All saves for a scene are grouped together in this directory, so a single scene project might contain several save files representing different states or branches.

When you save a scene, Talemate also records the changes in an automatic version history (changelog). This means you can [restore a scene to any previous revision](/talemate/user-guide/restoring-scenes) at any time.

Saves can also serve as **restore points**. By designating one save file as the restoration source in the [scene settings](/talemate/user-guide/world-editor/scene/settings), you can quickly reset a scene back to that state whenever needed — useful for testing or creating repeatable starting points.

## Saving from the scene

To save while looking at the scene, click the :material-content-save: **Save** button on the right of the [Scene tools](/talemate/user-guide/scenario-tools) toolbar.

![Scene save](/talemate/img/0.26.0/scene-save.png)

## Saving from the world editor

While in the world editor it is also possible to save changes by clicking the :material-content-save: **Save** button in the top center of the screen.

![World Editor Save](/talemate/img/0.26.0/world-editor-save.png)

## Auto save

To disable / enable auto save, click the the auto save shortcut above the scene tools toolbar.

![Auto save disabled](/talemate/img/0.26.0/autosave-disabled.png)
![Auto save enabled](/talemate/img/0.26.0/autosave-enabled.png)

### I can't toggle auto save

![Auto save blocked](/talemate/img/0.26.0/autosave-blocked.png)

Some scenes start out with a locked save file. This is so that this particular scene file cannot be overwritten by accident. In order to enable autosave, you need to manually save the scene once. After that, the autosave toggle will be available.


!!! info
    Alternatively you can also unlock the save file through the [Scene editor](/talemate/user-guide/world-editor/scene/settings) found in **:material-earth-box: World Editor** :material-arrow-right: **:material-script: Scene** :material-arrow-right: **:material-cogs: Settings**.

## Save As

When you use **Save As**, a new save file is created in the same project directory. This is useful for creating checkpoints you can return to later — for example, saving an initial state before experimenting with different story directions.

These additional save files can be set as [restore points](/talemate/user-guide/world-editor/scene/settings#restoration-settings) so you can always return to a known good state.

## Forking a copy of a scene

You can create a new copy of a scene from any message in the scene by clicking the :material-source-fork: **Fork** button underneath the message.

All progress after the target message will be removed and a new scene will be created with the previous messages.