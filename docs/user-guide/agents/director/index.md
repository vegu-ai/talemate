# Overview
The director agent is responsible for guiding the scene progression and generating dynamic actions.

In the future it will shift / expose more of a game master role, controlling the progression of the story.

### Dynamic Actions
Will occasionally generate clickable choices for the user during scene progression. This can be used to allow the user to make choices that will affect the scene or the story in some way without having to manually type out the choice.

### Guide Scene
Will use the summarizer agent's scene analysis to guide characters and the narrator for the next generation, hopefully improving the quality of the generated content.

### Auto Direction
A very experimental feature that will cause the director to attempt to direct the scene automatically, instructing actors or the narrator to move the scene forward according to the story and scene intention.

!!! note "Experimental"
    This is the first iteration of this feature and is very much a work in progress. It will likely change substantially in the future.