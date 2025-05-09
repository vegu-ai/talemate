# Scene Types

Scene type templates are used to define different types of scenes that can be played in your game. Each scene type has different rules and constraints that guide the generation and flow of the scene.

## Creating a scene type

--8<-- "docs/snippets/common.md:world-editor-create-group"

Next enter a template name and select **Scene type** as a template type.

### Template name

The name / label of the template. This is the name that will be displayed in the list of templates.

### Template type

Specify the type of template you are creating. In this case, select **Scene type**.

![world editor templates create scene type template 1](/talemate/img/0.30.0/create-template-scene-type.png)

### Template description

A longer description of the template. What is the purpose of the template? What should it be used for?

### Scene type instructions

This should be the actual scene type instructions that govern the director's actions when a scene of this type is played.

!!! warning "Very early WIP"
    This is a very early WIP - right now do not expect this to do anything but control style and pacing. Eventually this would be where more complicated rules could be defined to guide the progress of the scene. (Turn based combat, etc.)
    
    We're not quite there yet.

### Favorite

Mark the template as a favorite to make it easier to find in the list of templates.

Favorited templates will be shown at the top of the list of templates.

## Create the template

When you have filled out the form, click the **:material-cube-scan: Create Template** button to create the template.

## Using the scene type template

Right now the only place **Scene Type** templates are used is in the [Scene Direction](/talemate/user-guide/world-editor/scene/direction) section of the World Editor, where you can import scene types from these templates.