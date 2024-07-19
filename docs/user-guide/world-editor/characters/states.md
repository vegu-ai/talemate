# Tracked states

!!! info "What is a tracked state?"

    --8<-- "docs/talemate/user-guide/tracking-a-state.md:what-is-a-tracked-state"
    
## Setting up a new state
In the :material-account-group: **Character** editor select the character you want to add a new state to. 

![Select character](/talemate/img/0.26.0/world-editor-character-select.png)

<!-- --8<-- [start:new-state] -->
Then select the :material-image-auto-adjust: **States** tab.

![Character states tab](/talemate/img/0.26.0/world-editor-character-state-new-1.png)

Next find the `New state` input field in the upper right and enter the name of the new state.

!!! info
    This should either be a descriptive name like "Mental State" or phrased as a question like "What is Kaira's mental state?"
    In our own testing we found questions generally work better.

For this example we will use "What is Kaira's mental state?".

![New state input](/talemate/img/0.26.0/world-editor-character-state-new-2.png)

Hit `enter` to create the new state.

This will not only add the state, but also begin immediately generating its current value.

Once the generation is complete, you will see the new state in the list of states.

![New state generated](/talemate/img/0.26.0/world-editor-character-state-new-3.png)
<!-- --8<-- [end:new-state] -->

## Editing the state properties

### Re-inforce / Update detail every `N` turns

This setting lets you control how many game rounds need to pass before this state is re-evaluated.

By default it will be `10` turns, but you can change this to any number you like.

### Context Attachment Method

--8<-- "docs/talemate/user-guide/tracking-a-state.md:context-attachment-method"

### Additional Instructions

Allows you to specify extra instructions to give to the AI for the generation of this state.

For our example, if we wanted it to particularly track how scared Kaira is, we could add:

`Track how scared Kaira is. Is she calm or panicking?`

![Generation instructions](/talemate/img/0.26.0/world-editor-character-state-new-4.png)

Then click the :material-refresh: **Refresh State** button to re-generate the state with the new instructions.

### :material-refresh: Refresh State

Will immediately re-generate the state with the current settings.

### :material-backup-restore: Reset State

Will remove all previous generation data and start fresh, generating a new value for the state.

!!! note "Sometimes states get messy"
    Since the pervious value of the state is used - in combination with the scene progression since - to generate the new value, sometimes it can get a bit messy. It only takes one bad generation from the AI to start spiraling out of control. When you notice that the state has a nonsensical value, it's best to reset it.