# Create an empty scene

To start a new, empty scene, go to the :material-home: **Home** screen and click the **Create new scene** card — it sits in the right-hand column of the [scene browser](/talemate/user-guide/scene-browser/), below the Import dropzone.

![Create empty scene](/talemate/img/0.40.0/create-new-scene.png)

A **Create New Story** dialog opens where you give the scene a name and can optionally pick a writing style, a director persona, a story mode (Standard by default), the character knowledge effort, and whether the Director should assist with story setup. For this walkthrough just enter a name and click :material-check-circle-outline: **Continue**.

After a moment of loading you will be taken to the new scene and `creative` mode will be enabled. In `creative` mode normal scene progression is suspended and input in the scene view will be for command execution only. (covered elsewhere, ignore for now)

## Create the outline for the scene

--8<-- "docs/user-guide/world-editor/scene/outline.md:outline"

## Save the scene

![World editor scene outline 2](/talemate/img/0.26.0/world-editor-scene-outline-2.png)

Once you are happy with the outline, click on the :material-content-save: **Save** button to save the scene.

![world editor unsaved changes](/talemate/img/0.26.0/world-editor-unsaved-changes.png)

Since this is the first time you are saving the scene, you will be prompted to give it a name. Type in `the-forgotten-house` and click on the :material-check-circle-outline: **Continue** button.

![world editor save scene](/talemate/img/0.26.0/world-editor-save-scene-first-save.png)

## Character perspectives

In **Create New Story**, the two mode cards come first, and the **Character knowledge effort** slider below them starts at **Minimal** with **Standard** selected by default. Click or keyboard-select **Character perspectives** before play to use the integrated audience mode for this story; its default effort is **Balanced**. Each card keeps its short guidance visible, while its Pros and Cons start collapsed behind **Show pros and cons**. Character perspectives adds analytical requests and pauses dependent generation on a failed analysis. You can still change the mode in Scene Settings while both history and archived history are empty. Once history exists, the mode is locked; resaving or forking does not reconstruct past perceptions. See [Choosing a mode](/talemate/user-guide/world-editor/knowledge/#choosing-a-mode) for the full comparison and [Knowledge](/talemate/user-guide/world-editor/knowledge/#character-perspectives-opt-in) for costs, retry behavior and shared authoring fields.

## Next

Next we will [add a player character](/talemate/user-guide/howto/create-a-new-scene/create-player-character) to the scene.
