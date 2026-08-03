# :material-gamepad-square: Game

Application settings open in the main view via the **:material-cog: Settings** tab in the top navigation (or the cogwheel icon on the right side of the top bar). Navigation lives in the left sidebar, grouped by topic, with a **search field** at the top that finds any setting by name and jumps straight to it.

Changes are collected as you edit — an **Unsaved changes** indicator with **Save** and **Discard** actions appears in the toolbar whenever your edits differ from the stored configuration. Nothing is applied until you save. Unsaved edits survive switching to another main tab and back. While you have unsaved changes, the **Settings** tab in the top navigation also shows a warning badge, so the state stays visible even after you switch to another tab.

If the configuration is changed elsewhere while you have unsaved edits — from another window, or by the [help agent](/talemate/user-guide/agents/help/) — a **Changed outside this view — saving overwrites** warning appears in the toolbar instead of your edits being silently overwritten (or silently overwriting the other change). **Discard** loads the latest stored configuration; **Save** overwrites the outside change with your edits.

![Settings tab showing the unsaved-changes badge](/talemate/img/0.39.0/app-settings-unsaved-badge.png)

![App settings - search](/talemate/img/0.39.0/app-settings-search.png)

The **Game** group holds general game behavior and the default player character.

## :material-cog: General

![App settings - Game - General](/talemate/img/0.39.0/app-settings-gameplay.png)

##### Auto save

If enabled the scene will save everytime the game loop completes. This can also be toggled on or off directly from the main screen.

If a scene is set to be immutable, this setting will be disabled.

##### Auto progress

If enabled the game will automatically progress to the next character after your turn. This can also be toggled on or off directly from the main screen.

##### Max backscroll

The maximum number of messages that will be displayed in the backscroll. This is a display only setting and does not affect the game in any way. (If you find your interface feels sluggish, try reducing this number.)

##### Show agent activity bar

When enabled, a horizontal bar appears above the scene tools showing which agents are currently working. Each active agent is displayed as a small chip with the agent's name and its current action. This provides visibility into background processing without needing to check the system bar at the top of the screen.

This setting is enabled by default.

##### Release GPU cache on scene load

When enabled, idle GPU memory reserved by local CUDA embeddings or TTS is handed back to the driver when switching scenes, so it doesn't pile up and eventually leave too little VRAM to load another scene. Disable only if you have VRAM to spare and would rather keep it reserved.

## :material-human-edit: Player Character

![App settings - Player Character](/talemate/img/0.39.0/app-settings-player-character.png)

Lets you manage a basic default character.

This character is used when a scene is loaded that does not define a player character. Mostly relevant when you load character-cards that aren't in the talemate scene format (e.g., ST character cards).

##### Add default character to blank talemate scenes

When creating a new scene, add the default player character to the scene.
