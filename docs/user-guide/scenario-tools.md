# Scene Tools

<!--- --8<-- [start:tools-ux] -->
![Tool bar](/img/0.26.0/getting-started-ui-element-tools.png)
<!--- --8<-- [end:tools-ux] -->

#### :material-refresh: Regenerate AI response

This will regenerate the most recent message, if it is an AI generated message.

!!! note "Keyboard modifiers"
    If you hold `ctrl` when clicking this button you will be prompted to supply some instructions for the
    regeneration. This can be useful to guide the AI in a certain direction.

    If you hold `ctrl+alt` when clicking this button you will be prompted to supply some instructions for the
    regeneration while keeping the original message as context. This is useful for rewrites.

#### :material-nuke: Regenerate AI Response (nuke option)

This will regenerate the most recent message, if it is an AI generated message, but with a higher temperature and repetition penalties applied, which can lead to more creative responses. Use this to break out of repetitive loops.

!!! note "Keyboard modifiers"
    If you hold `ctrl` when clicking this button you will be prompted to supply some instructions for the
    regeneration. This can be useful to guide the AI in a certain direction.

    If you hold `ctrl+alt` when clicking this button you will be prompted to supply some instructions for the
    regeneration while keeping the original message as context. This is useful for rewrites.

### :material-account-voice: Actor Actions

Will open a context menu that allows you to have the actor perform actions.

![Actor Actions](/img/0.26.0/scene-tool-character-actions.png)

!!! info "Recommendation"
    Turn auto progress off if you want full control and use these actions to guide the scene.

    ![auto progress off](/img/0.26.0/auto-progress-off.png)


#### :material-bullhorn: Talk with direction - Specific Character

Will prompt you for a direction and then have the actor will generate dialogue and actions based on that direction.

Depending on what the `Actor Direction Mode` setting in the [Director Agent Settings](/user-guide/agents/director) the direction will either be given as an instruction or as inner monologue.

Regardless of mode you should write your instruction so it completets the following sentence: `I want you to ...`

Some examples:

- `be angry at the other character`
- `be annoyed at the situation and storm off`

#### :material-comment-account-outline: Talk - Specific Character

Will cause the character to generate dialogue and actions based on the current scene state.

#### :material-comment-text-outline: Talk

Automatically picks a character to generate dialogue and actions based on the current scene state.

### :material-script-text: Narrator Actions

Will open a context menu that allows you to have the narrator perform actions.

![Narrator Actions](/img/0.26.0/scene-tool-narrator-actions.png)


#### :material-script-text-play: Progress Story

Generates narrative text based on the current scene state, moving the story forward.

#### :material-script-text-play: Progress Story with Direction

Will prompt you for a direction and then have the narrator generate narrative text based on that direction.

#### :material-waves: Narrate Environment

A special type of narration that aims to narrate the environment, focusing on visuals, sounds and other sensory information.

#### :material-crystal-ball: Query

Will prompt you for a question and then have the narrator generate narrative text based on that question.

#### :material-table-headers-eye: Look at Scene

Will narrate the current state of the scene, without progressing the story.

#### :material-eye: Look at Character

Will narrate the current state of a character, without progressing the story.

### :material-clock: Advance time

Opens a context menu with options to advance time in the scene, ranging from 5 minutes to 10 years.


By default the [Narrator Agent](/user-guide/agents/narrator) will narrate the time jump, but you can disable this in the [Narrator Agent Settings](/user-guide/agents/narrator).


!!! note "Summarization"
    Whenever time is advanced, the scene state will be updated, and the next message will trigger the [Summarization Agent](/user-guide/agents/summarization) to summarize any events before the time jump.


### :material-earth: World State Actions

##### Automatic State Updates

Allows you to quickly set up tracked character and world states. 

!!! info "What is a tracked state?"

    --8<-- "docs/user-guide/tracking-a-state.md:what-is-a-tracked-state"

Please refer to the [World State](/user-guide/world-state) section for more information on how set up custom states to track.
<!--- --8<-- [start:quick-apply-favorite-state] -->
Any favorited state will be shown in the :material-earth: world state context menu. *Your list may be different than the one shown here, depending on what you have favorited.*

![World State Actions](/img/0.26.0/scene-tool-world-state-actions.png)

Clicking on any item in `Autoamtic State Updates` will generate the current state and keep it tracked until it is removed.

A tracked state will have a checkmark next to it.

![World State Tracked](/img/0.26.0/scene-tool-world-state-applied.png)
<!--- --8<-- [end:quick-apply-favorite-state] -->

#### :material-book-open-page-variant: Open the world state manager

Will open the world state template editor, where you can view and edit your available world states templates.

#### :material-refresh: Update the world state

Will cause a regeneration of the world state.

!!! info "Does not run state re-inforcement"
    Currently, this will not re-inforce the state of the world or characters, it will only update the world state context that is displayed in the left panel under the :material-earth: `World` section.

### :material-puzzle-edit: Creative Actions

![Creative Actions](/img/0.26.0/scene-tool-creative-actions.png)

#### :material-exit-run: Take character out of scene

![Take character out of scene](/img/0.26.0/scene-tool-creative-deactivate-character.png)

Will remove the character from the scene. This will **NOT** remove the character from the character list, it will only remove them from the current scene, making the actor no longer partake in the scene.

If the current narration and scene progress has not yet indicated the character has left, you will be prompted for a reason, which will be used to narrate the characters exit. If you provide no reason it will be automatically narrated.

![Take character out of scene reason](/img/0.26.0/scene-tool-creative-deactivate-character-narration.png)

!!! info "Keyboard modifiers"
    You can hold the `ctrl` key when clicking this action to disable the automatic narration altogether.

#### :material-human-greeting: Call character to scene

![Call character to scene](/img/0.26.0/scene-tool-creative-activate-character.png)

Will add the character back to the scene. 

If the current narration and scene progress has not yet indicated the character has entered, you will be prompted for a reason, which will be used to narrate the characters entrance. If you provide no reason it will be automatically narrated.

![Call character to scene reason](/img/0.26.0/scene-tool-creative-activate-character-narration.png)

!!! info "Keyboard modifiers"
    You can hold the `ctrl` key when clicking this action to disable the automatic narration altogether.

#### :material-account-plus: Introduce new character - Directed

Will prompt you for a name and a description of the character, and then generate it and add it to the scene.

![Prompt for character name](/img/0.26.0/scene-tool-creative-add-character-1.png)

![Prompt for character description](/img/0.26.0/scene-tool-creative-add-character-2.png)

The AI will be prompted to generate a character based on the information you provide. THis may take a moment.

Once it is done, narrative text will be generated to introduce the character.

![Character introduction](/img/0.26.0/scene-tool-creative-add-character-3.png)

And the character will now be part of the scene and can be interacted with.

![Character added to scene](/img/0.26.0/scene-tool-creative-add-character-4.png)

#### :material-human-greeting: Introduce new character - From context

If narration or dialogue has been generated that references a character that has not yet been created, you can use this action to introduce them and make them real and interactable.

![World State Context](/img/0.26.0/scene-tool-creative-introduce-2.png)

The AI will be prompted to generate a character based on what is known about them in the context.

Once it is done, the character will now be part of the scene and can be interacted with.

![Character added to scene](/img/0.26.0/scene-tool-creative-add-character-4.png)

!!! info "Indicator"
    The availability of this is directly tied to the world state on the left panel. 

    ![World State Context](/img/0.26.0/scene-tool-creative-introduce-1.png)

    The character needs to appear in the list of characters in the world state context. 

    ![Indicator](/img/0.26.0/scene-tool-creative-introduce-indicator.png) a little human icon will appear next to the :material-puzzle-edit: `Creative Actions` button if there is a character that can be introduced.


### :material-image-frame: Visualizer

!!! info "Availability"
    If the visualization menu is greyed out, it means that the [Visualizer Agent](/user-guide/agents/visualizer) is not enabled or ready.

    Please refer to the [Visualizer Agent](/user-guide/agents/visualizer) section for more information on how to set it up.

#### :material-image-filter-hdr: Visualize Environment

Will generate a stable diffusion prompt and send it to the visualizer agent to generate an image of the current scene.

The generated image can be viewed by clicking on the :material-image-multiple-outline: **New images** button on the top right of the screen.

![Images ready](../../../img/0.20.0/visualze-new-images.png)

!!! note "Early Development"
    At this early stage of development, all you can do with this generated image is to view it. Future versions will allow you to set it as the background image for the scene.

#### :material-brush: Visualize Character

Will generate a stable diffusion prompt and send it to the visualizer agent to generate an image of the selected character.

The generated image can be viewed by clicking on the :material-image-multiple-outline: **New images** button on the top right of the screen.

!!! info
    This will take longer than the environment visualization, as it will do multiple inquisition prompts to find out more about the character and their current state.

    If the character does not have a cover image set the generated image will automatically be set as the cover image.

### :material-content-save: Saving

Context menu that will provide you with `Save` and `Save As` options.