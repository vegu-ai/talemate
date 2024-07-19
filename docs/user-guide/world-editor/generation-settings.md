# Generation Settings

Through out the :material-earth-box: **World Editor** you will find several opportunities to **:material-auto-fix: Generate** content using AI.

On top of the world editor interface you can configure some settings for this type of content generation.

![world editor generation settings 1](/talemate/img/0.26.0/world-editor-generation-settings-1.png)

## Applying a writing style

Allows you to apply a writing style to AI generated content.

Writing styles are managed through [:material-script-text: writing style templates](/talemate/user-guide/world-editor/templates/writing-style). 

Once there is a writing style template available, you can select it from the dropdown list.

![world editor generation settings 1](/talemate/img/0.26.0/world-editor-generation-settings-2.png)

## Applying spice

Spice is a way to add some controlled randomness to AI generated content.

Spices are managed through [:material-chili-mild: spice collection templates](/talemate/user-guide/world-editor/templates/spice).

Once there is a spice template available, you can select it from the dropdown list.

![world editor generation settings 1](/talemate/img/0.26.0/world-editor-generation-settings-3.png)

Whether or not spice is applied to the generated content is controlled by the **Spice Chance** setting.

By default it will set a `10%` chance for spice to be applied to the generated content. You can click the :material-minus: and :material-plus: buttons to adjust the spice chance.

!!! tip
    Holding `ctrl` while clicking the buttons will adjust fully to `10%` or `100%`.

    You can also hold `ctrl` when selecting the spice in the dropdown to immediately set the spice chance to `100%`.

So if you are generating 10 character attributes, and have the spice chance set to `10%`, then on average 1 of the attributes will have spice applied.

If you are generating one specific attribute and want to ensure there is spice applied, you can set the spice chance to `100%`.

## Content that can be generated and is affected by these settings

- Character descriptions
- Character names
- Character attributes
- Character details
- Character dialogue instructions and examples
- Scene descriptions
- Scene introduction text

!!! note "Currently only in the world editor"
    Generation settings are currently **NOT** applied to dialogue or narration generation during
    scene progression, although this is planned for a future release.

