# Per-Scene Agent Overrides

Every agent has a set of global settings that apply to all of your scenes. Sometimes a single scene needs different behavior — a longer conversation length, a different narration style, or an action turned off — without you having to change your global configuration and remember to change it back afterwards.

**Per-scene agent overrides** let you do exactly that. You can override selected agent settings for the current scene only. Anything you don't override keeps using your global configuration.

## How overrides work

Overrides are **sparse**: only the specific fields you choose to override are stored. Everything else falls through to the global agent settings. This means that if you later change a global setting, scenes pick up that change automatically — unless they have an active override for that particular field.

Each overridden field is independent. You can override the conversation length for a scene while leaving its format, client, and every other setting on the global value.

## Editing overrides: the Global / Scene switch

Overrides are edited in the same place as global settings — the **agent modal** (opened by clicking an agent in the agent panel).

When a scene is loaded and the agent has at least one setting that supports overrides, a **Global / Scene** switch appears at the top of the modal:

- **Global** — the normal view. Changes here affect every scene.
- **Scene** — the override view. Changes here apply only to the current scene.

A small number next to the **Scene** button shows how many overrides are currently active for that agent.

!!! note
    The switch only appears while a saved scene is loaded. Overrides need a scene (and its project folder) to be stored in, so they aren't available on the placeholder/empty scene.

### Activating an override for a field

In **Scene** mode, each overridable setting has a small link icon next to it:

- :material-link-variant-off: **Inheriting global** — the field is using the global value and is read-only. Click the icon to start overriding it.
- :material-link-variant: **Override active** — the field is overriding the global value for this scene. Edit it freely, or click the icon again to go back to inheriting the global value.

When you activate an override, the field starts out seeded with the current global value, so you always begin from a known state.

Some agents also let you override whether an entire action is **enabled** for the scene, using the same link icon next to the action's enable checkbox.

In Scene mode, the modal only shows the settings (and tabs) that actually support overriding, to keep the view focused. If an agent has no overridable settings at all, the Global / Scene switch won't appear.

### Saving

Overrides are saved automatically when you close the agent modal, the same way global settings are. If the scene doesn't yet have an overrides file (see below), you'll be asked to name one the first time you save an override.

## The overrides file

Per-scene overrides are stored in a JSON file inside an `agent-settings/` folder in the scene's project directory. The default file name is `agent-settings.json`.

A few things worth knowing:

- **Overrides are project-level.** The `agent-settings/` folder lives with the project, so every save file in the same project (including **Save As** copies and restore points) shares the same overrides. Different projects have completely independent overrides.
- **Overrides travel with exports.** When you export a scene, the `agent-settings/` folder is included, so your overrides survive being shared with or imported on another system.
- **Bad files fall back safely.** If an overrides file is missing or can't be read, the scene simply falls back to your global configuration and the link is cleared.

## Choosing, swapping, or opting out

Which overrides file a scene uses is controlled from **World Editor → Scene → Settings**, in the **Agent settings file** dropdown. See [Scene Settings](/talemate/user-guide/world-editor/scene/settings#agent-settings-file) for the full description. In short, you can:

- **Auto-link (default)** — the scene automatically uses `agent-settings.json` if one exists in the project. This is the normal behavior. The first override you set in the agent modal creates this file.
- **Pick a specific file** — link the scene to a particular file in the project's `agent-settings/` folder. This lets a project hold more than one overrides file and switch between them.
- **None (opt out)** — disable per-scene overrides entirely for this scene. The scene uses global configuration only and won't auto-link to a default file.

## Related

- [Scene Settings](/talemate/user-guide/world-editor/scene/settings) — where the overrides file is chosen, swapped, or opted out.
- [Agents overview](/talemate/user-guide/agents/) — the global settings that overrides fall back to.
