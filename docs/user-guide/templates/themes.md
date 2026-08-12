# Themes

Theme templates hold a complete set of colors for the interface surfaces, the application, the node editor, the scene messages and the chats, together with how message text is styled and whether the theme is light or dark. Applying one repaints Talemate with those colors.

A theme is a world state template like any other — it lives in a template group, is edited in the Templates tab, and is shared as a file.

!!! info "Shipped theme: Talemate Dark"
    Talemate ships a **Talemate Dark** theme, in a group of the same name, that reproduces the application's standard look. It is an ordinary template, so it can be edited — but the edits are written back to the file that ships with Talemate and an update can overwrite them. Build your own theme in your own group for changes that should stick.

## Creating a theme

--8<-- "docs/snippets/common.md:world-editor-create-group"

Next enter a template name and select **Theme** as the template type.

### Template name

The name / label of the template. This is the name that will be displayed in the list of templates.

### Notes

Optional notes about the theme, for example what it is meant to look like. They are not used for anything else.

### Favorite

Mark the template as a favorite to make it easier to find in the list of templates. Favorited templates are shown at the top of the list.

### Colors

The colors are edited in five accordion panels, 67 slots in total. Each slot opens a color picker and shows the color it currently holds; the theme is saved when the picker closes.

| Panel | Slots | What it covers |
|-------|-------|----------------|
| **Surfaces** | 6 | The page background and the card surfaces everything else is drawn on. These decide whether the theme reads as light or dark, and Talemate works out readable text colors from them |
| **App** | 29 | The general interface palette — primary and secondary, the muted tones, the highlight and subdued series, and the state colors (enabled, disabled, unsaved, dirty, favorite marker, delete, cancel) |
| **Node editor** | 8 | The node editor background and the colors that tell core, template, scene and locked node modules apart, selected and unselected |
| **Messages** | 15 | Every scene message type and text markup type, plus the message chrome around them — the play-audio icon, avatar and card borders, and the default badge |
| **Chats** | 9 | The message colors of the director chat and the help chat |

A slot a theme does not carry yet is filled in with the color currently in use, so a new theme starts out looking exactly like what you already see.

### Mode

The **Mode** toggle above the panels marks the theme as **Light** or **Dark**. It does not change any color you have picked. It tells Talemate how to draw everything it derives rather than reads from the theme — the dividers and outlines, how strongly muted text is dimmed, and the appearance of native controls such as scrollbars.

!!! warning "Set Mode to match your Surfaces panel"
    Mode and the Surfaces panel have to agree. A theme with light surfaces left on Dark keeps its readable text, but draws white dividers and outlines on white cards and gives you dark scrollbars on a light page. A new theme starts on the mode you are currently running.

### Message appearance

The **Message appearance** panel sets how message text is written, independent of its color:

- **Italic** and **Bold**, for each message type (narrator, actor, director, time, context investigation, information) and each markup type (quotes, parentheses, brackets, emphasis, entities)
- **Show**, for the types that can be hidden
- **Own color**, for the markup types — whether the markup uses its own color or inherits the color of the message it appears in
- **Backdrop panel opacity** and **Backdrop text shadow**, which control the legibility of message text rendered over a [scene backdrop](/talemate/user-guide/inline-visuals/#scene-backdrop)

These are the same settings as on the [Appearance settings](/talemate/user-guide/app-settings/appearance/#messages) page — a theme carries a set of them so it can be handed out complete.

## Applying a theme

The **:material-palette-swatch: Apply theme** button makes the theme the active one. The template has to be created first — for a new template, click **Create template**.

Applying does two different things, and the difference matters:

**The colors are taken live.** Talemate remembers which theme is active and reads its colors as it renders. Editing the active theme's colors repaints the running application immediately — no reload, no applying again.

**The styling is copied.** Applying writes the theme's message appearance into your [Appearance settings](/talemate/user-guide/app-settings/appearance/#messages), where it becomes yours to adjust. Editing the theme's Message appearance panel afterwards changes nothing until you apply the theme again.

### What a theme leaves alone

A theme does not touch the message asset settings — render cadence, display size and auto-attaching of visuals. Those are workflow preferences rather than a look, so they survive a theme switch untouched.

### Message colors and your own overrides

The theme supplies the color of every message and markup type. A color you set yourself on the appearance settings page wins over the theme for that type — a deliberate exception, kept across theme switches. Click **Reset** next to the message or markup type to give the color back to the theme.

## Sharing a theme

Template groups are stored as single files in the `templates/world-state` directory, so sharing a theme means handing that group's file to someone else, who drops it into the same directory. There is no separate import or export.

## Editing and deleting

To edit an existing template, select it from the list of templates in the left sidebar and adjust the fields — updates are applied automatically.

To delete a template, select it and click **Remove template**, then confirm. If the deleted theme was the active one, Talemate falls back to its built-in default colors rather than rendering unstyled — the same thing happens when the active theme cannot be loaded for any other reason.

## Limitations

!!! warning "What the theme does not reach"
    The node editor canvas itself and the in-app code editors bring their own colors and do not follow the theme. Both stay dark, so they will stand out against a light theme.

!!! warning "Opening a theme group in an older Talemate"
    A version of Talemate that does not know the `theme` template type drops the themes out of any group it loads that contains them — and writes the group back without them if the group is saved. Keep a copy before handing a group to an older install.
