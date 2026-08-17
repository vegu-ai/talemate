# Scene Tools

!!! note "Mac users"
    Throughout this guide, hold **Cmd** wherever **Ctrl** is mentioned. macOS reserves `Ctrl`+click for the system context menu, so Talemate also accepts the Command key as the primary modifier on every click and shortcut.

## Agent Activity Bar

![Agent activity bar showing active agents](/talemate/img/0.35.0/agent-activity-bar.png)

Above the scene tools, you may notice a row of small chips appearing and disappearing. This is the **Agent Activity Bar**, which shows you which agents are currently working in the background.

When an agent becomes active, a chip appears displaying:

- The **agent's name** (e.g., Narrator, Director, Summarizer)
- The **current action** being performed (e.g., "Analyzing", "Generating", "Processing")

Agents appear in the order they became active, with the oldest on the left and the newest on the right. As agents complete their work, their chips fade away.

This feature provides visibility into what's happening behind the scenes without needing to look at the system bar at the top of the screen. It's especially useful when multiple agents are working simultaneously.

The agent activity bar can be toggled on or off in [Settings > Game > General](/talemate/user-guide/app-settings/game#show-agent-activity-bar). It is enabled by default.

## Quick Settings

![Quick settings chips](/talemate/img/0.39.0/scene-tools-quick-settings.png)

Above the scene tools sits a row of small toggle chips. Click a chip to toggle it — a green check marks an active toggle.

- **:material-content-save: Auto Save** — Automatically save after each game loop. Requires the scene to have been saved manually once; until then the chip shows a warning explaining why it is unavailable.
- **:material-robot: Auto Progress** — The AI automatically progresses the scene after your turn.
- **:material-image-area: Immersive** — Render the [scene backdrop](/talemate/user-guide/inline-visuals/#scene-backdrop) behind the scene text. This chip only appears when the scene has a backdrop image set (or a generated background is available to become one); toggling it off remembers the chosen image, so you can switch back at any time.
- **:material-cog: Settings** — Not a toggle: opens a shortcut menu to commonly used [application settings](/talemate/user-guide/app-settings/) (Game, Appearance) and the settings of individual agents (Conversation, Narrator, Creator, Director, Visualizer, Text to Speech).

## Tool Bar

<!--- --8<-- [start:tools-ux] -->
![Tool bar](/talemate/img/0.26.0/getting-started-ui-element-tools.png)
<!--- --8<-- [end:tools-ux] -->

#### :material-refresh: Regenerate AI response

This will regenerate the most recent message, if it is an AI generated message.

!!! note "Keyboard modifiers"
    If you hold `ctrl` when clicking this button you will be prompted to supply some instructions for the
    regeneration. This can be useful to guide the AI in a certain direction.

    If you hold `ctrl+alt` when clicking this button you will be prompted to supply some instructions for the
    regeneration while keeping the original message as context. This is useful for rewrites.

!!! info "Previous versions are kept"
    Regenerating doesn't throw away the old message -- each result is added to the message's revision history, which you can browse with the paginator above the message. See [Message revision history](/talemate/user-guide/interacting#message-revision-history).

#### :material-nuke: Regenerate AI Response (nuke option)

This will regenerate the most recent message, if it is an AI generated message, but with a higher temperature and repetition penalties applied, which can lead to more creative responses. Use this to break out of repetitive loops.

!!! note "Keyboard modifiers"
    If you hold `ctrl` when clicking this button you will be prompted to supply some instructions for the
    regeneration. This can be useful to guide the AI in a certain direction.

    If you hold `ctrl+alt` when clicking this button you will be prompted to supply some instructions for the
    regeneration while keeping the original message as context. This is useful for rewrites.

### :material-account-voice: Actor Actions

Will open a context menu that allows you to have the actor perform actions.

![Actor Actions](/talemate/img/0.30.0/scene-tool-character-actions.png)

!!! info "Recommendation"
    Turn auto progress off if you want full control and use these actions to guide the scene.

    ![auto progress off](/talemate/img/0.26.0/auto-progress-off.png)

#### :material-comment-account-outline: Actor Action (Specific Character)

Will pick a character to performan an action.

##### Hold ctrl to provide direction

If you hold the `ctrl` key while clicking the menu item it will prompt you for a direction to inform the character's action.

Depending on what the `Actor Direction Mode` setting in the [:material-bullhorn: Director Agent Settings](/talemate/user-guide/agents/director/settings/#actor-direction-mode) the direction will either be given as an instruction or as inner monologue.

Regardless of mode you should write your instruction so it completets the following sentence: `I want you to ...`

Some examples:

> be angry at the other character

or

> be annoyed at the situation and storm off

#### :material-comment-text-outline: Actor Action

Automatically picks a character to generate dialogue and actions based on the current scene state.

### :material-bullhorn: Director Actions

Opens a context menu with director-driven actions for the scene.

![Director Actions](../img/0.40.0/director-scene-tools-menu.png)

#### :material-tournament: Generate dynamic actions

Asks the director to generate a set of clickable action choices for the current player turn. See [Dynamic Actions](/talemate/user-guide/agents/director/settings/#dynamic-actions) for how to configure this.

!!! note "Keyboard modifiers"
    Hold `ctrl` (Cmd on macOS) while clicking to provide a one-off direction that guides the generated actions.

#### :material-movie-play: Scene direction turn

Manually triggers a single [Autonomous Scene Direction](/talemate/user-guide/agents/director/scene-direction) turn. Useful when Scene Direction is enabled but auto-progression is off and you want to step the director through the scene one turn at a time.

Greyed out when Scene Direction is disabled in the [director agent settings](/talemate/user-guide/agents/director/scene-direction#enabling-scene-direction).

!!! note "Keyboard modifiers"
    Hold `ctrl` (Cmd on macOS) while clicking to provide one-off instructions for the director to follow on this turn only.

#### :material-flag-variant: Evaluate scene intent

Asks the director to evaluate the current [scene intent](/talemate/user-guide/world-editor/scene/direction) and update it if the scene has moved on. The director may also decide the current intent still fits — the status message "Director left the scene intent unchanged" reports that outcome.

!!! note "Keyboard modifiers"
    Hold `ctrl` (Cmd on macOS) while clicking to provide an optional direction that guides the determination.

#### :material-movie-open: Generate long progress

Opens the Generate Long Progress dialog, where the director plans and autonomously generates a multi-beat scene arc from your instructions.

See [Director Planning](/talemate/user-guide/agents/director/planning) for the full workflow and settings.

### :material-script-text: Narrator Actions

Will open a context menu that allows you to have the narrator perform actions.

![Narrator Actions](/talemate/img/0.30.0/scene-tool-narrator-actions.png)


#### :material-script-text-play: Progress Story

Generates narrative text based on the current scene state, moving the story forward.

All actions can be given directions by holding the `ctrl` key when clicking it.

##### Scope of progress

By default the progress is aimed to move the scene forward slightly. As of version `0.30` there exist three sub actions here for `minor`, `major` and `curveball` style progression. How weill this works strongly depends on the model.

All they do is try to coerce the narrator to provide a story progression at a bigger scale, with the curveball one aiming for a story upset.

Note that you can still hold the `ctrl` key to provide further direction for these as well.

#### :material-waves: Narrate Environment

A special type of narration that aims to narrate the environment, focusing on visuals, sounds and other sensory information that currently exist in the scene.

#### :material-image-filter-hdr: Look at Scene

Provide a descriptive, visually focused narration of what is currently happening.

#### :material-account-eye: Look at (Character Name)

Provide a descriptive, visually focused narration of the character's appearance / current action.

#### :material-crystal-ball: Query

Will prompt you for a question and then have the narrator generate narrative text based on that question.

### :material-clock: Advance time

Opens a menu with options to advance time in the scene. As of version 0.37.0, the presets are organized into per-unit submenus and the menu includes a **Custom...** entry for durations that are not covered by the presets.

![Advance Time menu with grouped presets](../img/0.37.0/advance-time-menu.png)

#### Preset submenus

Hovering a group opens its submenu. Clicking a preset advances time by that amount immediately.

| Group | Options |
| --- | --- |
| :material-timer-sand: **Minutes** | 5, 15, 30 minutes |
| :material-clock-outline: **Hours** | 1, 2, 4, 8, 12 hours |
| :material-weather-sunny: **Days** | 1, 2, 3 days |
| :material-calendar-week: **Weeks** | 1, 2 weeks |
| :material-calendar-month: **Months** | 1, 3, 6 months |
| :material-calendar-multiple: **Years** | 1, 2, 3, 5, 10 years |

#### Custom time dialog

Selecting **Custom...** at the bottom of the menu opens a small dialog for entering an arbitrary duration.

![Custom time dialog](../img/0.37.0/advance-time-custom-dialog.png)

1. Enter an **Amount** (minimum `1`).
2. Pick a **Unit** from the dropdown: *minutes*, *hours*, *days*, *weeks*, *months*, or *years*.
3. Click **Advance** to apply, or **Cancel** to close without advancing.

The dialog defaults to `1 hour` each time it is opened.

By default the [:material-script-text: Narrator Agent](/talemate/user-guide/agents/narrator) will narrate the time jump, but you can disable this in the [:material-script-text: Narrator Agent Settings](/talemate/user-guide/agents/narrator/settings/).


!!! note "Summarization"
    Whenever time is advanced, the scene state will be updated, and the next message will trigger the [Summarization Agent](/talemate/user-guide/agents/summarization) to summarize any events before the time jump.


### :material-earth: World State Actions

The :material-earth: world state menu lets you set up and manage tracked states, apply favorited state templates, and generate or edit world context — all without leaving the scene.

![World State Actions](/talemate/img/0.40.0/scene-tool-world-state-actions.png)

!!! info "What is a tracked state?"

    --8<-- "docs/user-guide/tracking-a-state.md:what-is-a-tracked-state"

    Please refer to the [World State](/talemate/user-guide/world-state) section for more information on how to set up custom states to track.

#### :material-cube-scan: Track state

Opens a dialog to quickly set up a new tracked state — a shortcut for doing the same thing in the world editor. Choose whether to track the **World** or a specific **character**, describe what to track, then set how often it updates and how it attaches to context.

![Track State dialog](/talemate/img/0.39.0/scene-tool-track-state-modal.png)

When a character is the target, an extra **Require character active** option appears so the state only progresses while that character is in the scene. The default context attachment also adapts to the target — `Passive` for the world, `Sequential` for a character.

![Track State dialog for a character](/talemate/img/0.39.0/scene-tool-track-state-modal-character.png)

See [Context Attachment Method](/talemate/user-guide/tracking-a-state/#context-attachment-method) for what each attachment option does. Once created, the state can be viewed and managed in the World State Manager.

#### Quick-apply favorite states
<!--- --8<-- [start:quick-apply-favorite-state] -->
Any state template you have favorited appears under its target in the world state menu — the player character, each NPC, and **World** each get a submenu of the favorites relevant to them. *Your list may be different than the one shown here, depending on what you have favorited.*

![Favorite states submenu](/talemate/img/0.39.0/scene-tool-world-state-submenu.png)

Clicking a favorite generates the current state and keeps it tracked until it is removed. A state that is already tracked is marked with a checkmark; clicking it opens the state in the World State Manager instead of creating a duplicate.
<!--- --8<-- [end:quick-apply-favorite-state] -->

#### :material-auto-fix: Generate world context

Generates a new world entry from the current scene context — useful for locations, lore, backstory, and other world details.

#### :material-book-open-page-variant: World context editor / Character context editor

Open the World State Manager to view and edit world entries and character context, including any tracked states you have set up.

#### :material-refresh: Update world snapshot

Regenerates the world state snapshot shown in the left :material-earth: `World` panel. Hold ++ctrl++ (or ++cmd++) while clicking to open a dialog with an optional instructions box that guides this one update and a **Wipe and start fresh** checkbox that discards the current snapshot. A plain click updates immediately.

!!! info "Does not run state re-inforcement"
    This only refreshes the world state snapshot displayed in the left panel under the :material-earth: `World` section; it does not re-inforce the tracked states of the world or characters.

### :material-puzzle-edit: Creative Tools

![Creative Actions](/talemate/img/0.30.0/scene-tool-creative-actions.png)

#### :material-exit-run: Take character out of scene

![Take character out of scene](/talemate/img/0.26.0/scene-tool-creative-deactivate-character.png)

Will remove the character from the scene. This will **NOT** remove the character from the character list, it will only remove them from the current scene, making the actor no longer partake in the scene.

If the current narration and scene progress has not yet indicated the character has left, you will be prompted for a reason, which will be used to narrate the characters exit. If you provide no reason it will be automatically narrated.

![Take character out of scene reason](/talemate/img/0.26.0/scene-tool-creative-deactivate-character-narration.png)

!!! info "Keyboard modifiers"
    You can hold the `ctrl` key when clicking this action to disable the automatic narration altogether.

#### :material-human-greeting: Call character to scene

![Call character to scene](/talemate/img/0.26.0/scene-tool-creative-activate-character.png)

Will add the character back to the scene. 

If the current narration and scene progress has not yet indicated the character has entered, you will be prompted for a reason, which will be used to narrate the characters entrance. If you provide no reason it will be automatically narrated.

![Call character to scene reason](/talemate/img/0.26.0/scene-tool-creative-activate-character-narration.png)

!!! info "Keyboard modifiers"
    You can hold the `ctrl` key when clicking this action to disable the automatic narration altogether.

#### :material-human-greeting: Introduce new character - Directed

Allows you to quickly generate a new, interactive character to add to the scene.

![Introduce new character 1](/talemate/img/0.39.0/scene-tool-intro-char-1.png)

##### Determine Name

If selected will try to generate a reasonable name from both your instructions AND the existing scene context. A reasonable name means "Joseph" instead of "Clumsy Cabbage Vendor".

##### Active

If selected this means the character will be inserted as an **active** character into the current scene right away.

If not selected the character will get created but exist as deactivated and will need to be called into the scene manually.

##### Narrate entry

If selected, the narrator will generate some flavor text for how the character enters the scene (if they arent already there). This will follow the instructions you provide in the text box below.

##### Instructions for the new character

Write any instructions that you want to pass along for the creation, this can be as little or as detailed as you want.

##### Narration direction for the character's entry

Write direction on how you want the character to enter the scene.

!!! note "A character already interacting in the scene will not have their entrance narrated"
    If the narrator has already established the character interacting with your characters this "entry narration" will be skipped. The check for this 100% based on an AI prompt so may not always work correctly.

##### Generate example dialogue

If selected, the AI will generate a few example dialogue lines for the character, showcasing how they speak and act.

When checked, an **Example dialogue guidance** field appears where you can optionally steer how the examples are written — tone, speech patterns, quirks (e.g. "Speaks in short sentences, dry humor"). Leave it blank to let the AI infer the voice from the character's description and attributes.

![Introduce new character example dialogue](/talemate/img/0.39.0/scene-tool-intro-char-example-dialogue.png)

The generated examples can be reviewed and edited later under the character's [Actor management](/talemate/user-guide/world-editor/characters/actor) tab in the world editor.

##### Templates

Control attribute generation using your existing [World State Templates](/talemate/user-guide/templates).

![Select templates](/talemate/img/0.30.0/scene-tool-intro-char-templates.png)

##### Augment Attributes

If you are generating **any** attributes via templatews the default assumption is that you want full control over the attributes, so no additional attributes will be generated. However if you **do** want randomly generated attributes alongside your template generated ones you can check this box.

#### :material-human-greeting: Introduce new character - From context

If narration or dialogue has been generated that references a character that has not yet been created, you can use this action to introduce them and make them real and interactable.

![World State Context](/talemate/img/0.30.0/scene-tool-creative-introduce-2.png)

The AI will be prompted to generate a character based on what is known about them in the context.

!!! note "Hold ctrl for advanced options"
    You can hold `ctrl` to bring up the advanced options similar to when introducing a character from scratch.

Once it is done, the character will now be part of the scene and can be interacted with.

![Character added to scene](/talemate/img/0.26.0/scene-tool-creative-add-character-4.png)

!!! info "Indicator"
    The availability of this is directly tied to the world state on the left panel. 

    ![World State Context](/talemate/img/0.26.0/scene-tool-creative-introduce-1.png)

    The character needs to appear in the list of characters in the world state context. 

    ![Indicator](/talemate/img/0.26.0/scene-tool-creative-introduce-indicator.png) a little human icon will appear next to the :material-puzzle-edit: `Creative Actions` button if there is a character that can be introduced.


### :material-console-line: Custom Commands

Commands that a scene defines through [command modules](/talemate/user-guide/node-editor/core-concepts/command_module/) in the node editor can be run from this menu instead of being typed with `!`.

The menu only appears when the loaded scene actually exposes commands to it — a command module decides that by carrying a menu id. Commands sharing a menu id sit together in one sub menu, labelled with that id.

Clicking a command runs it. If the command takes arguments, a dialog asks for them first — a checkbox, a number field, a text area (one list item per line) or a text field, depending on the argument. Leave a field blank to let the command's own handling for that argument apply.

### :material-image-frame: Visualizer

!!! info "Availability"
    If the visualization menu is greyed out, it means that the [Visualizer Agent](/talemate/user-guide/agents/visualizer) is not enabled or ready.

    Please refer to the [Visualizer Agent](/talemate/user-guide/agents/visualizer) section for more information on how to set it up.

The visualizer menu provides several options for generating images of your scene and characters. As of version 0.35.0, generated images can appear directly in your scene feed as [inline visuals](/talemate/user-guide/inline-visuals).

![Scene tools visualizer menu](../img/0.37.0/scene-tools-visual-menu.png)

As of version 0.37.0, per-character entries are grouped into submenus. Scene-level actions stay at the top level of the menu; each character in the scene has its own submenu with the character-specific actions inside.

#### Auto-attach visuals

At the top of the menu, you can toggle the **Auto-attach visuals** option. When enabled, generated images will automatically appear alongside relevant messages in your scene feed. See [Inline Visuals](/talemate/user-guide/inline-visuals) for more details.

!!! note "Keyboard modifiers"
    - Hold **ALT** to generate only the prompt without creating an image (useful for reviewing prompts before generation)
    - Hold **CTRL** to open a dialog where you can provide custom instructions for the generation

#### :material-image-filter-hdr: Visualize Scene (Card)

Generates a portrait-oriented cover image of the current scene, suitable for use as a scene card or thumbnail.

#### :material-image-filter-hdr: Visualize Scene (Background)

Generates a purely environmental image of the scene without characters. Good for establishing shots or backgrounds.

#### :material-account-tie: / :material-account: Character submenus

Each character present in the scene has its own submenu, listed between the scene-level entries and the scene illustration entry. The player character is marked with the :material-account-tie: icon; NPCs are marked with :material-account:. Hovering a character entry opens the submenu.

![Visual tools character submenu expanded](../img/0.37.0/scene-tools-visual-menu-character-submenu.png)

Each character submenu contains:

- **:material-brush: Card** — Generates a cover image portrait of the character in the current scene context. This creates a larger, more detailed character image.
- **:material-brush: Portrait** — Generates a face-focused portrait of the character. These are ideal for showing expressions and are commonly used as character avatars in the message feed.

The **ALT** and **CTRL** keyboard modifiers described above apply to items inside the character submenus as well.

#### :material-image-filter-hdr: Visualize Moment (Illustration)

Generates a scene illustration depicting the current moment in the story. This captures the environment, characters, and action together in a single image.

!!! tip "Inline Display"
    When **Auto-attach visuals** is enabled, scene illustrations appear in your scene feed. You can configure how they display (size and positioning) in the [Appearance Settings](/talemate/user-guide/app-settings/appearance#visuals).

Generated images can be viewed and managed in the [Visual Library](/talemate/user-guide/agents/visualizer/visual-library), accessible by clicking the :material-image-multiple-outline: image icon in the toolbar.

### :material-content-save: Saving

Context menu that will provide you with `Save` and `Save As` options, restoration actions — `Restore` to the configured [restore point](/talemate/user-guide/world-editor/scene/settings#restoration-settings) and the [`Timeline`](/talemate/user-guide/restoring-scenes) for previewing or forking from any revision — and `Reset Scene State`.

### :material-lightning-bolt: Shortcuts

A shortcut is a menu entry you define yourself: an agent action with a label, an icon and optional standing instructions. If you keep typing the same direction into the same action, turn it into a shortcut and it becomes a single click.

The :material-account-voice: Actor, :material-bullhorn: Director, :material-script-text: Narrator and :material-image-frame: Visualizer menus each carry an **:material-plus: Add shortcut** entry at the bottom, below their regular actions.

#### Creating a shortcut

Clicking **Add shortcut** opens the shortcut dialog.

![Shortcut creation dialog](/talemate/img/0.40.0/scene-tool-shortcut-modal.png)

**Action** — the agent action the shortcut runs. The dropdown lists every eligible action, prefixed with the menu section it belongs to:

| Section | Actions |
| --- | --- |
| :material-account-voice: **Actor** | Actor Action |
| :material-bullhorn: **Director** | Generate dynamic actions, Scene direction turn |
| :material-script-text: **Narrator** | Progress Story, Narrate Environment, Look at Scene, Look at Character |
| :material-image-frame: **Visual** | Visualize Scene (Card), Visualize Scene (Background), Visualize Character (Card), Visualize Character (Portrait) |

**Label** — the title the shortcut gets in the menu.

**Instructions** — optional direction handed to the agent whenever the shortcut runs. This is the same kind of text you would type into the `ctrl`-click direction prompt of the action itself. Leave it empty to run the action as-is.

**Icon** — click one of the common icons in the grid, or type any Material Design Icon name (for example `mdi-sword-cross`) into the field below it. The icon is previewed in the field as soon as the name matches an icon that actually exists — misspelled or unknown names are rejected. The link below the field opens the [full Material Design Icons listing](https://pictogrammers.com/library/mdi/) to browse names.

Saving adds the shortcut to its menu right away, below the menu's regular actions and above the **Add shortcut** entry.

![Shortcut entries in a scene tool menu](/talemate/img/0.40.0/scene-tool-shortcut-menu.png)

#### Running a shortcut

Click the shortcut and the action runs immediately with the stored instructions — you are not prompted for anything.

Actions that target a character — **Actor Action**, **Look at Character** and the **Visualize Character** actions — render one entry per character in the scene, with the character's name appended to the label. **Actor Action** and **Look at Character** list the non-player characters; the **Visualize Character** actions also include the player character, like their regular menu entries. The character is decided by which entry you click, not stored in the shortcut, so a single shortcut keeps up with whoever is in the scene. An **Actor Action** shortcut additionally gets one entry with no character attached, which picks a random non-player character to act.

A shortcut that cannot run right now stays visible as a dimmed entry with the reason under its label — when the scene has no character the action could target, or when the action itself is disabled (for example **Scene direction turn** while scene direction is off). A plain click does nothing there; `ctrl`+click still opens it for editing.

#### Editing and deleting a shortcut

!!! note "Keyboard modifiers"
    Hold `ctrl` (Cmd on macOS) while clicking a shortcut to open it in the dialog instead of running it. Every field can be changed, and **Delete** removes the shortcut.

!!! info "Shortcuts are application wide"
    Shortcuts are stored in the application configuration, not in the scene, so they are available in every scene you load.

#### Sharing a shortcut as a template

A shortcut can be saved as a [Scene tool shortcut template](/talemate/user-guide/templates/scene-tool-shortcut), which is what makes it shareable.

Open a shortcut with `ctrl` (Cmd on macOS) + click and click **:material-cube-scan: Save as template** in the dialog. A second dialog asks for a **Template group** — pick one of the existing groups from the dropdown, or type a name to create a new group. The shortcut's action, label, icon and instructions are written into that group as a template, and the dialog confirms which group it went into.

Template groups are stored as single files in the `templates/world-state` directory, so sharing a shortcut means handing that group's file to someone else, who drops it into the same directory.

#### Installing a shortcut from a template

Every menu that carries shortcuts also carries an **:material-cube-scan: Add from template** entry below **Add shortcut**, whenever there is at least one shortcut template for that menu. Hovering it opens a submenu listing the templates, each with the action it runs below its label. Clicking one adds it to your shortcuts right away.

Shortcut templates can also be installed from the template itself — see [Scene tool shortcut templates](/talemate/user-guide/templates/scene-tool-shortcut).

!!! info "Installed shortcuts are copies"
    Installing a template copies it into your own shortcuts, so editing or deleting the shortcut afterwards leaves the template alone. Installing the same template twice does nothing — a shortcut with the same action, label, icon and instructions is not added a second time.
