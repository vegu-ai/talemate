# Per-Scene Agent Overrides

Every agent has a set of global settings that apply to all of your scenes. Sometimes a single scene needs different behavior — a longer conversation length, a different narration style, or an action turned off — without you having to change your global configuration and remember to change it back afterwards.

**Per-scene agent overrides** let you do exactly that. You can override selected agent settings for the current scene only. Anything you don't override keeps using your global configuration.

## How overrides work

Overrides are **sparse**: only the specific fields you choose to override are stored. Everything else falls through to the global agent settings. This means that if you later change a global setting, scenes pick up that change automatically — unless they have an active override for that particular field.

Each overridden field is independent. You can override the conversation length for a scene while leaving its format, client, and every other setting on the global value.

## Knowledge effort during creation

**Create New Story** and **Character Card Import** pin their selected knowledge effort as scene overrides. Selected values stay pinned even if they already match global settings. Each creation gets a separate settings file, so reusing a project name does not change a previous story's overrides. Unrelated inherited settings remain intact.

A blank story keeps its normal unsaved state until you save it; that save stores the settings link. Imported cards save the link during import. Once the story is saved, the knowledge hub marks overrides with :material-movie-open-cog-outline:. Activate the icon beside one setting to restore that setting's global value, the icon beside a group to restore the whole group, or the **Scene override** label and icon above the effort slider to restore every knowledge setting owned by the hub. Each action leaves unrelated scene overrides intact.

## Saving a knowledge-hub change for the first time

Changing a setting in a character's knowledge hub opens **Save Scene** when the scene has no save file yet. After the save succeeds, Talemate applies the pending knowledge change automatically. Scenes with a save file and project name apply hub changes directly, including read-only stock scenes. The exception is a read-only scene that is opted out of agent-settings overrides: it cannot store the link a hub change needs, so the change is refused with an error. Save the scene as a copy first (**Save As**), then make the change in the copy.

If a save fails, the dialog stays open with the error and entered name so you can correct it and retry. Cancelling keeps the exact change pending. Use **Save and apply** in the hub to reopen the dialog, or **Discard change** to drop it. Loading another scene discards the pending change so it cannot affect a different story. The pending notice is not confirmation that the settings were saved.

## Editing overrides: the Global / Scene switch

Overrides are edited in the same place as global settings — the **Agents settings page** at **Settings → Connections → Agents**. Clicking an agent in the agent panel opens it there directly.

When a scene is loaded and the agent has at least one setting that supports overrides, a **Global / Scene** switch appears in the header of the agent's detail pane:

- **:material-earth: Global** — the normal view. Changes here affect every scene.
- **:material-movie-open-outline: Scene** — the override view. Changes here apply only to the current scene.

A small number next to the **Scene** button shows how many overrides are currently active for that agent.

![The Agents settings page in Scene mode](/talemate/img/0.40.0/agents-scene-overrides.png)

!!! note
    The switch only appears while a saved scene is loaded. Overrides need a scene (and its project folder) to be stored in, so they aren't available on the placeholder/empty scene.

### Activating an override for a field

In **Scene** mode, each overridable setting has a small link icon next to it:

- :material-link-variant-off: **Inheriting global** — the field is using the global value and is read-only. Click the icon to start overriding it.
- :material-link-variant: **Override active** — the field is overriding the global value for this scene. Edit it freely, or click the icon again to go back to inheriting the global value.

When you activate an override, the field starts out seeded with the current global value, so you always begin from a known state.

Any action that can be switched off globally can also be switched off for the scene alone: its **enable** checkbox carries the same link icon as the individual settings. So a scene can turn off Auto Narration, Revision, Scene Analysis, Long Term Memory and so on without touching your global configuration.

Some sections are always on by design — for example the World State's Character Portraits, the Summarizer's Scene History, and the Conversation and Narrator Generation sections. They have no enable checkbox and cannot be switched off globally or per scene; a `false` left for one in the configuration file (or in a scene's overrides) is ignored.

API keys and passwords are never scene-overridable. They belong to your installation rather than to any one story — a scene file is something you can share — so they never appear in Scene mode, and a value left for one in a scene's overrides file is ignored.

In Scene mode, the page only shows the settings (and sections) that actually support overriding, to keep the view focused. If an agent has no currently overridable settings at all, the Global / Scene switch won't appear.

Some settings only apply while another setting is switched on — for example the Creator agent's Fast-mode fields (Consolidate, One-shot token budget, Fill in misses) only matter while **Fast Character Generation** is on. Those settings appear in Scene mode only while their gating setting allows it, and the gate is read as this scene sees it: the scene's override if there is one, otherwise the global value. So overriding the gate for a scene reveals the settings it gates, and a section whose settings are all currently hidden drops out of Scene mode entirely.

One exception keeps things recoverable: a setting you have **already** overridden stays visible even when its gate is off, so you can always see it in the count and clear it. Its stored value still applies whenever the gate is on again.

### Saving

Overrides are treated like every other edit on the settings page: activating one, or changing an overridden value, marks the page as having **Unsaved changes**, and nothing reaches the scene until you press **:material-check-circle-outline: Save** in the settings toolbar. **:material-undo: Discard** drops them again. Switching agents, switching back to **Global**, or leaving the page writes nothing on its own — the pending overrides simply stay pending.

If the scene doesn't yet have an overrides file (see below), the first save that carries an override asks you to name one before it writes; cancelling that prompt cancels the save and leaves your edits untouched.

On the Agents settings page, choosing a name other than `agent-settings.json` for a read-only scene opens **Save As** to create a writable copy. After it succeeds, Talemate attempts to save the pending overrides and link the copy to the named file. Cancelling **Save As** cancels the save too and leaves your edits pending. This Agents-page flow leaves the original scene unchanged.

If that name already exists in the project's `agent-settings/` folder, the naming prompt shows an error before opening Save As or sending any agent edits. If a file appears after the prompt's file list was loaded, the server also refuses the save with the same guidance for every pending agent. Your edits remain pending. Choose a new filename to store those edits separately. To use the existing file's settings, discard the pending edits and select that file in **World Editor → Scene → Settings → Agent settings file**. The naming prompt never replaces an existing file.

## Quick-toggle chips

Some actions and settings are also exposed as quick-toggle chips directly on the agent in the agent panel, so they can be flipped mid-play without opening the settings page.

A chip always shows the value the loaded scene is actually running on — the scene override when one is active, your global value otherwise — and clicking it changes exactly the value it is showing:

- **No override active** — the chip toggles the global setting, as it always has.
- **Override active** — the chip carries a small :material-movie-open-cog-outline: marker and toggles the scene's override only. Your global setting is left alone; hover the chip to see what it currently is.

Unlike the settings page, a chip writes immediately — there is no pending state and no save step.

To go back to following the global value, clear the override in **Scene** mode on the Agents settings page and save.

## The overrides file

Per-scene overrides are stored in a JSON file inside an `agent-settings/` folder in the scene's project directory. The default file name is `agent-settings.json`.

A few things worth knowing:

- **Overrides are project-scoped.** Every save in a project, including stock scenes, **Save As** copies and restore points, shares its default overrides through automatic linking. Read-only stock scenes can edit these overrides directly; creating another file for them on the Agents settings page takes a **Save As** copy. Explicitly choosing another settings file or opting out changes what that save uses (see below). Different projects have completely independent overrides.
- **Overrides travel with exports.** When you export a scene, the `agent-settings/` folder is included, so your overrides survive being shared with or imported on another system.
- **Bad files fall back safely.** If an overrides file is missing or can't be read, the scene simply falls back to your global configuration and the link is cleared.

## Choosing, swapping, or opting out

Which overrides file a scene uses is controlled from **World Editor → Scene → Settings**, in the **Agent settings file** dropdown. See [Scene Settings](/talemate/user-guide/world-editor/scene/settings#agent-settings-file) for the full description. In short, you can:

- **Auto-link (default)** — the scene automatically uses `agent-settings.json` if one exists in the project. This is the normal behavior. The first override you save creates this file — you are prompted for its name.
- **Pick a specific file** — link the scene to a particular file in the project's `agent-settings/` folder. This lets a project hold more than one overrides file and switch between them.
- **None (opt out)** — disable per-scene overrides entirely for this scene. The scene uses global configuration only and won't auto-link to a default file.

## Related

- [Scene Settings](/talemate/user-guide/world-editor/scene/settings) — where the overrides file is chosen, swapped, or opted out.
- [Agents overview](/talemate/user-guide/agents/) — the global settings that overrides fall back to.
