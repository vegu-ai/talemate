# Client Configuration

Clients are configured on the **Clients** page of the application settings, at **Settings → Connections → Clients**. The page lists every client you have on the left and shows the editor for the selected one on the right.

!!! info "Changed in 0.40.0"
    Client configuration moved out of the pop-up dialog and onto the Clients settings page. What used to be tabs are now collapsible sections in the client editor, and nothing is applied until you press **Save** in the settings toolbar.

## Opening the Clients page

Click the **:material-cog: Settings** tab in the top navigation — the settings view opens on **Connections → Clients**, which is its first page.

The buttons on the client list in the right hand sidebar take you to the same place:

- The :material-cogs: cogwheels on a client row open the Clients page with that client selected.
- **:material-plus-box: Add client** opens the Clients page with the client type menu open.

![Clients settings page with the client list and the editor](/talemate/img/0.40.0/client-configuration-page.png)

## The client list

Clients are listed by name, each with a status dot (green when the client is ready, orange for a warning, red for an error, grey when the client is disabled, and a spinner while it is busy) and, underneath, its client type and the model it reports.

A client marked with an **Unsaved** chip has no running counterpart yet — you just added (or renamed) it here and it does not exist until you save. The chip disappears once the saved client connects and starts reporting its status.

**:material-plus-box: Add client** below the list opens the **Client type** menu. Picking a type immediately creates a client with that type's default settings, gives it a name and selects it so you can configure it. Experimental client types are marked with a :material-flask: icon.

## The client editor

The header above the editor carries the name of the selected client and two actions:

- **:material-transit-connection-variant: Assign to all agents** — makes every agent that generates with an LLM client use this client. Like everything else on this page it is applied when you save. The button is disabled while the client itself is disabled; enable the client first with the :material-power-standby: button on its row in the sidebar.
- **:material-close-circle-outline: Remove** — asks for confirmation, then drops the client. It is disconnected and purged when you save.

Renaming a client (the **Client Name** field in the **General** section) carries through to the agents that use it, and removing one clears the assignment so those agents get a client assigned again on save.

![Client editor with its sections](/talemate/img/0.40.0/client-configuration-editor.png)

### Sections

The editor is a stack of collapsible sections. **General** is open when you select a client, and you can have as many of the others open at the same time as you like. Which sections appear depends on the client type.

| Section | Purpose |
|---|---|
| **:material-tune: General** | Client type, name, API URL / key, model, context length, prompt template (for clients where Talemate builds the prompt). |
| **:material-account-lock-open: Coercion** | Prefill text used to enforce compliance. Only shown for clients that can be coerced. |
| **:material-cog-outline: Advanced** | Inference Presets, Structured Data Format, [Section Format](section-format.md), [Response Length Enforcement](response-length.md), Prompt Caching, [Prompt Deduplication](../prompts/deduplication.md), [Rate Limit](rate-limiting.md), and [Auto Retry](auto-retry.md). |
| **:material-brain: Reasoning** | [Reasoning model support](reasoning.md) settings. |
| **:material-text-box: System Prompts** | Per-client [system prompt overrides](../app-settings/system-prompts.md). |

Some client types add sections of their own — for example **Endpoint Override** on remote clients, **Concurrency** on clients that support [concurrent requests](concurrent-requests.md), **Vision** on clients that can analyze images, or **Parameters** on the [OpenRouter](types/openrouter.md) and [OpenAI compatible](types/openai-compatible.md) clients.

### Client Type

The **Client Type** field in the **General** section is read-only. The type is picked when the client is added and cannot be changed afterwards — to switch to a different backend, add a new client of that type and remove the old one.

### Advanced section

The Advanced section contains settings that you usually only need to touch once per client:

- **Inference Presets** — selects which [preset group](presets.md) is used for generation parameters.
- **Structured Data Format** — whether structured responses (function calls, data management) are formatted as JSON or YAML. Leave set to *Talemate decides* to use the application default.
- **Section Format** — whether prompt sections are rendered as Markdown headings or XML tags. See [Section Format](section-format.md).
- **Response Length Enforcement** — how the response length is communicated to the model. See [Response Length Enforcement](response-length.md).
- **Optimize for Prompt Caching** — moves volatile context after the scene history to improve cache hit rates. See [Volatile Context Placement](../prompts/volatile-context-placement.md).
- **Deduplicate Prompts** — strips near-duplicate lines from rendered prompts. Off by default. See [Prompt Deduplication](../prompts/deduplication.md).
- **Rate Limit** — caps requests per minute. See [Rate Limiting](rate-limiting.md).
- **Auto Retry** — automatic retries on empty or rate-limited responses before you are notified. See [Auto Retry](auto-retry.md).

### Shared API keys

Client types that authenticate with an application-wide API key (OpenAI, Anthropic, OpenRouter and the other hosted APIs) show that key as an outlined card in the **General** section, titled after the provider and tagged **Configured** or **Required**. The card starts expanded while no key is set and collapsed once there is one — the :material-chevron-down: chevron opens it again.

It is the same key as the one on the [API Keys page](../app-settings/application.md) and it is shared by every client of that type, so changing it here changes it for all of them.

## Saving

Nothing on this page is applied while you edit. Adding, removing, renaming and every field change only touch a working copy of your configuration until you use the toolbar at the top of the settings view:

- **:material-check-circle-outline: Save** writes the configuration and applies it — new clients are connected, removed clients are disconnected, and changed clients are reconfigured. The same Save covers every settings page, so unsaved changes elsewhere are written along with it.
- **:material-undo: Discard** appears while there are unsaved changes and throws them away, reloading the stored configuration.
- **Unsaved changes.** next to the buttons is the reminder that you have edits pending.

A client needs a name and a context length greater than zero. If one does not have them, Save shows the problem in the toolbar, selects the offending client, and sends nothing.

!!! note "Changed outside this view"
    If your configuration is changed somewhere else — another browser window, or the [help agent](../agents/help/index.md) — while you have unsaved edits here, the toolbar shows a **Changed outside this view — saving overwrites** warning. **Discard** loads the newer configuration, **Save** overwrites it with what you have on screen.
