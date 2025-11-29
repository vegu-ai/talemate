# Shared World & Episodes

The Shared World panel allows you to manage shared context and episodes, enabling you to create interconnected scenes and alternative storylines within your project.

## Accessing Shared World

Navigate to **:material-earth-box: World Editor** :material-arrow-right: **:material-script: Scene** :material-arrow-right: **:material-earth-arrow-right: Shared World**

![Shared World Overview](/talemate/img/0.34.0/shared-world-1.png)

## Shared Context

Shared Context allows you to share specific characters, world entries, and history across multiple scenes within the same project. This is useful for creating interconnected stories where certain elements remain consistent across different scenarios.

### Creating a Shared Context

1. Click the **New** button in the Shared Context section.

![Shared World Create](/talemate/img/0.34.0/shared-world-2.png)

2. Enter a filename for your shared context in the prompt dialog.

![Shared World Name](/talemate/img/0.34.0/shared-world-3.png)

3. The file will be saved as a `.json` file in the scene's `shared-context` folder and will appear in the list.

![Shared World List](/talemate/img/0.34.0/shared-world-4.png)

### Linking a Scene to Shared Context

1. Select a shared context file from the list by clicking the checkbox.
2. The selected shared context will appear as a chip at the top of the panel.
3. Only one shared context can be active per scene.

![Shared World Active](/talemate/img/0.34.0/shared-world-6.png)

When a scene is linked to a shared context, you'll see the active context displayed in the "New Scene Section" at the top.

![Shared World Linked](/talemate/img/0.34.0/shared-world-7.png)

### Bulk Sharing Elements

Once linked, you can quickly share or unshare all characters and world entries from the current scene to the shared context.

1. Click on the **Shared Characters** or **Shared World Entries** chip.
2. Select **Share all...** or **Unshare all...** from the menu.

![Shared World Bulk Share](/talemate/img/0.34.0/shared-world-5.png)

This is a convenient way to populate a new shared context with all the entities from your current scene.

### Creating New Scenes with Shared Context

Once a scene is linked to a shared context, you can create new scenes that inherit the same shared elements:

1. Click the **New Scene** button at the top of the panel.
2. The dialog will indicate that the new scene will be linked to the selected shared context.
3. Optionally provide instructions for generating a new premise.
4. Select which shared characters to activate in the new scene.
5. Click **Create and load**.

![Create New Scene dialog](/talemate/img/0.34.0/shared-world-8.png)

The new scene will:

- Be linked to the same shared context
- Inherit the content classification settings
- Use the same agent persona templates
- Use the same writing style template
- Include selected shared characters
- Be part of the same project

## Episodes

Episodes are alternative introductions that can be used to start new scenes. They are shared across all scenes in the project.

### Managing Episodes

The Episodes section allows you to view and manage your episodes.

![Episodes List](/talemate/img/0.34.0/shared-world-9.png)

- **Add New**: Click the "Add New" button to create a new episode.
- **Edit**: Click the edit icon next to an episode to modify it.
- **Delete**: Click the delete icon to remove an episode.

### Creating an Episode

1. Click the **Add New** button.

![Create Episode Button](/talemate/img/0.34.0/shared-world-10.png)

2. Provide a Title, Description, and Introduction for the episode.

- **Title**: A name for the episode.
- **Description**: A short description of what happens in the episode.
- **Introduction**: The actual text that will start the scene.

![Creating Episode Form](/talemate/img/0.34.0/shared-world-11.png)

3. Click **Save**.

### Creating a Scene from an Episode

You can use an episode to start a new scene:

1. Select an episode from the list by clicking on it.

![Select Episode](/talemate/img/0.34.0/shared-world-12.png)

2. The selected episode will appear as a chip at the top of the panel.

![Episode Selected Chip](/talemate/img/0.34.0/shared-world-13.png)

3. Click the **New Scene** button.
4. The dialog will show the selected episode. Note that you do not need to provide premise instructions, as the episode's introduction will be used.
5. Select any additional characters to activate (characters mentioned in the intro are auto-detected).
6. Click **Create and load**.

![Scene from Episode](/talemate/img/0.34.0/shared-world-14.png)

## Marking Elements as Shared

Once a scene is linked to a shared context, you can mark specific elements to be shared across all scenes using that context.

### Sharing Characters

1. Navigate to **:material-earth-box: World Editor** :material-arrow-right: **:material-account-multiple: Characters**
2. Select a character from the list
3. At the bottom of the character editor, check the **Shared to World Context** checkbox

![Shared to World Context checkbox](/talemate/img/0.33.0/shared-context-3.png)

When shared, the character card will highlight in orange/amber to indicate its shared status.

#### Sharing Individual Attributes and Details

Once a character is marked as shared, you can control which specific attributes and details are shared:

**For Attributes:**

1. Open the character and go to the **Attributes** tab
2. Select an attribute from the list
3. Click ![Share with world](/talemate/img/0.33.0/share-with-world.png) to add it to the shared context
4. Shared attributes are marked with a :material-earth: icon in the list
5. Click ![Unshare from world](/talemate/img/0.33.0/unshare-from-world.png) to remove it from sharing

**For Details:**

1. Open the character and go to the **Details** tab
2. Select a detail from the list
3. Click ![Share with world](/talemate/img/0.33.0/share-with-world.png) to add it to the shared context
4. Shared details are marked with a :material-earth: icon in the list
5. Click ![Unshare from world](/talemate/img/0.33.0/unshare-from-world.png) to remove it from sharing

This allows you to selectively share only relevant character information across scenes while keeping other aspects scene-specific.

### Sharing World Entries

1. Navigate to **:material-earth-box: World Editor** :material-arrow-right: **:material-earth: World**
2. Select or create a world entry
3. Check the **Shared to World Context** checkbox in the entry editor

![World Entry Shared to World Context](/talemate/img/0.33.0/world-entry-shared-context.png)

Shared world entries appear with an orange/amber highlight. These entries contain locations, lore, and world-building information that will be accessible across all linked scenes.

### Sharing History

1. Navigate to **:material-earth-box: World Editor** :material-arrow-right: **:material-history: History**
2. If the sidebar isn't visible, click the :material-arrow-collapse-left: icon in the upper left to open it
3. Under **Shared world context**, check **Share static history**

![History Shared Context](/talemate/img/0.33.0/history-shared-context.png)

!!! info "Static History Only"
    Only **static history entries** (manually created base entries) can be shared. Summarized history layers cannot be shared directly.

!!! tip "Sharing Summarized Content"
    To share summarized scene progression, use the **Summarize to World Entry** button in the History tools menu. This creates a world entry from your scene's progress that can then be marked as shared.

## What Gets Shared

- **Characters** - Complete character definitions, personalities, attributes, and details
- **World Entries** - Locations, lore, and world-building information
- **Static History** - Manually created history entries (not summarized layers)

These elements remain synchronized across all scenes linked to the same shared context.
