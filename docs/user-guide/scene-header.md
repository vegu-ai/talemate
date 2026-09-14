# Scene Header

!!! info "New in 0.40.0"

![Scene header](/talemate/img/0.40.0/scene-header.png)

The scene header sits at the top of the scene, as part of the page. It shows the scene title in the middle and a set of information items on either side of it, and it stays in view while the scene scrolls.

```text
[ Left of the title: items ]   Scene title   [ Right of the title: items ]
```

Each item reads as a value with a short label next to it, for example **105** messages. Both sides hold as many items as you like, in the order you pick them, and either side can be empty. A long title is cut short with an ellipsis; hover over it to read the whole title. Hover over any item, or move to it with the keyboard, for an explanation of what its number means.

In a narrow scene column (the creative environment, or a phone) the title moves to its own line above the items.

The header is hidden while [Playthrough Mode](playthrough.md) runs.

Because the header carries the title, the scene's tab in the main navigation reads **:material-script: Story** rather than the scene title, in both the gameplay and the creative environment.

## Items

##### :material-layers-outline: History stats

Two values: the number of messages in the scene history (including messages that have already been summarized) and the number of summary layers. The base archive counts as the first summary layer once it holds a summary; each populated layer of the [layered history](/talemate/user-guide/agents/summarizer/settings/#layered-history) adds one. The World Editor's History tab shows the same layers as **Base**, **Layer 0**, **Layer 1** and so on.

Until the scene reports its history, the item reads **History stats unavailable**.

##### :material-archive-arrow-down-outline: Summarizer

The dialogue tokens gathered since the last summary against the [summarizer](/talemate/user-guide/agents/summarizer/)'s threshold, for example **798 / 1536** tokens. The tooltip says how many more tokens take the scene past the threshold, after which the summarizer archives the recent messages. A time passage or a change in who is present can trigger a summary earlier, so that remainder is a ceiling, not a countdown.

When a summary is due on the next message, the value changes colour and gains a :material-archive-clock-outline: marker; the count stays visible. The tooltip names the reason: the gathered dialogue passed the threshold, a time passage cut the span, or who is present changed.

When the summarizer has no ready client the item reads **Summarizer unavailable**.

## Choosing the items

![Scene header item picker](/talemate/img/0.40.0/scene-header-picker.png)

Hover over the header and click the **:material-tune-variant:** button at its right edge. A small menu lists every item under **Left of the title** and **Right of the title**; tick an item to add it to that side, untick it to remove it. A newly ticked item goes to the end of its side, so untick and tick an item again to move it to the end. The header updates at once and the choice is saved.

The same choice is available as **Left of the title** and **Right of the title** in [Settings > Game > General](/talemate/user-guide/app-settings/game#scene-header). Both places edit the same setting, so a change in one shows in the other.

By default the header is on, with **History stats** on the left and **Summarizer** on the right.

## Turning the header off and on

Hover over the header and click the **:material-close:** button at its right edge to hide it. Hiding the header this way turns off the same setting as **Show scene header** in [Settings > Game > General](/talemate/user-guide/app-settings/game#scene-header), which is where you turn it back on. Your item choices are kept while the header is hidden.

Both buttons are also reachable with the keyboard, and they are always visible on touch screens.
