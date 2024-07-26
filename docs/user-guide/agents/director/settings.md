# Settings

![Director agent settings](/talemate/img/0.26.0/director-agent-settings.png)

##### Direct

If enabled the director will attempt to direct the scene.

This is currently only relevant if the scene loaded comes with a script file. For the scenes that are currently included that is only true for the **Simulation Suite**.

###### Turns

How many turns to wait before the director makes a decision.

##### Direct Scene

If enabled the director will attempt to direct the scene through narration.

##### Direct Actors

Enables the director to direct the actors in the scene.

Right now this is only triggered manually by the player when the players uses the `Direct actor` toolset from the [Scenario tools](/talemate/user-guide/scenario-tools).

###### Actor Direction Mode

When an actor is given a direction, how is it to be injected into the context

- `Direction`
- `Inner Monologue`

If `Direction` is selected, the actor will be given the direction as a direct instruction, by the director.

If `Inner Monologue` is selected, the actor will be given the direction as a thought.