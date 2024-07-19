# Pins

Pins allow you to permanently pin a context entry to the AI context. While a pin is active, the AI will always consider the pinned entry when generating text.  

!!! warning
    Pinning too many entries may use up your available context size, so use them wisely.

    Remember there is also automatic insertion of context based on relevance to the current scene progress, which happens regardless of pins. Pins are just a way to ensure that a specific entry is always considered relevant.

Entries are pinned through the [:material-book-open-page-variant: Context](/talemate/user-guide/world-editor/context-db) editor.

Find the entry you want to pin and click the :material-pin: **Pin** button.

![world editor pins](/talemate/img/0.26.0/world-editor-pins.png)

## Set pin active or inactive

The pin can be set to active or inactive. Inactive pins will not be considered by the AI when generating text.

Select the pinned entry from the list and check or uncheck the `Pin active` checkbox.

## Automatically pinning entries

Define auto pin conditions that the [:material-earth: World State Agent](/talemate/user-guide/agents/world-state/settings/#update-conditional-context-pins) will check every turn. If the condition is met, the entry will be pinned. If the condition is no longer met, the entry will be unpinned.

The conditions should be phrases as a question that can be evaluated as true or false. (or yes or no)

For example:

> Is it raining?

Once a pin exists that has conditioning set up, talemate will query the condition every round and pin or unpin the entry based on the result.

#### Current condition evaluation

This checkbox holds the current evaluation of the pin condition. You may also manually set this value to true or false.