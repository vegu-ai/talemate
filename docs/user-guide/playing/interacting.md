# Interacting with the scene

There two main ways to interact with the scene, through dialogue and through scene actions.

## Your turn!

Whenever the input element at the bottom of the screen is available, it means it is your turn to do something.

By default the main player character will be selected, but you can act as any active character or even the narrator. [See the section on acting as another character](#acting-as-another-character).

![Dialogue input](/img/0.26.0/interacting-input-request.png)

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

![Dialogue input - act as other character](/img/0.26.0/interacting-input-act-as-character.png)

![Dialogue input - act as narrator](/img/0.26.0/interacting-input-act-as-narrator.png)

### Autocomplete

When typing out your action / dialogue, you can hit the `ctrl+enter` key combination to generate an autocompletion of your current text. 

!!! abstract "This works best if the client is in control of the prompt template"
    Success rate on this feature when the text generation api controls the prompt template is reduced, as Talemate cannot prefix the partial text.

    See [Prompt Templates](/user-guide/clients/prompt-templates) for more information.

## Auto progress

By default Talemate will give the next turn to the AI after you have sent a message, automatically progressing the scene.

You can turn this off by disabling the auto progress setting, either in the game settings or with the shortcut by the interaction input.

![auto progress off](/img/0.26.0/auto-progress-off.png)

## Scene Actions

![Tool bar](/img/0.26.0/getting-started-ui-element-tools.png)

A set of tools to help you interact with the scenario. Find out more about the various actions in the [Scene Tools](/user-guide/playing/scenario-tools) section of the user guide.
