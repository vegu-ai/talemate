# Add an AI controlled character

Continuing from [adding a player character](/user-guide/howto/create-a-new-scene/create-player-character), we will now add an ai controlled character to the scene.

The steps are identical to adding a player character, with the exception that you will **not** toggle on the **Controlled by Player** switch.

Still in the :material-account-group: **Characters** tab, click on the :material-account-plus: **Create Character** button once more.

## Generate the ai controlled character

In the :material-account-plus: **Create New Character** dialog toggle on **Enable AI Generation**.

Then in the `AI Generation Instructions` field type in something like

> The other worldly housekeeper, with a dark, horrible secret. Appearing like a peculiar man, his true form is horrid beyond imagination and not yet revealed to Annabelle.
>
> You must include an attribute that describes his true form.

!!! tip
    Make sure you include intructions for everything that is important for the character, LLMs are not great at generating something interesting by themselves, they will often go down tropes and cliches. So be specific and detailed, but not long winded.

Then leave everything else as is and click the **Create Character** button.

![world-editor-create-npc-1](/talemate/img/0.26.0/world-editor-create-npc-1.png)

This will start the generation process, which may take a few moments and then the character will be added to the scene.

![world-editor-create-npc-2](/talemate/img/0.26.0/world-editor-create-npc-2.png)

## Refining the character

Unlike the player character, which is going to be controlled by a human being, its important to make sure the AI controlled character has all the information it needs to act in a way that is consistent with the scene and the story.

You should look over the `Attributes` and add / remove any that are not needed or missing.

There is more information on how to do this in the [Character Editor](/user-guide/world-editor/characters/index) section of the user guide.

However one thing that's always good to do is switch to :material-bullhorn: **Actor** tab and generate some dialogue instructions. These will guide the AI on how to act and talk.

On top of the `Acting instructions` field is a :material-auto-fix: **Generate** button, click on it to have the AI generate some instructions for you. You can then edit them as needed.

![world-editor-create-npc-3](/talemate/img/0.26.0/world-editor-create-npc-3.png)

For our example it generated

> Speak in a polite and cultured tone, punctuated with moments of chilling intensity.  Elias enjoys wordplay and subtle threats, often veiled as quaint observations. His voice should be soft and measured, like velvet over steel. When discussing souls or his true form, let a hint of primal hunger seep into his words, a guttural undercurrent betraying the monster beneath.

Which seems good enough for our purposes. 

!!! tip "Related Resources"
    - [Character Editor](/user-guide/world-editor/characters) - learn more about the character editor.
    - [Generation Settings](/user-guide/world-editor/generation-settings) - see how you can influence the AI's output.

## Save the scene

![world editor unsaved changes](/talemate/img/0.26.0/world-editor-unsaved-changes.png)

Once you are happy with the character, click on the :material-content-save: **Save** button to save the scene.