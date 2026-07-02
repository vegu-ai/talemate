# Changelog

_Auto-generated. Do not edit by hand._

## 0.38.0

### Per-Scene Agent Overrides

Agent configuration can now be overridden per scene without changing your global config. The Agent Modal gains a Global / Scene mode switch for toggling and editing overrides, and you can choose, swap, or opt out of the override file under World Editor → Scene → Settings.

### Message Revision History

Regenerated AI messages now show a paginator above the message body so you can browse earlier regenerations. The version you're viewing becomes the one the AI continues from. Continuing a character or narrator message also creates a navigable revision entry, and narrator messages gain a Continue action on the hover toolbar.

### Scene Perspective Overrides

The scene outline perspective now supports per-speaker overrides for the player, NPCs, and the narrator, each falling back to the default when left empty. Reusable presets are managed under Settings → Creator → Perspective Presets.

### Entity Highlights

Notable characters, items, and places in the most recent scene message are now highlighted as clickable entities — click any of them for a short description. The highlight prompt reads the full scene context, so the entities it surfaces stay anchored to what's happening right now.

### Durable World State Snapshot

The world state snapshot now carries entities forward across refreshes instead of regenerating from scratch, updating what changed and dropping entities that are no longer relevant. Stale entries are auto-evicted after several untouched updates, and you can Ctrl/Cmd-click the refresh button to wipe on demand.

The snapshot can also be pinned into the conversation, narrator, and scene-analysis prompts so its tracked entities inform dialogue, narration, and planning, pull in relevant long-term memory, and run in the background when the client supports concurrent inference. A Custom instructions field lets you steer what it focuses on.

### Improvements

**World State Snapshot**

- Added a Custom instructions field to steer what the snapshot focuses on. Empty by default.
- Semantic memory recall now feeds the snapshot so it can build on established lore and earlier scene history. On by default.
- Context pinning surfaces the snapshot in conversation, narrator, and scene-analysis prompts. Off by default.
- Background generation no longer locks scene input when the client supports concurrent inference; manual refreshes can be cancelled mid-generation.
- The snapshot now refreshes per character turn rather than per full round; the default interval was raised from 5 to 10 to keep the cadence comparable.

**Editor & Revision**

- Triggering a revision now shows a Revising spinner that clears whether the text changes, fails, or is cancelled.
- Added a Repetition handling setting (Remove or Attempt rewrite) for AI-assisted revision.
- Context-investigation messages (Look at, Investigate, Query) can now be revised automatically (opt-in, off by default) or manually via the Revise chip.
- The revision chip on the message hover toolbar now shows the configured revision method (Dedupe, Unslop, or Targeted Rewrite) instead of a generic label.

**Autocomplete & Generation**

- Autocomplete accepts a free-form {...} hint block at the end of the input to steer the continuation; the block is stripped when accepted.
- A chip beside the field now offers Redo and Undo after an autocomplete suggestion is applied.
- The Add Dialogue Example and World information fields now support autocomplete (Ctrl+Enter), with the same hint and Redo/Undo affordances.
- Instructions you provide when generating field content are now followed more reliably, with static history entries treating your instruction as the seed to expand on.

**Clients & Generation**

- OpenAI Compatible client gains a Parameters tab with individual toggles for temperature, top_p, and presence_penalty, so unsupported parameters can be omitted entirely.
- llama.cpp client adds a Concurrent Inference toggle so batch operations can run requests in parallel against a single server. Off by default.
- Added a HuggingFace access token to application settings for downloading gated model weights such as the Pocket TTS voice-cloning model.
- Response length gains an Adaptive option (now the default) that drops the token cap when reasoning is enabled, so responses aren't cut off mid-thought.
- Clients can now define a reasoning-start pattern so models that skip reasoning are accepted as-is instead of erroring; built-in Qwen, Gemma, GPT-OSS, and Seed templates set it automatically.
- The client's Reasoning tab now shows a Template default chip when the prompt template supplies a strip or validation pattern, clarifying where the value comes from.

**Installation & Tooling**

- The frontend now installs dependencies with pnpm for supply-chain hardening, provisioned automatically through Corepack; the install, update, and Docker scripts provision Node.js 22.

**Inference Presets**

- Added an Apply to all action that copies the current preset's values to every other preset in the group; Reset now asks for confirmation.
- Widened the adjustable range and refined the step increments on several parameter sliders for more precise tuning.

**Scene & UI**

- Long scenes render more smoothly; removing or rearranging messages now re-renders only the affected slot instead of everything after it.
- Removed the read-only Character Sheet dialog — the Manage character button already covers viewing and editing.
- Renamed the Creator sub-tab from Content Context to Content Classification to match the scene outline editor.
- Added a Make Player Character / Unmark as Player action to the character editor that swaps which character the player controls.
- Context-investigation messages gain a Visualize action that generates a matched image into the message.
- Added a Per-Action Reasoning override so reasoning can be forced off for specific agent actions, via the brain icon in the prompt log.

**Node Editor**

- Event Modules gain an auto_register toggle so a module subscribes to its event as soon as it's registered, without being placed in the scene loop graph.
- Log entries now show a right-aligned HH:MM:SS.mmm timestamp for easier correlation with scene activity.

### Bug Fixes

**Backends**

- Google: an incomplete setup no longer overwrites the client's model name, which left the client looking configured while every request failed; existing bad values are repaired automatically.
- Anthropic: the Optimize for Prompt Caching toggle now actually enables caching by sending the required parameter when on.
- OpenRouter applies the same caching for anthropic/* models; note that enabling it forces routing to direct Anthropic.
- Conversation agent no longer injects # into the stop-sequence list on every turn.

**Messages & Toolbar**

- Message toolbar actions and double-click editing now disable while a background operation runs, with the hint reading Editing locked.
- The Create Pin action on narrator messages now respects the UI lock during generation.
- World entries created via Create Pin are marked Include only when pinned, so they surface through the pin rather than as ambient memory.
- Toolbar deletes, edits, and revision swaps now write through immediately with autosave on, so forking or rollback reflects them without a manual save.
- Intro message TTS now activates the scene tools audio control when triggered manually.

**Scene & Memory**

- Forks and rollbacks created from the changelog UI no longer fail to load with a missing-field error; affected history entries are repaired on reconstruction.
- Switching scenes now releases GPU memory reserved by local CUDA work (embeddings, TTS); can be turned off under Settings → Game → General.
- Scene-group templates created in the prompt manager are now resolvable from Jinja include calls regardless of the active agent type.
- Contextual autocomplete no longer repeats text you've already typed instead of continuing from where you left off.

**UI & Startup**

- Fixed an empty grey toast flashing after operations with no visible change; swallowed cancellation toasts now display.
- Node Editor boolean property checkboxes now repaint immediately on click instead of waiting for focus to move.
- The onboarding long-term memory step now scrolls on shorter viewports, keeping the Apply & finish button in view.
- Automatic prompt-template detection now times out and continues startup when HuggingFace can't be reached, instead of hanging indefinitely.

## 0.37.0

### Upgrade Notes

Ports and environment variable names changed in this release. Review these before launching.

#### Frontend default port: 8080 → 8082

The frontend now listens on `8082` by default to avoid colliding with llama.cpp. Update bookmarks and reverse-proxy configs that pointed at `localhost:8080`. To keep the old port, set `TALEMATE_FRONTEND_PORT=8080` before launching.

#### Docker env vars renamed

`FRONTEND_PORT` → `TALEMATE_FRONTEND_PORT` and `BACKEND_PORT` → `TALEMATE_BACKEND_PORT`. Rename these in any `.env` files or shell environments — the new variables control both the published host port and the port uvicorn binds inside the container.

### Director Planning

The director can now build and track its own todo lists during multi-step work in director chat, ticking tasks off as it completes them.

A new **Generate long progress** action on the scene toolbar produces multi-beat scene arcs from a short seed and plays them out beat by beat, with configurable pacing and dialogue ratio.

### Auto Narration

Replaces the old **Narrate after Dialogue** toggle with a unified auto-narration system on the Narrator agent. A master chance slider gates whether narration fires per actor turn, and a weighted action mix decides which kind runs (Progress Story, Narrate Scene, or Narrate Environment). Suppresses itself while scene direction is active.

### LLM Prompt Templates Manager

A dedicated tab for viewing, creating, editing, and deleting LLM prompt templates. Built-in templates are read-only and can be copied to user templates; user templates live in `std/user/` and are gitignored. GGUF / llama.cpp chat templates can be used directly.

### Character Folders

Optionally organize the World State Manager character list into collapsible folders. Assign folders from the character editor and rename them from the sidebar. Folder assignments sync across scenes linked to the same shared world context.

### OpenAI Compatible TTS

Now supports multiple backends, each with its own base URL, API key, model, and voice list. Voices auto-fetch from servers that expose a listing endpoint, and can be added manually for those that don't.

### KoboldCpp TTS Auto-Setup

KoboldCpp clients with a TTS model loaded are automatically registered as a TTS backend. The configuration persists across restarts and auto-enables when the model is loaded, auto-disabling when it isn't.

### Model Testing Harness

A bundled scene that runs a suite of minimum-viability tests against a connected language model client.

### Improvements

**Director & Scene Direction**

- New scene tools menu button to manually trigger a scene direction turn; Ctrl+click for one-off instructions.
- Type `#text` in the main input to insert a player-authored director message without taking a turn; `##text` keeps your turn.
- Scene direction instructions accept a Jinja2 template field that renders alongside the raw instruction text.
- The director's action confirmation timeout is now configurable (0–60 minutes; 0 waits indefinitely).
- Default scene loop's Scene Direction node now defers to the director's configured `max_actions_per_turn` instead of hardcoding 10.

**Prompts & Templates**

- New `{{ system_prompt }}` template variable for use inside system prompt overrides at app and client level.
- New `{{ render_game_state("path/to/var") }}` Jinja helper renders a targeted slice of the game state with optional title and token budget.
- Active overrides show a pencil icon, and the Prompts tab surfaces a warning when any override is outdated.
- Active Templates preview gains shortcuts to create or edit overrides and to jump to the resolved template's source.
- Added a Gemma 4 prompt template with a thinking-mode toggle.

**Scene & UI**

- New scene perspective field for narrative perspective and tense (e.g., "Third person limited, past tense").
- Visual tools menu is now grouped into per-character submenus.
- Time advancement reorganized with grouped presets (Minutes, Hours, Days, Weeks, Months, Years) and a custom duration dialog.

**Clients & Generation**

- Advanced client settings moved into a dedicated Advanced tab.
- New per-client Section Format setting to format prompt sections as Markdown or XML.
- Targeted rewrites now run as a single LLM call instead of two, halving latency and token cost.
- Anthropic: added `claude-opus-4-7` and a new `xhigh` reasoning effort option between `high` and `max`.
- Pocket TTS upgraded to v2 with an optional int8 quantize toggle for ~30% faster CPU inference; existing configs auto-migrate.
- Prompt deduplication is now opt-in per client (off by default) via a Deduplicate Prompts toggle on the Advanced tab. Enable only when RAG injection is producing substantial duplication and the context window is tight — modern large context windows rarely benefit, and dedupe breaks prompt caching.

**Context & Memory**

- New Search Strictness slider in the Context Database UI tunes embedding similarity on the fly; the underlying preset value is now a float (0.1–2.0).
- Switching the embeddings device (e.g., CPU ↔ CUDA) no longer requires a restart.
- Multi-line context (world info, memories, pins) is no longer permanently flattened by deduplication; original formatting is restored after the comparison.

**Infrastructure**

- Backend and frontend host/port can be set via `TALEMATE_BACKEND_HOST/PORT` and `TALEMATE_FRONTEND_HOST/PORT` environment variables. (#254)
- Set `TALEMATE_LOG_PROMPTS=1` to write full prompt+response data to `logs/prompt_log.jsonl`.

**Node Editor**

- Asset Exists: new `allow_partial` option for prefix matching instead of exact asset ID matching.
- Prompt From Template: new `dedupe` property (default on) to control prompt deduplication.
- Dict Get (Path): new node that retrieves values from nested dicts/lists by dotted path, with a `found` flag and a `default` input.
- As Number: new `default` input socket that substitutes when the primary value is None or unresolved, coerced to the configured numeric type.

### Bug Fixes

**Generation & Cancellation**

- Failed message regeneration no longer permanently removes the original message from the scene.
- Contextual Generate now has a working Cancel button and runs in the background so the cancel signal is processed mid-generation.
- Autocomplete moved to a background task: it can be cancelled, no longer freezes the input on empty responses, and the snackbar shows a cancel button.
- Scene input no longer stays disabled after cancelling any background generation.
- Contextual Generate no longer prefills an empty line after `1.` in list-type generation.
- World State Manager: cancelling an LLM connection error during Refresh/Reset State, Apply Templates, Generate Dialogue Instructions, Regenerate History Entry, or Revise Message no longer hangs the card.

**Output Quality**

- Narrate Progress no longer occasionally generates screenplay-style dialogue instead of prose.
- Fixed response extraction failing when only a closing anchor tag was present.
- Unslop revisions that hallucinate substantially longer text are now discarded.
- Fixed duplicated character descriptions in dialogue, narrator, director, and creator prompts.

**Backends**

- Anthropic: fixed generation when response length capping is disabled; cleaned up outdated dated model IDs.
- Reasoning Pattern: blanking the field no longer silently restores the old default; template-derived patterns are now picked up.
- TabbyAPI: fixed empty responses on streaming requests.
- Text-Generation-WebUI / KoboldCpp: fixed a streaming crash that discarded the entire generated response.
- OpenRouter: fixed redundant provider/model list fetches when multiple OpenRouter clients are configured.

**Director**

- Introduce Character: the advanced dialog (Ctrl+click) now uses your instructions instead of scene context.
- Removed a redundant LLM call from the scene direction action.

**Memory & RAG**

- RAG Query Generation now respects the volatile context placement setting, restoring prompt-cache hit rates on the long-term memory retrieval flow.
- Character memory: multi-line character descriptions are now stored as a single vectordb entry instead of one entry per line, matching how other base attributes are committed.

**Security & Config**

- API keys in agent action configs (e.g., OpenAI Compatible TTS, visual backends) are now properly encrypted at rest instead of stored in plaintext.

**UI**

- Voice library: fixed character manager crash when a character was deactivated.
- Episodes: the "No episodes available" placeholder is no longer selectable.
- Prompts: template preview editor is no longer clipped at the bottom across the Active, group, and LLM template tabs.
- Character visuals: fixed an infinite request loop in the cover image and portrait tabs when a character had no scene assets.
- Windows 10: fixed blank page from JavaScript files being served with the wrong MIME type.
- macOS: Ctrl+click affordances throughout the UI now also accept Cmd. (#261)

**Loop, Time & Nodes**

- Passive narration no longer skips AI turns.
- Toolbar time advancement is functional again, and the 1-week and 2-week presets use valid durations.
- `data/MakeDict` and `data/MakeList` no longer leak values across graph executions.
- Function Argument node: passing `None` to a numeric argument no longer crashes.

## 0.36.1

### Improvements

**Prompts & Templates**

- Added a prompt template for Google's Gemma 4 model family.

### Bug Fixes

**Output Quality**

- Contextual Generate: fixed white-space issues that broke list creation tasks.
- Narrator: tweaked prompts for the story progress narration.

**Backends**

- Text-Generation-WebUI: fixed SSE event termination on the [DONE] signal.

## 0.36.0

### Prompt Manager

The prompt template system has been rebuilt into a unified Prompt Manager accessible from the main UI. Templates are organized into groups with a configurable priority order controlling which overrides take effect. The resolved template tree is color-coded by source group, and recently rendered templates and sent prompts can be inspected with direct navigation to the source for editing.

### Context History Review

A new context review panel visualizes how scene history is rendered into context for AI prompts, broken into sections with per-section token counts and budget allocation. A new best-fit mode automatically distributes budget across layers to cover the full timeline with a detail gradient — compressed at the start, detailed at the end.

### Multiple Director Chats

The director chat now supports multiple concurrent conversations, each with its own message history and mode settings. Titles are auto-generated after the first exchange.

### Scene State Reset

A new dialog provides granular control over resetting scene data — context DB, history, intent state, per-agent cached states, and reinforcements can be selected individually. Replaces the scattered reset commands with a single unified interface.

### Time Passage Management

Time passage messages can now be inserted, edited, and deleted directly through the scene view. Layered history statistics including compression rate are now displayed in the history tools menu.

### Image Analysis via Local Clients

Image analysis now supports two new backends: OpenAI Compatible for any OpenAI-compatible vision endpoint, and Talemate Client which uses any vision-capable Talemate LLM client.

### API Key Encryption

API keys stored in `config.yaml` are now encrypted at rest. The encryption key is stored in the OS keyring when available, with a file-based fallback for Docker and headless environments. Existing plaintext keys are encrypted automatically on next save.

### Volatile Context Placement

Volatile content — such as long-term memory, dynamic notes, and other frequently changing context — can now be placed after the scene history instead of before it. Improves prompt caching hit rates on API backends that support it.

### Improvements

**Narrator & Conversation**

- Narrator generation length is now configurable per narration type.
- Conversation: new AI Aware mode where characters know they are AI personas.
- Summarizer: custom instructions and writing style are now included during summarization.

**Clients & Generation**

- Anthropic: adaptive thinking support with configurable effort level.
- Anthropic: added claude-opus-4-5, claude-opus-4-6, and claude-haiku-4-5.
- Google: added support for gemini-3.1 models.

**Scene & UI**

- TTS: audio tag support for vocal markers (e.g., [laughing]) with ElevenLabs v3.
- World Editor: Generate from Topic for creating world entries from a prompt.
- Frontend: version mismatch detection between frontend and backend.

### Bug Fixes

**Output Quality**

- Fixed `)`, `]`, and `}` terminators being stripped from the end of messages.
- Fixed `:` in conversation generation causing content loss.
- Fixed conversation agent not respecting generation length.
- Fixed duplicate length instructions when reasoning was enabled.
- Fixed leading whitespace producing duplicate prepared responses.
- Fixed multi-line text handling in parentheses and brackets.

**Memory & RAG**

- Fixed summarize-dialogue sending too much context with layered history.
- Fixed layered history construction and summary-to-dialogue crossover.

**Director**

- Fixed a recursive retry bug in the focal agent.

**UI**

- Fixed context ID dot notation when character names contained dots.

## 0.35.0

### Autonomous Scene Direction

Allows autonomous scene progression through the director agent, using the same actions available in director chat. The Direction tab shows actions taken during the director's turn. A strong LLM (100B+) with reasoning capabilities is recommended. New director actions can be added via Director Action Nodes in the node editor.

### Character Visuals & Avatars

A new Visuals tab in the character editor for managing portraits and cover images, with generation support. Character messages now display portraits. The world state manager can re-evaluate which portrait to use based on scene context and commission new portraits via the director.

### Inline Visuals

Images created through scene tools or director actions now appear inline in the scene feed. Size and display options can be configured in appearance settings.

### llama.cpp Client

Added official llama.cpp client support for llama-server.

### Pocket TTS

Added Pocket TTS support for local CPU-based text-to-speech with voice cloning using audio prompts.

### Improvements

**Scene & UI**

- New setup wizard on initial launch for LLM, Memory, and Visual agent configuration.
- Message appearance overhaul with configurable markdown display.
- Agent activity stack is now visible above the scene tools.

**Clients & Generation**

- KoboldCpp: adaptive-p, min-p, and presence/frequency penalty support.
- Experimental concurrent requests for hosted clients on visual prompts.

**Visual Agent**

- Resolution presets, prompt revision, auto analysis, and prompt length config.
- Visual Library: image crop regions for cover images.

**World & Pins**

- Pin conditions can now target game state variables.

**Node Editor**

- X for staging/alignment, Y for vertical alignment.

## 0.34.1

### Bug Fixes

**Backends**

- OpenRouter: fixed empty responses from reasoning models.
- OpenRouter: fixed reasoning token not found errors.
- OpenRouter: reasoning token collection now delegates to OpenRouter.
- OpenRouter: reasoning effort is configured correctly.

## 0.34.0

### Visual Agent Refactor

Adds image editing with reference images and image analysis. Image editing modifies existing images using reference images. Image analysis extracts information from images for use in generation. Supported backends: ComfyUI, Automatic1111, SD.Next, OpenAI, Google, OpenRouter. Visual prompt instructions can now be customized through new Visual Style templates in the Templates editor. Nodes for image generation have been added to the node editor.

### Visual Library

Visual library system for managing generated images and scene assets, including character portraits, scene covers, and other generated images. The image queue allows generating new images, regenerating existing ones, and iterating on generated images with modifications. Nodes for asset management have been added to the node editor.

### Character Card Support

Character card import has been completely refactored. The director agent analyzes greeting texts to detect multiple characters present in the card, allowing selective import of detected characters. Alternate greetings can be imported as episodes with optional AI-generated titles. Character books (lore books) are imported as world state entries. Character generation now uses the card description, greeting texts, and character book entries together to determine character descriptions, attributes, and dialogue examples. The player character can be set from a default template, selected from detected characters in the card, or imported from another scene.

### Improvements

**Scene & UI**

- Templates editor moved out of the World Editor — now available from the main navigation, no scene required.
- Add Reset shortcut to the Save menu, plus a save-required indicator.
- App now properly locks inputs when client configuration is missing.
- Improvements to director chat.
- Token-per-second calculation has been improved.

**Clients & Generation**

- Setup now prompts for unified API key configuration during client setup.
- Client selection in agent config now only shows enabled clients.

**Shared World**

- Button to share or unshare all characters at once.
- Button to share or unshare all world entries at once.
- New episodes — Talemate's version of alternate introductions.

**Narrator & Director**

- Narrator: story progress now respects the generation length setting in the narrator config.
- Character state reinforcements: new `require_active` setting requires the character to be active for the state to be reprocessed (default on).

**Infrastructure**

- Scene assets are now managed in a shared `assets/library.json` per project.

### Bug Fixes

**Output Quality**

- Fixed an issue where the narrator would use the wrong preset or system message.

**UI**

- Fixed character image generation missing information when the targeted character was inactive.
- Fixed `'_SceneRef' object has no attribute '_changelog'` error.

## 0.33.0

### Director Chat

A chat interface for conversing with the Director agent about the current scene. The Director can execute actions through 25+ specialized node modules covering scene queries, character/world state updates, game state management, narrative direction, and history modifications. Minimum recommended parameters: 12k+ context, 32B+ model with reasoning enabled, ideally 100B+ models for best results. Accessible through the director console once a scene is loaded.

### Scene Changelog and Restoration

Tracks all scene changes over time using delta compression. Stores incremental changes between revisions in segmented changelog files. Allows scenes to be reconstructed fully to a specific point in history and will be used for restoring scenes as well as true forking of scenes.

### Shared World Context

Allows marking characters, world entries, and static history entries as shared to synchronize them across multiple scenes in the same project. Shared elements are exported to a dedicated context file that other scenes can reference. For characters, supports granular sharing at the attribute and detail level. Shared context files can be created and managed in World Editor → Scene → Shared Context.

### Improvements

**Director & Scene Direction**

- New agent persona setting (currently only available for the director).
- Pin decay: pins stay active for N turns without re-evaluation.
- Game state variable editor.
- ContextID system for unified management of context.
- Summarizer / editor / director message access added to the scene toolbar.

**Scene & UI**

- Ctrl+Up/Down arrow cycles through previous messages in the scene chat input.
- Scene forking now uses the new changelog system to reconstruct the scene at the chosen revision.
- World Editor → Context DB is now read-only outside of pin management.

**Memory & Generation**

- Improvements to data structure handling in LLM responses.
- Memory agent: semantic retrieval improvements.

**Node Editor**

- Many new nodes added.
- Module library overhauled to a treeview display in the sidebar.
- Required inputs that aren't connected now show as red links.
- Certain nodes can be Alt+Shift+dragged to spawn a counterpart.
- New collector nodes for collecting values into lists or dicts.
- Clicking outside the node property editor no longer discards changes automatically.
- New nodes auto-resize to fit their title and inputs.
- Property choice fields are now sorted alphabetically.
- Added group presets and node search improvements.

### Bug Fixes

**Scene & UI**

- Fixed drag-and-drop scene / character cover images.
- Fixed several layout issues in the World Editor.
- Context DB clean-up is now enforced on scene load.
- Renamed remaining `World state manager` references in the UI to `World Editor`.
- Scenes that no longer exist are now removed from the recent scenes list.
- Contextual generate now defaults to the scene writing style if one is set.

**Backends**

- OpenRouter: setting the API key from unset to set now immediately fetches models.

**Director**

- Fixed AI function argument conversion casting everything to string.

**Node Editor**

- Errors in event nodes can no longer cause infinite loops of failures.
- Deleting a module while it is loaded no longer errors.
- Argument nodes now convert to their type correctly.
- Switching from node editor to world editor no longer loses graph changes.
- Get node can now access tuple and set items.
- Contextual Generate node now errors clearly when `context_name` is not set.
- Ctrl+Enter in text editor nodes no longer adds extra newlines on submit.

## 0.32.3

### Bug Fixes

**Node Editor**

- Fixed LiteGraph context menu positioning.

## 0.32.2

### Bug Fixes

**Backends**

- Fixed KoboldCpp connection issues.

## 0.32.1

### Improvements

**Prompts & Templates**

- Tweaked scene analysis and director guidance prompts for conversation.
- Added GLM 4.5 templates.

### Bug Fixes

**Backends**

- Fixed LMStudio connection. (#212)

**Scene & UI**

- Windows: fixed setup failure when any parent folder path contained spaces. (#211)
- Fixed character creation issues.

## 0.32.0

### Upgrade Notes

#### XTTS2 TTS support removed

Switch to one of the new local backends (F5-TTS, Chatterbox, Kokoro) or a remote backend (ElevenLabs, Google Gemini-TTS, OpenAI) via the new voice library.

### TTS Agent Refactor

The Text-to-Speech agent has been completely refactored, adding support for additional APIs, per-character voice assignment, and speaker separation. Voices can now be managed through the new voice library. Local backends: F5-TTS (zero-shot voice cloning), Chatterbox (zero-shot voice cloning), Kokoro (predefined voice models). Remote backends: ElevenLabs, Google Gemini-TTS, OpenAI. The director agent can automatically assign voices to new characters based on voice library tags.

### Reasoning / Thinking Models

Support for reasoning / thinking models has been added across all client types. Activate it via the new Reasoning tab in the client configuration UI.

### Scene Export / Import Packages

Scenes can now be exported as complete packages — including nodes, assets, and info files — and imported through the home view. Stand-alone JSON scene files remain supported for backward compatibility.

### Improvements

**Clients & Generation**

- OpenRouter: provider selection and generation quality fixes.
- KoboldCpp: default prompt template added.

**Scene & UI**

- Agents can now be Ctrl+clicked to toggle their enabled state.
- Visual agent: prevents scene cover image from being overwritten.
- Scene analysis and guidance are now skipped when building image generation prompts.
- Simulation suite: fixed inactive characters.

**Infrastructure**

- Migrated the frontend build from vue-cli to Vite (thanks @pax-co).
- Refactored config handling for improved stability.

**Node Editor**

- New nodes: As String, Generate TTS, Get Narrator Voice, Get Voice, TTS Agent settings, Unpack Voice.

### Bug Fixes

**Director**

- Fixed a Jinja2 error during auto direction generation.

## 0.31.0

### Installable Node Modules

A rudimentary way to register node modules as packages so they can be installed into a scene. A Mods tab becomes available once a scene is loaded and allows installing or uninstalling such modules. The Dynamic Story node module ships with a package, so manual node-editor setup is no longer required.

### History Management

Add, edit, remove, and regenerate entries in the History tab of the World Editor. Entries based on summarization can be inspected to show their source messages.

### Improvements

**Clients & Generation**

- OpenRouter support added.
- Ollama support added.
- KoboldCpp embeddings support added.
- Instructor embeddings are functional again.

**Visual & Memory**

- Visual agent can now generate prompts only — available even if the visual agent is not fully configured for image generation.
- Memory agent: improved memory retrieval.
- Summarization agent: summarization improvements.

**Node Editor**

- Jinja2 templates in `templates/modules` are now properly loaded.
- New Emit System Message node — communicate messages to the user outside of the context history.

### Bug Fixes

**Scene & UI**

- Fixed `chara_card_v3` spec character card import.

**Node Editor**

- Errors inside custom node graphs no longer hang Talemate.
- Several math nodes no longer run when their wires are inactive.
- DynamicInstruction node no longer runs when its wires are inactive.
- Editor revision events now include the `template_vars` value.

## 0.30.0

### Node Editor

The backend has been refactored to a node-based architecture, allowing for more complex and dynamic scenes and customizable, reusable modules. This is the first iteration — accessible from creative mode once a scene is loaded.

### Revisions

A revision action has been added to the Editor agent. When toggled on, it analyzes text for repetition or unwanted prose and revises it accordingly. Unwanted prose is defined through the writing style template assigned in the scene settings.

### Auto-Direction

The Director agent can now automatically direct the scene based on the current state and intention of the scene. Experimental and a work in progress — the goal is to test the waters towards giving the reins to the Director agent to direct the scene as it sees fit.

### Improvements

**Clients & Generation**

- Inference preset groups.
- AI function calling improvements.
- Client rate limiting.
- Clients can now configure data communication to be in YAML or JSON format.

**Scene & UI**

- Simulation Suite V2 — remade using the new node editor (v1 still exists).
- Director guidance cache.

## 0.29.0

### Scene Analysis

Adds scene analysis capabilities, providing analytical summaries that other agents can use to enhance their output.

### Director Guidance

The director agent now offers conversation and narration guidance based on the summarizer's scene analysis.

### Character Progress

The world state agent can now automatically track character progress and provide proposals of updates to the character description and attributes.
