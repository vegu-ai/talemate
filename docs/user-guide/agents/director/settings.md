# Settings

## General

![Director agent settings](/talemate/img/0.29.0/director-general-settings.png)

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

## Long Term Memory

--8<-- "docs/snippets/tips.md:agent_long_term_memory_settings"

## Dynamic Actions

Dynamic actions are introduced in `0.28.0` and allow the director to generate a set of clickable choices for the player to choose from.

![Director agent dynamic actions settings](/talemate/img/0.29.0/director-dynamic-actions-settings.png)

##### Enable Dynamic Actions

If enabled the director will generate a set of clickable choices for the player to choose from.

##### Chance

The chance that the director will generate a set of dynamic actions when its the players turn.

This ranges from `0` to `1`. `0` means the director will never generate dynamic actions, `1` means the director will always generate dynamic actions.

##### Number of Actions

The number of actions to generate.

##### Never auto progress on action selection

If this is checked and you pick an action, the scene will NOT automatically pass the turn to the next actor.

##### Instructions

Allows you to provide extra specific instructions to director on how to generate the dynamic actions.

For example you could provide a list of actions to choose from, or a list of actions to avoid. Or specify that you always want a certain action to be included.

## Guide Scene

![Director agent guide scene settings](/talemate/img/0.29.0/director-guide-scene-settings.png)

The director can use the summarizer agent's scene analysis to guide characters and the narrator for the next generation, hopefully improving the quality of the generated content.

!!! danger "This may break dumber models"
    The guidance generated is inserted **after** the message history and **right before** the next generation. Some older models may struggle with this and generate incoherent responses.

##### Guide Actors

If enabled the director will guide the actors in the scene.

##### Guide Narrator

If enabled the director will guide the narrator in the scene.

##### Max. Guidance Length

The maximum number of tokens for the guidance. (e.g., how long should the guidance be).

## Auto Direction

A very experimental first attempt at giving the reigns to the director to direct the scene automatically.

Currently it can only instruct actors and the narrator, but different actions will be exposed in the future. This is very early in the development cycle and will likely go through substantial changes.

!!! note "Both overall and current intent need to be set for auto-direction to be available"
    If either the overall or current scene intention is not set, the auto-direction feature will not be available.

    ![Auto Direction Unavailable](/talemate/img/0.30.0/auto-direction-unavailable.png)

    Story and scene intentions are set in the [Scene Direction](/talemate/user-guide/world-editor/scene/direction) section of the World Editor.

![Director agent auto direction settings](/talemate/img/0.30.0/director-auto-direction-settings.png)

##### Enable Auto Direction

Turn auto direction on and off. 

!!! note "Auto progress needs to also be enabled"
    If auto direction is enabled, auto progress needs to be enabled as well.

    ![Auto Progress On](/talemate/img/0.30.0/auto-progress-on.png)
#### Natural flow

Will place strict limits on actor turns based on the provided constraints. That means regardless of what the director would like to do, the actor availability will always take precedence.

##### Max. Auto turns

Maximum turns the AI gets in succession (spread accross characters). When this limit is reached, the player will get a turn no matter what.

##### Max. Idle turns

The maximum number of turns a character can go without speaking before they are automatically given a turn by the director. (per character)

##### Max. Repeat Turns

The maximum number of times a character can go in succession without speaking before the director will force them to speak. (per character)


#### Instructions

##### Instruct Actors

Allow the director to instruct actors.

##### Instruct Narrator

Allow the director to instruct the narrator.

##### Instruct Frequency

Only pass on instructions to the actors or the narrator every N turns.

!!! note "Evaluation of the scene happens regardless"
    The director will evaluate the scene after each round regardless of the frequency. This setting merely controls how often the instructions are actually passed on.

##### Evaluate Scene Intention

Allows the director to evaluate the current scene phase and switch to a different scene type or set a new intention.

The number of turns between evaluations. (0 = NEVER)

!!! note "Recommended to leave at 0 (never)"
    This isn't really working well at this point, so recommended to leave at 0 (never)