# Tracked states

!!! info "What is a tracked state?"

    --8<-- "docs/talemate/user-guide/tracking-a-state.md:what-is-a-tracked-state"

## Setting up a new state
In the :material-earth: **World** editor, in the left panel, click the :material-image-auto-adjust: **New State Reinforcement** button.

<!-- --8<-- [start:new-state] -->
![World states tab](/talemate/img/0.26.0/world-editor-world-state-new-1.png)

### Question or State description

This should be a question or a descriptive name for the state you want to track.

For this example we will use `What is the state of the Starlight Nomad?` - We want to track the state of the ship.

!!! info
    This should either be a descriptive name like "Ship state" or phrased as a question like "What is the state of the Starlight Nomad?"

    In our own testing we found questions generally work better.

### Pre-specify the state value (optional)

As you type in the question, the next field's label will automatically sync with the question you are asking. This is the field where the state value will end up. You can pre-specify the value here if you want to.

### Re-inforce / Update detail every `N` turns

This setting lets you control how many game rounds need to pass before this state is re-evaluated.

By default it will be `10` turns, but you can change this to any number you like.

### Context Attachment Method

--8<-- "docs/talemate/user-guide/tracking-a-state.md:context-attachment-method"

For this example, we always want to know the state of the ship, so we will set it to `All context`.

### Additional Instructions

Allows you to specify extra instructions to give to the AI for the generation of this state.

For our example, we want to know the state of the ship, so we could add:

`Is the ship functional? Keep track of changes to the Starlight Nomad as an environment.`

### Create the state

Click :material-text-box-plus: **Create** to create the new state.

This will create the state, but also immediately generate its current value.

This may take a moment, once it's done you will see the new state in the list of states and the current value in the world state.


![Generated state](/talemate/img/0.26.0/world-editor-world-state-new-2.png)

!!! note "Tracked world states consist of the state and the world info"

    ![Generated state](/talemate/img/0.26.0/world-editor-world-list.png)

    It has generated both a state entry (controlling how the state is tracked) and a world info entry holding the current value of the state.
<!-- --8<-- [end:new-state] -->
## Managing the state

### :material-refresh: Reset State Reinforcement

Will remove all previous generation data and start fresh, generating a new value for the state.

!!! note "Sometimes states get messy"
    Since the pervious value of the state is used - in combination with the scene progression since - to generate the new value, sometimes it can get a bit messy. It only takes one bad generation from the AI to start spiraling out of control. When you notice that the state has a nonsensical value, it's best to reset it.
