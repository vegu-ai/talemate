# Generation Settings

Throughout the :material-earth-box: **World Editor** you will find several opportunities to **:material-auto-fix: Generate** content using AI.

On top of the world editor interface you can configure some settings for this type of content generation.

![world editor generation settings 1](/talemate/img/0.26.0/world-editor-generation-settings-1.png)

## Generation length

When using the **:material-auto-fix: Generate** button with additional instructions (hold `ctrl` when clicking), a dialog opens that includes a **Generation Length** dropdown. This allows you to control how long the generated content should be, measured in tokens.

The available length options range from very short (8 tokens) to comprehensive (1024 tokens):

| Length | Tokens | Description |
|--------|--------|-------------|
| Tiny | 8 | Single word or very brief phrase |
| Very Short | 16 | Short phrase |
| Short | 32 | A sentence fragment |
| Brief | 64 | One or two sentences |
| Concise | 92 | A short paragraph |
| Moderate | 128 | A paragraph |
| Standard | 192 | One to two paragraphs |
| Detailed | 256 | Multiple paragraphs |
| Comprehensive | 512 | Extended content |
| Extensive | 768 | Long form content |
| Complete | 1024 | Full detailed content |

### Remembered length per context type

The generation length you select is remembered separately for each type of content you generate. For example, if you set character descriptions to generate at 256 tokens and dialogue examples to generate at 64 tokens, each will remember its own setting.

This means you can configure different lengths for different content types without needing to change the setting each time you switch between them.

The remembered lengths include:

- Character descriptions
- Character details
- Character attributes
- Dialogue instructions
- Dialogue examples
- Scene introductions
- Scene intentions and phases
- Scene type descriptions and instructions
- Episode introductions
- World entries
- History entries

!!! note
    Length settings are remembered for the current session. They will reset when you close and reopen Talemate.

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
- Scene introduction text
- Scene intentions and phase intentions
- Scene type descriptions and instructions
- Episode introductions
- World entries
- History entries

!!! note "Currently only in the world editor"
    Generation settings are currently **NOT** applied to dialogue or narration generation during
    scene progression, although this is planned for a future release.
