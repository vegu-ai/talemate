# Writing Styles

Writing style templates are used to define a writing style that can be applied to the generated content. They can be used to add a specific flavor or tone. A template must explicitly support writing styles to be able to use a writing style template.

## Creating a writing style

Fist, if you have not done so, [create a template group](/user-guide/world-editor/templates/groups) to store the template in.

Then select the group you want to add the template to and click the **:material-plus: Create Template** button.

![world editor templates create attribute template 1](/talemate/img/0.26.0/world-editor-templates-create-attribute-template-1.png)

Next enter a template name and select **Writing style** as a template type.

### Template name

The name / label of the template. This is the name that will be displayed in the list of templates.

### Template type

Specify the type of template you are creating. In this case, select **Writing style**.

Once the template type is selected, the form will update to show the fields required for a writing style template.

![world editor templates create writing style template 1](/talemate/img/0.26.0/world-editor-templates-create-writing-style-template-1.png)

### Template description

A longer description of the template. What is the purpose of the template? What should it be used for?

### Writing style instructions

This should be the actual writing style instructions. It will be passed to the AI to generate content in the specified style.

##### Example

> Write in a clear, engaging style typical of modern sci-fi, with accessible language and vivid descriptions of futuristic concepts.

or

> Use a narrative writing style that reminds of mid 90s point and click adventure games.

### Favorite

Mark the template as a favorite to make it easier to find in the list of templates.

Favorited templates will be shown at the top of the list of templates.

## Create the template

When you have filled out the form, click the **:material-cube-scan: Create Template** button to create the template.

## Using the writing style template

Please see the [Generation settings](/user-guide/world-editor/generation-settings) section for general information on how to apply a writing style template during generation.

### Example: Update character's description

Go to the [Character Editor - Description](/user-guide/world-editor/characters/description) section of the World Editor.

In the **:material-auto-fix: Generation Settings** on top of the world editor, click the **:material-script-text: Writing Style** dropdown and select the writing style template you just created.

![world editor templates create writing style template 2](/talemate/img/0.26.0/world-editor-templates-create-writing-style-template-2.png)

![world editor templates create writing style template 3](/talemate/img/0.26.0/world-editor-templates-create-writing-style-template-3.png)

This will apply the writing style toi any content generations you do.

Next, click the **:material-auto-fix: Generate** button bove the character description to generate a new description for the character using the selected writing style. (Hold `alt` if you want to do a rewrite of the existing content)


## Editing a writing style template

To edit an existing template, select it from the list of templates in the left sidebar.

Then adjust any of the fields in the form that appears.

Updates are appied automatically and there is no need to manually save the template.

## Deleting a writing style template

To delete a template, select it from the list of templates in the left sidebar, then click the **:material-close-box-outline: Remove Template** button.