# Settings

![Editor agent settings](/talemate/img/0.26.0/editor-agent-settings.png)

##### Fix exposition

If enabled the editor will attempt to fix exposition in the generated dialogue.

That means it will ensure that actions are correctly encased in `*` and that quotes are correctly applied to spoken text.

###### Fix narrator messages

Applies the same rules as above to the narrator messages.

##### Add detail

Will take the generate message and attempt to add more detail to it.

##### Fix continuity errors

Will attempt to fix continuity errors in the generated text.

!!! warning "Experimental, and doesn't work most of the time"
    There is something about accurately identifying continuity errors that is currently very 
    difficult for AI to do. So this feature is very hit and miss. More miss than hit.

    Also takes long to process, so probably leave it turned off.