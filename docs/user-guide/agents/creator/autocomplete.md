# Autocomplete

Autocomplete uses the AI to continue whatever you have already started typing in a text field. Instead of generating content from scratch, it picks up from your partial text and writes the next part for you.

To trigger it, place your cursor in a supported field and press `ctrl+Enter` (or `cmd+Enter` on macOS). The generated text is appended to what you have already written.

!!! abstract "This works best if the client is in control of the prompt template"
    Success rate on this feature when the text generation API controls the prompt template is reduced, as Talemate cannot prefix the partial text.

    See [Prompt Templates](/talemate/user-guide/clients/prompt-templates) for more information.

## Steering the continuation with hints

You can guide the continuation by adding a short hint in curly braces `{...}` at the very end of your input before you trigger autocomplete. The hint is free-form, so you can describe whatever you want the AI to keep in mind: tone, beats to hit, sensory detail, who else is in the scene, and so on.

The brace block is only an instruction for the AI. When the suggestion is accepted, the `{...}` block is stripped out, so it never ends up in your actual text.

#### Example

Typing:

> `"Kaira!?" he yelled {dark corridor, no response}`

and pressing `ctrl+Enter` cues the AI on the tone and the beats you want, then continues the line. The `{dark corridor, no response}` part is removed once the suggestion is applied, leaving only the dialogue and its continuation.

Hints are controlled by the **Enable Hints** setting on the Creator agent, which is on by default. When the setting is turned off, a trailing `{...}` block is treated as ordinary text and sent as part of your input instead of being used as a hint. See [Settings](/talemate/user-guide/agents/creator/settings) for more.

## Redo and Undo

After a suggestion is applied, a small chip appears beside the field with two actions:

- **:material-refresh: Redo** — re-runs autocomplete from your original input (including any hint you added). This lets you keep trying for a different continuation without retyping anything.
- **:material-undo: Undo** — restores your original input and removes the applied suggestion.

The chip disappears once you start editing the field yourself.

## Where autocomplete is available

Autocomplete is available across many of Talemate's text fields, including:

- Your action and dialogue in the [main input](/talemate/user-guide/interacting/#autocomplete)
- Scene messages when you edit them in place — double-click a character, narrator, or context investigation message to edit it, then press `ctrl+Enter`
- Character [attributes](/talemate/user-guide/world-editor/characters/attributes) and [details](/talemate/user-guide/world-editor/characters/details)
- Character [description](/talemate/user-guide/world-editor/characters/description)
- The [scene introduction](/talemate/user-guide/world-editor/scene/outline)
- The character actor's **Add Dialogue Example** field (see [Actor management](/talemate/user-guide/world-editor/characters/actor))

The hint and Redo/Undo behaviour described above works the same way in every field that supports autocomplete.

You can adjust how long the generated suggestions are, per field type, on the Creator agent's [Settings](/talemate/user-guide/agents/creator/settings) page.
