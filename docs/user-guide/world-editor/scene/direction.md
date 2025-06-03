## Direction

Allows you to define an overall intention of the story as well as a more specific intention for the current scene.

This mostly used for the director's auto-direction feature, but may also affect the director's scene guidance actions.

!!! note "Both overall and current intent need to be set for auto-direction to be available"
    If either the overall or current scene intention is not set, the auto-direction feature will not be available.

    ![Auto Direction Unavailable](/talemate/img/0.30.0/auto-direction-unavailable.png)

### :material-compass: Overall Intention

The overall intention guides the director when making decisions that require a bigger picture context.

It should state what the goal and expections of the experience should be.

### :material-flag: Current Phase

Defines the type and intention of the current scene (phase).

#### Scene Type

The scene type defines general instructions for the type of scene that is currently being played.

This allows to differentiate between, for example `roleplay` or `combat` scenes, which may require different handling by the director.

!!! warning "Very early WIP"
    This is a very unfinished feature, so don't expect that you can plugin in some D&D style turn based combat rules into a scene type and have it work. Right now it will mostly affect the type of text that is generated and the pacing of the scene.

Re-usable scene types can be created in the [Template Editor](/talemate/user-guide/world-editor/templates)

#### Current Scene Intention

Should describe the specific intention (goal) of the current scene.

Currently this is free-form instructions and still under strong review as to figuree out what works well, but generally speaking here is a good guideline:

- Define the characters involved, their location and the general setting of the scene.
- The intention of the scene
- Define one or more goals that would cause the scene to be considered successful / complete.
- Any important notes about the scene that should be remembered.


