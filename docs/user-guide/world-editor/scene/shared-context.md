# Shared Context

Shared Context allows you to share specific characters, world entries, and history across multiple scenes within the same project. This is useful for creating interconnected stories where certain elements remain consistent across different scenarios.

## Accessing Shared Context

Navigate to **:material-earth-box: World Editor** :material-arrow-right: **:material-script: Scene** :material-arrow-right: **:material-earth: Shared Context**

![Shared Context - No link](/talemate/img/0.33.0/shared-context-1.png)

## Creating a Shared Context

1. Click the **New** button
2. Enter a filename for your shared context
3. The file will be saved as a `.json` file in the scene's `shared-context` folder

## Linking a Scene to Shared Context

1. Select a shared context file from the **Available** list by checking its checkbox
2. Only one shared context can be active per scene
3. To unlink, uncheck the selected shared context

When a scene is linked to a shared context, you'll see:

- Number of shared characters
- Number of shared world entries
- A **New scene** button for creating additional scenes with the same context

![Shared Context - Linked](/talemate/img/0.33.0/shared-context-2.png)

## Creating New Scenes with Shared Context

Once a scene is linked to a shared context, you can create new scenes that inherit the same shared elements:

1. Click the **New scene** button
2. Optionally provide instructions for generating a new premise
3. Select which shared characters to activate in the new scene
4. Click **Create and load**

![Create New Scene dialog](/talemate/img/0.33.0/shared-context-new-scene.png)

The new scene will:

- Be linked to the same shared context
- Inherit the content classification settings
- Use the same agent persona templates
- Use the same writing style template
- Include selected shared characters
- Be part of the same project

!!! warning
    If the current scene is not saved, any unsaved changes will be lost when creating a new scene.

## Managing Shared Context Files

- **Refresh** - Updates the list of available shared context files
- **Delete** - Removes a shared context file (use the inline delete button next to each item)

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
