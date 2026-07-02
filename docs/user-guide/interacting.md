# Interacting with the scene

There two main ways to interact with the scene, through dialogue and through scene actions.

## Your turn!

Whenever the input element at the bottom of the screen is available, it means it is your turn to do something.

By default the main player character will be selected, but you can act as any active character or even the narrator. [See the section on acting as another character](#acting-as-another-character).

![Dialogue input](/talemate/img/0.26.0/interacting-input-request.png)

Write a message and hit `enter` to send it to the scene.

### Separate actions and dialogue

When writing out your character's actions, spoken words should go into `"` and actions should be written in `*`. Talemate will automatically supply the other if you supply one.

That means if you enter `Elmer enters the room. "Hello everyone!"`, Talemate will automatically convert it to `*Elmer enters the room.* "Hello everyone!"`.

Likewise if you enter `*Elmer enters the room.* Hello everyone!`, Talemate will automatically convert it to `*Elmer enters the room.* "Hello everyone!"` as well.

If no markers are provided, Talemate will assume the text is spoken.

### Linebreaks are ok!

You can use linebreaks in your messages, to do so press `shift+enter` to create a new line.

### Acting as another character

Version `0.26` introduces a new `act-as` feature, which allows you to act as another character in the scene. This can be done by hitting the `tab` key while the input is focused. It will cycle through all active characters and finally the narrator before returning to the main player character.

![Dialogue input - act as other character](/talemate/img/0.26.0/interacting-input-act-as-character.png)

![Dialogue input - act as narrator](/talemate/img/0.26.0/interacting-input-act-as-narrator.png)

### Quick action

If you start a message with the `@` character you can have the AI generate the response based on what action you are taking. This is useful if you want to quickly generate a response without having to type out the full action and narration yourself.

![Quick action](/talemate/img/0.28.0/quick-action.png)

![Quick action generated text](/talemate/img/0.28.0/quick-action-generated-text.png)

This functionality was added in version `0.28.0`

### Player direction (# / ##)

!!! info "New in 0.37.0"

When [Autonomous Scene Direction](/talemate/user-guide/agents/director/scene-direction) is enabled, you can steer the director straight from the main input box by prefixing your input:

- **`#text`** — actively steer the scene without interacting with it. Your direction is your turn.
- **`##text`** — passively steer the scene while still getting your turn. Your direction is a side hint; the input box re-opens so you can take your turn normally.

See [Nudging the director from the main input](/talemate/user-guide/agents/director/scene-direction/#nudging-the-director-from-the-main-input) for the full behaviour, examples, and the Scene Direction requirement.

### Autocomplete

When typing out your action / dialogue, you can hit the `ctrl+enter` key combination to generate an autocompletion of your current text. 

!!! abstract "This works best if the client is in control of the prompt template"
    Success rate on this feature when the text generation api controls the prompt template is reduced, as Talemate cannot prefix the partial text.

    See [Prompt Templates](/talemate/user-guide/clients/prompt-templates) for more information.

!!! note "Generation length"
    The amount of text generated can be configured through the [Creator Agent Settings](/talemate/user-guide/agents/creator/settings)

## Auto progress

By default Talemate will give the next turn to the AI after you have sent a message, automatically progressing the scene.

You can turn this off by disabling the auto progress setting, either in the game settings or with the shortcut by the interaction input.

![auto progress off](/talemate/img/0.26.0/auto-progress-off.png)

## Scene Actions

![Tool bar](/talemate/img/0.26.0/getting-started-ui-element-tools.png)

A set of tools to help you interact with the scenario. Find out more about the various actions in the [Scene Tools](/talemate/user-guide/scenario-tools) section of the user guide.


## Message revision history

!!! info "New in 0.38.0"

Character and narrator messages (and context investigation results) keep a history of their previous versions. When a message has more than one version, a small paginator appears just above the message body so you can browse through them.

![Message revision paginator](/talemate/img/0.38.0/message-revision-paginator.png)

The paginator shows:

- **Left / right arrows** to step between versions.
- A **counter** (for example `2/3`) telling you which version you are viewing and how many exist in total.
- A **tag** describing where the version you are currently looking at came from:
    - **Original** -- the message as it was first generated.
    - **Regenerated** -- a version produced by regenerating the message.
    - **Revised** -- a version that the [Editor agent](/talemate/user-guide/agents/editor) automatically rewrote.
    - **Continued** -- a version created by continuing the message (see below).

The paginator only appears on the **most recent** message, and only once that message has more than one version.

!!! note "The version you view is the one that sticks"
    Whichever version you have selected in the paginator becomes the message's active text. That is the version saved with the scene, and the version the AI builds on when it continues the scene. Browsing to an earlier version and leaving it selected effectively rolls the message back to that version.

### How new versions are created

You don't add versions manually -- they accumulate as you work with a message:

- **Regenerating** the most recent AI message (see [Regenerate AI response](/talemate/user-guide/scenario-tools#material-refresh-regenerate-ai-response)) keeps the message in place and adds the new result as a version instead of replacing the old text. The previous version is still there to navigate back to. If the Editor agent automatically revises the regenerated text, both the raw **Regenerated** version and the **Revised** version are kept so you can pick either one.
- **Continuing** a message adds a **Continued** version that contains the original text plus the newly generated continuation. The version you continued from stays available, so you can step back if you don't like how the continuation turned out.

### Continuing a message

The most recent character or narrator message offers a **:material-fast-forward: Continue** action on its hover toolbar.

Clicking **Continue** generates more text and appends it to the message, recording the result as a new **Continued** version in the revision history. Narrator messages support the Continue action as well as character messages.

## Cancel Generation

Sometimes Talemate will be generating a response (or go through a chain of generations) and you want to cancel it. You can do this by hitting the **:material-stop-circle-outline:** button that will appear in the scene tools bar.

![Cancel generation](/talemate/img/0.27.0/cancel-generation.png)

!!! info
    While the generation is cancelled immediately, the current inference request will still be processed by the LLM backend. The Talemate UI will be responsive but the LLM api may require some time to finish the request.