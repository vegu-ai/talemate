# Details

**Details** are low to high detail information about the character. They could contain information about the character's background, history, or other relevant information.

To add or change the details of a character, open the :material-earth-box: **World Editor** under the :material-account-group: **Characters** tab. Then click on the :material-account-details: **Details** tab.

![World editor characters attributes 1](/talemate/img/0.26.0/world-editor-characters-details.png)

!!! note "Tracked states and details"
    When a **:material-image-auto-adjust: state reinforcement** is updated, the value is set to the corresponding detail. Learn more about tracked states in the [Tracked states](/talemate/user-guide/world-editor/characters/states) section. 

## Adding a detail

To add a new detail find the **New detail** input in the top right corner of the **Details** tab. Type in 
the detail you want to add and press the **Enter** key.

!!! tip
    The detail name can be a descriptive title or a question. 
    
    So `Where did Kaira grow up?` and `Kaira's childhood home` are both valid details.

    When using the AI generation features to generate content we have found that questions generally work better.

![World editor characters new detail](/talemate/img/0.26.0/world-editor-characters-details-new-detail-1.png)

A new empty detail will be added to the list. You can now type in the detail's description.

![World editor characters new detail](/talemate/img/0.26.0/world-editor-characters-details-new-detail-2.png)

You dont need to confirm the changes, they are applied automatically. However if your scene auto-save is disabled you will need to save the scene to keep the changes.

--8<-- "docs/snippets/tips.md:generate_and_autocomplete"

## Editing a detail

To edit an existing detail, select the detail you want to edit by clicking on it. Then make the changes you want to make in the input field that appears.

You dont need to confirm the changes, they are applied automatically. However if your scene auto-save is disabled you will need to save the scene to keep the changes.

--8<-- "docs/snippets/tips.md:generate_and_autocomplete"

## Removing a detail

To remove a detail, select the detail you want to remove by clicking on it. Then press the **:material-close-box-outline: Remove detail** button beneath the detail description.

You will be asked to confirm the removal. Press the **:material-close-box-outline: Confirm Removal** button to remove the detail.

## Setup tracked state

When a detail changes often and lends itself to being tracked, you can quickly set up a tracked state for it, by clicking the :material-image-auto-adjust: **Setup Auto State** button.

--8<-- "docs/snippets/tips.md:tracked_state"

## Pinning a detail

!!! info "New in 0.35.0"

You can pin a character detail to ensure it is always included in the AI context. This is useful for important information that should always be considered when generating text, such as a character's current emotional state, key relationships, or critical backstory elements.

To pin a detail, select the detail from the list, then click the :material-pin: **Add pin** button at the bottom of the detail editor.

This creates a new pin for the detail and opens the [Pins](/talemate/user-guide/world-editor/pins) editor where you can configure the pin settings, such as activation conditions.

If a pin already exists for the selected detail, the button will display :material-pin: **View pin** instead. Clicking it will navigate to the Pins editor with that pin selected.

## Generating details using templates

You can use [templates](/talemate/user-guide/world-editor/templates/detail) to quickly generate details for your characters. 

In the **Details** tab, click the **:material-cube-scan: Templates** button above the detail list to expand the templates list. 

![World editor characters details templates](/talemate/img/0.26.0/world-editor-characters-detail-from-template-2.png)

Templates are contained in groups.

Apply a single template by clicking on it. 

You can select multiple templates by checking the box next to the template name, then clicking **:material-expand-all: Generate Selected**. button.

![World editor characters details templates](/talemate/img/0.26.0/world-editor-characters-detail-from-template-3.png)

!!! tip "Generate entire group"
    Apply a whole group by checking the box next to the group name, then clicking **:material-expand-all: Generate Selected**. button.


Details will be generated one by one and added to the list. The interface is locked during generation.

Depending on how many details are generated, this can take a moment.

--8<-- "docs/snippets/tips.md:generation_templates_and_settings"