## Direction

Allows you to define an overall intention of the story as well as a more specific intention for the current scene.

These intentions are used by:

- The [Narrator](/talemate/user-guide/agents/narrator/) agent, which incorporates them into its prompts to generate narrative that aligns with your story goals
- The director's [Autonomous Scene Direction](/talemate/user-guide/agents/director/scene-direction) feature
- The director's scene guidance actions

!!! note "Both overall and current intent need to be set for scene direction to be available"
    If either the overall or current scene intention is not set, the Autonomous Scene Direction feature will not be available.

    ![Scene Direction Unavailable](/talemate/img/0.30.0/auto-direction-unavailable.png)

### :material-bullhorn: Director Instructions

Scene-specific instructions that are available to the director during both automated scene direction and director chat. Use this field to provide guidance tailored to this particular story or scene, such as:

- Genre-specific guidance (e.g., "maintain a noir atmosphere", "keep dialogue witty and fast-paced")
- Story-specific rules or constraints
- Tone and style preferences for this experience
- Any special handling instructions for this scene

These instructions are stored with the scene, so different stories can have different director behaviors.

!!! tip "Global vs Scene-Specific Instructions"
    The Director agent settings also has a **Custom Instructions** field. That field applies globally to all scenes. Use **Director Instructions** here for story-specific guidance that should only apply to this scene.

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


