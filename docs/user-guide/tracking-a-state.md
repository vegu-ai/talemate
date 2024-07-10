# Tracked states


## What is a tracked state?
<!--- --8<-- [start:what-is-a-tracked-state] -->
Tracked states occassionally re-inforce the state of the world or a character. This re-inforcement is kept in the context sent to the AI during generation, giving it a better understanding about the current truth of the world.

Some examples could be, tracking a characters physical state, time of day, or the current location of a character.
<!--- --8<-- [end:what-is-a-tracked-state] -->
## Track a character's state

### Character states are managed in the character editor

The fastest way to get to the character editor for a specific character, is to click on the character's name in the world state.

![track-a-state-character-1](/img/0.26.0/track-a-state-character-1.png)

Click the :material-book-open-page-variant: **Manage Character** button.

Then follow the instructions at [Tracking a character state](/user-guide/world-editor/characters/states).

### Inspect the state value

Once the state has been generated, you can see the current value in the world state entry for the character.

![track-a-state-character-2](/img/0.26.0/track-a-state-character-state-inspect.png)

## Track a world state

When tracking a world state, we mean the state of anything that is not a character. This could be the time of day, the current location, or the state of an object.

### World states are managed in the world editor

In the top navigation bar, click :material-earth-box: **World Editor** tab.

Then follow the instructions at [Tracking a world state](/user-guide/world-editor/world/states).

## Quickly apply often tracked states via templates

--8<-- "docs/user-guide/scenario-tools.md:tools-ux"

--8<-- "docs/user-guide/scenario-tools.md:quick-apply-favorite-state"

## Context Attachment Method
<!-- --8<-- [start:context-attachment-method] -->
The state's `Context Attachment Method` determines how the state is attached to the context.

##### Passive

The state is only included in context through relevancy, handled by the [Memory Agent](/user-guide/agents/memory/).

##### Sequential

The state is inserted into the context as part of the scene progression. So when it's re-evaluated, it will be at the bottom of the context.

This is the default for character states.

##### Conversation Context

The state is ALWAYS inserted as an important part of the context during the character's dialogue generation. This is useful for states that are important for the AI to know about during conversation.

##### All Context

The state is always included in the context, no matter what. This is useful for states that are important for the AI to know about at all times.
<!-- --8<-- [end:context-attachment-method] -->