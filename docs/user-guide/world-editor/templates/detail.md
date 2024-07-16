# Character Detail

Character detail templates are used to define details that a character can have. They can be used to define character traits, skills, or other properties. The AI will use this template to generate content that matches the detail, based on the current progression of the scene or their backstory.

They are used in the [Character Editor - Details](/user-guide/world-editor/characters/details) section of the World Editor.

## Creating a character detail template

Fist, if you have not done so, [create a template group](/user-guide/world-editor/templates/groups) to store the template in.

Then select the group you want to add the template to and click the **:material-plus: Create Template** button.

![world editor templates create detail template 1](/talemate/img/0.26.0/world-editor-templates-create-attribute-template-1.png)


Next enter a template name and select **Character detail** as a template type.

### Template name

The name / label of the template. This is the name that will be displayed in the list of templates.

### Template type

Specify the type of template you are creating. In this case, select **Character detail**.

Once the template type is selected, the form will update to show the fields required for a character detail template.

![world editor templates create detail template 2](/talemate/img/0.26.0/world-editor-templates-create-detail-template-2.png)

### Question / Statement

Detail name or question that will be answered during generation.

This can be a question or a statement that the AI will use to generate content.

So for example `Flaws` or `What is the character's biggest flaw?` are both valid. 

We find that questions work best as they provide a clear prompt for the AI to generate content.

##### Example

> What is the character's biggest flaw?

or 

> Flaws

### Template description

A longer description of the template. What is the purpose of the template? What should it be used for?

### Additional instructions

Additional instructions to pass to the AI for generating content based on this detail.

##### Example

> What is the {character_name}'s biggest flaw? What problems does it cause? 

!!! tip "Variables"
    Currently there are two variables that can be used in the additional instructions field:

    - character_name: The name of the character the detail is being generated for.
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

![world editor templates create detail template 3](/talemate/img/0.26.0/world-editor-templates-create-detail-template-3.png)

## Create the template

When you have filled out the form, click the **:material-cube-scan: Create Template** button to create the template.

## Apply the template

The template will be added to the group and will be available for use in the [Character Editor - Details](/user-guide/world-editor/characters/details) section of the World Editor.

![world editor templates create detail template 4](/talemate/img/0.26.0/world-editor-templates-create-detail-template-4.png)

And when we click it, the AI will generate content based on the template.

![world editor templates create detail template 5](/talemate/img/0.26.0/world-editor-templates-create-detail-template-5.png)

![world editor templates create detail template 6](/talemate/img/0.26.0/world-editor-templates-create-detail-template-6.png)

## Editing a character detail template

To edit an existing template, select it from the list of templates in the left sidebar.

Then adjust any of the fields in the form that appears.

Updates are appied automatically and there is no need to manually save the template.

## Deleting a character detail template

To delete a template, select it from the list of templates in the left sidebar, then click the **:material-close-box-outline: Remove Template** button.