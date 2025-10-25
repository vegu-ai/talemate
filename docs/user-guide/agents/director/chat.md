# Director Chat

!!! example "Experimental"
    Currently experimental and may change substantially in the future.

Introduced in version 0.33.0 the director chat feature allows you interact with the director agent directly once a scene is loaded.

As part of the chat session the director can query for information as well as make changes to the scene.

!!! warning "Strong model recommended"
    In my personal testing I've found that while its possible to have a coherent chat session with weaker models, the experience is going to be
    significantly better with [reasoning enabled](/talemate/user-guide/clients/reasoning/) models past the 100B parameter mark.

    This may change as smaller models get stronger and your mileage may vary.

!!! info "Chat settings"
    You can customize various aspects of the director chat behavior in the [Director Chat settings](/talemate/user-guide/agents/director/settings/#director-chat), including response length, token budgets, and custom instructions.

## Accessing the director chat

Once a scene is loaded click the **:material-bullhorn:** director console icon in the top right corner of the screen.

![Director Console](/talemate/img/0.33.0/open-director-console.png)

![Director Console](/talemate/img/0.33.0/director-console-chat.png)

## Chat interface

The director chat provides a conversational interface where you can ask the director to perform various tasks, from querying information about your scene to making changes to characters, world entries, and progressing the story.

![Director Chat Interaction](/talemate/img/0.33.0/director-chat-interaction.png)

### What can you ask the director to do?

The director can help you with many tasks:

- Progress the story by generating new narration or dialogue
- Answer questions about your characters, world, or story details
- Create or modify characters, world entries, and story configuration
- Advance time in your story
- Manage game state variables (if your story uses them)

Simply describe what you want in natural language, and the director will figure out how to accomplish it.

### Viewing action details

When the director performs an action, you can expand it to see exactly what was done:

![Expanded Function Call](/talemate/img/0.33.0/director-chat-expanded-function-call.png)

This gives you full transparency into the changes being made to your scene.

## Chat modes

The director chat supports three different modes that control how the director behaves:

![Chat Mode Selection](/talemate/img/0.33.0/director-chat-mode.png)

!!! note
    Chat mode behavior is not guaranteed and depends heavily on the model's ability to follow instructions. Stronger models, especially those with reasoning capabilities, will respect these modes much more consistently than weaker models.

### Normal mode

The default mode where the director can freely discuss the story and reveal information. It will ask for clarification when needed and take a more conversational approach.

### Decisive mode

In this mode, the director acts more confidently on your instructions and avoids asking for clarifications unless strictly necessary. Use this when you trust the director to make the right decisions autonomously.

### No Spoilers mode

This mode prevents the director from revealing information that could spoil the story. The director will still make changes and answer questions, but will be careful not to discuss plot points or details that should remain hidden.

## Write action confirmation

By default, the director will ask for confirmation before performing actions that modify your scene (like progressing the story or making significant changes).

![Confirm On](/talemate/img/0.33.0/director-chat-confirm-on.png)

You can toggle this behavior to allow the director to act without confirmation:

![Confirm Off](/talemate/img/0.33.0/director-chat-confirm-off.png)

!!! tip
    Keep confirmation enabled when experimenting or when you want more control over changes. Disable it when you trust the director to act autonomously.

### Confirmation workflow example

When confirmation is enabled, the director will describe what it plans to do and wait for your approval:

![Confirmation Request](/talemate/img/0.33.0/director-chat-0001.png)

The confirmation dialog shows the instructions that will be sent and the expected result:

![Confirmation Dialog](/talemate/img/0.33.0/director-chat-0002.png)

Once confirmed, the action executes and new content is added to your scene:

![Action Approved](/talemate/img/0.33.0/director-chat-0003.png)

The director then analyzes the result and discusses what happened:

![Result Analysis](/talemate/img/0.33.0/director-chat-0004.png)

### Rejecting actions

You can also reject actions if you change your mind or want to revise your request:

![Action Rejection Request](/talemate/img/0.33.0/director-chat-reject-0001.png)

When rejected, the director acknowledges and waits for your next instruction:

![Action Rejected](/talemate/img/0.33.0/director-chat-reject-0002.png)

## Director personas

You can customize the director's personality and initial greeting by assigning a persona:

![Persona Selection](/talemate/img/0.33.0/director-chat-persona-0001.png)

Personas can completely change how the director presents itself and communicates with you:

![Persona Example](/talemate/img/0.33.0/director-chat-persona-0002.png)

To create or manage personas, select "Manage Personas" from the persona dropdown. You can define a custom description and initial chat message for each persona.