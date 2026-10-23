<!-- Generated from the changelog build. Do not edit by hand. -->

# Upgrading

Each release below lists the changes that may need something from you when you update: a setting to review, a file to back up, or a value that now means something else. Releases without such changes are not listed. The newest release comes first.

## 0.40.0

### Scene Revisions (breaking change)

Upgrading from 0.39.0 starts revisions from a current save when you first load or save it, in `<project>/data.db`. The new system ignores `<project>/changelog/` and leaves it untouched; you can delete that old directory by hand. Earlier revisions are not converted.

### OpenAI Clients

Review saved OpenAI settings after upgrading. GPT-5 and GPT-6 models keep Reasoning on; enable it for o-series models if needed. Sampling controls start off. For o1-mini or o1-preview, turn Send System Message off; turn Stream off if unavailable, and choose max_tokens for servers requiring it. Save your settings.

### OpenRouter Reasoning

The client no longer sends a reasoning budget. With Reasoning on it sends your Reasoning Effort, or asks the model to think at its own default effort; with Reasoning off it sends nothing, and models that always think use their provider's default. A saved Reasoning Tokens number from 0.39.0 no longer controls how much the model thinks: it now means Extra Completion Tokens. If you used it to control thinking, choose a Reasoning Effort instead.

### Compatible Voice Servers

OpenAI-compatible voice backends now request MP3 by default. Select WAV under Response format if your server cannot produce MP3.

### Shared Worlds

Back up older shared worlds before upgrading. Missing shared entries can be recovered from a linked scene only until 0.40 first writes that world, so load the scene holding them first. Entries intentionally removed in an older version may also return. Recover overwritten text from older revisions in 0.39.0 before upgrading, or from a backup of `<project>/changelog/`.

### Scene Context Format

The scene context format (Screenplay, Chat, Narrative, AI Aware) moved from the Conversation agent's Generation settings to the Summarizer agent's Scene History settings. A format set on the Conversation agent in an earlier version is not carried over: the format starts at Screenplay, so set it again in Scene History if you used another one.

### Scene Backgrounds

Auto Backdrop for scene backgrounds is removed: backgrounds generated for the story always become the backdrop, and Visual Library backgrounds only go to the library. Backgrounds already attached to messages keep showing.

### Visual Styles

Shipped visual styles moved into Talemate's template group. Back up edits to templates/world-state/visual-styles.yaml before updating; if they block the update, stash them or restore the tracked file.

## 0.37.0

- Default frontend port changed from 8080 to 8082. Update any bookmarks or reverse-proxy configs that pointed at `localhost:8080`. To keep the old port, set `TALEMATE_FRONTEND_PORT=8080` before launching.

- Docker compose variable `FRONTEND_PORT` renamed to `TALEMATE_FRONTEND_PORT`. If you had `FRONTEND_PORT` set in a `.env` file or your shell, rename it. The new variable controls both the published host port and the port uvicorn binds inside the container.

- Docker compose variable `BACKEND_PORT` renamed to `TALEMATE_BACKEND_PORT`. Same migration as above — rename in any `.env` files or shell environments. The new variable controls both the published host port and the port uvicorn binds inside the container.

## 0.32.0

- XTTS2 TTS support has been removed. Switch to one of the new local backends (F5-TTS, Chatterbox, Kokoro) or a remote backend (ElevenLabs, Google Gemini-TTS, OpenAI) via the voice library.
