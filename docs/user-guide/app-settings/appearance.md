# :material-palette-outline: Appearance

The Appearance settings let you customize how messages and visuals are displayed in your scene. The **Appearance** group in the settings sidebar holds three pages: **Theme**, **Messages** and **Visuals**.

While you edit appearance settings on the Messages and Visuals pages, the scene view previews your changes live; they only become permanent when you save. Applying a theme on the Theme page is the exception — it takes effect immediately.

## :material-palette-swatch: Theme

![App settings - Appearance - Theme](/talemate/img/0.40.0/app-settings-appearance-theme.png)

The Theme page is where you pick the [theme](/talemate/user-guide/templates/themes) that paints the app. Every theme template is listed under the template group it comes from — the shipped **Themes** group first — with a few of its colors shown as swatches, so you can tell the themes apart at a glance.

Each theme has two actions:

- **Apply** repaints the app with the theme's colors and copies its message styling — italic, bold, visibility and own color — and backdrop legibility into your appearance settings, replacing yours. It asks for confirmation first because of that replacement; a color you set yourself is kept and keeps overriding the theme. Applying takes effect immediately and does not wait for **Save**.
- **Manage** opens the theme's template in the Templates tab, which is where themes are edited.

The applied theme is marked with an **Active** chip and its **Apply** is disabled — re-copying its styling over your own edits is what **Restore from theme** on the Messages page is for.

### Switching theme from the app bar

![App bar - theme switcher](/talemate/img/0.40.0/app-bar-theme-switcher.png)

The :material-palette-swatch: button in the app bar, beside the settings cog, is a shortcut to the same list. It carries the same groups, the same order and the same swatches as this page, and marks the active theme with a checkmark.

Picking a theme there applies it immediately, without the confirmation this page asks for — the switcher is the fast way to try a theme on. It replaces your message styling exactly as **Apply** does, so a color you set yourself is kept and keeps overriding the theme. **Theme settings** at the bottom of the menu opens this page.

!!! info "Adding a theme"
    New themes are added as templates in the Templates tab — the note at the top of the page links there. See [Themes](/talemate/user-guide/templates/themes) for creating your own.

## :material-script: Messages

![App settings - Appearance - Messages](/talemate/img/0.40.0/app-settings-appearance-messages.png)

The Messages page gives you control over how text appears in the scene feed. You can customize the styling for different message types and special text formatting.

### Message Types

Configure the appearance of each type of message that appears in your scene:

| Message Type | Description |
|-------------|-------------|
| **Narrator Messages** | Descriptive text that sets the scene and describes actions |
| **Actor Messages** | Dialogue and actions from characters |
| **Director Messages** | Instructions and guidance from the director agent |
| **Time Messages** | Indicators showing the passage of time |
| **Context Investigations** | Results from context investigation queries |

For each message type, you can configure:

- **Italic** - Display the message text in italics
- **Bold** - Display the message text in bold
- **Show** - Toggle visibility of certain message types (available for Director Messages and Context Investigations)
- **Color** - Set a custom color for the message type

### Text Markup Styling

One of the key features in version 0.35.0 is the ability to independently configure how special text markup is displayed. This gives you fine-grained control over the visual presentation of different text elements.

You can configure these markup styles:

| Markup | Symbols | Example |
|--------|---------|---------|
| **Quotes** | `" "` | "Hello there!" |
| **Parentheses** | `( )` | (whispering softly) |
| **Brackets** | `[ ]` | [Author's note] |
| **Emphasis** | `* *` | *dramatic pause* |
| **Entity Highlights** | — | clickable [entity highlights](/talemate/user-guide/world-state/#entity-highlights-in-scene-messages) in the latest message |

For each markup type, you can set:

- **Italic** - Render the marked text in italics
- **Bold** - Render the marked text in bold
- **Show** - Render the markup at all. Switch it off and Parentheses and Brackets are removed from the message along with their markers, while Entity Highlights stop being highlighted and keep their text. Available for Parentheses, Brackets and Entity Highlights; quotes and emphasis always render.
- **Color** - Enable or disable color override. When enabled, the markup uses its own configured color. When disabled, it inherits the color from the surrounding message type.

!!! tip "Color Override"
    The **Color** checkbox for markup styles controls whether that markup uses its own dedicated color or inherits from the message type it appears in. This is useful when you want quotes to stand out in a different color, or when you prefer a more uniform look where all text within a message shares the same color.

### Memories button on character replies

Below the table, **Memories button on character replies** shows or hides the **Memories** button in a character reply's toolbar. The button lists the memories [Refine memories with AI](/talemate/user-guide/agents/conversation/settings/#see-what-a-character-recalled) chose for that reply. On by default.

### Live Preview

As you adjust your settings, the preview panel on the left side of the settings window shows you exactly how your messages will look. The preview includes examples of:

- Narrator text with various markup types
- Character dialogue with quotes and actions
- Director instructions
- Time passage indicators
- Context investigation results

This makes it easy to experiment with different combinations until you find a style you like.

### Setting Custom Colors

To change a color:

1. Click the **Color** button next to the message or markup type you want to customize
2. Use the color picker that appears on the right side of the panel
3. The preview updates immediately so you can see the result
4. Click **Reset** to clear your color and go back to the theme's color

!!! info "Themes supply these colors"
    Every message and markup color comes from the active [theme](/talemate/user-guide/templates/themes). A color you set here overrides the theme for that one type until you reset it, and **Reset** hands the color back to the theme — or to Talemate's built-in default when no theme is active.

### Restore from Theme

**Restore from theme** hands the whole message appearance back to the active theme. It asks for confirmation first, because it drops the appearance edits you made yourself:

- Every color override is cleared, so each message type and each markup type follows the theme's color again
- The theme's styling is copied in once more — italic and bold for every message and markup type, visibility for the types that can be hidden, own color for the markup types, and the [backdrop panel opacity and text shadow](#backdrop-legibility)

The message asset settings — render cadence, display size, auto backdrop and auto-attaching — are left as they are. They are workflow preferences rather than a look, so they sit outside the theme by design.

Restoring changes the settings you are editing, nothing more: keep it with **Save**, or drop it with **Discard**, like any other settings edit. It works with no theme template applied as well, restoring Talemate's built-in default.

!!! info "Picking up a later edit to a theme"
    A theme's colors are read live, but its styling is copied into these settings at the moment the theme is applied. Editing the theme's Message appearance panel afterwards does not reach an installation that already applied it — **Restore from theme** is how you pick those edits up.

## :material-image-outline: Visuals

![App settings - Appearance - Visuals](/talemate/img/0.39.0/app-settings-appearance-visuals.png)

The Visuals page controls how images appear alongside messages in your scene feed. This includes character portraits, cards, scene illustrations, and scene backgrounds.

### Visual Types

Configure display settings for each type of visual:

| Visual Type | Description |
|-----------|-------------|
| **Portrait** | Character portraits that appear next to character messages |
| **Card** | Character or scene cards that can be attached to messages |
| **Scene Illustration** | Images of the current moment ("Visualize Moment") attached to messages |
| **Scene Background** | Purely environmental images ("Visualize Scene (Background)"). Also sets how Backdrop entries show their image while Immersive is off: Display Size picks the size, and Render Cadence **Never** shows the entry without its image |

### Display Settings

For each visual type, you can configure:

#### Render Cadence

Controls when the visual is displayed:

- **Always** - Show the visual on every message that has one (default)
- **On Change** - Only show when the visual differs from the previous message of the same type (portraits only)
- **Never** - Hide this type of visual entirely

!!! tip "Using On Change for Portraits"
    Setting portrait cadence to **On Change** can reduce visual clutter in long conversations. The character's portrait will only appear when it changes, such as when the character's expression or appearance shifts during the scene.

#### Display Size

Controls how large the visual appears:

- **Small** - Compact display, good for keeping focus on the text
- **Medium** - Balanced size (default)
- **Big** - Large display, scene illustrations appear above the message

!!! note "Scene Illustration Positioning"
    When set to **Big**, scene illustrations display above the message text rather than inline. This gives them more prominence and works well for important scene moments.

#### Auto Backdrop

Available for **Scene Illustration**. When enabled, newly generated illustrations automatically become the [scene backdrop](/talemate/user-guide/inline-visuals/#scene-backdrop) — rendered behind the scene text instead of only appearing inline. Off by default.

Scene backgrounds generated for the story always become the backdrop and are recorded as **Backdrop** entries in the story, so Scene Background has no Auto Backdrop checkbox.

Any illustration can also be set as the backdrop manually via its image menu, and the scene tools **Immersive** chip toggles the backdrop on and off.

### Backdrop Legibility

When a backdrop is active, message text sits on translucent panels so it stays readable over the image. Two settings control this:

- **Backdrop message panel opacity** - How opaque the panels behind the message text are. Defaults to `0.8`; lower values let more of the backdrop show through.
- **Backdrop message text shadow** - Renders a subtle drop shadow behind the message text for extra contrast. On by default.

### Auto-attach Visuals

When enabled (the default), newly generated visuals are automatically attached to the relevant messages in your scene. Generated scene backgrounds become the [scene backdrop](/talemate/user-guide/inline-visuals/#scene-backdrop) instead. Disable this if you prefer to manually manage which images appear with which messages; scene backgrounds then only go to the Visual Library as well.
