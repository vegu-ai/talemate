# Create an empty scene

To start a new, empty scene, go to the :material-home: **Home** screen and click on the :material-plus: **Create** button in the left sidebar.

![Create empty scene](/img/0.26.0/create-new-scene.png)

After a moment of loading you will be taken to the new scene and `creative` mode will be enabled. In `creative` mode normal scene progression is suspended and imput in the scene view will be for command execution only. (covered elsewhere, ignore for now)

## Create the outline for the scene

The outline describes the scene and its contents. Its where you manage the title, description and introductory text shown to the user when they first enter the scene.

Click on the :material-earth-box: **World Editor** to open the world editor.

In the world editor the :material-script: **Scene** tab should be selected, if not, click on it.

![World editor scene outline 1](/img/0.26.0/world-editor-scene-outline-1.png)

### Title

The scene title as it will be shown to the user. Currently this should be `New Scenario`

Lets put in a more descriptive title, for example `The forgotten house`.

### Content Context

In Talemate the `Content Context` is used to set the tone and expectation of the generated content, it can strongly influence the AI's responses.

You can type in a value or pick something from the list. 

!!! note
    What is available in the list is controlled in the :material-cog: application settings under the `Creator` tab.

For our example lets type in `A terrifying adventure with lovecraftian elements`.

### Description

This should be an internal description - that will be included in the context sent to the ai, but not the player. It can be used to give the ai more information about the scene or how to treat certain elements.

##### Example

> The player controls a young woman named Annabelle as her car breaks down in a secluded neighborhood on the outskirts of a non-descript town.
>
> Its the year 2024 and her mobile phone has no signal, after walking for a while she comes across a plain looking house without any remarkable feature, it looks slightly out of place.
>
> The scene starts after Annabelle has knocked on the door.

### Introduction

The introduction is the first thing the player will see when they enter the scene. It should set the stage and give the player an idea of what to expect.

There are two ways to set the introduction, you can either type it in directly or use the :material-auto-fix: **Generate** button to have the AI generate an introduction for you.

#### 1. Create manually

Type in the introduction text. The text should be engaging and set the stage for the scene.

##### Example

> The engine coughed its last, sputtering and wheezing like a dying animal. You yanked the key out of the ignition, the silence that followed almost deafening. Great. Just great. Stranded in some godforsaken suburb on the outskirts of... well, you weren't even sure what town this was. All you knew was that your phone was about as useful as a chocolate teapot, its signal bars stubbornly stuck at zero.
>
> Dust motes danced in the dying sunlight slanting through the windshield.  You sighed, the weight of the situation sinking in. What were you supposed to do? Walk?  In this heat?  With night coming on? Your gaze drifted towards the only building within sight – a squat, two-story house with peeling paint and a porch that sagged like a tired old man. It wasn't exactly inviting, but it was something.
>
> You grabbed your tattered backpack and started walking, the gravel crunching under your worn sneakers. The silence was unnerving, broken only by the occasional chirp of a cricket. Reaching the porch, you hesitated for a moment, then raised your fist and knocked three times.
>
> The sound echoed in the stillness.  What now?


!!! tip "Autocompletion"
    While typing you can hit `ctrl+enter` to generrate a short autocompletion of the current text.

#### 2. Generate

Click on the :material-auto-fix: **Generate** button to have the AI generate an introduction for you.


!!! tip
    Make sure to check out the [Generation Settings](/user-guide/playing/world-editor/generation-settings) to see how you can influence the AI's output.

## Save the scene

![World editor scene outline 2](/img/0.26.0/world-editor-scene-outline-2.png)

Once you are happy with the outline, click on the :material-content-save: **Save** button to save the scene.

![world editor unsaved changes](/img/0.26.0/world-editor-unsaved-changes.png)

Since this is the first time you are saving the scene, you will be prompted to give it a name. Type in `the-forgotten-house` and click on the :material-check-circle-outline: **Continue** button.

![world editor save scene](/img/0.26.0/world-editor-save-scene-first-save.png)

## Next

Next we will [add a player character](/user-guide/playing/world-editor/creating-a-new-scene/create-player-character) to the scene.