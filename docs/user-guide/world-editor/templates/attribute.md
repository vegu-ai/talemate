# Character Attribute

Character attribute templates are used to define attributes that a character can have. They can be used to define character traits, skills, or other properties. The AI will use this template to generate content that matches the attribute, based on the current progression of the scene or their backstory.

They are used in the [Character Editor - Attributes](/talemate/user-guide/world-editor/characters/attributes) section of the World Editor.

## Creating a character attribute template

Fist, if you have not done so, [create a template group](/talemate/user-guide/world-editor/templates/groups) to store the template in.

Then select the group you want to add the template to and click the **:material-plus: Create Template** button.

![world editor templates create attribute template 1](/talemate/img/0.26.0/world-editor-templates-create-attribute-template-1.png)


Next enter a template name and select **Character attribute** as a template type.

### Template name

The name / label of the template. This is the name that will be displayed in the list of templates.

### Template type

Specify the type of template you are creating. In this case, select **Character attribute**.

Once the template type is selected, the form will update to show the fields required for a character attribute template.

![world editor templates create attribute template 2](/talemate/img/0.26.0/world-editor-templates-create-attribute-template-2.png)

### Attribute name

The name of the attribute that will be generated from the template.

##### Example

> Hair style

### Priority

Attribute generation can use other existing attributes to influence the generation of new attributes. The priority field is used to determine the order in which attributes are generated. A higher priority means that the attribute will be generated before attributes with a lower priority.

### Template description

A longer description of the template. What is the purpose of the template? What should it be used for?

### Additional instructions

Additional instructions to pass to the AI for generating content based on this attribute.

##### Example

> A description of {character_name}'s current hair style. Include details about the length, cut and color of the hair.

!!! tip "Variables"
    Currently there are two variables that can be used in the additional instructions field:

    - character_name: The name of the character the attribute is being generated for.
    - player_name: The name of the main player character

    More will be added in the future.

### Supports spice

This checkbox indicates if the template supports spice. If checked, the template will be able to use spice collections, allowing for randomness or unexpectedness in the generated content.

--8<-- "docs/snippets/tips.md:spice_collections"

### Supports writing style flavoring

This checkbox indicates if the template supports writing style flavoring. If checked, the template will be able to use writing style templates, allowing for a specific flavor or tone in the generated content.

--8<-- "docs/snippets/tips.md:writing_styles"

### Favorite

Mark the template as a favorite to make it easier to find in the list of templates.

Favorited templates will be shown at the top of the list of templates.

![world editor templates create attribute template 3](/talemate/img/0.26.0/world-editor-templates-create-attribute-template-3.png)

## Create the template

When you have filled out the form, click the **:material-cube-scan: Create Template** button to create the template.

## Apply the template

The template will be added to the group and will be available for use in the [Character Editor - Attributes](/talemate/user-guide/world-editor/characters/attributes) section of the World Editor.

![world editor templates create attribute template 4](/talemate/img/0.26.0/world-editor-templates-create-attribute-template-4.png)

And when we click it, the AI will generate content based on the template.

![world editor templates create attribute template 5](/talemate/img/0.26.0/world-editor-templates-create-attribute-template-5.png)

![world editor templates create attribute template 6](/talemate/img/0.26.0/world-editor-templates-create-attribute-template-6.png)

## Editing a character attribute template

To edit an existing template, select it from the list of templates in the left sidebar.

Then adjust any of the fields in the form that appears.

Updates are appied automatically and there is no need to manually save the template.

## Deleting a character attribute template

To delete a template, select it from the list of templates in the left sidebar, then click the **:material-close-box-outline: Remove Template** button.