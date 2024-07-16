# Spice Collection

Spice collections are used to define a set of instructions that can be applied during the generation of spice collections or details. They are used to add a bit of randomness or unexpectedness. 

## Creating a spice collection

Fist, if you have not done so, [create a template group](/user-guide/world-editor/templates/groups) to store the template in.

Then select the group you want to add the template to and click the **:material-plus: Create Template** button.

![world editor templates create attribute template 1](/talemate/img/0.26.0/world-editor-templates-create-attribute-template-1.png)

Next enter a template name and select **Spice collection** as a template type.

### Template name

The name / label of the template. This is the name that will be displayed in the list of templates.

### Template type

Specify the type of template you are creating. In this case, select **Spice collection**.

Once the template type is selected, the form will update to show the fields required for a spice collection template.

![world editor templates create spice template 1](/talemate/img/0.26.0/world-editor-templates-create-spice-template-1.png)

### Template description

A longer description of the template. What is the purpose of the template? What should it be used for?

### Additional instructions

Additional instructions to pass to the AI while applying the spice collection.

This introduces a variable called `{spice}` while will be subsituted with a randomly selected spice from the collection.

In its most basic form you could just put `{spice}` and that could be enough.

But you can also be more creative with it, and assuming `{spice}` values are formatted a specific way, structure sentences around it.

##### Examples

> {spice}

If spice values are along the lines of `make it sad` or `make it funny`

> She likes to {spice}.

If spice values are along the lines of `dance` or `sing`

> Make it {spice}.

If spice values are along the lines of `a little sad` or `funny`

### Spices

The list of spice values in the collection.

#### Adding a spice

In the **New spice** field enter a value and hit enter or the **:material-plus** button.

![world editor templates create spice template 2](/talemate/img/0.26.0/world-editor-templates-create-spice-template-2.png)

#### Generating spices

You can also generate a number of spices at once.

Click the **:material-auto-fix: Generate** button beneath the spices list and in the dialog that pops up enter some clear instructions on the list of items you wish to generate.

##### Example

> A list of hobbies, where each list item can complete the following sentence:
> 
> {character_name} likes to

![world editor templates create spice template 3](/talemate/img/0.26.0/world-editor-templates-create-spice-template-3.png)

After a moment the list should be populated with the generated spices.

![world editor templates create spice template 4](/talemate/img/0.26.0/world-editor-templates-create-spice-template-4.png)

!!! warning "This is hit and miss"
    May require a few attempts to get the desired results.

### Favorite

Mark the template as a favorite to make it easier to find in the list of templates.

Favorited templates will be shown at the top of the list of templates.

## Create the template

When you have filled out the form, click the **:material-cube-scan: Create Template** button to create the template.

## Using the spice collection template

Please see the [Generation settings](/user-guide/world-editor/generation-settings) section for general information on how to apply a spice collection template during generation.

### Example: Generate a character attribute with a spice collection

In the [Character Editor - Attributes](/user-guide/world-editor/characters/attributes) section of the World Editor, select the attribute you want to apply the spice collection to.

For this example it will be the `Likes` attribute, which holds a list of things the character likes.

If you don't have a `Likes` attribute, add it.

![world editor templates create spice template 5](/talemate/img/0.26.0/world-editor-templates-create-spice-template-5.png)

In the **:material-auto-fix: Generation Settings** on top of the world editor, click the **:material-chili-mild: Spice** button and select the **Hobbies** spice collection template. (if you followed this example so far)

![world editor templates create spice template 6](/talemate/img/0.26.0/world-editor-templates-create-spice-template-6.png)

This applies the `Hobbies` spice collection to any future generation.

![world editor templates create spice template 7](/talemate/img/0.26.0/world-editor-templates-create-spice-template-7.png)

However, by default, it will be configured with a very low chance of being applied. (10%)

We want it to be applied 100% when we generate the new `Likes` attribute. So `ctrl` click the `+` button to increase the chance to 100%.

![world editor templates create spice template 8](/talemate/img/0.26.0/world-editor-templates-create-spice-template-8.png)

Back at the `Likes` attribute, click the **:material-auto-fix: Generate** button to generate the content.

You should see a small popup confirming that some spice was applied to the generation.

![world editor templates create spice template 9](/talemate/img/0.26.0/world-editor-templates-create-spice-template-9.png)

And the generated content should reflect the spice applied.

![world editor templates create spice template 10](/talemate/img/0.26.0/world-editor-templates-create-spice-template-10.png)

## Editing a spice collection template

To edit an existing template, select it from the list of templates in the left sidebar.

Then adjust any of the fields in the form that appears.

Updates are appied automatically and there is no need to manually save the template.

## Deleting a spice collection template

To delete a template, select it from the list of templates in the left sidebar, then click the **:material-close-box-outline: Remove Template** button.