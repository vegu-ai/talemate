# State Reinforcement
State reinforcement templates are used to quickly (or even automatically) setup common attribues and states you want to track for characters or the world itself. They revolve around a question, statement or attribute name that you want to track for a character. The AI will use this template to generate content that matches the query, based on the current progression of the scene.

They are used in the [Character Editor - Tracked States](/user-guide/world-editor/characters/states) section of the World Editor.

--8<-- "docs/snippets/tips.md:what_is_a_tracked_state"

## Creating a state reinforcement template

Fist, if you have not done so, [create a template group](/user-guide/world-editor/templates/groups) to store the template in.

Then select the group you want to add the template to and click the **:material-plus: Create Template** button.

![world editor templates create detail template 1](/talemate/img/0.26.0/world-editor-templates-create-attribute-template-1.png)


Next enter a template name and select **Character detail** as a template type.

### Template name

The name / label of the template. This is the name that will be displayed in the list of templates.

### Template type

Specify the type of template you are creating. In this case, select **Character detail**.

Once the template type is selected, the form will update to show the fields required for a state reinforcement template.

![world editor templates create state template 1](/talemate/img/0.26.0/world-editor-templates-create-state-template-1.png)

#### Question or Attribute name

Detail name or question that will be answered during generation.

This can be a question or a statement that the AI will use to generate content.

So for example `Sanity` or `What is the character's current sanity?` are both valid. 

We find that questions work best as they provide a clear prompt for the AI to generate content.

##### Example

> What is the character's current sanity?

or 

> Sanity

### Description

A longer description of the template. What is the purpose of the template? What should it be used for?

### State Type

Specifies what type of object the state is attached to, currently this can be

- `All Characters`- The state is attached to all characters
- `Player Character` - The state is attached to the player character
- `Non-Player Characters` - The state is attached to all non-player characters
- `World` - The state is attached to the world itself

### Context Attachment Method

--8<-- "docs/user-guide/tracking-a-state.md:context-attachment-method"

### Update every `N` turns

This setting lets you control how many game rounds need to pass before this state is re-evaluated.

### Additional Instructions

Allows you to specify extra instructions to give to the AI for the generation of this state.

##### Example

> Track how sane the character is. Are they seeing things? Are they calm or panicking?

### Automtically create

Automatically create instances of this template for new games / characters.

So when you create a new character, this state will be automatically added to them.

### Favorite

Mark the template as a favorite to make it easier to find in the list of templates.

Favorited templates will be shown at the top of the list of templates.

![world editor templates create state template 2](/talemate/img/0.26.0/world-editor-templates-create-state-template-2.png)

## Create the template

When you have filled out the form, click the **:material-cube-scan: Create Template** button to create the template.

## Generate a state from the template

To generate a state from the template, go to the **:material-account-group: Characters** editor and select the character you want to add the state to.

Then select the **:material-image-auto-adjust: States** tab.

In The **:material-cube-scan: Templates** list, find the template you just added and click it.

![world editor templates create state template 3](/talemate/img/0.26.0/world-editor-templates-create-state-template-3.png)

![world editor templates create state template 4](/talemate/img/0.26.0/world-editor-templates-create-state-template-4.png)

After a moment the state should be generated and added to the character.

![world editor templates create state template 5](/talemate/img/0.26.0/world-editor-templates-create-state-template-5.png)

## Editing a state reinforcement template

To edit an existing template, select it from the list of templates in the left sidebar.

Then adjust any of the fields in the form that appears.

Updates are appied automatically and there is no need to manually save the template.

## Deleting a state reinforcement template

To delete a template, select it from the list of templates in the left sidebar, then click the **:material-close-box-outline: Remove Template** button.