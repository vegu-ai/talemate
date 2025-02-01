# Settings

![Editor agent settings](/talemate/img/0.29.0/editor-agent-settings.png)

##### Fix exposition

If enabled the editor will attempt to fix exposition in the generated dialogue.

It will do this based on the selected format. 

###### Fix narrator messages

Applies the same rules as above to the narrator messages.

###### Fix user input

Applies the same rules as above to the user input messages.

##### Add detail

Will take the generate message and attempt to add more detail to it.

##### Fix continuity errors

Will attempt to fix continuity errors in the generated text.

!!! example "Experimental, and doesn't work most of the time"
    There is something about accurately identifying continuity errors that is currently very 
    difficult for AI to do. So this feature is very hit and miss. More miss than hit.

    Also takes long to process, so probably leave it turned off.