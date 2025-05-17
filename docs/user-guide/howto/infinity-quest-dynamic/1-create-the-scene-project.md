# 1 - Scene Project

Creating the scene project and saving it.

## 1.1 - Create the scene project

Load up talemate and find the **Create :material-plus:** button in the left sidebar.

Click it.

![Create Scene Project](./img/1-btn-create-scene.png)

Ignore the node editor for now and head to the **:material-earth-box: World Editor** tab.

Fill in `Title`, `Description` and `Content Context`

Then click the **Save** button. Enter a file name `infinity-quest-dynamic` and click **Save**.

![Save Scene Project](./img/1-save-project.png)

## 1.2 - Lets import characters

Since this is going to be a dynamic version of the existing `Infinity Quest` project, we can just import the two main characters from the existing project.

Head over to the **Characters** tab and click the **Import Character** button on the left.

![Import Characters](./img/1-0001.png)

In the modal that opens up, search for the `infinity-quest.json` scene file and then select the `Elmer` character.

![Import Elmer](./img/1-0002.png)

Click **Import**.

Repeat the process for the `Kaira` character.

Both characters should now be in the character list.

![Import Kaira](./img/1-0003.png)

Make sure to then also activate both characters. Click on each name in the character list and then click the **Activate** button.

![Activate Characters](./img/1-0007.png)

**Save** the scene project again.

## 1.3 - Finalize

When working on a scene you should always do two things:

1. Lock the save file - this will prevent auto-saving of any progress in the scene that may happen during testing. When a save is locked a save outside of the world editor will always trigger a `Save As` dialog, forcing you to save the scene under a new name.
2. Set a restoration file - set this to the file we just saved at `infinity-quest-dynamic.json`.

Head over to **Scene**, then **Settings** and set both fields accordingly:

![Lock Save](./img/1-0004.png)

![Set Restoration File](./img/1-0005.png)

Save the scene project again.

### Optionally

I also like to disable `auto progress` while working on the scene, unless its something that needs to be tested specifically. You can do that back in the main screen above the message input field.

![Disable Auto Progress](./img/1-0006.png)