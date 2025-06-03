# Inference Configuration

!!! abstract "Work in progress"
    Letting users manipulate the inference parameters for text generation is currently a work in progress and expect
    changes to this system in the future.

If you wish to alter the inference parameters sent with the generation requests for text-generation you can do in the settings interface.

![open settings](/talemate/img/0.26.0/open-settings.png)

Navigate to the :material-tune: **Presets** tab then select the :material-matrix: **Inference** tab.

![selected preset](/talemate/img/0.30.0/inference-presets-1.png)

!!! warning
    Not all clients support all parameters, and generally it is assumed that the client implementation handles the parameters in a sane way, especially if values are passed for all of them. All presets are used and will be selected depending on the action the agent is performing. If you don't know what these mean, it is recommended to leave them as they are.

## All presets are used

Its important to understand that all presets are used, depending on which action is performed by an agent.

!!! abstract "Work in progress"
    This is currently transitioning to a better system. Main goal was to expose the parameters to the user, and make it somewhat understandable.

    We've tried to categorize them in a sensible way, but there is probably still work that needs to be done in this area. A lot of them can probably be merged into a single category.

## Categories

### Analytical

Used when the agent is performing some kind of analysis, that requires accurate and truthful information.

### Conversation

Used for generating actor responses in a conversation.

### Creative

Used for content generation (Generating characters, details etc.) and narration.

### Creative instruction

Similar to `Creative` but will be used when the agent is expected to follow the instruction very closely. This is one of the areas that needs more work and can probably be merged with one of the other categories.

### Deterministic

Used when the agent is expected to follow the instruction very closely and we want to ensure that the output is deterministic.

### Scene Direction

Used mostly for the director when directing the scene flow. Need to be creative but also follow the instruction closely.

### Summarization

Used for summarizing the scene progress into narrative text.


## Preset Groups

Initially there is a `Default` group in which the presets are edited, but if you want you can create additional groups to create - for example - model / client specific presets.

To add a new group, type the title in to the **New Group Name** field in the upper right and press `Enter`.

![new group](/talemate/img/0.30.0/inference-presets-custom-group-1.png)


The new group will be added and automatically selected for editing.

![new group](/talemate/img/0.30.0/inference-presets-custom-group-2.png)

Once you have adjusted the presets to your liking you can save the group by clicking the :material-content-save: **Save** button.

### Setting the group for the client

In the client listing find the :material-tune: selected preset and click it to expand the meny containing the groups.

![select group](/talemate/img/0.30.0/inference-preset-group-apply.png)

![select group](/talemate/img/0.30.0/inference-preset-group-applied.png)
