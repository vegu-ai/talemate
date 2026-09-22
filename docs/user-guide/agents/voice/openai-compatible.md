# OpenAI Compatible

!!! info "Updated in 0.37.0"
    OpenAI Compatible is now a registry — add as many backends as you need, each with its own URL, key, model, and voice list. Voices are auto-fetched when the server supports it.

Use this backend to connect Talemate to any TTS service that implements the OpenAI speech API format. Each registered backend talks to one server, has its own settings, and contributes its own voices to the global voice library.

You can register multiple backends side by side — for example a local server and a hosted one, or two local servers running different models — and pick which ones are active from the [Enabled APIs](settings.md#enabled-apis) list.

## The OpenAI Compatible section

Open the Voice agent settings (**Settings → Connections → Agents → Voice**) and expand the **OpenAI Compatible** section. This is where the registry is managed — every backend you add gets its own :material-subdirectory-arrow-right: section nested underneath it.

![OpenAI Compatible registry section with several registered backends](/talemate/img/0.40.0/voice-openai-compatible-registry.png)

### Adding a backend

Type a display label into the field at the top of the registry section and press **:material-plus: Add backend**; Talemate derives an internal slug from the label and shows it below the field before you add. Once added, the new backend:

- Appears as its own section nested under **OpenAI Compatible**.
- Shows up as a checkbox in the Voice agent's [Enabled APIs](settings.md#enabled-apis) list, so you can turn it on or off without losing its configuration.
- Starts with sensible defaults you can edit in that section.

![Adding a backend to the OpenAI Compatible registry](/talemate/img/0.40.0/voice-openai-compatible-add-backend.png)

!!! note "Enable the backend in Enabled APIs"
    Adding a backend registers it but does not necessarily enable it for generation. Make sure the backend's checkbox is on under the Voice agent's [Enabled APIs](settings.md#enabled-apis) before you expect voices from it to be selectable.

### Removing or renaming a backend

Both controls live in the registry section, on each backend's entry: :material-pencil: renames it, :material-delete: removes it. Removing a backend also removes any voices that were registered under it from the voice library; renaming only changes the display label and does not invalidate stored voices.

!!! note
    Adding, renaming and removing take effect immediately — they change which backends exist rather than the value of a setting, so they are not part of the settings toolbar's **Save**. The fields inside a backend's section are.

## Per-backend settings

Each backend renders its own section nested under **OpenAI Compatible**.

![Per-backend OpenAI Compatible section](/talemate/img/0.40.0/voice-openai-compatible-backend-panel.png)

##### API Base URL

Base URL of the OpenAI-compatible TTS server, including the `/v1` path. Default: `http://localhost:8000/v1`.

The backend reports `API URL not set` and will not generate audio until this value is provided.

**Refresh voices** asks the running agent for the list, so it uses the last *saved* URL — save your changes before using it (the button is disabled while the settings page has unsaved edits).

##### API Key

API key for the server. Leave empty if the server does not require authentication — Talemate will send a placeholder value so the underlying OpenAI client accepts the request.

##### Model

Model identifier sent with each request. Some servers ignore this field and always use the model they have loaded; others route based on it. Check your server's documentation. Default: `tts-1`.

##### Response format

!!! info "New in 0.40.0"

The audio format Talemate asks the server for, sent as `response_format` with every request. Default: `mp3`. Leave the field empty to send `mp3`.

Talemate plays the audio in your browser, so the format must be one the browser can play. `mp3` plays in every browser and is the default of the OpenAI speech API, so most servers accept it. If your server needs something else, type the value its documentation names — the field takes any value, for example `wav` or `opus`. When the server refuses the value, Talemate shows the server's error message.

!!! warning "Raw pcm does not play"
    `pcm` is raw audio with no header, and the browser cannot play it: you hear nothing, and the browser console shows `Unable to decode audio data`. Some servers send `pcm` when no format is requested, which is why Talemate always requests one.

##### Voices endpoint (optional)

Override the path Talemate uses to list voices. Leave empty to probe a small set of common defaults (see [Refresh voices](#refresh-voices)). Accepts:

- A relative path (e.g. `audio/speech/voices`) — resolved against the API base URL.
- An absolute path (e.g. `/voices`) — anchored to the host root.
- A full URL (e.g. `https://example.com/list-voices`) — used as-is.

Use this when your server exposes a non-standard listing path.

##### Chunk size

Split text into chunks of this size before sending to the server. Smaller values increase responsiveness at the cost of losing context between chunks (inflection, pacing, etc.). `0` disables chunking. Default: `512`. Range: `0`–`2048`, in steps of `64`.

## Refresh voices

Each backend row in the registry section has a **:material-refresh: Refresh voices** button. Pressing it asks the server for the voices it can produce and merges the result into the global voice library, keyed under the backend's slug.

It runs against the configuration the agent is currently using, so the button is disabled while the settings page has unsaved changes — save first, then refresh.

The auto-fetcher tries the optional [Voices endpoint](#voices-endpoint-optional) first. If none is configured, it probes a few common compat-server paths in order:

| Path (relative to base URL) | Used by |
|---|---|
| `audio/voices` | KoboldCpp |
| `audio/speech/voices` | Speaches |
| `voices` | openedai-speech |

The first path that returns a valid voice list wins. Talemate accepts flat arrays (`["alloy", "echo"]`) and objects that hold the list under `voices`, `data`, `results` or `items` (`{"voices": [...]}`). Each entry is either a plain string or an object that carries the voice id as `id`, `voice_id`, `_id`, `name` or `voice`, plus an optional display name in `label`, `display_name` or `title`.

### Servers without a listing endpoint

Not every OpenAI-compatible server exposes a voice listing — OpenAI proper, for instance, does not. In that case **Refresh voices** comes back with zero entries and a status toast surfaces saying so. Add the voices you want manually in the [Voice Library](voice-library.md) (see below).

If your server uses a non-standard path, set [Voices endpoint](#voices-endpoint-optional) instead of relying on the probes.

## Adding voices manually

Voices that aren't auto-fetched can be added manually through the [Voice Library](voice-library.md):

![Adding an OpenAI Compatible voice in the Voice Library](/talemate/img/0.37.0/voice-openai-compatible-add-voice.png)

1. Open the Voice Library from the main application bar.
2. Click **:material-plus: New**.
3. Select the backend (each registered backend appears as its own provider option).
4. Fill in the voice:

    - **Label** — Display name shown in Talemate.
    - **Voice ID** — The voice identifier your server expects (e.g. `alloy`, or a custom voice name defined by the server).
    - **Tags** — Optional descriptive tags for organization and filtering.

Refer to your TTS server's documentation for supported voice identifiers. Once added, voices can be [assigned to characters](voice-library.md#character-voice-assignment) or used as the [narrator voice](settings.md#narrator-voice).

## Fish Audio

[Fish Audio](https://fish.audio) is a hosted TTS service with an OpenAI-compatible endpoint, so it runs as a backend here. You need a Fish Audio API key.

1. Add a backend, for example "Fish Audio".
2. Fill in its settings:

    | Setting | Value |
    |---|---|
    | API Base URL | `https://api.fish.audio/compat/v1` |
    | API Key | your Fish Audio API key |
    | Model | `fish-audio/s2.1-pro` |
    | Response format | `mp3` (the default) |
    | Voices endpoint | `https://api.fish.audio/model?self=true&page_size=100` |

3. Press **Save**, turn the backend on in [Enabled APIs](settings.md#enabled-apis), then press **Refresh voices**.

The voices endpoint lists the voices that your Fish Audio workspace owns, such as the ones you cloned or designed, up to 100 of them. They arrive in the Voice Library under the names they have on Fish Audio.

A voice from the Fish Voice Library that you do not own is not in that list. Copy its voice id from the Fish Voice Library and [add it manually](#adding-voices-manually), with the id as the **Voice ID**. OpenAI voice names do not work on Fish Audio: `nova`, `echo` and the other OpenAI preset names fail, and `alloy` plays an unrelated voice. Use a Fish voice id.

!!! warning "Keep the response format"
    When no format is requested, Fish Audio sends raw `pcm`, which the browser cannot play. Keep **Response format** at `mp3`.

## Auto-managed backends

Some Talemate clients can register a backend in this registry automatically when they have a TTS model loaded. The clearest example is [KoboldCpp](../../clients/types/koboldcpp.md#tts-auto-setup), which registers a backend pointing at its own URL and refreshes its voice list as soon as it sees a TTS model.

Auto-managed backends behave the same as manually-added ones once registered. If the underlying client later stops serving TTS (for example, KoboldCpp restarts without a TTS model), the backend's slug is dropped from Enabled APIs but its configuration is kept, so it re-enables cleanly the next time the server comes back.

The agent-level [Automatic Setup](settings.md#automatic-setup) toggle controls whether any client is allowed to register or toggle backends this way.

## Troubleshooting

**Connection errors**: Verify the base URL is correct (including the `/v1` path) and that the server is running and reachable from Talemate.

**Empty or silent audio**: Confirm your server has a TTS model loaded and that the voice ID you sent is valid for that model. Some servers fall back silently when given an unknown voice.

**No audio, and the browser console shows `Unable to decode audio data`**: The server sent audio in a format the browser cannot play, usually raw `pcm`. Set [Response format](#response-format) to `mp3`.

**A server that worked before now shows an error**: Since 0.40.0 Talemate asks for `mp3` where it used to send no format. Some servers sent `wav` in that case and make `mp3` only through ffmpeg, for example LocalAI or Chatterbox-TTS-Server. Without ffmpeg they refuse the request. Install ffmpeg for the server, or set [Response format](#response-format) to `wav`.

**Authentication errors**: If your server requires an API key, make sure it is set in the per-backend settings. Otherwise leave the field empty.

**Refresh voices returns nothing**: Either the server has no listing endpoint (add voices manually) or the listing path is non-standard (set [Voices endpoint](#voices-endpoint-optional) explicitly).

See also the general [TTS Troubleshooting Guide](troubleshooting.md).
